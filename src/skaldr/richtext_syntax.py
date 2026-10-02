import re
from collections.abc import Collection, Sequence
from typing import Final

from markdown_it import MarkdownIt
from markdown_it.rules_inline import StateInline
from markdown_it.token import Token
from typing_extensions import override

from skaldr.errors import ReportError
from skaldr.mathml import refuse_invalid_math
from skaldr.models import ALLOWED_URL_SCHEMES, REFERENCE_KEY_PATTERN

ANCHOR_PREFIX: Final = "#"
PLACEHOLDER: Final = "placeholder"
CITATION: Final = "citation"
INLINE_MATH: Final = "inline_math"

_REFERENCE_KEYS: Final = "reference_keys"
_PLACEHOLDER_OPEN: Final = "{{"
_PLACEHOLDER_CLOSE: Final = "}}"
_PLACEHOLDER_NAME: Final = re.compile(REFERENCE_KEY_PATTERN)
_BRACE: Final = re.compile(r"[{}]")
_CITATION: Final = re.compile(rf"\[\^({REFERENCE_KEY_PATTERN})\]")
_MATH_OPEN: Final = "$`"
_MATH_CLOSE: Final = "`$"


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


def _rich_markdown() -> MarkdownIt:
    markdown = _RichMarkdown("zero")
    markdown.enable(["escape", "backticks", "strikethrough", "emphasis", "link"])
    inline = markdown.inline.ruler
    inline.before("backticks", INLINE_MATH, _inline_math)
    inline.before("link", CITATION, _citation)
    inline.after("emphasis", PLACEHOLDER, _placeholder)
    return markdown


RICH_MARKDOWN: Final = _rich_markdown()


def inline_tokens(text: str, reference_keys: Collection[str] = ()) -> Sequence[Token]:
    [inline] = RICH_MARKDOWN.parseInline(text, {_REFERENCE_KEYS: frozenset(reference_keys)})
    return inline.children or []
