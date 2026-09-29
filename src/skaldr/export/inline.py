import re
from dataclasses import dataclass
from typing import Literal

from skaldr.errors import ReportError
from skaldr.models import ALLOWED_URL_SCHEMES, BadgeColor
from skaldr.render import (
    BOLD_PATTERN,
    CODE_SPAN_PATTERN,
    FOOTNOTE_PATTERN,
    ITALIC_PATTERN,
    LINK_PATTERN,
    PLACEHOLDER_NAME_PATTERN,
    PLACEHOLDER_PATTERN,
    STRIKE_PATTERN,
)


@dataclass(frozen=True)
class Plain:
    text: str


@dataclass(frozen=True)
class Code:
    text: str


@dataclass(frozen=True)
class Link:
    label: "tuple[Plain | Code, ...]"
    url: str


@dataclass(frozen=True)
class AnchorLink:
    label: "tuple[Plain | Code, ...]"
    anchor: str


@dataclass(frozen=True)
class Citation:
    number: int
    url: str | None


@dataclass(frozen=True)
class Placeholder:
    name: str


@dataclass(frozen=True)
class Chip:
    label: str
    color: BadgeColor


@dataclass(frozen=True)
class Break:
    pass


@dataclass(frozen=True)
class Styled:
    style: Literal["bold", "italic", "strike"]
    runs: "Rich"


Run = Plain | Code | Link | AnchorLink | Citation | Placeholder | Chip | Break | Styled
Rich = tuple[Run, ...]

_SENTINEL = re.compile(r"\x00(\d+)\x00")
_STYLE_PASSES: tuple[tuple[re.Pattern[str], Literal["bold", "italic", "strike"]], ...] = (
    (BOLD_PATTERN, "bold"),
    (STRIKE_PATTERN, "strike"),
    (ITALIC_PATTERN, "italic"),
)


@dataclass(frozen=True)
class InlineContext:
    citation_numbers: dict[str, int]
    citation_urls: dict[str, str | None]
    anchor_ids: frozenset[str]


def plain(text: str) -> Rich:
    return (Plain(text),) if text else ()


def bold(text: str) -> Rich:
    return (Styled("bold", plain(text)),) if text else ()


def italic(runs: Rich) -> Rich:
    return (Styled("italic", runs),) if runs else ()


def parse_rich(text: str, context: InlineContext) -> Rich:
    source = " ".join(str(text).replace("\x00", "").split())
    stash: list[Run] = []

    def set_aside(run: Run) -> str:
        stash.append(run)
        return f"\x00{len(stash) - 1}\x00"

    def flatten(fragment: str) -> tuple[Plain | Code, ...]:
        return tuple(run for run in _resolve(fragment, stash) if isinstance(run, (Plain, Code)))

    staged = CODE_SPAN_PATTERN.sub(lambda match: set_aside(Code(match.group(1))), source)

    def citation(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in context.citation_numbers:
            return match.group(0)
        return set_aside(Citation(context.citation_numbers[key], context.citation_urls.get(key)))

    staged = FOOTNOTE_PATTERN.sub(citation, staged)

    def link(match: re.Match[str]) -> str:
        label, url = match.group(1), match.group(2)
        if url.startswith("#"):
            if url[1:] not in context.anchor_ids:
                raise ReportError(
                    f"rich text links to unknown anchor '{url}' — no heading or section has that id"
                )
            return set_aside(AnchorLink(flatten(label), url[1:]))
        if url.startswith(ALLOWED_URL_SCHEMES):
            return set_aside(Link(flatten(label), url))
        return match.group(0)

    staged = LINK_PATTERN.sub(link, staged)

    def placeholder(match: re.Match[str]) -> str:
        name = match.group(1)
        if "\x00" in name or not PLACEHOLDER_NAME_PATTERN.fullmatch(name):
            raise ReportError(
                f"invalid placeholder '{{{{{name}}}}}': a placeholder name is letters, digits, '_' or "
                "'-' only"
            )
        return set_aside(Placeholder(name))

    staged = PLACEHOLDER_PATTERN.sub(placeholder, staged)
    return _styled(staged, 0, stash)


def _styled(fragment: str, pass_index: int, stash: list[Run]) -> Rich:
    if pass_index == len(_STYLE_PASSES):
        return _resolve(fragment, stash)
    pattern, style = _STYLE_PASSES[pass_index]

    def wrap(match: re.Match[str]) -> str:
        stash.append(Styled(style, _styled(match.group(1), pass_index + 1, stash)))
        return f"\x00{len(stash) - 1}\x00"

    return _styled(pattern.sub(wrap, fragment), pass_index + 1, stash)


def _resolve(fragment: str, stash: list[Run]) -> Rich:
    runs: list[Run] = []
    position = 0
    for match in _SENTINEL.finditer(fragment):
        if match.start() > position:
            runs.append(Plain(fragment[position : match.start()]))
        runs.append(stash[int(match.group(1))])
        position = match.end()
    if position < len(fragment):
        runs.append(Plain(fragment[position:]))
    return tuple(runs)


def paragraphs(text: str) -> list[str]:
    return [part.strip() for part in str(text).split("\n\n") if part.strip()]


def visible_text(runs: Rich) -> str:
    out: list[str] = []
    for run in runs:
        if isinstance(run, (Plain, Code)):
            out.append(run.text)
        elif isinstance(run, (Link, AnchorLink)):
            out.append(visible_text(run.label))
        elif isinstance(run, Citation):
            out.append(f"[{run.number}]")
        elif isinstance(run, Placeholder):
            out.append(run.name)
        elif isinstance(run, Chip):
            out.append(run.label)
        elif isinstance(run, Break):
            out.append(" ")
        else:
            out.append(visible_text(run.runs))
    return "".join(out)
