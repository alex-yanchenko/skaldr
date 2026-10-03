from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final, Literal, Protocol

from markdown_it.token import Token
from typing_extensions import assert_never

from skaldr.errors import ReportError
from skaldr.models import ToneLiteral
from skaldr.richtext_syntax import (
    ANCHOR_PREFIX,
    CITATION,
    CODE_INLINE,
    EM_OPEN,
    INLINE_MATH,
    LINK_OPEN,
    MAX_NESTING,
    PLACEHOLDER,
    SPAN_TONES,
    STRIKE_OPEN,
    STRONG_OPEN,
    SUBSCRIPT,
    SUPERSCRIPT,
    TINT_OPEN,
    UNDERLINE_OPEN,
    SpanTones,
    inline_tokens,
    nested_too_deep,
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
    STRONG_OPEN: "bold",
    EM_OPEN: "italic",
    STRIKE_OPEN: "strike",
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
    runs, _ = _runs_until_close(inline_tokens(text, rules.reference_numbers or {}), 0, rules, 0)
    return runs


def _runs_until_close(
    tokens: Sequence[Token], start: int, rules: RichContext, depth: int
) -> tuple[Rich, int]:
    runs: list[Run] = []
    index = start
    while index < len(tokens) and tokens[index].nesting != -1:
        token = tokens[index]
        if token.nesting == 1:
            if depth == MAX_NESTING:
                raise nested_too_deep()
            inner, index = _runs_until_close(tokens, index + 1, rules, depth + 1)
            runs.extend(_wrapped_runs(token, inner, rules))
        else:
            runs.append(_leaf_run(token, rules))
        index += 1
    return _merged(runs), index


def _wrapped_runs(opener: Token, inner: Rich, rules: RichContext) -> Rich:
    if opener.type == LINK_OPEN:
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
    if token.type == CODE_INLINE:
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
