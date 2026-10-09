import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Final

from typing_extensions import assert_never

from skaldr.export.apportion import apportioned
from skaldr.export.budget import Budget, Cost, RenderedBlock
from skaldr.export.glyphs import CALLOUT_ICON, tab_icon
from skaldr.export.markup import (
    DIVIDER_LINE,
    MarkupRuns,
    bang_cannot_open_an_image,
    body_cell_texts,
    code_block_lines,
    escape_block_start,
    indent_lines,
    is_emphasised_body_cell,
    styled,
)
from skaldr.export.mermaid import mermaid_fence_lines
from skaldr.export.runs import Chip, ExportRich, export_visible_text, holds_a_chip, write_export_runs
from skaldr.export.tree import (
    COLUMN_RATIO_TOTAL,
    Callout,
    CodeBlock,
    Columns,
    Diagram,
    DisplayMath,
    Divider,
    Heading,
    HeadingLevel,
    ListKind,
    ListNode,
    Node,
    Paragraph,
    Quote,
    Region,
    TableCell,
    TableNode,
    TableOfContents,
    TableRow,
    Tabs,
    Toggle,
    ToneName,
    heading_of,
)
from skaldr.models import BADGE_COLOR_TONE, BadgeColorLiteral, NotionWidth, ToneLiteral
from skaldr.richtext import ScriptPosition

NOTION_ESCAPES: Final = str.maketrans({character: "\\" + character for character in "\\*_~`$[]<>{}|^="})
FILE_NAME_NOTION_LINKIFIES = re.compile(r"(?<![\w/.-])([\w./-]*\w\.(?:md|py|sh)(?::\d+(?:-\d+)?)?)(?![\w`])")
SPACED_PLUS_AFTER_CODE: Final = re.compile(r"` \+ ")
FULL_WIDTH_PLUS: Final = "\N{FULLWIDTH PLUS SIGN}"
CLOSING_TAG_OPENER: Final = "</"
CHUNK_BOUNDARY_LEVEL: Final = 2
DEEPEST_NOTION_HEADING: Final = 4
NOTION_LIST_START: Final = 1
OPENING_SECTION_LABEL: Final = "the opening section, before the first level 1 or 2 heading"
EMPTY_BLOCK: Final = "<empty-block/>"
EQUATION_FENCE: Final = "$$"
NOTION_PLAIN_TEXT_LANGUAGE: Final = "plain text"
NOTION_DEFAULT_PAGE_WIDTH_PX: Final = 708
NOTION_FULL_PAGE_WIDTH_PX: Final = 1200
NOTION_PAGE_WIDTH_PX: Final[Mapping[NotionWidth, int]] = {
    "normal": NOTION_DEFAULT_PAGE_WIDTH_PX,
    "full": NOTION_FULL_PAGE_WIDTH_PX,
}
NARROWEST_COLUMN_CHARACTERS: Final = 8
NARROWEST_COLUMN_PX: Final = 64
WIDEST_COLUMN_CHARACTERS: Final = 60
BACKGROUND_SUFFIX: Final = "_bg"
BLOCK_COLOR: Final[Mapping[ToneName, str]] = {
    "neutral": "gray",
    "muted": "gray",
    "info": "blue",
    "success": "green",
    "warning": "yellow",
    "danger": "red",
    "accent": "purple",
    "teal": "brown",
    "sky": "pink",
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


@dataclass(frozen=True)
class TableRoom:
    width: int
    sizes_every_table: bool

    @classmethod
    def on_page(cls, page_width: NotionWidth) -> "TableRoom":
        return cls(NOTION_PAGE_WIDTH_PX[page_width], sizes_every_table=page_width == "full")

    def within(self, ratio: int) -> "TableRoom":
        if not self.sizes_every_table:
            return self
        return replace(self, width=round(self.width * ratio / COLUMN_RATIO_TOTAL))


def latex_text(text: str) -> str:
    return "\\text{" + text.translate(LATEX_TEXT_ESCAPES) + "}"


@dataclass(frozen=True)
class _NotionRuns(MarkupRuns):
    inside_bold: bool = False
    on_fill: bool = False

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
        return self.escape(text) if "`" in text or CLOSING_TAG_OPENER in text else f"`{text}`"

    def anchor_link(self, label: str, _anchor: str, /) -> str:
        return label

    def placeholder(self, name: str, /) -> str:
        return f'<span color="yellow_bg">{self.escape("{{" + name + "}}")}</span>'

    def chip(self, run: Chip, /) -> str:
        label = self.text(run.label)
        bolded = label if self.inside_bold else styled("bold", label)
        return bolded if self.on_fill else _colored_span(CHIP_COLOR[run.tone], bolded)

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


def notion_inline(runs: ExportRich, *, inside_bold: bool = False, on_fill: bool = False) -> str:
    return write_export_runs(runs, _NotionRuns(inside_bold, on_fill))


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


def _table_cell_text(cell: TableCell, *, inside_bold: bool, on_fill: bool = False) -> str:
    text = notion_inline(cell.text, inside_bold=inside_bold, on_fill=on_fill)
    return escape_block_start(_plus_after_code_that_notion_cannot_read_as_a_bullet(text))


def _background_attribute(tone: ToneName | None) -> str:
    return _color_attribute(tone, BACKGROUND_SUFFIX) if tone else ""


def _row_lines(cells: Sequence[TableCell], texts: Sequence[str], tone: ToneName | None) -> list[str]:
    tagged = [
        f"<td{_background_attribute(cell.tone)}>{text}</td>" for cell, text in zip(cells, texts, strict=True)
    ]
    return [f"<tr{_background_attribute(tone)}>", *_indent(tagged), "</tr>"]


def _row_tone_in_one_cell(cells: Sequence[TableCell], tone: ToneName) -> tuple[TableCell, ...]:
    filled = next((index for index, cell in enumerate(cells) if holds_a_chip(cell.text)), 0)
    return tuple(
        replace(cell, tone=cell.tone or tone) if index == filled else cell for index, cell in enumerate(cells)
    )


def _column_tones(table: TableNode) -> list[ToneName | None]:
    return [column.tone for column in table.columns] or [None] * len(table.header)


def _in_a_toned_column(column_tones: Sequence[ToneName | None], index: int) -> bool:
    return index < len(column_tones) and column_tones[index] is not None


def _body_row_lines(table: TableNode, row: TableRow) -> list[str]:
    band = (row.tone or "neutral") if row.emphasis == "group" else None
    cells = _row_tone_in_one_cell(row.cells, row.tone) if row.tone and band is None else row.cells
    column_tones = _column_tones(table)
    texts = body_cell_texts(
        table,
        row,
        [
            _table_cell_text(
                cell,
                inside_bold=is_emphasised_body_cell(table, row, index),
                on_fill=band is not None or cell.tone is not None or _in_a_toned_column(column_tones, index),
            )
            for index, cell in enumerate(cells)
        ],
    )
    return _row_lines(cells, texts, band)


def _longest_text(table: TableNode, index: int) -> int:
    cells = [table.header, *(row.cells for row in table.rows)]
    return max((len(export_visible_text(row[index].text)) for row in cells if index < len(row)), default=0)


def _content_weight(table: TableNode, index: int) -> int:
    return max(NARROWEST_COLUMN_CHARACTERS, min(WIDEST_COLUMN_CHARACTERS, _longest_text(table, index)))


def _column_widths(table: TableNode, room: TableRoom) -> Sequence[int | None]:
    shares = [column.share for column in table.columns] or [None] * len(table.header)
    auto_count = shares.count(None)
    if auto_count == len(shares):
        if not room.sizes_every_table:
            return [None] * len(shares)
        return _readable_widths([_content_weight(table, index) for index in range(len(shares))], room.width)
    if not room.sizes_every_table:
        auto_share = (1 - sum(share or 0 for share in shares)) / auto_count if auto_count else 0.0
        return apportioned([auto_share if share is None else share for share in shares], room.width)
    return _readable_widths(_shares_with_the_rest_by_text(table, shares), room.width)


def _shares_with_the_rest_by_text(table: TableNode, shares: Sequence[float | None]) -> list[float]:
    rest = max(0.0, 1 - sum(share or 0 for share in shares))
    text_weights = {
        index: _content_weight(table, index) for index, share in enumerate(shares) if share is None
    }
    text_total = sum(text_weights.values()) or 1
    return [
        share if share is not None else rest * text_weights[index] / text_total
        for index, share in enumerate(shares)
    ]


def _readable_widths(weights: Sequence[float], width: int) -> list[int]:
    floored: set[int] = set()
    while True:
        free = [index for index in range(len(weights)) if index not in floored]
        shared = apportioned([weights[index] for index in free], width - NARROWEST_COLUMN_PX * len(floored))
        too_narrow = {index for index, part in zip(free, shared, strict=True) if part < NARROWEST_COLUMN_PX}
        if not too_narrow:
            widths = dict.fromkeys(floored, NARROWEST_COLUMN_PX) | dict(zip(free, shared, strict=True))
            return [widths[index] for index in range(len(weights))]
        floored |= too_narrow


def _width_attribute(width: int | None) -> str:
    return "" if width is None else f' width="{width}"'


def _colgroup_lines(table: TableNode, room: TableRoom) -> list[str]:
    tones = _column_tones(table)
    widths = _column_widths(table, room)
    if not any(tones) and all(width is None for width in widths):
        return []
    cols = [
        f"<col{_background_attribute(tone)}{_width_attribute(width)}>"
        for tone, width in zip(tones, widths, strict=True)
    ]
    return ["<colgroup>", *_indent(cols), "</colgroup>"]


def _table_lines(table: TableNode, room: TableRoom) -> list[str]:
    attributes = ['fit-page-width="true"', 'header-row="true"']
    if table.header_column:
        attributes.append('header-column="true"')
    header_texts = [styled("bold", _table_cell_text(cell, inside_bold=True)) for cell in table.header]
    lines = _colgroup_lines(table, room) + _row_lines(table.header, header_texts, None)
    lines += [line for row in table.rows for line in _body_row_lines(table, row)]
    return [f"<table {' '.join(attributes)}>", *_indent(lines), "</table>"]


def _numbers_as_bullets(node: ListNode) -> bool:
    return node.kind == "number" and node.start != NOTION_LIST_START


def _written_kind(node: ListNode) -> ListKind:
    return "bullet" if _numbers_as_bullets(node) else node.kind


def _list_marker(node: ListNode, index: int, checked: bool) -> str:
    match node.kind:
        case "bullet":
            return "-"
        case "number":
            return f"- {index}\\." if _numbers_as_bullets(node) else f"{index}."
        case "check":
            return "- [x]" if checked else "- [ ]"
        case _:
            assert_never(node.kind)


def _list_lines(node: ListNode, room: TableRoom) -> list[str]:
    lines: list[str] = []
    for index, entry in enumerate(node.entries, start=node.start):
        marker = _list_marker(node, index, entry.checked)
        lines.append(f"{marker} {_block_text(entry.text)}")
        lines += _indent(_notion_blocks(entry.children, room))
    return lines


def _quote_line(node: Quote) -> str:
    body = "<br>".join(_block_text(line) for line in node.lines)
    if node.cite:
        body += "<br>" + styled("italic", notion_inline(node.cite))
    return f"> {body}"


def _heading_marks(level: HeadingLevel) -> str:
    return "#" * min(level, DEEPEST_NOTION_HEADING)


def _toggle_lines(node: Toggle, room: TableRoom) -> list[str]:
    children = _indent(_notion_blocks(node.children, room))
    if node.heading_level is not None:
        return [
            f'{_heading_marks(node.heading_level)} {notion_inline(node.title)} {{toggle="true"}}',
            *children,
        ]
    return ["<details>", f"<summary>{notion_inline(node.title)}</summary>", *children, "</details>"]


def _columns_lines(node: Columns, room: TableRoom) -> list[str]:
    lines: list[str] = []
    for column in node.columns:
        children = _notion_blocks(column.children, room.within(column.ratio))
        lines += [f'<column ratio="{column.ratio}">', *_indent(children), "</column>"]
    return ["<columns>", *_indent(lines), "</columns>"]


def _tabs_lines(node: Tabs, room: TableRoom) -> list[str]:
    lines: list[str] = []
    for tab in node.tabs:
        icon = tab_icon(tab.tone)
        lines.append(f'<tab icon="{icon}">' if icon else "<tab>")
        lines += [*_indent([_block_text(tab.title), *_notion_blocks(tab.children, room)]), "</tab>"]
    return ["<tabs>", *_indent(lines), "</tabs>"]


def _notion_lines(node: Node, room: TableRoom) -> list[str]:
    match node:
        case Heading():
            return [f"{_heading_marks(node.level)} {notion_inline(node.text)}"]
        case Paragraph():
            text = _block_text(node.text)
            return [text + _trailing_color(node.tone)] if text else []
        case ListNode():
            return _list_lines(node, room)
        case TableNode():
            return _table_lines(node, room)
        case CodeBlock():
            return code_block_lines(replace(node, language=node.language or NOTION_PLAIN_TEXT_LANGUAGE))
        case DisplayMath():
            return [EQUATION_FENCE, *node.expression.split("\n"), EQUATION_FENCE]
        case Callout():
            icon = node.icon or CALLOUT_ICON[node.tone]
            opening = f'<callout icon="{icon}"{_color_attribute(node.tone, BACKGROUND_SUFFIX)}>'
            return [opening, *_indent(_notion_blocks(node.children, room)), "</callout>"]
        case Quote():
            return [_quote_line(node)]
        case Divider():
            return [DIVIDER_LINE]
        case Toggle():
            return _toggle_lines(node, room)
        case Columns():
            return _columns_lines(node, room)
        case Tabs():
            return _tabs_lines(node, room)
        case Diagram():
            return [*mermaid_fence_lines(node.figure), *_notion_blocks(node.supplement, room)]
        case TableOfContents():
            return ["<table_of_contents/>"]
        case _:
            assert_never(node)


def _list_kind(node: Node) -> ListKind | None:
    return _written_kind(node) if isinstance(node, ListNode) else None


def _notion_blocks(nodes: Sequence[Node], room: TableRoom) -> list[str]:
    return [line for block in _rendered_blocks(nodes, room) for line in block.lines]


def _page(lines: Sequence[str]) -> str:
    return "\n".join(lines) + "\n"


def render_notion(nodes: Sequence[Node], page_width: NotionWidth = "normal") -> str:
    return _page(_notion_blocks(nodes, TableRoom.on_page(page_width)))


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


@dataclass(frozen=True)
class _Piece:
    text: str
    cost: Cost


def _sections(regions: Sequence[Region]) -> list[list[Node]]:
    sections: list[list[Node]] = [[]]
    for region in regions:
        for node in region.nodes:
            if _chunk_heading(node) is not None and sections[-1]:
                sections.append([])
            sections[-1].append(node)
    return sections


def chunk_notion(
    regions: Sequence[Region], budget: Budget, page_width: NotionWidth = "normal"
) -> NotionChunks:
    room = TableRoom.on_page(page_width)
    sections = _sections(regions)
    chunks: list[str] = []
    oversized: list[str] = []
    current_chunk = _Piece("", budget.nothing)
    for section in sections:
        pieces = _section_pieces(_rendered_blocks(section, room), budget)
        if any(not budget.allows(piece.cost) for piece in pieces):
            oversized.append(_section_label(section))
        for piece in pieces:
            if current_chunk.text and not budget.allows(current_chunk.cost + piece.cost):
                chunks.append(current_chunk.text)
                current_chunk = _Piece("", budget.nothing)
            current_chunk = _Piece(current_chunk.text + piece.text, current_chunk.cost + piece.cost)
    if current_chunk.text:
        chunks.append(current_chunk.text)
    whole_page = render_notion([node for section in sections for node in section], page_width)
    return NotionChunks(tuple(chunks) or (whole_page,), tuple(oversized))


def _rendered_blocks(nodes: Sequence[Node], room: TableRoom) -> list[RenderedBlock]:
    blocks: list[RenderedBlock] = []
    previous_kind: ListKind | None = None
    for node in nodes:
        node_lines = _notion_lines(node, room)
        if not node_lines:
            continue
        kind = _list_kind(node)
        separator = [EMPTY_BLOCK] if kind is not None and kind == previous_kind else []
        blocks.append(RenderedBlock(node, (*separator, *node_lines)))
        previous_kind = kind
    return blocks


def _text_of(blocks: Sequence[RenderedBlock]) -> str:
    return _page([line for block in blocks for line in block.lines]) if blocks else ""


def _piece_of(blocks: Sequence[RenderedBlock], budget: Budget) -> _Piece:
    return _Piece(_text_of(blocks), budget.total(budget.cost(block) for block in blocks))


def _trailing_headings(blocks: Sequence[RenderedBlock]) -> list[RenderedBlock]:
    count = 0
    while count < len(blocks) and isinstance(blocks[len(blocks) - 1 - count].node, Heading):
        count += 1
    return list(blocks[len(blocks) - count :])


def _section_pieces(blocks: Sequence[RenderedBlock], budget: Budget) -> list[_Piece]:
    whole = _piece_of(blocks, budget)
    if budget.allows(whole.cost):
        return [whole] if blocks else []
    groups: list[list[RenderedBlock]] = [[]]
    spent = budget.nothing
    for block in blocks:
        group = groups[-1]
        cost = budget.cost(block)
        if group and not budget.allows(spent + cost):
            carried = _trailing_headings(group)
            kept = group[: len(group) - len(carried)]
            if kept:
                groups[-1] = kept
                groups.append(carried)
                spent = budget.total(budget.cost(member) for member in carried)
        groups[-1].append(block)
        spent += cost
    return [_piece_of(group, budget) for group in groups if group]
