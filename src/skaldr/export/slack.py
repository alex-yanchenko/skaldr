from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Final, Literal

from typing_extensions import assert_never

from skaldr.errors import ExportRejectedError
from skaldr.export.glyphs import CALLOUT_ICON, tab_icon
from skaldr.export.markup import (
    DIVIDER_LINE,
    ENTITY_LOOKALIKE,
    HTML_LINE_BREAK,
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
from skaldr.export_targets import SLACK_TARGET
from skaldr.models import (
    MEDIA_KIND_LABELS,
    InnerGrid,
    Report,
    Walkthrough,
)
from skaldr.richtext import MarkerStyle, Plain, ScriptPosition

SLACK_CANVAS_LIMIT: Final = 1_048_576
SLACK_TABLE_CELL_LIMIT: Final = 300
DEEPEST_CANVAS_HEADING: Final = 3
MOST_LAYOUT_COLUMNS: Final = 3
CANVAS_ESCAPES: Final = str.maketrans({character: "\\" + character for character in "\\*_`[]<>~"})
CANVAS_FENCE: Final = ":::"
CALLOUT_OPEN: Final = "::: {.callout}"
LAYOUT_OPEN: Final = "::: {.layout}"
COLUMN_OPEN: Final = "::: {.column}"
MATH_LANGUAGE: Final = "latex"
BULLET_MARKER: Final = "*"
BULLET_INDENT: Final = len(BULLET_MARKER) + 1
LIST_SEPARATOR: Final = "\N{NO-BREAK SPACE}"
HARD_LINE_BREAK: Final = "\\\n"
LINE_BREAK_ON_ONE_LINE: Final = " "
OUT_OF_THE_LIST: Final = "move it out of the list, after the list"
OUT_OF_THE_STEP: Final = "move it out of the step, after the walkthrough"
UNICODE_SCRIPT_FORMS: Final[Mapping[ScriptPosition, Mapping[int, int]]] = {
    "superscript": str.maketrans(
        "0123456789+-\N{MINUS SIGN}=()ABDEGHIJKLMNOPRTUVWabcdefghijklmnoprstuvwxyz",
        "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁻⁼⁽⁾ᴬᴮᴰᴱᴳᴴᴵᴶᴷᴸᴹᴺᴼᴾᴿᵀᵁⱽᵂᵃᵇᶜᵈᵉᶠᵍʰⁱʲᵏˡᵐⁿᵒᵖʳˢᵗᵘᵛʷˣʸᶻ",
    ),
    "subscript": str.maketrans(
        "0123456789+-\N{MINUS SIGN}=()aehijklmnoprstuvx",
        "₀₁₂₃₄₅₆₇₈₉₊₋₋₌₍₎ₐₑₕᵢⱼₖₗₘₙₒₚᵣₛₜᵤᵥₓ",
    ),
}
Place = Literal["top", "callout", "column"]


def _slack_date(day: date) -> str:
    return f"![](slack_date:{day.isoformat()})"


def _script_without_a_unicode_form(
    position: ScriptPosition, text: str, character: str
) -> ExportRejectedError:
    return ExportRejectedError(
        SLACK_TARGET,
        f"a Slack canvas cannot show the {position} '{text}', "
        f"since '{character}' has no Unicode {position} form",
        f"write the text without the {position} or export the document elsewhere",
    )


def _in_unicode_script_form(position: ScriptPosition, text: str) -> str:
    forms = UNICODE_SCRIPT_FORMS[position]
    without_a_form = next((character for character in text if ord(character) not in forms), None)
    if without_a_form is not None:
        raise _script_without_a_unicode_form(position, text, without_a_form)
    return text.translate(forms)


class _SlackRuns(CommonMarkRuns):
    def __init__(self, written_line_break: str) -> None:
        self.written_line_break = written_line_break

    def line_break(self) -> str:
        return self.written_line_break

    def unflanked_emphasis(self, _style: MarkerStyle, inner: str, /) -> str:
        return inner

    def escape(self, text: str, /) -> str:
        return ENTITY_LOOKALIKE.sub(r"\\&", text.translate(CANVAS_ESCAPES))

    def date_mention(self, _label: str, start: date, end: date | None, /) -> str:
        return f"{_slack_date(start)} to {_slack_date(end)}" if end else _slack_date(start)

    def math(self, expression: str, /) -> str:
        return code_span(expression)

    def underline(self, inner: str, /) -> str:
        return inner

    def script(self, position: ScriptPosition, text: str, /) -> str:
        return _in_unicode_script_form(position, text)


@dataclass(frozen=True)
class _Item:
    text: ExportRich
    checked: bool
    nested: "_List | None"


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
_LIST_SEPARATOR_PARAGRAPH: Final = Paragraph((Plain(LIST_SEPARATOR),))
_MOVED_OUT_OF_A_CALLOUT: Final = (TableNode, _CanvasCallout, Divider, _Layout)
_KEPT_OUT_OF_A_LAYOUT: Final = (TableNode, _CanvasCallout)


def _with_paragraph(text: ExportRich, paragraph: ExportRich) -> ExportRich:
    if not text or not paragraph:
        return text or paragraph
    return (*text, Plain(" "), *paragraph)


_HeldOutsideAListItem = (
    TableNode
    | CodeBlock
    | DisplayMath
    | Media
    | Callout
    | Quote
    | Divider
    | Toggle
    | Columns
    | Tabs
    | Diagram
    | TableOfContents
    | Heading
)


def _what_a_list_item_cannot_hold(node: _HeldOutsideAListItem) -> str:
    match node:
        case CodeBlock():
            return "a code block"
        case TableNode():
            return "a table"
        case Quote():
            return "a quote"
        case Callout():
            return "a callout"
        case Media():
            return "an image or a media link"
        case Diagram():
            return "a diagram"
        case DisplayMath():
            return "a math block"
        case Heading():
            return "a heading"
        case Toggle():
            return "a toggle"
        case Tabs():
            return "a set of tabs"
        case Columns():
            return "a column layout"
        case Divider():
            return "a divider"
        case TableOfContents():
            return "a table of contents"
        case _:
            assert_never(node)


def _authored_on_its_own_inside_the_item(held: Node, holder: ListNode) -> bool:
    return held.authored_at != holder.authored_at


def _list_item_cannot_hold(what: str, held: Node, holder: ListNode) -> ExportRejectedError:
    return ExportRejectedError(
        SLACK_TARGET,
        f"a Slack canvas list item holds only text and one nested list, so it cannot show {what}",
        OUT_OF_THE_STEP if _authored_on_its_own_inside_the_item(held, holder) else OUT_OF_THE_LIST,
        f"at {held.authored_at}" if held.authored_at else None,
    )


def _canvas_item(entry: ListEntry, holder: ListNode) -> _Item:
    text = entry.text
    nested: _List | None = None
    for child in entry.children:
        match child:
            case Paragraph() if nested is not None and child.text:
                raise _list_item_cannot_hold("a paragraph after its nested list", child, holder)
            case Paragraph():
                text = _with_paragraph(text, child.text)
            case ListNode() if nested is not None:
                raise _list_item_cannot_hold("a second nested list", child, holder)
            case ListNode():
                nested = _canvas_list(child)
            case _:
                raise _list_item_cannot_hold(_what_a_list_item_cannot_hold(child), child, holder)
    return _Item(text, entry.checked, nested)


def _canvas_list(node: ListNode) -> _List:
    return _List(node.kind, tuple(_canvas_item(entry, node) for entry in node.entries), node.start)


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
            return [_canvas_list(node)]
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
            return BULLET_MARKER, BULLET_INDENT
        case "number":
            marker = f"{min(number, LARGEST_ORDERED_MARKER_NUMBER)}."
            return marker, len(marker) + 1
        case "check":
            return f"{BULLET_MARKER} [{'x' if checked else ' '}]", BULLET_INDENT
        case _:
            assert_never(kind)


def _table_over_the_cell_limit(cells: int, nearest_heading: str) -> ExportRejectedError:
    return ExportRejectedError(
        SLACK_TARGET,
        f"a table has {cells:,} cells, over the {SLACK_TABLE_CELL_LIMIT} a Slack canvas table can hold",
        "split it into two tables or export it elsewhere",
        f"under the heading '{nearest_heading}'" if nearest_heading else None,
    )


def _grid_in_a_walkthrough_step(path: str) -> ExportRejectedError:
    return ExportRejectedError(
        SLACK_TARGET,
        "a Slack canvas cannot show a grid inside a walkthrough step, "
        "since a canvas list item holds only text",
        "move the grid out of the step, after the walkthrough",
        f"at {path}",
    )


def _grids_in_walkthrough_steps(report: Report) -> Iterator[str]:
    for path, block in report.located_blocks:
        if not isinstance(block, Walkthrough):
            continue
        for step_index, step in enumerate(block.steps):
            for index, detail in enumerate(step.detail):
                if isinstance(detail, InnerGrid):
                    yield f"{path}.steps.{step_index}.detail.{index}.{detail.type}"


def reject_what_a_canvas_cannot_show(report: Report) -> None:
    first_grid = next(_grids_in_walkthrough_steps(report), None)
    if first_grid is not None:
        raise _grid_in_a_walkthrough_step(first_grid)


def _canvas_over_the_size_limit(size: int) -> ExportRejectedError:
    return ExportRejectedError(
        SLACK_TARGET,
        f"the canvas Markdown is {size:,} characters, "
        f"over the {SLACK_CANVAS_LIMIT:,} a Slack canvas can hold",
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
        self.nearest_heading = ""

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
        for number, item in enumerate(canvas_list.items, start=canvas_list.start):
            marker, indent = _list_marker(canvas_list.kind, number, item.checked)
            lines.append(f"{marker} {self.block_text(item.text)}".rstrip())
            if item.nested is not None:
                lines += indent_lines(self.list_lines(item.nested), " " * indent)
        return lines

    def table_lines(self, table: TableNode) -> list[str]:
        cells = table_width(table) * (1 + len(table.rows))
        if cells > SLACK_TABLE_CELL_LIMIT:
            raise _table_over_the_cell_limit(cells, self.nearest_heading)
        return pipe_table_lines(table, self.table_cell_runs.write)

    def title_lines(self, title: _Title) -> list[str]:
        text = self.inline(title.text)
        if not text:
            return [title.icon] if title.icon else []
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
                self.nearest_heading = export_visible_text(block.text).strip() or self.nearest_heading
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
        return _with_lists_kept_apart([(block, lines) for block, lines in written if lines])

    def blocks(self, blocks: Sequence[_CanvasBlock]) -> list[str]:
        return joined([lines for _, lines in self.rendered(blocks)])


def render_slack(nodes: Sequence[Node]) -> str:
    blocks = _canvas_blocks(nodes, "top")
    text = "\n".join(_CanvasWriter().blocks(blocks)) + "\n"
    if len(text) > SLACK_CANVAS_LIMIT:
        raise _canvas_over_the_size_limit(len(text))
    return text
