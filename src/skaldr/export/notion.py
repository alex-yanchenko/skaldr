import re
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date
from typing import Final

from typing_extensions import assert_never

from skaldr import compute
from skaldr.errors import ExportInvariantError
from skaldr.export.apportion import apportioned, apportioned_at_least
from skaldr.export.budget import Budget, Cost, RenderedBlock
from skaldr.export.capabilities import (
    BACKTICK,
    CLOSING_TAG_OPENER,
    FIRST_LIST_NUMBER,
    EnclosingContainers,
    NotionContainer,
)
from skaldr.export.folds import cell_text, folded, quote_lines
from skaldr.export.glyphs import CALLOUT_ICON, tab_icon
from skaldr.export.inline import ZERO_WIDTH_SPACE, bold, one_line, plain
from skaldr.export.markup import (
    DIVIDER_LINE,
    MarkupRuns,
    bang_cannot_open_an_image,
    body_cell_texts,
    code_block_lines,
    encode_url,
    escape_block_start,
    indent_lines,
    is_emphasised_body_cell,
    label_then,
    styled,
)
from skaldr.export.mermaid import mermaid_fence_lines
from skaldr.export.runs import (
    Chip,
    ExportRich,
    ExportRun,
    IndicatorMark,
    Mark,
    SpanKind,
    StatusMark,
    TonedLabel,
    export_visible_text,
    holds_a_chip,
    nested_runs,
    write_export_run_around,
    write_export_runs,
)
from skaldr.export.swaps import (
    data_table_swapped_in,
    figure_mermaid_draws,
    swaps_the_figure,
    web_address_of,
)
from skaldr.export.tree import (
    COLUMN_RATIO_TOTAL,
    MOST_COLUMNS_PER_STRIP,
    Callout,
    Card,
    Cards,
    CodeBlock,
    Columns,
    DefinitionList,
    Diagram,
    DisplayMath,
    Divider,
    FactStrip,
    GenericNode,
    GridColumn,
    Heading,
    HeadingLevel,
    KeyValueList,
    LabelledValue,
    ListKind,
    ListNode,
    LoweredDocument,
    Media,
    Node,
    Paragraph,
    Quote,
    Tab,
    TableCell,
    TableNode,
    TableOfContents,
    TableRow,
    Tabs,
    Toggle,
    ToneName,
    deepest_heading_level,
    heading_of,
    nested_nodes,
    uses_heading_level_1,
)
from skaldr.mathml import NOTION_EQUATION_FENCE
from skaldr.models import (
    BADGE_COLOR_TONE,
    BadgeColorLiteral,
    NotionWidth,
    Person,
    StatusState,
    ToneLiteral,
)
from skaldr.richtext import Code, Placeholder, ScriptPosition, Styled, Tinted

NOTION_ESCAPES: Final = str.maketrans({character: "\\" + character for character in "\\*_~`$[]<>{}|^="})
EXTENSIONS_NOTION_LINKIFIES: Final = (
    "ai",
    "ar",
    "cc",
    "cr",
    "do",
    "in",
    "io",
    "is",
    "it",
    "java",
    "md",
    "me",
    "ml",
    "mov",
    "nu",
    "pl",
    "pm",
    "ps",
    "py",
    "rs",
    "sh",
    "so",
    "tf",
    "to",
    "zip",
)
FILE_NAME_NOTION_LINKIFIES = re.compile(
    rf"(?<![\w/.-])([\w./-]*\w\.(?:{'|'.join(EXTENSIONS_NOTION_LINKIFIES)})(?::\d+(?:-\d+)?)?)(?![\w`])"
)
SPACE_RUN: Final = re.compile(r"(\s+)")
WEB_ADDRESS_OR_EMAIL_MARKS: Final = ("://", "@", "www.")
BLOCK_ATTRIBUTE_OPENING: Final = re.compile(r'\{(?=(?:color|toggle)=")')
TABLE_TAG_OPENING: Final = re.compile(r"<(?:td|tr|table)(?=[\s/>])")
SPACED_PLUS_AFTER_CODE: Final = re.compile(r"` \+ ")
FULL_WIDTH_PLUS: Final = "\N{FULLWIDTH PLUS SIGN}"
CHUNK_BOUNDARY_LEVEL: Final = 2
DEEPEST_NOTION_HEADING: Final = 4
OPENING_SECTION_LABEL: Final = "the opening section, before the first level 1 or 2 heading"
EMPTY_BLOCK: Final = "<empty-block/>"
EQUATION_FENCE: Final = NOTION_EQUATION_FENCE
CODE_FENCE_RUN: Final = re.compile(r"`{3,}")
LINE_INSIDE_A_BLOCK: Final = re.compile(
    r"</[a-z_]+>|<colgroup>|<col\b[^>]*>|<td\b.*</td>|<summary>.*</summary>"
)
TAB_OPENING: Final = re.compile(r"<tab(?: icon=\"[^\"]*\")?>")
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
STATUS_TONE: Final[Mapping[StatusState, ToneName]] = {
    "done": "success",
    "current": "info",
    "pending": "muted",
    "failed": "danger",
    "blocked": "warning",
}
NotionNode = GenericNode | FactStrip | KeyValueList | DefinitionList | Cards
PLACEHOLDER_HIGHLIGHT: Final = BLOCK_COLOR["warning"] + BACKGROUND_SUFFIX
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
    in_a_column: bool = False
    enclosing: EnclosingContainers = field(default_factory=EnclosingContainers)
    heading_shift: int = 0

    def inside(self, container: NotionContainer) -> "TableRoom":
        return replace(self, enclosing=self.enclosing.inside(container))

    @classmethod
    def on_page(cls, page_width: NotionWidth, nodes: Iterable[Node]) -> "TableRoom":
        return cls(
            NOTION_PAGE_WIDTH_PX[page_width],
            sizes_every_table=page_width == "full",
            heading_shift=notion_heading_shift(tuple(nodes)),
        )

    def within(self, ratio: int) -> "TableRoom":
        if not self.sizes_every_table:
            return replace(self, in_a_column=True)
        return replace(self, width=round(self.width * ratio / COLUMN_RATIO_TOTAL), in_a_column=True)


def _with_block_attributes_kept_apart(code: str) -> str:
    return BLOCK_ATTRIBUTE_OPENING.sub("{" + ZERO_WIDTH_SPACE, code)


def latex_text(text: str) -> str:
    return "\\text{" + text.translate(LATEX_TEXT_ESCAPES) + "}"


@dataclass(frozen=True)
class _NotionRuns(MarkupRuns):
    inside_bold: bool = False
    on_fill: bool = False
    in_a_table_cell: bool = False

    def escape(self, text: str, /) -> str:
        return text.translate(NOTION_ESCAPES)

    def text(self, text: str, /) -> str:
        tokens = SPACE_RUN.split(text)
        return bang_cannot_open_an_image("".join(map(self._token, tokens)))

    def _token(self, token: str) -> str:
        if any(mark in token for mark in WEB_ADDRESS_OR_EMAIL_MARKS):
            return self.escape(token)
        return self._with_file_names_as_code(token)

    def _with_file_names_as_code(self, text: str) -> str:
        pieces = FILE_NAME_NOTION_LINKIFIES.split(text)
        return "".join(self._piece(index, piece) for index, piece in enumerate(pieces))

    def _piece(self, index: int, piece: str) -> str:
        is_file_name = index % 2 == 1
        return self.code(piece) if is_file_name else self.escape(piece)

    def code(self, text: str, /) -> str:
        if BACKTICK in text:
            raise ExportInvariantError(
                f"Notion cannot show inline code holding a backtick, '{text}'; "
                "the export check should have refused it"
            )
        if self.in_a_table_cell and CLOSING_TAG_OPENER in text:
            raise ExportInvariantError(
                f"Notion loses a table cell whose inline code holds '</', '{text}'; "
                "the export check should have refused it"
            )
        if self.in_a_table_cell:
            return self._code_in_a_table_cell(text)
        return f"`{_with_block_attributes_kept_apart(text)}`"

    def _code_in_a_table_cell(self, text: str) -> str:
        if TABLE_TAG_OPENING.search(text):
            return self.text(text)
        return f"`{text}`"

    def anchor_link(self, _label: str, _anchor: str, /) -> str:
        raise ExportInvariantError(
            "a Notion page cannot link to its own headings; the export check should have refused it"
        )

    def date_mention(self, label: str, start: date, end: date | None, /) -> str:
        finish = f' end="{end.isoformat()}"' if end else ""
        return label_then(label, f'<mention-date start="{start.isoformat()}"{finish}/>')

    def person_mention(self, label: str, _key: str, person: Person, /) -> str:
        if person.notion is None:
            return label
        return f'<mention-user url="{person.notion}">{label}</mention-user>'

    def blank(self, name: str, /) -> str:
        return self.escape("{{" + name + "}}")

    def placeholder(self, name: str, /) -> str:
        return _placeholder_written_in(_Span(), name, self)

    def chip(self, run: Chip, /) -> str:
        label = self.text(run.label)
        bolded = label if self.inside_bold else styled("bold", label)
        return bolded if self.on_fill else _colored_span(CHIP_COLOR[run.tone], bolded)

    def mark(self, run: Mark, /) -> str:
        if not isinstance(run, StatusMark):
            return super().mark(run)
        glyph = compute.STATUS_GLYPHS[run.state].page
        return glyph if self.on_fill else _colored_span(BLOCK_COLOR[STATUS_TONE[run.state]], glyph)

    def underline(self, inner: str, /) -> str:
        return _Span().underlined().around(inner)

    def script(self, position: ScriptPosition, text: str, /) -> str:
        return self.math(LATEX_SCRIPT_OPERATOR[position] + "{" + latex_text(text) + "}")

    def tinted(self, tone: ToneLiteral | None, background: ToneLiteral | None, inner: str, /) -> str:
        return _Span().tinted(tone, background).around(inner)

    def toned_label(self, tone: ToneLiteral, inner: str, /) -> str:
        return _Span().tinted(tone, None).around(inner)


def _colored_span(color: str, inner: str) -> str:
    return f'<span color="{color}">{inner}</span>'


def _codes_holding_a_closing_tag(runs: Iterable[ExportRun]) -> Iterator[str]:
    for run in runs:
        if isinstance(run, Code) and CLOSING_TAG_OPENER in run.text:
            yield run.text
        yield from _codes_holding_a_closing_tag(nested_runs(run))


@dataclass(frozen=True)
class _Span:
    color: str | None = None
    kind: SpanKind | None = None
    underline: bool = False
    colour_is_generated: bool = False

    def coloured(self, kind: SpanKind, color: str) -> "_Span":
        if self.kind is not None and self.kind != kind:
            raise ExportInvariantError(
                f"Notion holds no span inside a span, so it cannot show a {kind} inside a {self.kind}; "
                "the export check should have refused it"
            )
        return replace(self, color=color, kind=kind, colour_is_generated=False)

    def toned(self, tone: ToneLiteral) -> "_Span":
        return replace(self.coloured("colour", BLOCK_COLOR[tone]), colour_is_generated=True)

    def leaves_out(self, run: ExportRun) -> bool:
        return (
            self.colour_is_generated
            and not self.underline
            and isinstance(run, Code)
            and CLOSING_TAG_OPENER in run.text
        )

    def tinted(self, tone: ToneLiteral | None, background: ToneLiteral | None) -> "_Span":
        if tone and background:
            raise ExportInvariantError(
                "a Notion text run takes a colour or a highlight, not both; "
                "the export check should have refused it"
            )
        if background:
            return self.coloured("highlight", BLOCK_COLOR[background] + BACKGROUND_SUFFIX)
        return self.coloured("colour", BLOCK_COLOR[tone]) if tone else self

    def underlined(self) -> "_Span":
        return replace(self, underline=True)

    def for_a_blank(self) -> "_Span":
        return replace(self, color=PLACEHOLDER_HIGHLIGHT, kind="highlight")

    def _attributes(self) -> str:
        color = f' color="{self.color}"' if self.color else ""
        return color + (' underline="true"' if self.underline else "")

    def around(self, inner: str) -> str:
        attributes = self._attributes()
        return f"<span{attributes}>{inner}</span>" if attributes and inner else inner

    def holding(self, runs: ExportRich, writer: "_NotionRuns") -> str:
        if self._attributes():
            closing = next(_codes_holding_a_closing_tag(runs), None)
            if closing is not None:
                raise ExportInvariantError(
                    "Notion closes a coloured, highlighted or underlined span early at inline code "
                    f"holding '</', '{closing}'; the export check should have refused it"
                )
        return self.around(write_export_runs(runs, writer))


def _placeholder_written_in(span: _Span, name: str, writer: "_NotionRuns") -> str:
    return span.for_a_blank().around(writer.blank(name))


def _is_a_span(run: ExportRun) -> bool:
    match run:
        case Tinted() | TonedLabel() | Placeholder():
            return True
        case Styled():
            return run.style == "underline"
        case _:
            return False


def _splits_the_span(span: _Span, run: ExportRun) -> bool:
    return _is_a_span(run) or span.leaves_out(run)


def _holds_a_split(span: _Span, run: ExportRun) -> bool:
    return any(_splits_the_span(span, inner) or _holds_a_split(span, inner) for inner in nested_runs(run))


def _written_in(span: _Span, runs: ExportRich, writer: "_NotionRuns") -> str:
    parts: list[str] = []
    inside_the_span: list[ExportRun] = []
    for run in runs:
        if not _splits_the_span(span, run) and not _holds_a_split(span, run):
            inside_the_span.append(run)
            continue
        parts.append(span.holding(tuple(inside_the_span), writer))
        inside_the_span = []
        parts.append(_run_written_in(span, run, writer))
    parts.append(span.holding(tuple(inside_the_span), writer))
    return writer.concat(parts)


def _run_written_in(span: _Span, run: ExportRun, writer: "_NotionRuns") -> str:
    match run:
        case Tinted():
            return _written_in(span.tinted(run.tone, run.background), run.runs, writer)
        case TonedLabel():
            return _written_in(span.toned(run.tone), run.runs, writer)
        case Styled() if run.style == "underline":
            return _written_in(span.underlined(), run.runs, writer)
        case Placeholder():
            return _placeholder_written_in(span, run.name, writer)
        case _:
            return write_export_run_around(run, _written_in(span, nested_runs(run), writer), writer)


def notion_inline(
    runs: ExportRich, *, inside_bold: bool = False, on_fill: bool = False, in_a_table_cell: bool = False
) -> str:
    return _written_in(_Span(), runs, _NotionRuns(inside_bold, on_fill, in_a_table_cell))


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
    text = notion_inline(cell_text(cell), inside_bold=inside_bold, on_fill=on_fill, in_a_table_cell=True)
    return escape_block_start(_plus_after_code_that_notion_cannot_read_as_a_bullet(text))


def _background_attribute(tone: ToneName | None) -> str:
    return _color_attribute(tone, BACKGROUND_SUFFIX) if tone else ""


def _is_a_dot_alone(cell: TableCell) -> bool:
    match cell.text:
        case (IndicatorMark(tone=tone),):
            return tone == cell.tone
        case _:
            return False


def _cell_fill(cell: TableCell) -> ToneName | None:
    return None if _is_a_dot_alone(cell) else cell.tone


def _row_lines(texts: Sequence[str], tone: ToneName | None, fills: Sequence[ToneName | None]) -> list[str]:
    tagged = [
        f"<td{_background_attribute(fill)}>{text}</td>" for fill, text in zip(fills, texts, strict=True)
    ]
    return [f"<tr{_background_attribute(tone)}>", *_indent(tagged), "</tr>"]


def _own_fills(cells: Sequence[TableCell]) -> list[ToneName | None]:
    return [_cell_fill(cell) for cell in cells]


def _fills_with_the_row_tone_in_one_cell(cells: Sequence[TableCell], tone: ToneName) -> list[ToneName | None]:
    fills = _own_fills(cells)
    fillable = [index for index, cell in enumerate(cells) if not _is_a_dot_alone(cell)]
    chip_cell = next((index for index in fillable if holds_a_chip(cell_text(cells[index]))), None)
    filled = chip_cell if chip_cell is not None else next(iter(fillable), 0)
    return [fill or tone if index == filled else fill for index, fill in enumerate(fills)]


@dataclass(frozen=True)
class _RowFill:
    whole_row: ToneName | None = None
    one_cell: ToneName | None = None
    struck_title: bool = False


def _row_fill(row: TableRow) -> _RowFill:
    if row.emphasis == "group":
        return _RowFill(whole_row=row.fill or "neutral")
    if row.tone == "muted":
        return _RowFill(struck_title=True)
    return _RowFill(one_cell=row.fill)


def _column_count(table: TableNode) -> int:
    return len(table.header) or max((len(row.cells) for row in table.rows), default=0)


def _column_tones(table: TableNode) -> list[ToneName | None]:
    return [column.tone for column in table.columns] or [None] * _column_count(table)


def _in_a_toned_column(column_tones: Sequence[ToneName | None], index: int) -> bool:
    return index < len(column_tones) and column_tones[index] is not None


def _struck_when(struck: bool, text: str) -> str:
    return styled("strike", text) if struck else text


def _body_row_lines(table: TableNode, row: TableRow) -> list[str]:
    fill = _row_fill(row)
    cells = row.cells
    fills = _fills_with_the_row_tone_in_one_cell(cells, fill.one_cell) if fill.one_cell else _own_fills(cells)
    column_tones = _column_tones(table)
    texts = body_cell_texts(
        table,
        row,
        [
            _struck_when(
                fill.struck_title and index == table.title_column,
                _table_cell_text(
                    cell,
                    inside_bold=is_emphasised_body_cell(table, row, index),
                    on_fill=fill.whole_row is not None
                    or fills[index] is not None
                    or _in_a_toned_column(column_tones, index),
                ),
            )
            for index, cell in enumerate(cells)
        ],
    )
    return _row_lines(texts, fill.whole_row, fills)


def _longest_text(table: TableNode, index: int) -> int:
    cells = [table.header, *(row.cells for row in table.rows)]
    return max(
        (len(export_visible_text(cell_text(row[index]))) for row in cells if index < len(row)), default=0
    )


def _content_weight(table: TableNode, index: int) -> int:
    return max(NARROWEST_COLUMN_CHARACTERS, min(WIDEST_COLUMN_CHARACTERS, _longest_text(table, index)))


def _column_widths(table: TableNode, room: TableRoom) -> Sequence[int | None]:
    shares = [column.share for column in table.columns] or [None] * _column_count(table)
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
    return apportioned_at_least(weights, width, NARROWEST_COLUMN_PX)


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
    attributes = ['fit-page-width="true"']
    if table.header:
        attributes.append('header-row="true"')
    if table.header_column:
        attributes.append('header-column="true"')
    header_texts = [styled("bold", _table_cell_text(cell, inside_bold=True)) for cell in table.header]
    header_fills = _own_fills(table.header)
    header_lines = _row_lines(header_texts, None, header_fills) if table.header else []
    lines = _colgroup_lines(table, room) + header_lines
    lines += [line for row in table.rows for line in _body_row_lines(table, row)]
    return [f"<table {' '.join(attributes)}>", *_indent(lines), "</table>"]


def _list_marker(node: ListNode, index: int, checked: bool) -> str:
    match node.kind:
        case "bullet":
            return "-"
        case "number":
            return f"{index}."
        case "check":
            return "- [x]" if checked else "- [ ]"
        case _:
            assert_never(node.kind)


def _list_lines(node: ListNode, room: TableRoom) -> list[str]:
    if node.kind == "number" and node.start != FIRST_LIST_NUMBER:
        raise ExportInvariantError(
            f"Notion numbers every list from 1, not from {node.start}; "
            "the export check should have refused it"
        )
    lines: list[str] = []
    for index, entry in enumerate(node.entries, start=node.start):
        marker = _list_marker(node, index, entry.checked)
        lines.append(f"{marker} {_block_text(entry.text)}")
        lines += _indent(_notion_blocks(entry.children, room))
    return lines


def _media_line(node: Media) -> str:
    url = encode_url(web_address_of(node, "notion"))
    if node.kind == "image":
        return f"![{notion_inline(node.caption or node.description)}]({url})"
    return f'<{node.kind} src="{url}">{notion_inline(node.caption)}</{node.kind}>'


def _quote_line(node: Quote) -> str:
    body = "<br>".join(_block_text(line) for line in quote_lines(node))
    if node.cite:
        body += "<br>" + styled("italic", notion_inline(node.cite))
    return f"> {body}"


def notion_heading_shift(nodes: Sequence[Node]) -> int:
    goes_past_the_deepest = deepest_heading_level(nodes) > DEEPEST_NOTION_HEADING
    return 1 if goes_past_the_deepest and not uses_heading_level_1(nodes) else 0


def _heading_marks(level: HeadingLevel, shift: int) -> str:
    return "#" * min(level - shift, DEEPEST_NOTION_HEADING)


def _toggle_lines(node: Toggle, room: TableRoom) -> list[str]:
    if node.heading_level is not None:
        marks = _heading_marks(node.heading_level, room.heading_shift)
        return [
            f'{marks} {notion_inline(node.title)} {{toggle="true"}}',
            *_indent(_notion_blocks(node.children, room)),
        ]
    children = _indent(_notion_blocks(node.children, room.inside("details")))
    return ["<details>", f"<summary>{notion_inline(node.title)}</summary>", *children, "</details>"]


def _columns_lines(node: Columns, room: TableRoom) -> list[str]:
    lines: list[str] = []
    for column in node.columns:
        children = _notion_blocks(column.children, room.within(column.ratio).inside("column"))
        lines += [f'<column ratio="{column.ratio}">', *_indent(children), "</column>"]
    return ["<columns>", *_indent(lines), "</columns>"]


def _tab_lines(tab: Tab, room: TableRoom) -> list[str]:
    if not tab.title:
        raise ExportInvariantError(
            "a Notion tab needs a title, since Notion reads the first line of a tab as its title; "
            "the export check should have refused it"
        )
    icon = tab_icon(tab.tone)
    opening = "<tab>" if icon is None else f'<tab icon="{icon}">'
    children = _notion_blocks(tab.children, room.inside("tab"))
    return [opening, *_indent([_block_text(tab.title), *children]), "</tab>"]


def _tabs_lines(node: Tabs, room: TableRoom) -> list[str]:
    return ["<tabs>", *_indent([line for tab in node.tabs for line in _tab_lines(tab, room)]), "</tabs>"]


def _starts_a_numbered_list_past_one(nodes: Sequence[Node]) -> bool:
    return any(
        (isinstance(node, ListNode) and node.kind == "number" and node.start != FIRST_LIST_NUMBER)
        or _starts_a_numbered_list_past_one(nested_nodes(node))
        for node in nodes
    )


def _quote_holds_lists_notion_can_nest(node: Quote) -> bool:
    return any(isinstance(child, ListNode) for child in node.body) and not _starts_a_numbered_list_past_one(
        node.body
    )


def _quote_with_its_lists_lines(node: Quote, room: TableRoom) -> list[str]:
    if not _quote_holds_lists_notion_can_nest(node):
        return [_quote_line(node)]
    first, *rest = node.body
    opens_with_text = isinstance(first, Paragraph)
    head = _block_text(first.text) if isinstance(first, Paragraph) else ""
    cite = [styled("italic", notion_inline(node.cite))] if node.cite else []
    children = [*_notion_blocks(rest if opens_with_text else node.body, room), *cite]
    return [f"> {head}".rstrip(), *_indent(children)]


def _label_text(label: str | None) -> ExportRich:
    return plain(one_line(label or "").removesuffix(":").rstrip())


def _fact_column(fact: LabelledValue) -> tuple[Node, ...]:
    label, value = _label_text(fact.label), fact.value
    return (*((Paragraph(label, "muted"),) if label else ()), *((Paragraph(value),) if value else ()))


def _fact_columns(node: FactStrip) -> list[tuple[Node, ...]]:
    return [column for column in map(_fact_column, node.facts) if column]


def _card_column(card: Card) -> tuple[Node, ...]:
    label = one_line(card.label or "").removesuffix(":").rstrip()
    head = (Chip.on_one_line(label, card.badge),) if card.badge is not None and label else bold(label)
    note = plain(card.note)
    children = [
        *([Paragraph(head)] if head else []),
        *([Paragraph(card.value)] if card.value else []),
        *([Paragraph(note, "muted")] if note else []),
    ]
    return (Callout(card.tone or "neutral", tuple(children)),) if children else ()


def _card_columns(node: Cards) -> list[tuple[Node, ...]]:
    return [column for column in map(_card_column, node.cards) if column]


def _row_sizes(count: int) -> list[int]:
    rows = -(-count // MOST_COLUMNS_PER_STRIP)
    base, extra = divmod(count, rows)
    return [base + 1 if index < extra else base for index in range(rows)]


def _column_strip_lines(columns: Sequence[tuple[Node, ...]], room: TableRoom) -> list[str]:
    if len(columns) == 1 or room.in_a_column:
        return _notion_blocks([node for column in columns for node in column], room)
    lines: list[str] = []
    first = 0
    for size in _row_sizes(len(columns)):
        row = columns[first : first + size]
        ratios = apportioned([1] * size, COLUMN_RATIO_TOTAL)
        grid = Columns(
            tuple(GridColumn(ratio, children) for ratio, children in zip(ratios, row, strict=True))
        )
        lines += _columns_lines(grid, room)
        first += size
    return lines


def _key_value_table(node: KeyValueList) -> TableNode:
    rows = tuple(TableRow((TableCell(_label_text(pair.label)), TableCell(pair.value))) for pair in node.pairs)
    return TableNode((), rows, header_column=True)


def _definition_lines(node: DefinitionList, room: TableRoom) -> list[str]:
    lines: list[str] = []
    for definition in node.definitions:
        body = _notion_blocks(definition.body, room)
        term = _block_text(bold(definition.term))
        lines += [term, *_indent(body)] if term else body
    return lines


def _natively_or_folded(node: Node, room: TableRoom) -> tuple[NotionNode, ...]:
    match node:
        case FactStrip() if len(_fact_columns(node)) > 1 and not room.in_a_column:
            return (node,)
        case KeyValueList() if not any(
            next(_codes_holding_a_closing_tag(pair.value), None) is not None for pair in node.pairs
        ):
            return (node,)
        case Cards() if _card_columns(node):
            return (node,)
        case DefinitionList():
            return (node,)
        case _:
            return folded((node,))


def _refuse_a_code_line_reading_as_a_container_tag(node: CodeBlock, room: TableRoom) -> None:
    tag = room.enclosing.code_line_reading_as_a_tag(node.content)
    if tag is not None:
        raise ExportInvariantError(
            f"Notion reads the code line '{tag.line}' as a tag of the {tag.container} around it; "
            "the export check should have refused it"
        )


def _notion_lines(node: NotionNode, room: TableRoom) -> list[str]:
    match node:
        case FactStrip():
            return _column_strip_lines(_fact_columns(node), room)
        case KeyValueList():
            return _table_lines(_key_value_table(node), room)
        case DefinitionList():
            return _definition_lines(node, room)
        case Cards():
            return _column_strip_lines(_card_columns(node), room)
        case Heading():
            return [f"{_heading_marks(node.level, room.heading_shift)} {notion_inline(node.text)}"]
        case Paragraph():
            text = _block_text(node.text)
            return [text + _trailing_color(node.tone)] if text else []
        case ListNode():
            return _list_lines(node, room)
        case TableNode():
            return _table_lines(node, room)
        case CodeBlock():
            _refuse_a_code_line_reading_as_a_container_tag(node, room)
            return code_block_lines(replace(node, language=node.language or NOTION_PLAIN_TEXT_LANGUAGE))
        case DisplayMath():
            return [EQUATION_FENCE, *node.expression.split("\n"), EQUATION_FENCE]
        case Media():
            return [_media_line(node)]
        case Callout():
            icon = node.icon or CALLOUT_ICON[node.tone]
            opening = f'<callout icon="{icon}"{_color_attribute(node.tone, BACKGROUND_SUFFIX)}>'
            return [opening, *_indent(_notion_blocks(node.children, room.inside("callout"))), "</callout>"]
        case Quote():
            return _quote_with_its_lists_lines(node, room)
        case Divider():
            return [DIVIDER_LINE]
        case Toggle():
            return _toggle_lines(node, room)
        case Columns():
            return _columns_lines(node, room)
        case Tabs():
            return _tabs_lines(node, room)
        case Diagram() if swaps_the_figure(node, "notion"):
            return _notion_blocks(data_table_swapped_in(node, "notion"), room)
        case Diagram():
            return [
                *mermaid_fence_lines(figure_mermaid_draws(node, "notion")),
                *_notion_blocks(node.supplement, room),
            ]
        case TableOfContents():
            return ["<table_of_contents/>"]
        case _:
            assert_never(node)


def _written_natively_or_folded(nodes: Iterable[Node], room: TableRoom) -> tuple[NotionNode, ...]:
    return tuple(written for node in nodes for written in _natively_or_folded(node, room))


def _list_kind(node: Node) -> ListKind | None:
    return node.kind if isinstance(node, ListNode) else None


def _notion_blocks(nodes: Sequence[Node], room: TableRoom) -> list[str]:
    return [line for block in _rendered_blocks(nodes, room) for line in block.lines]


def _page(lines: Sequence[str]) -> str:
    return "\n".join(lines) + "\n"


def render_notion(nodes: Sequence[Node], page_width: NotionWidth = "normal") -> str:
    return _page(_notion_blocks(nodes, TableRoom.on_page(page_width, nodes)))


def _chunk_heading(node: Node) -> Heading | None:
    heading = heading_of(node)
    return heading if heading is not None and heading.level <= CHUNK_BOUNDARY_LEVEL else None


def _section_label(section: Sequence[Node], heading_shift: int) -> str:
    heading = _chunk_heading(section[0]) if section else None
    if heading is None:
        return OPENING_SECTION_LABEL
    return f"{_heading_marks(heading.level, heading_shift)} {export_visible_text(heading.text)}"


@dataclass(frozen=True)
class NotionChunks:
    chunks: tuple[str, ...]
    oversized_sections: tuple[str, ...]


@dataclass(frozen=True)
class _Piece:
    text: str
    cost: Cost


@dataclass(frozen=True)
class _CostedBlock:
    block: RenderedBlock
    cost: Cost


def _sections(nodes: Sequence[Node], room: TableRoom) -> list[list[Node]]:
    sections: list[list[Node]] = [[]]
    for node in _written_natively_or_folded(nodes, room):
        if _chunk_heading(node) is not None and sections[-1]:
            sections.append([])
        sections[-1].append(node)
    return sections


def chunk_notion(nodes: Sequence[Node], budget: Budget, page_width: NotionWidth = "normal") -> NotionChunks:
    room = TableRoom.on_page(page_width, nodes)
    chunks: list[str] = []
    oversized: list[str] = []
    current_chunk = _Piece("", budget.nothing)
    for section in _sections(nodes, room):
        costed = [_CostedBlock(block, budget.cost(block)) for block in _rendered_blocks(section, room)]
        pieces = _section_pieces(costed, budget)
        if any(not budget.allows(piece.cost) for piece in pieces):
            oversized.append(_section_label(section, room.heading_shift))
        for piece in pieces:
            if current_chunk.text and not budget.allows(current_chunk.cost + piece.cost):
                chunks.append(current_chunk.text)
                current_chunk = _Piece("", budget.nothing)
            current_chunk = _Piece(current_chunk.text + piece.text, current_chunk.cost + piece.cost)
    if current_chunk.text:
        chunks.append(current_chunk.text)
    return NotionChunks(tuple(chunks) or (render_notion(nodes, page_width),), tuple(oversized))


def _rendered_blocks_by_position(
    nodes: Sequence[Node], room: TableRoom
) -> Iterator[tuple[int, RenderedBlock]]:
    previous_kind: ListKind | None = None
    for position, node in enumerate(_written_natively_or_folded(nodes, room)):
        node_lines = _notion_lines(node, room)
        if not node_lines:
            continue
        kind = _list_kind(node)
        separator = [EMPTY_BLOCK] if kind is not None and kind == previous_kind else []
        yield position, RenderedBlock(node, (*separator, *node_lines))
        previous_kind = kind


def _rendered_blocks(nodes: Sequence[Node], room: TableRoom) -> list[RenderedBlock]:
    return [block for _, block in _rendered_blocks_by_position(nodes, room)]


def notion_fence_closer(stripped_line: str) -> str | None:
    if stripped_line == EQUATION_FENCE:
        return EQUATION_FENCE
    run = CODE_FENCE_RUN.match(stripped_line)
    return run.group(0) if run else None


def starts_a_block(stripped_line: str) -> bool:
    return bool(stripped_line) and LINE_INSIDE_A_BLOCK.fullmatch(stripped_line) is None


def notion_block_count(text: str) -> int:
    count = 0
    closer: str | None = None
    title_follows = False
    for line in text.split("\n"):
        stripped = line.strip()
        if closer is not None:
            closer = None if stripped == closer else closer
            continue
        if title_follows and stripped:
            title_follows = False
            continue
        if not starts_a_block(stripped):
            continue
        title_follows = TAB_OPENING.fullmatch(stripped) is not None
        closer = notion_fence_closer(stripped)
        count += 1
    return count


def render_notion_regions(document: LoweredDocument, page_width: NotionWidth = "normal") -> tuple[str, ...]:
    room = TableRoom.on_page(page_width, document.body)
    region_of_node = [
        position
        for position, region in enumerate(document.regions)
        for _ in _written_natively_or_folded(region.nodes, room)
    ]
    lines_by_region: list[list[str]] = [[] for _ in document.regions]
    for node_position, block in _rendered_blocks_by_position(document.body, room):
        lines_by_region[region_of_node[node_position]] += block.lines
    return tuple(_page(lines) if lines else "" for lines in lines_by_region)


def _piece_of(costed: Sequence[_CostedBlock], budget: Budget) -> _Piece:
    text = _page([line for member in costed for line in member.block.lines]) if costed else ""
    return _Piece(text, budget.total(member.cost for member in costed))


def _trailing_headings(costed: Sequence[_CostedBlock]) -> list[_CostedBlock]:
    count = 0
    while count < len(costed) and isinstance(costed[len(costed) - 1 - count].block.node, Heading):
        count += 1
    return list(costed[len(costed) - count :])


def _section_pieces(costed: Sequence[_CostedBlock], budget: Budget) -> list[_Piece]:
    whole = _piece_of(costed, budget)
    if budget.allows(whole.cost):
        return [whole] if costed else []
    groups: list[list[_CostedBlock]] = [[]]
    spent = budget.nothing
    for member in costed:
        group = groups[-1]
        if group and not budget.allows(spent + member.cost):
            carried = _trailing_headings(group)
            kept = group[: len(group) - len(carried)]
            if kept:
                groups[-1] = kept
                groups.append(carried)
                spent = budget.total(carried_member.cost for carried_member in carried)
        groups[-1].append(member)
        spent += member.cost
    return [_piece_of(group, budget) for group in groups if group]
