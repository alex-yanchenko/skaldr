import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from typing_extensions import assert_never

from skaldr.export.markup import (
    CALLOUT_ICON,
    MarkupRuns,
    bang_cannot_open_an_image,
    code_block_lines,
    escape_block_start,
    indent_lines,
    styled,
)
from skaldr.export.tree import (
    Callout,
    CodeBlock,
    Heading,
    ListKind,
    ListNode,
    Node,
    Paragraph,
    Quote,
    TableOfContents,
    Toggle,
    ToneName,
)
from skaldr.richtext import Rich, visible_text, write_runs

NOTION_ESCAPES: Final = str.maketrans({character: "\\" + character for character in "\\*~`$[]<>{}|^"})
FILE_NAME_NOTION_LINKIFIES = re.compile(r"(?<![\w/.-])([\w./-]*\w\.(?:md|py|sh)(?::\d+(?:-\d+)?)?)(?![\w`])")
CHUNK_BOUNDARY_LEVEL: Final = 2
OPENING_SECTION_LABEL: Final = "the opening section, before the first level 1 or 2 heading"
EMPTY_BLOCK: Final = "<empty-block/>"
BLOCK_COLOR: Final[Mapping[ToneName, str]] = {
    "neutral": "gray",
    "muted": "gray",
    "info": "blue",
    "success": "green",
    "warning": "yellow",
    "danger": "red",
    "accent": "purple",
    "teal": "green",
    "sky": "blue",
}


def _escape(text: str) -> str:
    return text.translate(NOTION_ESCAPES)


class _NotionRuns(MarkupRuns):
    def __init__(self) -> None:
        super().__init__(_escape)

    def text(self, text: str, /) -> str:
        pieces = FILE_NAME_NOTION_LINKIFIES.split(text)
        return bang_cannot_open_an_image(
            "".join(self.code(piece) if index % 2 else _escape(piece) for index, piece in enumerate(pieces))
        )

    def code(self, text: str, /) -> str:
        return _escape(text) if "`" in text else f"`{text}`"

    def anchor_link(self, label: str, _anchor: str, /) -> str:
        return label

    def placeholder(self, name: str, /) -> str:
        return f'<span color="yellow_bg">{_escape("{{" + name + "}}")}</span>'


def notion_inline(runs: Rich) -> str:
    return write_runs(runs, _NotionRuns())


def _block_text(runs: Rich) -> str:
    return escape_block_start(notion_inline(runs))


def _color_attribute(tone: ToneName | None, suffix: str = "") -> str:
    return f' color="{BLOCK_COLOR[tone]}{suffix}"' if tone else ""


def _trailing_color(tone: ToneName | None) -> str:
    return f' {{color="{BLOCK_COLOR[tone]}"}}' if tone else ""


def _indent(lines: Sequence[str], depth: int = 1) -> list[str]:
    return indent_lines(lines, "\t" * depth)


def _list_lines(node: ListNode) -> list[str]:
    lines: list[str] = []
    for index, entry in enumerate(node.entries, start=1):
        match node.kind:
            case "bullet":
                marker = "-"
            case "number":
                marker = f"{index}."
            case "check":
                marker = "- [x]" if entry.checked else "- [ ]"
            case _:
                assert_never(node.kind)
        lines.append(f"{marker} {_block_text(entry.text)}{_trailing_color(entry.tone)}")
        lines += _indent(_notion_blocks(entry.children))
    return lines


def _quote_line(node: Quote) -> str:
    body = "<br>".join(_block_text(line) for line in node.lines)
    if node.cite:
        body += "<br>" + styled("italic", notion_inline(node.cite))
    return f"> {body}"


def _toggle_lines(node: Toggle) -> list[str]:
    children = _indent(_notion_blocks(node.children))
    if node.heading_level is not None:
        return [f'{"#" * node.heading_level} {notion_inline(node.title)} {{toggle="true"}}', *children]
    return ["<details>", f"<summary>{notion_inline(node.title)}</summary>", *children, "</details>"]


def _notion_lines(node: Node) -> list[str]:
    match node:
        case Heading():
            return [f"{'#' * node.level} {notion_inline(node.text)}"]
        case Paragraph():
            text = _block_text(node.text)
            return [text + _trailing_color(node.tone)] if text else []
        case ListNode():
            return _list_lines(node)
        case CodeBlock():
            return code_block_lines(node)
        case Callout():
            opening = f'<callout icon="{CALLOUT_ICON[node.tone]}"{_color_attribute(node.tone, "_bg")}>'
            return [opening, *_indent(_notion_blocks(node.children)), "</callout>"]
        case Quote():
            return [_quote_line(node)]
        case Toggle():
            return _toggle_lines(node)
        case TableOfContents():
            return ["<table_of_contents/>"]
        case _:
            assert_never(node)


def _list_kind(node: Node) -> ListKind | None:
    return node.kind if isinstance(node, ListNode) else None


def _notion_blocks(nodes: Sequence[Node]) -> list[str]:
    lines: list[str] = []
    previous_kind: ListKind | None = None
    for node in nodes:
        node_lines = _notion_lines(node)
        if not node_lines:
            continue
        kind = _list_kind(node)
        if kind is not None and kind == previous_kind:
            lines.append(EMPTY_BLOCK)
        lines += node_lines
        previous_kind = kind
    return lines


def _page(lines: Sequence[str]) -> str:
    return "\n".join(lines) + "\n"


def render_notion(nodes: Sequence[Node]) -> str:
    return _page(_notion_blocks(nodes))


def _starts_a_chunk(node: Node) -> bool:
    if isinstance(node, Heading):
        return node.level <= CHUNK_BOUNDARY_LEVEL
    return (
        isinstance(node, Toggle)
        and node.heading_level is not None
        and node.heading_level <= CHUNK_BOUNDARY_LEVEL
    )


def _section_label(section: Sequence[Node]) -> str:
    match section[0] if section else None:
        case Heading(level=level, text=title) if level <= CHUNK_BOUNDARY_LEVEL:
            return f"{'#' * level} {visible_text(title)}"
        case Toggle(heading_level=int(level), title=title) if level <= CHUNK_BOUNDARY_LEVEL:
            return f"{'#' * level} {visible_text(title)}"
        case _:
            return OPENING_SECTION_LABEL


@dataclass(frozen=True)
class NotionChunks:
    chunks: tuple[str, ...]
    oversized_sections: tuple[str, ...]


def chunk_notion(nodes: Sequence[Node], limit: int) -> NotionChunks:
    sections: list[list[Node]] = [[]]
    for node in nodes:
        if _starts_a_chunk(node) and sections[-1]:
            sections.append([])
        sections[-1].append(node)
    chunks: list[str] = []
    oversized: list[str] = []
    current_chunk = ""
    for section in sections:
        lines = _notion_blocks(section)
        if not lines:
            continue
        text = _page(lines)
        if len(text) > limit:
            oversized.append(_section_label(section))
        if current_chunk and len(current_chunk) + len(text) > limit:
            chunks.append(current_chunk)
            current_chunk = ""
        current_chunk += text
    if current_chunk:
        chunks.append(current_chunk)
    return NotionChunks(tuple(chunks) or (render_notion(nodes),), tuple(oversized))
