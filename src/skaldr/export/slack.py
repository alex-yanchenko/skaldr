from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Final, Literal, NoReturn

from typing_extensions import assert_never

from skaldr.errors import ExportInvariantError, ExportRejectedError
from skaldr.export.capabilities import (
    CANVAS_LAYOUT_COLUMN_LIMIT,
    CANVAS_TABLE_CELL_LIMIT,
    FIRST_LIST_NUMBER,
    TARGET_SUBJECTS,
    in_unicode_script_form,
)
from skaldr.export.folds import folded
from skaldr.export.glyphs import callout_icon, tab_title_led_by_its_icon
from skaldr.export.markup import (
    DIVIDER_LINE,
    ENTITY_LOOKALIKE,
    HTML_LINE_BREAK,
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
from skaldr.export.runs import ExportRich
from skaldr.export.swaps import data_table_swapped_in, require_the_swap, web_address_of
from skaldr.export.tree import (
    Callout,
    CodeBlock,
    Columns,
    Diagram,
    DisplayMath,
    Divider,
    GenericNode,
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
)
from skaldr.export_targets import SLACK_TARGET
from skaldr.models import MEDIA_KIND_LABELS, Person
from skaldr.richtext import MarkerStyle, Plain, ScriptPosition

# external:slack canvases.create and canvases.edit limit markdown to "1 MiB (1,048,576 characters)"
SLACK_CANVAS_CHARACTER_LIMIT: Final = 1_048_576
DEEPEST_CANVAS_HEADING: Final = 3
CANVAS_ESCAPES: Final = str.maketrans({character: "\\" + character for character in "\\*_`[]<>~"})
CANVAS_FENCE: Final = ":::"
CALLOUT_OPEN: Final = "::: {.callout}"
LAYOUT_OPEN: Final = "::: {.layout}"
COLUMN_OPEN: Final = "::: {.column}"
MATH_LANGUAGE: Final = "latex"
BULLET_MARKER: Final = "*"
BULLET_INDENT: Final = len(BULLET_MARKER) + 1
LIST_SEPARATOR: Final = "&nbsp;"
HARD_LINE_BREAK: Final = "\\\n"
LINE_BREAK_ON_ONE_LINE: Final = " "
Place = Literal["top", "callout", "column"]


def _slack_date(day: date) -> str:
    return f"![](slack_date:{day.isoformat()})"


class _SlackRuns(CommonMarkRuns):
    def __init__(self, written_line_break: str) -> None:
        self.written_line_break = written_line_break

    def line_break(self) -> str:
        return self.written_line_break

    def unflanked_emphasis(self, _style: MarkerStyle, inner: str, /) -> str:
        return inner

    def refuse_a_tint(self) -> NoReturn:
        raise ExportInvariantError(
            "a Slack canvas cannot colour or highlight text; the export check should have refused it"
        )

    def require_links_to_its_own_headings(self) -> None:
        raise ExportInvariantError(
            "a Slack canvas cannot link to its own headings; the export check should have refused it"
        )

    def escape(self, text: str, /) -> str:
        return ENTITY_LOOKALIKE.sub(r"\\&", text.translate(CANVAS_ESCAPES))

    def date_mention(self, _label: str, start: date, end: date | None, /) -> str:
        return f"{_slack_date(start)} to {_slack_date(end)}" if end else _slack_date(start)

    def person_mention(self, label: str, _key: str, person: Person, /) -> str:
        if person.slack is None:
            return label
        return f"![](@{person.slack})"

    def math(self, expression: str, /) -> str:
        require_the_swap("inline math", "slack")
        return code_span(expression)

    def underline(self, _inner: str, /) -> str:
        raise ExportInvariantError("a Slack canvas has no underline; the export check should have refused it")

    def script(self, position: ScriptPosition, text: str, /) -> str:
        return in_unicode_script_form(position, text, TARGET_SUBJECTS["slack"])


@dataclass(frozen=True)
class _Item:
    text: ExportRich
    checked: bool
    nested: "_List | None"


@dataclass(frozen=True)
class _List:
    kind: ListKind
    items: tuple[_Item, ...]


@dataclass(frozen=True)
class _Title:
    text: ExportRich


@dataclass(frozen=True)
class _CanvasCallout:
    icon: str | None
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
    | _CanvasCallout
    | _Layout
)
_LIST_SEPARATOR_PARAGRAPH: Final = Paragraph((Plain(LIST_SEPARATOR),))


def _with_paragraph(text: ExportRich, paragraph: ExportRich) -> ExportRich:
    if not text or not paragraph:
        return text or paragraph
    return (*text, Plain(" "), *paragraph)


def _canvas_item(entry: ListEntry) -> _Item:
    text = entry.text
    nested: _List | None = None
    for child in folded(entry.children):
        match child:
            case Paragraph() if nested is None or not child.text:
                text = _with_paragraph(text, child.text)
            case ListNode() if nested is None:
                nested = _canvas_list(child)
            case _:
                raise ExportInvariantError(
                    f"a Slack canvas list item has no place for a {type(child).__name__} here; "
                    "the export check should have refused it"
                )
    return _Item(text, entry.checked, nested)


def _canvas_list(node: ListNode) -> _List:
    if node.kind == "number" and node.start != FIRST_LIST_NUMBER:
        raise ExportInvariantError(
            "a Slack canvas numbers every list from 1, so it has no form for a list starting at "
            f"{node.start}; the export check should have refused it"
        )
    return _List(node.kind, tuple(_canvas_item(entry) for entry in node.entries))


def _a_canvas_callout_cannot_hold(node: GenericNode) -> bool:
    match node:
        case TableNode() | Callout() | Toggle() | Divider():
            return True
        case Tabs():
            return bool(node.tabs)
        case _:
            return False


def _the_place_cannot_hold(node: GenericNode, place: Place) -> bool:
    match place:
        case "callout":
            return _a_canvas_callout_cannot_hold(node)
        case "column":
            return isinstance(node, TableNode | Callout | Divider | Columns)
        case "top":
            return False
        case _:
            assert_never(place)


def _require_the_place_can_hold(node: GenericNode, place: Place) -> None:
    if _the_place_cannot_hold(node, place):
        raise ExportInvariantError(
            f"a Slack canvas {place} has no place for a {type(node).__name__}; "
            "the export check should have refused it"
        )


def _canvas_callout(node: Callout) -> list[_CanvasBlock]:
    return [_CanvasCallout(callout_icon(node), tuple(_canvas_blocks(node.children, "callout")))]


def _canvas_columns(node: Columns) -> list[_CanvasBlock]:
    if len(node.columns) > CANVAS_LAYOUT_COLUMN_LIMIT:
        raise ExportInvariantError(
            f"a Slack canvas layout holds at most {CANVAS_LAYOUT_COLUMN_LIMIT} columns, not "
            f"{len(node.columns)}; the export check should have refused it"
        )
    return [_Layout(tuple(tuple(_canvas_blocks(column.children, "column")) for column in node.columns))]


def _toggle_title(node: Toggle) -> list[_CanvasBlock]:
    if node.heading_level is not None:
        return [Heading(node.heading_level, node.title, node.anchor)]
    return [_Title(node.title)]


def _canvas_tabs(node: Tabs, place: Place) -> list[_CanvasBlock]:
    return [
        block
        for tab in node.tabs
        for block in (_Title(tab_title_led_by_its_icon(tab)), *_canvas_blocks(tab.children, place))
    ]


def _canvas_block(node: GenericNode, place: Place) -> list[_CanvasBlock]:
    _require_the_place_can_hold(node, place)
    match node:
        case Heading() | Paragraph() | TableNode() | CodeBlock() | DisplayMath() | Media() | Quote():
            return [node]
        case ListNode():
            return [_canvas_list(node)]
        case Callout():
            return _canvas_callout(node)
        case Divider():
            return [node]
        case Toggle():
            return [*_toggle_title(node), *_canvas_blocks(node.children, place)]
        case Tabs():
            return _canvas_tabs(node, place)
        case Columns():
            return _canvas_columns(node)
        case Diagram():
            return _canvas_blocks(data_table_swapped_in(node, "slack"), place)
        case TableOfContents():
            return []
        case _:
            assert_never(node)


def _canvas_blocks(nodes: Sequence[Node], place: Place) -> list[_CanvasBlock]:
    return [block for node in folded(nodes) for block in _canvas_block(node, place)]


def _list_marker(kind: ListKind, number: int, checked: bool) -> tuple[str, int]:
    match kind:
        case "bullet":
            return BULLET_MARKER, BULLET_INDENT
        case "number":
            marker = f"{number}."
            return marker, len(marker) + 1
        case "check":
            return f"{BULLET_MARKER} [{'x' if checked else ' '}]", BULLET_INDENT
        case _:
            assert_never(kind)


def _canvas_over_the_size_limit(size: int) -> ExportRejectedError:
    return ExportRejectedError(
        SLACK_TARGET,
        f"the canvas Markdown is {size:,} characters, "
        f"over the {SLACK_CANVAS_CHARACTER_LIMIT:,} characters (1 MiB) a Slack canvas can hold",
        "split the document into several canvases or export it elsewhere",
    )


def _with_lists_kept_apart(
    rendered: Sequence[tuple[_CanvasBlock, list[str]]],
) -> list[tuple[_CanvasBlock, list[str]]]:
    kept_apart: list[tuple[_CanvasBlock, list[str]]] = []
    for block, lines in rendered:
        if kept_apart and isinstance(block, _List) and isinstance(kept_apart[-1][0], _List):
            kept_apart.append((_LIST_SEPARATOR_PARAGRAPH, [LIST_SEPARATOR]))
        kept_apart.append((block, lines))
    return kept_apart


class _CanvasWriter:
    def __init__(self) -> None:
        self.runs = _SlackRuns(LINE_BREAK_ON_ONE_LINE)
        self.paragraph_runs = _SlackRuns(HARD_LINE_BREAK)
        self.table_cell_runs = _SlackRuns(HTML_LINE_BREAK)

    def inline(self, runs: ExportRich) -> str:
        return self.runs.write(runs)

    def block_line(self, line: str) -> str:
        escaped = escape_block_start(line)
        return "\\" + escaped if escaped.startswith(CANVAS_FENCE) else escaped

    def block_text(self, runs: ExportRich) -> str:
        return self.block_line(self.inline(runs))

    def paragraph_lines(self, paragraph: Paragraph) -> list[str]:
        text = self.paragraph_runs.write(paragraph.text)
        return [self.block_line(line) for line in text.split("\n")] if text else []

    def list_lines(self, canvas_list: _List) -> list[str]:
        lines: list[str] = []
        for number, item in enumerate(canvas_list.items, start=FIRST_LIST_NUMBER):
            marker, indent = _list_marker(canvas_list.kind, number, item.checked)
            lines.append(f"{marker} {self.block_text(item.text)}".rstrip())
            if item.nested is not None:
                lines += indent_lines(self.list_lines(item.nested), " " * indent)
        return lines

    def table_lines(self, table: TableNode) -> list[str]:
        cells = table_width(table) * (1 + len(table.rows))
        if cells > CANVAS_TABLE_CELL_LIMIT:
            raise ExportInvariantError(
                f"a Slack canvas table holds at most {CANVAS_TABLE_CELL_LIMIT} cells, not {cells}; "
                "the export check should have refused it"
            )
        return pipe_table_lines(table, self.table_cell_runs)

    def title_lines(self, title: _Title) -> list[str]:
        text = self.inline(title.text)
        return [styled("bold", text)] if text else []

    def media_lines(self, media: Media) -> list[str]:
        url = web_address_of(media, "slack")
        if media.kind == "image":
            image = f"![{self.inline(media.description)}]({encode_url(url)})"
            caption = [styled("italic", self.inline(media.caption))] if media.caption else []
            return joined([[image], caption])
        return [self.runs.link(self.inline(media.caption) or MEDIA_KIND_LABELS[media.kind], url)]

    def quote_lines(self, quote: Quote) -> list[str]:
        parts = [self.block_text(line) for line in quote.lines]
        if quote.cite:
            parts.append(styled("italic", self.inline(quote.cite)))
        return quoted(joined([[part] for part in parts]))

    def callout_lines(self, callout: _CanvasCallout) -> list[str]:
        rendered = self.rendered(callout.blocks)
        body = joined([lines for _, lines in rendered])
        if callout.icon is None:
            return [CALLOUT_OPEN, *body, CANVAS_FENCE]
        if rendered and isinstance(rendered[0][0], Paragraph):
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
                return [heading_line(min(block.level, DEEPEST_CANVAS_HEADING), self.inline(block.text))]
            case Paragraph():
                return self.paragraph_lines(block)
            case _Title():
                return self.title_lines(block)
            case _List():
                return self.list_lines(block)
            case TableNode():
                return self.table_lines(block)
            case CodeBlock():
                return code_block_lines(block)
            case DisplayMath():
                require_the_swap("math block", "slack")
                return code_block_lines(CodeBlock(block.expression, MATH_LANGUAGE))
            case Media():
                return self.media_lines(block)
            case Quote():
                return self.quote_lines(block)
            case Divider():
                return [DIVIDER_LINE]
            case _CanvasCallout():
                return self.callout_lines(block)
            case _Layout():
                return self.layout_lines(block)
            case _:
                assert_never(block)

    def rendered(self, blocks: Sequence[_CanvasBlock]) -> list[tuple[_CanvasBlock, list[str]]]:
        written = [(block, self.lines(block)) for block in blocks]
        return _with_lists_kept_apart([(block, lines) for block, lines in written if lines])

    def blocks(self, blocks: Sequence[_CanvasBlock]) -> list[str]:
        return joined([lines for _, lines in self.rendered(blocks)])


def render_slack(nodes: Sequence[Node]) -> str:
    blocks = _canvas_blocks(nodes, "top")
    text = "\n".join(_CanvasWriter().blocks(blocks)) + "\n"
    if len(text) > SLACK_CANVAS_CHARACTER_LIMIT:
        raise _canvas_over_the_size_limit(len(text))
    return text
