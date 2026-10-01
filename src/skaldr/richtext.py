import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal, Protocol, TypeVar

from typing_extensions import assert_never

from skaldr.errors import ReportError
from skaldr.models import ALLOWED_URL_SCHEMES, REFERENCE_KEY_PATTERN

StyleName = Literal["bold", "italic", "strike"]


@dataclass(frozen=True)
class Plain:
    text: str


@dataclass(frozen=True)
class Code:
    text: str


@dataclass(frozen=True)
class Link:
    label: "Rich"
    url: str


@dataclass(frozen=True)
class AnchorLink:
    label: "Rich"
    anchor: str


@dataclass(frozen=True)
class Citation:
    key: str
    number: int
    url: str | None = None


@dataclass(frozen=True)
class Placeholder:
    name: str


@dataclass(frozen=True)
class Styled:
    style: StyleName
    runs: "Rich"


Run = Plain | Code | Link | AnchorLink | Citation | Placeholder | Styled
Rich = tuple[Run, ...]

_CODE_SPAN = re.compile(r"`([^`]+)`")
_FOOTNOTE = re.compile(rf"\[\^({REFERENCE_KEY_PATTERN})\]")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
_PLACEHOLDER = re.compile(r"\{\{\s*([^{}]*?)\s*\}\}")
_PLACEHOLDER_NAME = re.compile(r"[A-Za-z0-9_-]+")
_SENTINEL = re.compile(r"\x00(\d+)\x00")
_STYLE_PASSES: tuple[tuple[re.Pattern[str], StyleName], ...] = (
    (re.compile(r"\*\*([^*]+)\*\*"), "bold"),
    (re.compile(r"~~([^~]+)~~"), "strike"),
    (re.compile(r"(?<!\*)\*([^*]+)\*(?!\*)"), "italic"),
)


@dataclass(frozen=True)
class RichContext:
    reference_numbers: Mapping[str, int] | None = None
    reference_urls: Mapping[str, str | None] = field(default_factory=dict[str, "str | None"])
    anchor_ids: frozenset[str] | None = None


class _Stash:
    def __init__(self) -> None:
        self.runs: list[Run] = []

    def set_aside(self, run: Run) -> str:
        self.runs.append(run)
        return f"\x00{len(self.runs) - 1}\x00"

    def runs_in(self, fragment: str) -> Rich:
        runs: list[Run] = []
        position = 0
        for match in _SENTINEL.finditer(fragment):
            if match.start() > position:
                runs.append(Plain(fragment[position : match.start()]))
            runs.append(self.runs[int(match.group(1))])
            position = match.end()
        if position < len(fragment):
            runs.append(Plain(fragment[position:]))
        return tuple(runs)


def _invalid_placeholder(name: str) -> ReportError:
    if "\x00" in name:
        return ReportError(
            "invalid placeholder: a {{…}} blank is a bare name (letters, digits, '_' or '-'), so it "
            "can't contain a link, `code` span, or [^citation]"
        )
    return ReportError(
        "invalid placeholder '{{" + name + "}}': a placeholder name is letters, digits, '_' or "
        "'-' only (a fill-me-later blank is written {{name}}; for a literal {{ use a `code` span)"
    )


def parse_rich(text: str, context: RichContext | None = None) -> Rich:
    rules = context or RichContext()
    stash = _Stash()
    staged = _CODE_SPAN.sub(lambda match: stash.set_aside(Code(match.group(1))), text.replace("\x00", ""))

    def cite(match: re.Match[str]) -> str:
        key = match.group(1)
        if rules.reference_numbers is None or key not in rules.reference_numbers:
            return match.group(0)
        return stash.set_aside(Citation(key, rules.reference_numbers[key], rules.reference_urls.get(key)))

    def link(match: re.Match[str]) -> str:
        label, url = stash.runs_in(match.group(1)), match.group(2)
        if "\x00" in url:
            return match.group(0)
        if url.startswith("#"):
            if rules.anchor_ids is None:
                return match.group(0)
            if url[1:] not in rules.anchor_ids:
                raise ReportError(
                    f"rich text links to unknown anchor '{url}' — no heading or section has that id"
                )
            return stash.set_aside(AnchorLink(label, url[1:]))
        if url.startswith(ALLOWED_URL_SCHEMES):
            return stash.set_aside(Link(label, url))
        return match.group(0)

    def blank(match: re.Match[str]) -> str:
        name = match.group(1)
        if "\x00" in name or not _PLACEHOLDER_NAME.fullmatch(name):
            raise _invalid_placeholder(name)
        return stash.set_aside(Placeholder(name))

    staged = _FOOTNOTE.sub(cite, staged)
    staged = _LINK.sub(link, staged)
    staged = _PLACEHOLDER.sub(blank, staged)
    return _parse_styles(staged, 0, stash)


def _parse_styles(fragment: str, pass_index: int, stash: _Stash) -> Rich:
    if pass_index == len(_STYLE_PASSES):
        return stash.runs_in(fragment)
    pattern, style = _STYLE_PASSES[pass_index]

    def emphasise(match: re.Match[str]) -> str:
        return stash.set_aside(Styled(style, _parse_styles(match.group(1), pass_index + 1, stash)))

    return _parse_styles(pattern.sub(emphasise, fragment), pass_index + 1, stash)


class RunWriter(Protocol):
    def text(self, text: str, /) -> str: ...

    def bang_before_link(self) -> str: ...

    def code(self, text: str, /) -> str: ...

    def link(self, label: str, url: str, /) -> str: ...

    def anchor_link(self, label: str, anchor: str, /) -> str: ...

    def citation(self, run: Citation, /) -> str: ...

    def placeholder(self, name: str, /) -> str: ...

    def styled(self, style: StyleName, inner: str, /) -> str: ...


RunT = TypeVar("RunT")
WriterT = TypeVar("WriterT", bound=RunWriter)


def write_run(run: Run, writer: RunWriter) -> str:
    match run:
        case Plain():
            return writer.text(run.text)
        case Code():
            return writer.code(run.text)
        case Link():
            return writer.link(write_runs(run.label, writer), run.url)
        case AnchorLink():
            return writer.anchor_link(write_runs(run.label, writer), run.anchor)
        case Citation():
            return writer.citation(run)
        case Placeholder():
            return writer.placeholder(run.name)
        case Styled():
            return writer.styled(run.style, write_runs(run.runs, writer))
        case _:
            assert_never(run)


def write_sequence(runs: Sequence[RunT], writer: WriterT, write_one: Callable[[RunT, WriterT], str]) -> str:
    out: list[str] = []
    for index, run in enumerate(runs):
        following = runs[index + 1] if index + 1 < len(runs) else None
        if isinstance(run, Plain) and run.text.endswith("!") and isinstance(following, Link):
            out.append(writer.text(run.text[:-1]) + writer.bang_before_link())
        else:
            out.append(write_one(run, writer))
    return "".join(out)


def write_runs(runs: Rich, writer: RunWriter) -> str:
    return write_sequence(runs, writer, write_run)


class VisibleText:
    def text(self, text: str, /) -> str:
        return text

    def bang_before_link(self) -> str:
        return "!"

    def code(self, text: str, /) -> str:
        return text

    def link(self, label: str, _url: str, /) -> str:
        return label

    def anchor_link(self, label: str, _anchor: str, /) -> str:
        return label

    def citation(self, run: Citation, /) -> str:
        return f"[{run.number}]"

    def placeholder(self, name: str, /) -> str:
        return name

    def styled(self, _style: StyleName, inner: str, /) -> str:
        return inner


def visible_text(runs: Rich) -> str:
    return write_runs(runs, VisibleText())
