import re
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass
from typing import Final, Literal, get_args

from markdown_it import MarkdownIt
from markdown_it.rules_inline import StateInline
from markdown_it.rules_inline.state_inline import Delimiter
from markdown_it.token import Token
from pydantic import TypeAdapter, ValidationError
from typing_extensions import override

from skaldr.errors import ReportError
from skaldr.mathml import refuse_invalid_math
from skaldr.models import ALLOWED_URL_SCHEMES, REFERENCE_KEY_PATTERN, BadgeColorLiteral, Tone, ToneLiteral

ANCHOR_PREFIX: Final = "#"
PLACEHOLDER: Final = "placeholder"
CITATION: Final = "citation"
INLINE_MATH: Final = "inline_math"
TINT_OPEN: Final = "tint_open"
TINT_CLOSE: Final = "tint_close"
SPAN_TONES: Final = "span_tones"
UNDERLINE_OPEN: Final = "underline_open"
UNDERLINE_CLOSE: Final = "underline_close"
SUBSCRIPT: Final = "subscript"
SUPERSCRIPT: Final = "superscript"

_REFERENCE_KEYS: Final = "reference_keys"
_PLACEHOLDER_OPEN: Final = "{{"
_PLACEHOLDER_CLOSE: Final = "}}"
_PLACEHOLDER_NAME: Final = re.compile(REFERENCE_KEY_PATTERN)
_BRACE: Final = re.compile(r"[{}]")
_CITATION: Final = re.compile(rf"\[\^({REFERENCE_KEY_PATTERN})\]")
_MATH_OPEN: Final = "$`"
_MATH_CLOSE: Final = "`$"
_ATTRIBUTE_LIST: Final = re.compile(r"\{([^{}]*)\}")
_NAMES_A_TONE: Final = re.compile(r"(?<!\S)(?:tone|bg)\s*=")
_SPAN_ATTRIBUTES: Final = frozenset({"tone", "bg"})
_TONE: Final = TypeAdapter[ToneLiteral](Tone)
_PALETTE_ONLY_NAMES: Final = tuple(
    name for name in get_args(BadgeColorLiteral) if name not in get_args(ToneLiteral)
)
_SCRIPT_TEXT: Final = re.compile(r"(?:[^\W_]|[-+=().,'*" + "\N{MINUS SIGN}\N{PRIME}" + r"])+")
_UNDERLINE_MARKER: Final = "+"


@dataclass(frozen=True)
class SpanTones:
    tone: ToneLiteral | None
    background: ToneLiteral | None


class _RichMarkdown(MarkdownIt):
    @override
    def validateLink(self, url: str) -> bool:
        return url.startswith((*ALLOWED_URL_SCHEMES, ANCHOR_PREFIX)) and _PLACEHOLDER_OPEN not in url

    @override
    def normalizeLink(self, url: str) -> str:
        return url


def _invalid_placeholder(name: str) -> ReportError:
    return ReportError(
        "invalid placeholder '{{" + name + "}}': a placeholder name is letters, digits, '_' or "
        "'-' only (a fill-me-later blank is written {{name}}; for a literal {{ use a `code` span)"
    )


def _placeholder(state: StateInline, silent: bool) -> bool:
    start = state.pos
    if silent or not state.src.startswith(_PLACEHOLDER_OPEN, start, state.posMax):
        return False
    brace = _BRACE.search(state.src, start + len(_PLACEHOLDER_OPEN), state.posMax)
    if brace is None or not state.src.startswith(_PLACEHOLDER_CLOSE, brace.start(), state.posMax):
        return False
    name = state.src[start + len(_PLACEHOLDER_OPEN) : brace.start()].strip()
    if not _PLACEHOLDER_NAME.fullmatch(name):
        raise _invalid_placeholder(name)
    state.push(PLACEHOLDER, "", 0).content = name
    state.pos = brace.start() + len(_PLACEHOLDER_CLOSE)
    return True


def _citation(state: StateInline, silent: bool) -> bool:
    citation = _CITATION.match(state.src, state.pos, state.posMax)
    if silent or citation is None or citation.group(1) not in state.env[_REFERENCE_KEYS]:
        return False
    state.push(CITATION, "", 0).content = citation.group(1)
    state.pos = citation.end()
    return True


def _inline_math(state: StateInline, silent: bool) -> bool:
    start = state.pos
    body = start + len(_MATH_OPEN)
    if silent or not state.src.startswith(_MATH_OPEN, start, state.posMax):
        return False
    close = state.src.find("`", body, state.posMax)
    if close <= body or not state.src.startswith(_MATH_CLOSE, close, state.posMax):
        return False
    expression = state.src[body:close].strip()
    if not expression:
        raise ReportError(
            f"inline math {state.src[start : close + len(_MATH_CLOSE)]} is empty: write an expression "
            "between $` and `$, as in $`x_i`$"
        )
    refuse_invalid_math(expression, "inline")
    state.push(INLINE_MATH, "", 0).content = expression
    state.pos = close + len(_MATH_CLOSE)
    return True


def _attribute_token(attributes: str) -> str:
    return "{" + attributes.strip() + "}"


def _colours_no_text(attributes: str) -> ReportError:
    return ReportError(
        f"the attribute list {_attribute_token(attributes)} follows no [text] it can color: the text "
        "inside a [text]{…} span is not empty and holds no link"
    )


def _span_tones(attributes: str) -> SpanTones:
    token = _attribute_token(attributes)
    tones: dict[str, ToneLiteral] = {}
    for attribute in attributes.split():
        key, equals, value = attribute.partition("=")
        if not equals or not value:
            raise ReportError(
                f"malformed attribute '{attribute}' in {token}: write each attribute as key=value, "
                "with no spaces around '='"
            )
        if key not in _SPAN_ATTRIBUTES:
            raise ReportError(
                f"unknown attribute '{key}' in {token}: a [text]{{…}} span takes tone=<tone> and bg=<tone>"
            )
        if key in tones:
            raise ReportError(f"attribute '{key}' is set twice in {token}")
        tones[key] = _span_tone(value, token)
    return SpanTones(tones.get("tone"), tones.get("bg"))


def _span_tone(value: str, token: str) -> ToneLiteral:
    try:
        return _TONE.validate_python(value)
    except ValidationError as error:
        raise ReportError(
            f"unknown tone '{value}' in {token}: a tone is one of {', '.join(get_args(ToneLiteral))}, "
            f"or a palette name {', '.join(_PALETTE_ONLY_NAMES)}"
        ) from error


def _attribute_list_at(state: StateInline, position: int) -> re.Match[str] | None:
    attributes = _ATTRIBUTE_LIST.match(state.src, position, state.posMax)
    if attributes is None or not _NAMES_A_TONE.search(attributes.group(1)):
        return None
    return attributes


def _tinted_span(state: StateInline, silent: bool) -> bool:
    start = state.pos
    if silent or state.src[start] != "[":
        return False
    label_end = state.md.helpers.parseLinkLabel(state, start)
    attributes = _attribute_list_at(state, label_end + 1) if label_end >= 0 else None
    if attributes is None:
        return False
    if label_end == start + 1:
        raise _colours_no_text(attributes.group(1))
    opener = state.push(TINT_OPEN, "span", 1)
    first_label_token = len(state.tokens)
    end = state.posMax
    state.pos, state.posMax = start + 1, label_end
    state.md.inline.tokenize(state)
    state.posMax = end
    if any(token.type == "link_open" for token in state.tokens[first_label_token:]):
        raise _colours_no_text(attributes.group(1))
    opener.meta[SPAN_TONES] = _span_tones(attributes.group(1))
    state.push(TINT_CLOSE, "span", -1)
    state.pos = attributes.end()
    return True


def _stray_attribute_list(state: StateInline, silent: bool) -> bool:
    if silent or state.src[state.pos] != "]":
        return False
    attributes = _attribute_list_at(state, state.pos + 1)
    if attributes is not None:
        raise _colours_no_text(attributes.group(1))
    return False


def _script_rule(marker: str, token_type: str, refused_after: str) -> Callable[[StateInline, bool], bool]:
    def script(state: StateInline, silent: bool) -> bool:
        start = state.pos
        if silent or state.src[start] != marker or (start > 0 and state.src[start - 1] in refused_after):
            return False
        text = _SCRIPT_TEXT.match(state.src, start + 1, state.posMax)
        if text is None or not state.src.startswith(marker, text.end(), state.posMax):
            return False
        if state.src.startswith(marker, text.end() + 1, state.posMax):
            return False
        state.push(token_type, "", 0).content = text.group(0)
        state.pos = text.end() + 1
        return True

    return script


def _underline_delimiters(state: StateInline, silent: bool) -> bool:
    if silent or state.src[state.pos] != _UNDERLINE_MARKER:
        return False
    scanned = state.scanDelims(state.pos, False)
    if scanned.length < 2:
        return False
    pairs, odd = divmod(scanned.length, 2)
    if odd:
        state.push("text", "", 0).content = _UNDERLINE_MARKER
    for _ in range(pairs):
        state.push("text", "", 0).content = _UNDERLINE_MARKER * 2
        state.delimiters.append(
            Delimiter(
                marker=ord(_UNDERLINE_MARKER),
                length=0,
                token=len(state.tokens) - 1,
                end=-1,
                open=scanned.can_open,
                close=scanned.can_close,
            )
        )
    state.pos += scanned.length
    return True


def _become_underline_tag(token: Token, token_type: str, nesting: Literal[1, -1]) -> None:
    token.type = token_type
    token.tag = "u"
    token.nesting = nesting
    token.markup = _UNDERLINE_MARKER * 2
    token.content = ""


def _pair_underlines(state: StateInline, delimiters: Sequence[Delimiter]) -> None:
    for opener in delimiters:
        if opener.marker == ord(_UNDERLINE_MARKER) and opener.end != -1:
            _become_underline_tag(state.tokens[opener.token], UNDERLINE_OPEN, 1)
            _become_underline_tag(state.tokens[delimiters[opener.end].token], UNDERLINE_CLOSE, -1)


def _underline_pairs(state: StateInline) -> None:
    _pair_underlines(state, state.delimiters)
    for meta in state.tokens_meta:
        if meta and "delimiters" in meta:
            _pair_underlines(state, meta["delimiters"])


def _rich_markdown() -> MarkdownIt:
    markdown = _RichMarkdown("zero")
    markdown.enable(["escape", "backticks", "strikethrough", "emphasis", "link"])
    inline = markdown.inline.ruler
    inline.before("backticks", INLINE_MATH, _inline_math)
    inline.before("link", CITATION, _citation)
    inline.before("link", "tinted_span", _tinted_span)
    inline.after("link", "stray_attribute_list", _stray_attribute_list)
    inline.after("emphasis", PLACEHOLDER, _placeholder)
    inline.after("emphasis", SUBSCRIPT, _script_rule("~", SUBSCRIPT, "~"))
    inline.after("emphasis", SUPERSCRIPT, _script_rule("^", SUPERSCRIPT, "[^"))
    inline.after("strikethrough", "underline", _underline_delimiters)
    markdown.inline.ruler2.after("strikethrough", "underline", _underline_pairs)
    return markdown


RICH_MARKDOWN: Final = _rich_markdown()


def inline_tokens(text: str, reference_keys: Collection[str] = ()) -> Sequence[Token]:
    [inline] = RICH_MARKDOWN.parseInline(text, {_REFERENCE_KEYS: frozenset(reference_keys)})
    return inline.children or []
