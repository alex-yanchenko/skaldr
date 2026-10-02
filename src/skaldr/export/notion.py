import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from typing_extensions import assert_never

from skaldr.export.markup import (
    CALLOUT_ICON,
    MarkupRuns,
    bang_cannot_open_an_image,
    body_cell_texts,
    code_block_lines,
    escape_block_start,
    indent_lines,
    styled,
    tab_icon,
)
from skaldr.export.mermaid import mermaid_fence_lines
from skaldr.export.runs import Chip, ExportRich, export_visible_text, write_export_runs
from skaldr.export.tree import (
    Callout,
    CodeBlock,
    Columns,
    Diagram,
    DisplayMath,
    Heading,
    ListKind,
    ListNode,
    Node,
    Paragraph,
    Quote,
    TableCell,
    TableNode,
    TableOfContents,
    TableRow,
    Tabs,
    Toggle,
    ToneName,
    heading_of,
)
from skaldr.models import BADGE_COLOR_TONE, BadgeColorLiteral, ToneLiteral
from skaldr.richtext import ScriptPosition

NOTION_ESCAPES: Final = str.maketrans({character: "\\" + character for character in "\\*~`$[]<>{}|^"})
FILE_NAME_NOTION_LINKIFIES = re.compile(r"(?<![\w/.-])([\w./-]*\w\.(?:md|py|sh)(?::\d+(?:-\d+)?)?)(?![\w`])")
SPACED_PLUS_AFTER_CODE: Final = re.compile(r"` \+ ")
FULL_WIDTH_PLUS: Final = "\N{FULLWIDTH PLUS SIGN}"
CHUNK_BOUNDARY_LEVEL: Final = 2
OPENING_SECTION_LABEL: Final = "the opening section, before the first level 1 or 2 heading"
EMPTY_BLOCK: Final = "<empty-block/>"
EQUATION_FENCE: Final = "$$"
BACKGROUND_SUFFIX: Final = "_bg"
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
CHIP_COLOR: Final[Mapping[BadgeColorLiteral, str]] = {
    color: BLOCK_COLOR[tone] for color, tone in BADGE_COLOR_TONE.items()
}
LATEX_SCRIPT_OPERATOR: Final[Mapping[ScriptPosition, str]] = {"subscript": "_", "superscript": "^"}
LATEX_TEXT_ESCAPES: Final = str.maketrans(
    {
        "\\": "\\textbackslash{}",
        "^": "\\textasciicircum{}",
        "~": "\\textasciitilde{}",
        **{character: "\\" + character for character in "{}$&#%_"},
    }
)


def latex_text(text: str) -> str:
    return "\\text{" + text.translate(LATEX_TEXT_ESCAPES) + "}"


class _NotionRuns(MarkupRuns):
    def escape(self, text: str, /) -> str:
        return text.translate(NOTION_ESCAPES)

    def text(self, text: str, /) -> str:
        pieces = FILE_NAME_NOTION_LINKIFIES.split(text)
        return bang_cannot_open_an_image(
            "".join(self._piece(index, piece) for index, piece in enumerate(pieces))
        )

    def _piece(self, index: int, piece: str) -> str:
        is_file_name = index % 2 == 1
        return self.code(piece) if is_file_name else self.escape(piece)

    def code(self, text: str, /) -> str:
        return self.escape(text) if "`" in text else f"`{text}`"

    def anchor_link(self, label: str, _anchor: str, /) -> str:
        return label

    def placeholder(self, name: str, /) -> str:
        return f'<span color="yellow_bg">{self.escape("{{" + name + "}}")}</span>'

    def chip(self, run: Chip, /) -> str:
        return f'<span color="{CHIP_COLOR[run.tone]}_bg">{self.text(run.label)}</span>'

    def underline(self, inner: str, /) -> str:
        return f'<span underline="true">{inner}</span>'

    def script(self, position: ScriptPosition, text: str, /) -> str:
        return self.math(LATEX_SCRIPT_OPERATOR[position] + "{" + latex_text(text) + "}")

    def tinted(self, tone: ToneLiteral | None, background: ToneLiteral | None, inner: str, /) -> str:
        highlighted = (
            _colored_span(BLOCK_COLOR[background] + BACKGROUND_SUFFIX, inner) if background else inner
        )
        return _colored_span(BLOCK_COLOR[tone], highlighted) if tone else highlighted


def _colored_span(color: str, inner: str) -> str:
    return f'<span color="{color}">{inner}</span>'


def notion_inline(runs: ExportRich) -> str:
    return write_export_runs(runs, _NotionRuns())


def _block_text(runs: ExportRich) -> str:
    return escape_block_start(notion_inline(runs))


def _color_attribute(tone: ToneName, suffix: str = "") -> str:
    return f' color="{BLOCK_COLOR[tone]}{suffix}"'


def _trailing_color(tone: ToneName | None) -> str:
    return f' {{color="{BLOCK_COLOR[tone]}"}}' if tone else ""


def _indent(lines: Sequence[str], depth: int = 1) -> list[str]:
    return indent_lines(lines, "\t" * depth)


def _plus_after_code_that_notion_cannot_read_as_a_bullet(text: str) -> str:
    return SPACED_PLUS_AFTER_CODE.sub(f"` {FULL_WIDTH_PLUS} ", text)


def _table_cell_text(cell: TableCell) -> str:
    return escape_block_start(_plus_after_code_that_notion_cannot_read_as_a_bullet(notion_inline(cell.text)))


def _background_attribute(tone: ToneName | None) -> str:
    return _color_attribute(tone, BACKGROUND_SUFFIX) if tone else ""


def _row_lines(cells: Sequence[TableCell], texts: Sequence[str], tone: ToneName | None) -> list[str]:
    tagged = [
        f"<td{_background_attribute(cell.tone)}>{text}</td>" for cell, text in zip(cells, texts, strict=True)
    ]
    return [f"<tr{_background_attribute(tone)}>", *_indent(tagged), "</tr>"]


def _body_row_lines(table: TableNode, row: TableRow) -> list[str]:
    texts = body_cell_texts(table, row, [_table_cell_text(cell) for cell in row.cells])
    tone = "neutral" if row.tone is None and row.emphasis == "group" else row.tone
    return _row_lines(row.cells, texts, tone)


def _table_lines(table: TableNode) -> list[str]:
    attributes = ['fit-page-width="true"', 'header-row="true"']
    if table.header_column:
        attributes.append('header-column="true"')
    header_texts = [styled("bold", _table_cell_text(cell)) for cell in table.header]
    rows = _row_lines(table.header, header_texts, None)
    rows += [line for row in table.rows for line in _body_row_lines(table, row)]
    return [f"<table {' '.join(attributes)}>", *_indent(rows), "</table>"]


def _list_marker(kind: ListKind, index: int, checked: bool) -> str:
    match kind:
        case "bullet":
            return "-"
        case "number":
            return f"{index}."
        case "check":
            return "- [x]" if checked else "- [ ]"
        case _:
            assert_never(kind)


def _list_lines(node: ListNode) -> list[str]:
    lines: list[str] = []
    for index, entry in enumerate(node.entries, start=1):
        marker = _list_marker(node.kind, index, entry.checked)
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


def _columns_lines(node: Columns) -> list[str]:
    lines: list[str] = []
    for column in node.columns:
        lines += [f'<column ratio="{column.ratio}">', *_indent(_notion_blocks(column.children)), "</column>"]
    return ["<columns>", *_indent(lines), "</columns>"]


def _tabs_lines(node: Tabs) -> list[str]:
    lines: list[str] = []
    for tab in node.tabs:
        icon = tab_icon(tab.tone)
        lines.append(f'<tab icon="{icon}">' if icon else "<tab>")
        lines += [*_indent([_block_text(tab.title), *_notion_blocks(tab.children)]), "</tab>"]
    return ["<tabs>", *_indent(lines), "</tabs>"]


def _notion_lines(node: Node) -> list[str]:
    match node:
        case Heading():
            return [f"{'#' * node.level} {notion_inline(node.text)}"]
        case Paragraph():
            text = _block_text(node.text)
            return [text + _trailing_color(node.tone)] if text else []
        case ListNode():
            return _list_lines(node)
        case TableNode():
            return _table_lines(node)
        case CodeBlock():
            return code_block_lines(node)
        case DisplayMath():
            return [EQUATION_FENCE, *node.expression.split("\n"), EQUATION_FENCE]
        case Callout():
            opening = (
                f'<callout icon="{CALLOUT_ICON[node.tone]}"{_color_attribute(node.tone, BACKGROUND_SUFFIX)}>'
            )
            return [opening, *_indent(_notion_blocks(node.children)), "</callout>"]
        case Quote():
            return [_quote_line(node)]
        case Toggle():
            return _toggle_lines(node)
        case Columns():
            return _columns_lines(node)
        case Tabs():
            return _tabs_lines(node)
        case Diagram():
            return [*mermaid_fence_lines(node.figure), *_notion_blocks(node.supplement)]
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


def _chunk_heading(node: Node) -> Heading | None:
    heading = heading_of(node)
    return heading if heading is not None and heading.level <= CHUNK_BOUNDARY_LEVEL else None


def _section_label(section: Sequence[Node]) -> str:
    heading = _chunk_heading(section[0]) if section else None
    return f"{'#' * heading.level} {export_visible_text(heading.text)}" if heading else OPENING_SECTION_LABEL


@dataclass(frozen=True)
class NotionChunks:
    chunks: tuple[str, ...]
    oversized_sections: tuple[str, ...]


def chunk_notion(nodes: Sequence[Node], limit: int) -> NotionChunks:
    sections: list[list[Node]] = [[]]
    for node in nodes:
        if _chunk_heading(node) is not None and sections[-1]:
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
