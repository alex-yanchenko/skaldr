from collections.abc import Collection, Sequence
from typing import Final

from markdown_it import MarkdownIt
from markdown_it.token import Token
from typing_extensions import override

from skaldr.models import ALLOWED_URL_SCHEMES

ANCHOR_PREFIX: Final = "#"

_REFERENCE_KEYS: Final = "reference_keys"


class _RichMarkdown(MarkdownIt):
    @override
    def validateLink(self, url: str) -> bool:
        return url.startswith((*ALLOWED_URL_SCHEMES, ANCHOR_PREFIX))

    @override
    def normalizeLink(self, url: str) -> str:
        return url


def _rich_markdown() -> MarkdownIt:
    markdown = _RichMarkdown("zero")
    markdown.enable(["escape", "backticks", "strikethrough", "emphasis", "link"])
    return markdown


RICH_MARKDOWN: Final = _rich_markdown()


def inline_tokens(text: str, reference_keys: Collection[str] = ()) -> Sequence[Token]:
    [inline] = RICH_MARKDOWN.parseInline(text, {_REFERENCE_KEYS: frozenset(reference_keys)})
    return inline.children or []
