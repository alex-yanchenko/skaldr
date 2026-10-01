import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, Protocol

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


def _anchor_holding_markup(url: str) -> ReportError:
    return ReportError(
        f"rich text links to the anchor '{url.split(chr(0), 1)[0]}…', whose target holds a `code` span or "
        "[^citation]; an anchor link targets a heading or section id"
    )


def parse_rich(text: str, context: RichContext | None = None) -> Rich:
    rules = context if context is not None else RichContext()
    stash = _Stash()
    staged = _CODE_SPAN.sub(lambda match: stash.set_aside(Code(match.group(1))), text.replace("\x00", ""))

    def cite(match: re.Match[str]) -> str:
        key = match.group(1)
        if rules.reference_numbers is None or key not in rules.reference_numbers:
            return match.group(0)
        return stash.set_aside(Citation(key, rules.reference_numbers[key]))

    def anchor(match: re.Match[str], label: Rich, url: str) -> str:
        if rules.anchor_ids is None:
            return match.group(0)
        if "\x00" in url:
            raise _anchor_holding_markup(url)
        if url[1:] not in rules.anchor_ids:
            raise ReportError(
                f"rich text links to unknown anchor '{url}' — no heading or section has that id"
            )
        return stash.set_aside(AnchorLink(label, url[1:]))

    def link(match: re.Match[str]) -> str:
        label, url = stash.runs_in(match.group(1)), match.group(2)
        if url.startswith("#"):
            return anchor(match, label, url)
        if "\x00" not in url and url.startswith(ALLOWED_URL_SCHEMES):
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

    def code(self, text: str, /) -> str: ...

    def link(self, label: str, url: str, /) -> str: ...

    def anchor_link(self, label: str, anchor: str, /) -> str: ...

    def citation(self, run: Citation, /) -> str: ...

    def placeholder(self, name: str, /) -> str: ...

    def styled(self, style: StyleName, inner: str, /) -> str: ...


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


def write_runs(runs: Rich, writer: RunWriter) -> str:
    return "".join(write_run(run, writer) for run in runs)
