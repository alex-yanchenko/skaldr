from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final, Literal, Protocol, cast

from markdown_it.token import Token
from typing_extensions import assert_never

from skaldr.errors import ReportError
from skaldr.models import Report, ToneLiteral
from skaldr.richtext_syntax import (
    ANCHOR_PREFIX,
    CITATION,
    INLINE_MATH,
    PLACEHOLDER,
    SPAN_TONES,
    SUBSCRIPT,
    SUPERSCRIPT,
    TINT_OPEN,
    UNDERLINE_OPEN,
    SpanTones,
    inline_tokens,
)

MarkerStyle = Literal["bold", "italic", "strike"]
StyleName = Literal[MarkerStyle, "underline"]
ScriptPosition = Literal["subscript", "superscript"]
SCRIPT_HTML_TAG: Final[Mapping[ScriptPosition, str]] = {"subscript": "sub", "superscript": "sup"}


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


@dataclass(frozen=True)
class ScriptText:
    position: ScriptPosition
    text: str


@dataclass(frozen=True)
class Tinted:
    tone: ToneLiteral | None
    background: ToneLiteral | None
    runs: "Rich"


@dataclass(frozen=True)
class InlineMath:
    expression: str


Run = Plain | Code | Link | AnchorLink | Citation | Placeholder | Styled | ScriptText | Tinted | InlineMath
Rich = tuple[Run, ...]

_STYLE_OPENERS: Final[Mapping[str, StyleName]] = {
    "strong_open": "bold",
    "em_open": "italic",
    "s_open": "strike",
    UNDERLINE_OPEN: "underline",
}
_SCRIPT_TOKENS: Final[Mapping[str, ScriptPosition]] = {SUBSCRIPT: "subscript", SUPERSCRIPT: "superscript"}


@dataclass(frozen=True)
class RichContext:
    reference_numbers: Mapping[str, int] | None = None
    reference_urls: Mapping[str, str | None] = field(default_factory=dict[str, "str | None"])
    anchor_ids: frozenset[str] | None = None


def parse_rich(text: str, context: RichContext | None = None) -> Rich:
    rules = context if context is not None else RichContext()
    runs, _ = _runs_until_close(inline_tokens(text, rules.reference_numbers or {}), 0, rules)
    return runs


def _runs_until_close(tokens: Sequence[Token], start: int, rules: RichContext) -> tuple[Rich, int]:
    runs: list[Run] = []
    index = start
    while index < len(tokens) and tokens[index].nesting != -1:
        token = tokens[index]
        if token.nesting == 1:
            inner, index = _runs_until_close(tokens, index + 1, rules)
            runs.extend(_wrapped_runs(token, inner, rules))
        else:
            runs.append(_leaf_run(token, rules))
        index += 1
    return _merged(runs), index


def _wrapped_runs(opener: Token, inner: Rich, rules: RichContext) -> Rich:
    if opener.type == "link_open":
        return _link_runs(str(opener.attrs["href"]), inner, rules)
    if opener.type == TINT_OPEN:
        tones: SpanTones = opener.meta[SPAN_TONES]
        return (Tinted(tones.tone, tones.background, inner),)
    return (Styled(_STYLE_OPENERS[opener.type], inner),)


def _link_runs(url: str, label: Rich, rules: RichContext) -> Rich:
    if not url.startswith(ANCHOR_PREFIX):
        return (Link(label, url),)
    if rules.anchor_ids is None:
        return (Plain("["), *label, Plain(f"]({url})"))
    if url.removeprefix(ANCHOR_PREFIX) not in rules.anchor_ids:
        raise ReportError(f"rich text links to unknown anchor '{url}' — no heading or section has that id")
    return (AnchorLink(label, url.removeprefix(ANCHOR_PREFIX)),)


def _leaf_run(token: Token, rules: RichContext) -> Run:
    if token.type == "code_inline":
        return Code(token.content)
    if token.type == PLACEHOLDER:
        return Placeholder(token.content)
    if token.type == CITATION:
        numbers = rules.reference_numbers or {}
        return Citation(token.content, numbers[token.content], rules.reference_urls.get(token.content))
    if token.type == INLINE_MATH:
        return InlineMath(token.content)
    if token.type in _SCRIPT_TOKENS:
        return ScriptText(_SCRIPT_TOKENS[token.type], token.content)
    return Plain(token.content)


def _merged(runs: Iterable[Run]) -> Rich:
    merged: list[Run] = []
    for run in runs:
        if isinstance(run, Plain) and not run.text:
            continue
        previous = merged[-1] if merged else None
        if isinstance(run, Plain) and isinstance(previous, Plain):
            merged[-1] = Plain(previous.text + run.text)
        else:
            merged.append(run)
    return tuple(merged)


class RunWriter(Protocol):
    def text(self, text: str, /) -> str: ...

    def code(self, text: str, /) -> str: ...

    def link(self, label: str, url: str, /) -> str: ...

    def anchor_link(self, label: str, anchor: str, /) -> str: ...

    def citation(self, run: Citation, /) -> str: ...

    def placeholder(self, name: str, /) -> str: ...

    def styled(self, style: StyleName, inner: str, /) -> str: ...

    def script(self, position: ScriptPosition, text: str, /) -> str: ...

    def tinted(self, tone: ToneLiteral | None, background: ToneLiteral | None, inner: str, /) -> str: ...

    def math(self, expression: str, /) -> str: ...


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
        case ScriptText():
            return writer.script(run.position, run.text)
        case Tinted():
            return writer.tinted(run.tone, run.background, write_runs(run.runs, writer))
        case InlineMath():
            return writer.math(run.expression)
        case _:
            assert_never(run)


def write_runs(runs: Rich, writer: RunWriter) -> str:
    return "".join(write_run(run, writer) for run in runs)


class VisibleText:
    def text(self, text: str, /) -> str:
        return text

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

    def script(self, _position: ScriptPosition, text: str, /) -> str:
        return text

    def tinted(self, _tone: ToneLiteral | None, _background: ToneLiteral | None, inner: str, /) -> str:
        return inner

    def math(self, expression: str, /) -> str:
        return expression


def visible_text(runs: Rich) -> str:
    return write_runs(runs, VisibleText())


def _string_fields(value: object, path: tuple[str, ...]) -> Iterator[tuple[str, str]]:
    if isinstance(value, str):
        yield ".".join(path), value
    elif isinstance(value, dict):
        for key, item in cast("dict[str, object]", value).items():
            yield from _string_fields(item, (*path, key))
    elif isinstance(value, list):
        for index, item in enumerate(cast("list[object]", value)):
            yield from _string_fields(item, (*path, str(index)))


def located_rich_text_error(report: Report, text: str, error: ReportError) -> ReportError:
    fields = _string_fields(report.model_dump(mode="json"), ())
    field = next((path for path, value in fields if text in value), None)
    return ReportError(f"{field}: {error}" if field else str(error))
