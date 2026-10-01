import re
from collections.abc import Sequence
from dataclasses import dataclass

from typing_extensions import assert_never

from skaldr.export.markup import (
    CALLOUT_ICON,
    TAB_ICON,
    bold_once,
    code_block_lines,
    escape_block_start,
    indent_lines,
    styled,
)
from skaldr.export.mermaid import mermaid_fence_lines
from skaldr.export.tree import (
    Callout,
    CodeBlock,
    Columns,
    Diagram,
    Heading,
    ListNode,
    Node,
    Paragraph,
    Quote,
    Table,
    TableCell,
    TableOfContents,
    TableRow,
    Tabs,
    Toggle,
    ToneName,
)
from skaldr.models import BadgeColor
from skaldr.richtext import Chip, Citation, Rich, StyleName, write_runs

NOTION_ESCAPED = frozenset("\\*~`$[]<>{}|^")
NOTION_WEB_DOMAIN_FILE = re.compile(r"(?<![\w/.-])([\w./-]*\w\.(?:md|py|sh)(?::\d+(?:-\d+)?)?)(?![\w`])")
SPACED_PLUS_AFTER_CODE = re.compile(r"` \+ ")
FULL_WIDTH_PLUS = "\N{FULLWIDTH PLUS SIGN}"
CHUNK_BOUNDARY_LEVEL = 2
BLOCK_COLOR: dict[ToneName, str] = {
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
CHIP_COLOR: dict[BadgeColor, str] = {
    "slate": "gray",
    "blue": "blue",
    "green": "green",
    "amber": "yellow",
    "red": "red",
    "violet": "purple",
    "teal": "green",
    "sky": "blue",
}


def escape_notion_text(text: str) -> str:
    return "".join("\\" + character if character in NOTION_ESCAPED else character for character in text)


class _NotionRuns:
    def text(self, text: str) -> str:
        pieces = NOTION_WEB_DOMAIN_FILE.split(text)
        return "".join(
            self.code(piece) if index % 2 else escape_notion_text(piece) for index, piece in enumerate(pieces)
        )

    def code(self, text: str) -> str:
        return escape_notion_text(text) if "`" in text else f"`{text}`"

    def link(self, label: str, url: str) -> str:
        return f"[{label}]({url})"

    def anchor_link(self, label: str, _anchor: str, /) -> str:
        return label

    def citation(self, run: Citation) -> str:
        label = escape_notion_text(f"[{run.number}]")
        return f"[{label}]({run.url})" if run.url else label

    def placeholder(self, name: str) -> str:
        return f'<span color="yellow_bg">{escape_notion_text("{{" + name + "}}")}</span>'

    def chip(self, run: Chip) -> str:
        return f'<span color="{CHIP_COLOR[run.tone]}_bg">{escape_notion_text(run.label)}</span>'

    def line_break(self) -> str:
        return "<br>"

    def styled(self, style: StyleName, inner: str) -> str:
        return styled(style, inner)


def notion_inline(runs: Rich) -> str:
    return write_runs(runs, _NotionRuns())


def _block_text(runs: Rich) -> str:
    return escape_block_start(notion_inline(runs))


def _color(tone: ToneName | None, suffix: str = "") -> str:
    return f' color="{BLOCK_COLOR[tone]}{suffix}"' if tone else ""


def _block_color(tone: ToneName | None) -> str:
    return f' {{color="{BLOCK_COLOR[tone]}"}}' if tone else ""


def _indent(lines: Sequence[str], depth: int = 1) -> list[str]:
    return indent_lines(lines, "\t" * depth)


def _table_cell_text(cell: TableCell) -> str:
    return escape_block_start(SPACED_PLUS_AFTER_CODE.sub(f"` {FULL_WIDTH_PLUS} ", notion_inline(cell.text)))


def _table_row_lines(row: TableRow) -> list[str]:
    tone = "neutral" if row.tone is None and row.emphasis == "group" else row.tone
    texts = [_table_cell_text(cell) for cell in row.cells]
    if row.emphasis == "total":
        texts = [bold_once(text) for text in texts]
    cells = [
        f"<td{_color(cell.tone, '_bg')}>{text}</td>" for cell, text in zip(row.cells, texts, strict=True)
    ]
    return [f"<tr{_color(tone, '_bg')}>", *_indent(cells), "</tr>"]


def _table_lines(table: Table) -> list[str]:
    attributes = ' fit-page-width="true" header-row="true"'
    if table.header_column:
        attributes += ' header-column="true"'
    header = TableRow(table.header, emphasis="total")
    rows = [line for row in (header, *table.rows) for line in _table_row_lines(row)]
    return [f"<table{attributes}>", *_indent(rows), "</table>"]


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
        lines.append(f"{marker} {_block_text(entry.text)}{_block_color(entry.tone)}")
        lines += _indent(notion_blocks(entry.children))
    return lines


def _quote_line(node: Quote) -> str:
    body = "<br>".join(_block_text(line) for line in node.lines)
    if node.cite:
        body += "<br>" + styled("italic", notion_inline(node.cite))
    return f"> {body}"


def _toggle_lines(node: Toggle) -> list[str]:
    children = _indent(notion_blocks(node.children))
    if node.heading_level is not None:
        return [f'{"#" * node.heading_level} {notion_inline(node.title)} {{toggle="true"}}', *children]
    return ["<details>", f"<summary>{notion_inline(node.title)}</summary>", *children, "</details>"]


def _columns_lines(node: Columns) -> list[str]:
    lines: list[str] = []
    for column in node.columns:
        lines += [f'<column ratio="{column.ratio}">', *_indent(notion_blocks(column.children)), "</column>"]
    return ["<columns>", *_indent(lines), "</columns>"]


def _tabs_lines(node: Tabs) -> list[str]:
    lines: list[str] = []
    for tab in node.tabs:
        icon = TAB_ICON.get(tab.tone) if tab.tone else None
        lines.append(f'<tab icon="{icon}">' if icon else "<tab>")
        lines += [*_indent([notion_inline(tab.title), *notion_blocks(tab.children)]), "</tab>"]
    return ["<tabs>", *_indent(lines), "</tabs>"]


def notion_lines(node: Node) -> list[str]:
    match node:
        case Heading():
            return [f"{'#' * node.level} {notion_inline(node.text)}"]
        case Paragraph():
            text = _block_text(node.text)
            return [text + _block_color(node.tone)] if text else []
        case ListNode():
            return _list_lines(node)
        case Table():
            return _table_lines(node)
        case CodeBlock():
            return code_block_lines(node)
        case Callout():
            opening = f'<callout icon="{CALLOUT_ICON[node.tone]}"{_color(node.tone, "_bg")}>'
            return [opening, *_indent(notion_blocks(node.children)), "</callout>"]
        case Quote():
            return [_quote_line(node)]
        case Toggle():
            return _toggle_lines(node)
        case Columns():
            return _columns_lines(node)
        case Tabs():
            return _tabs_lines(node)
        case Diagram():
            return [*mermaid_fence_lines(node.figure), *notion_blocks(node.supplement)]
        case TableOfContents():
            return ["<table_of_contents/>"]
        case _:
            assert_never(node)


def notion_blocks(nodes: Sequence[Node]) -> list[str]:
    return [line for node in nodes for line in notion_lines(node)]


def render_notion(nodes: Sequence[Node]) -> str:
    return "\n".join(notion_blocks(nodes)) + "\n"


def _starts_a_chunk(node: Node) -> bool:
    if isinstance(node, Heading):
        return node.level <= CHUNK_BOUNDARY_LEVEL
    return (
        isinstance(node, Toggle)
        and node.heading_level is not None
        and node.heading_level <= CHUNK_BOUNDARY_LEVEL
    )


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
        text = render_notion(section)
        if len(text) > limit:
            oversized.append(text.split("\n", 1)[0])
        if current_chunk and len(current_chunk) + len(text) > limit:
            chunks.append(current_chunk)
            current_chunk = ""
        current_chunk += text
    if current_chunk:
        chunks.append(current_chunk)
    return NotionChunks(tuple(chunks), tuple(oversized))
