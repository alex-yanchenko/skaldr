from pathlib import PurePosixPath

from skaldr import models
from skaldr.export.inline import bold, italic, one_line, paragraphs, plain
from skaldr.export.lower.context import Lowering, bullets, spaced
from skaldr.export.tree import (
    Callout,
    CodeBlock,
    ListEntry,
    ListKind,
    ListNode,
    Node,
    Paragraph,
    Quote,
    ToneName,
)
from skaldr.richtext import Code, Link, Plain, Rich

CODE_LANGUAGE_BY_SUFFIX: dict[str, str] = {
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".mjs": "javascript",
    ".py": "python",
    ".sh": "bash",
    ".bash": "bash",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".sql": "sql",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".rb": "ruby",
    ".css": "css",
    ".html": "html",
    ".toml": "toml",
    ".md": "markdown",
}


def lower_list(block: models.ListBlock, lowering: Lowering) -> list[Node]:
    return [ListNode(block.style, tuple(_list_entry(item, block.style, lowering) for item in block.items))]


def _list_entry(item: str | models.ListItem, kind: ListKind, lowering: Lowering) -> ListEntry:
    if isinstance(item, str):
        return ListEntry(lowering.rich(item))
    children: tuple[Node, ...] = ()
    if item.items:
        children = (ListNode(kind, tuple(_list_entry(child, kind, lowering) for child in item.items)),)
    return ListEntry(lowering.rich(item.text), item.checked, children)


def _titled_callout(tone: ToneName, title: str | None, body: str, lowering: Lowering) -> list[Node]:
    heading: tuple[Node, ...] = (Paragraph(bold(title)),) if title else ()
    return [Callout(tone, heading + lowering.prose(body))]


def lower_callout(block: models.Callout, lowering: Lowering) -> list[Node]:
    return _titled_callout(block.tone, block.title, block.body, lowering)


def lower_note(block: models.Note, lowering: Lowering) -> list[Node]:
    return _titled_callout("neutral", block.title, block.body, lowering)


def code_language(label: str | None) -> str:
    if not label:
        return ""
    return CODE_LANGUAGE_BY_SUFFIX.get(PurePosixPath(label.strip()).suffix.lower(), "")


def lower_code(block: models.Code) -> list[Node]:
    label: list[Node] = [Paragraph((Code(one_line(block.label)),))] if block.label else []
    language = "diff" if block.mode == "diff" else code_language(block.label)
    return [*label, CodeBlock(block.content.rstrip("\n"), language)]


def lower_quote(block: models.Quote, lowering: Lowering) -> list[Node]:
    lines = tuple(lowering.rich(part) for part in paragraphs(block.body))
    return [Quote(lines, plain(block.cite) if block.cite else ())]


def lower_image(block: models.Image) -> list[Node]:
    return [Paragraph(italic(plain(f"Image: {block.caption or block.alt}")), "muted")]


def _reference_entry(item: models.ReferenceItem, lowering: Lowering) -> ListEntry:
    numbers = lowering.rich_context.reference_numbers or {}
    parts: list[Rich] = [plain(f"[{numbers[item.key]}]"), lowering.rich(item.text)]
    if item.url:
        parts.append((Link((Plain("source"),), item.url),))
    return ListEntry(spaced(parts))


def lower_references(block: models.References, lowering: Lowering) -> list[Node]:
    return [bullets(_reference_entry(item, lowering) for item in block.items)]
