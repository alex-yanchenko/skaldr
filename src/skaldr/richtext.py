import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal, Protocol

from typing_extensions import assert_never

from skaldr.errors import ReportError
from skaldr.models import ALLOWED_URL_SCHEMES, REFERENCE_KEY_PATTERN, BadgeColor

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
class Chip:
    label: str
    tone: BadgeColor


@dataclass(frozen=True)
class Break:
    pass


@dataclass(frozen=True)
class Styled:
    style: StyleName
    runs: "Rich"


Run = Plain | Code | Link | AnchorLink | Citation | Placeholder | Chip | Break | Styled
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

    def resolve(self, fragment: str) -> Rich:
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
        label, url = stash.resolve(match.group(1)), match.group(2)
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
    return _styled(staged, 0, stash)


def _styled(fragment: str, pass_index: int, stash: _Stash) -> Rich:
    if pass_index == len(_STYLE_PASSES):
        return stash.resolve(fragment)
    pattern, style = _STYLE_PASSES[pass_index]

    def emphasise(match: re.Match[str]) -> str:
        return stash.set_aside(Styled(style, _styled(match.group(1), pass_index + 1, stash)))

    return _styled(pattern.sub(emphasise, fragment), pass_index + 1, stash)


class RunWriter(Protocol):
    def text(self, text: str) -> str: ...

    def code(self, text: str) -> str: ...

    def link(self, label: str, url: str, /) -> str: ...

    def anchor_link(self, label: str, anchor: str, /) -> str: ...

    def citation(self, run: Citation) -> str: ...

    def placeholder(self, name: str) -> str: ...

    def chip(self, run: Chip) -> str: ...

    def line_break(self) -> str: ...

    def styled(self, style: StyleName, inner: str, /) -> str: ...


def write_runs(runs: Rich, writer: RunWriter) -> str:
    out: list[str] = []
    for run in runs:
        match run:
            case Plain():
                out.append(writer.text(run.text))
            case Code():
                out.append(writer.code(run.text))
            case Link():
                out.append(writer.link(write_runs(run.label, writer), run.url))
            case AnchorLink():
                out.append(writer.anchor_link(write_runs(run.label, writer), run.anchor))
            case Citation():
                out.append(writer.citation(run))
            case Placeholder():
                out.append(writer.placeholder(run.name))
            case Chip():
                out.append(writer.chip(run))
            case Break():
                out.append(writer.line_break())
            case Styled():
                out.append(writer.styled(run.style, write_runs(run.runs, writer)))
            case _:
                assert_never(run)
    return "".join(out)


class _VisibleText:
    def text(self, text: str) -> str:
        return text

    def code(self, text: str) -> str:
        return text

    def link(self, label: str, _url: str, /) -> str:
        return label

    def anchor_link(self, label: str, _anchor: str, /) -> str:
        return label

    def citation(self, run: Citation) -> str:
        return f"[{run.number}]"

    def placeholder(self, name: str) -> str:
        return name

    def chip(self, run: Chip) -> str:
        return run.label

    def line_break(self) -> str:
        return " "

    def styled(self, _style: StyleName, inner: str, /) -> str:
        return inner


def visible_text(runs: Rich) -> str:
    return write_runs(runs, _VisibleText())
