from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Final, Literal
from urllib.parse import urlsplit

from typing_extensions import assert_never

from skaldr.export.glyphs import CALLOUT_ICON, tab_icon
from skaldr.export.markup import (
    DIVIDER_LINE,
    ENTITY_LOOKALIKE,
    LARGEST_ORDERED_MARKER_NUMBER,
    CommonMarkRuns,
    code_block_lines,
    code_span,
    encode_url,
    escape_block_start,
    heading_line,
    indent_lines,
    joined,
    pipe_table_lines,
    quoted,
    spaced,
    styled,
    table_width,
)
from skaldr.export.mermaid import mermaid_fence_lines
from skaldr.export.runs import ExportRich, export_visible_text
from skaldr.export.tree import (
    Callout,
    CodeBlock,
    Columns,
    Diagram,
    DisplayMath,
    Divider,
    Figure,
    Heading,
    ListEntry,
    ListKind,
    ListNode,
    Media,
    Node,
    Paragraph,
    Quote,
    TableNode,
    TableOfContents,
    Tabs,
    Toggle,
    nested_nodes,
)
from skaldr.models import MEDIA_KIND_LABELS
from skaldr.richtext import Citation, MarkerStyle, Plain, ScriptPosition

SLACK_CANVAS_LIMIT: Final = 1_048_576
SLACK_TABLE_CELL_LIMIT: Final = 300
DEEPEST_CANVAS_HEADING: Final = 3
MOST_LAYOUT_COLUMNS: Final = 3
CANVAS_LINK_SCHEMES: Final = frozenset({"http", "https", "mailto", "tel", "ftp", "slack"})
CANVAS_ESCAPES: Final = str.maketrans({character: "\\" + character for character in "\\*_`[]<>~"})
CANVAS_FENCE: Final = ":::"
CALLOUT_OPEN: Final = "::: {.callout}"
LAYOUT_OPEN: Final = "::: {.layout}"
COLUMN_OPEN: Final = "::: {.column}"
MATH_LANGUAGE: Final = "latex"
CHECK_MARKER_INDENT: Final = 2
Place = Literal["top", "callout", "column"]


def _canvas_keeps_link(url: str) -> bool:
    if url.startswith("#"):
        return False
    try:
        scheme = urlsplit(url).scheme
    except ValueError:
        return False
    return not scheme or scheme.lower() in CANVAS_LINK_SCHEMES


def _slack_date(day: date) -> str:
    return f"![](slack_date:{day.isoformat()})"


class _SlackRuns(CommonMarkRuns):
    def unflanked_emphasis(self, _style: MarkerStyle, inner: str, /) -> str:
        return inner

    def escape(self, text: str, /) -> str:
        return ENTITY_LOOKALIKE.sub(r"\\&", text.translate(CANVAS_ESCAPES))

    def link(self, label: str, url: str, /) -> str:
        return super().link(label, url) if _canvas_keeps_link(url) else label

    def citation(self, run: Citation, /) -> str:
        label = self.escape(f"[{run.number}]")
        return self.link(label, run.url) if run.url else label

    def date_mention(self, _label: str, start: date, end: date | None, /) -> str:
        return f"{_slack_date(start)} to {_slack_date(end)}" if end else _slack_date(start)

    def math(self, expression: str, /) -> str:
        return code_span(expression)

    def underline(self, inner: str, /) -> str:
        return inner

    def script(self, _position: ScriptPosition, text: str, /) -> str:
        return self.escape(text)


@dataclass(frozen=True)
class _Item:
    text: ExportRich
    checked: bool
    nested: "tuple[_List, ...]"


@dataclass(frozen=True)
class _List:
    kind: ListKind
    items: tuple[_Item, ...]
    start: int


@dataclass(frozen=True)
class _Title:
    text: ExportRich
    icon: str | None = None


@dataclass(frozen=True)
class _Mermaid:
    figure: Figure


@dataclass(frozen=True)
class _CanvasCallout:
    icon: str
    blocks: "tuple[_CanvasBlock, ...]"


@dataclass(frozen=True)
class _Layout:
    columns: "tuple[tuple[_CanvasBlock, ...], ...]"


_CanvasBlock = (
    Heading
    | Paragraph
    | _Title
    | _List
    | TableNode
    | CodeBlock
    | DisplayMath
    | Media
    | Quote
    | Divider
    | _Mermaid
    | _CanvasCallout
    | _Layout
)
_MOVED_OUT_OF_A_CALLOUT: Final = (TableNode, _CanvasCallout, Divider, _Layout)
_KEPT_OUT_OF_A_LAYOUT: Final = (TableNode, _CanvasCallout)


def _with_paragraph(text: ExportRich, paragraph: ExportRich) -> ExportRich:
    if not text or not paragraph:
        return text or paragraph
    return (*text, Plain(" "), *paragraph)


def _canvas_item(entry: ListEntry, kind: ListKind) -> tuple[_Item, list[Node]]:
    text = entry.text
    nested: list[_List] = []
    moved: list[Node] = []
    for child in entry.children:
        match child:
            case Divider() | TableOfContents():
                continue
            case _ if moved:
                moved.append(child)
            case Paragraph():
                text = _with_paragraph(text, child.text)
            case ListNode():
                nested_list, moved_from_nested = _canvas_list(child, kind)
                nested.append(nested_list)
                moved += moved_from_nested
            case _:
                moved.append(child)
    return _Item(text, entry.checked, tuple(nested)), moved


def _canvas_list(node: ListNode, kind: ListKind) -> tuple[_List, list[Node]]:
    items: list[_Item] = []
    moved: list[Node] = []
    for entry in node.entries:
        item, item_moved = _canvas_item(entry, kind)
        items.append(item)
        moved += item_moved
    return _List(kind, tuple(items), node.start), moved


def _canvas_callout(node: Callout) -> list[_CanvasBlock]:
    inside: list[_CanvasBlock] = []
    outside: list[_CanvasBlock] = []
    for block in _canvas_blocks(node.children, "callout"):
        (outside if isinstance(block, _MOVED_OUT_OF_A_CALLOUT) else inside).append(block)
    return [_CanvasCallout(node.icon or CALLOUT_ICON[node.tone], tuple(inside)), *outside]


def _canvas_columns(node: Columns, place: Place) -> list[_CanvasBlock]:
    if place != "column" and len(node.columns) <= MOST_LAYOUT_COLUMNS:
        columns = tuple(tuple(_canvas_blocks(column.children, "column")) for column in node.columns)
        if not any(isinstance(block, _KEPT_OUT_OF_A_LAYOUT) for column in columns for block in column):
            return [_Layout(columns)]
    return _canvas_blocks(nested_nodes(node), place)


def _toggle_title(node: Toggle) -> list[_CanvasBlock]:
    if node.heading_level is not None:
        return [Heading(node.heading_level, node.title, node.anchor)]
    return [_Title(node.title)]


def _canvas_tabs(node: Tabs, place: Place) -> list[_CanvasBlock]:
    return [
        block
        for tab in node.tabs
        for block in (_Title(tab.title, tab_icon(tab.tone)), *_canvas_blocks(tab.children, place))
    ]


def _canvas_block(node: Node, place: Place) -> list[_CanvasBlock]:
    match node:
        case Heading() | Paragraph() | TableNode() | CodeBlock() | DisplayMath() | Media() | Quote():
            return [node]
        case ListNode():
            canvas_list, moved = _canvas_list(node, node.kind)
            return [canvas_list, *_canvas_blocks(moved, place)]
        case Callout():
            return _canvas_callout(node)
        case Divider():
            return [] if place == "column" else [node]
        case Toggle():
            return [*_toggle_title(node), *_canvas_blocks(node.children, place)]
        case Tabs():
            return _canvas_tabs(node, place)
        case Columns():
            return _canvas_columns(node, place)
        case Diagram():
            return [_Mermaid(node.figure), *_canvas_blocks(node.supplement, place)]
        case TableOfContents():
            return []
        case _:
            assert_never(node)


def _canvas_blocks(nodes: Sequence[Node], place: Place) -> list[_CanvasBlock]:
    return [block for node in nodes for block in _canvas_block(node, place)]


def _list_marker(kind: ListKind, number: int, checked: bool) -> tuple[str, int]:
    match kind:
        case "bullet":
            return "*", len("*") + 1
        case "number":
            marker = f"{min(number, LARGEST_ORDERED_MARKER_NUMBER)}."
            return marker, len(marker) + 1
        case "check":
            return f"* [{'x' if checked else ' '}]", CHECK_MARKER_INDENT
        case _:
            assert_never(kind)


@dataclass(frozen=True)
class SlackCanvas:
    text: str
    oversized_tables: tuple[str, ...] = ()


class _CanvasWriter:
    def __init__(self) -> None:
        self.runs = _SlackRuns()
        self.heading = ""
        self.oversized_tables: list[str] = []

    def inline(self, runs: ExportRich) -> str:
        return self.runs.write(runs)

    def block_text(self, runs: ExportRich) -> str:
        text = escape_block_start(self.inline(runs))
        return "\\" + text if text.startswith(CANVAS_FENCE) else text

    def list_lines(self, canvas_list: _List) -> list[str]:
        lines: list[str] = []
        for number, item in enumerate(canvas_list.items, start=canvas_list.start):
            marker, indent = _list_marker(canvas_list.kind, number, item.checked)
            lines.append(f"{marker} {self.block_text(item.text)}".rstrip())
            for nested in item.nested:
                lines += indent_lines(self.list_lines(nested), " " * indent)
        return lines

    def table_lines(self, table: TableNode) -> list[str]:
        cells = table_width(table) * (1 + len(table.rows))
        if cells > SLACK_TABLE_CELL_LIMIT:
            self.oversized_tables.append(self.table_limit_message(cells))
        return pipe_table_lines(table, self.inline)

    def table_limit_message(self, cells: int) -> str:
        message = (
            f"a table has {cells:,} cells, over Slack's limit of {SLACK_TABLE_CELL_LIMIT} per canvas table"
        )
        return f"{message}, under the heading '{self.heading}'" if self.heading else message

    def title_lines(self, title: _Title) -> list[str]:
        text = self.inline(title.text)
        if not text:
            return []
        return [styled("bold", f"{title.icon} {text}" if title.icon else text)]

    def media_lines(self, media: Media) -> list[str]:
        if media.kind == "image":
            image = f"![{self.inline(media.description)}]({encode_url(media.url)})"
            caption = [styled("italic", self.inline(media.caption))] if media.caption else []
            return joined([[image], caption])
        return [self.runs.link(self.inline(media.caption) or MEDIA_KIND_LABELS[media.kind], media.url)]

    def quote_lines(self, quote: Quote) -> list[str]:
        parts = [self.block_text(line) for line in quote.lines]
        if quote.cite:
            parts.append(styled("italic", self.inline(quote.cite)))
        return quoted(joined([[part] for part in parts]))

    def callout_lines(self, callout: _CanvasCallout) -> list[str]:
        rendered = self.rendered(callout.blocks)
        body = joined([lines for _, lines in rendered])
        if rendered and isinstance(rendered[0][0], Paragraph | _Title):
            body[0] = f"{callout.icon} {body[0]}"
        else:
            body = [callout.icon, *spaced(body)]
        return [CALLOUT_OPEN, *body, CANVAS_FENCE]

    def layout_lines(self, layout: _Layout) -> list[str]:
        columns = [
            line for blocks in layout.columns for line in (COLUMN_OPEN, *self.blocks(blocks), CANVAS_FENCE)
        ]
        return [LAYOUT_OPEN, *columns, CANVAS_FENCE]

    def lines(self, block: _CanvasBlock) -> list[str]:
        match block:
            case Heading():
                self.heading = export_visible_text(block.text).strip() or self.heading
                return [heading_line(min(block.level, DEEPEST_CANVAS_HEADING), self.inline(block.text))]
            case Paragraph():
                text = self.block_text(block.text)
                return [text] if text else []
            case _Title():
                return self.title_lines(block)
            case _List():
                return self.list_lines(block)
            case TableNode():
                return self.table_lines(block)
            case CodeBlock():
                return code_block_lines(block)
            case DisplayMath():
                return code_block_lines(CodeBlock(block.expression, MATH_LANGUAGE))
            case Media():
                return self.media_lines(block)
            case Quote():
                return self.quote_lines(block)
            case Divider():
                return [DIVIDER_LINE]
            case _Mermaid():
                return mermaid_fence_lines(block.figure)
            case _CanvasCallout():
                return self.callout_lines(block)
            case _Layout():
                return self.layout_lines(block)
            case _:
                assert_never(block)

    def rendered(self, blocks: Sequence[_CanvasBlock]) -> list[tuple[_CanvasBlock, list[str]]]:
        written = [(block, self.lines(block)) for block in blocks]
        return [(block, lines) for block, lines in written if lines]

    def blocks(self, blocks: Sequence[_CanvasBlock]) -> list[str]:
        return joined([lines for _, lines in self.rendered(blocks)])


def render_slack(nodes: Sequence[Node]) -> SlackCanvas:
    writer = _CanvasWriter()
    lines = writer.blocks(_canvas_blocks(nodes, "top"))
    return SlackCanvas("\n".join(lines) + "\n", tuple(writer.oversized_tables))
