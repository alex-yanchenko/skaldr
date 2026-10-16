import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Final, Literal, NoReturn, TypeGuard

from typing_extensions import assert_never

from skaldr.errors import ExportInvariantError, ExportRejectedError
from skaldr.export.capabilities import (
    CANVAS_HEADING_LEVEL_LIMIT,
    CANVAS_LAYOUT_COLUMN_LIMIT,
    CANVAS_TABLE_CELL_LIMIT,
    FIRST_LIST_NUMBER,
    TARGET_SUBJECTS,
    in_unicode_script_form,
)
from skaldr.export.folds import LINK_CARD_SEPARATOR, card_text, folded, quote_lines
from skaldr.export.glyphs import callout_icon, tab_title_led_by_its_icon
from skaldr.export.inline import bold, plain
from skaldr.export.lower.context import spaced as spaced_runs
from skaldr.export.lower.context import with_bold_label
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
from skaldr.export.runs import ExportRich, export_visible_text
from skaldr.export.swaps import data_table_swapped_in, require_the_swap, web_address_of
from skaldr.export.tree import (
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
    Heading,
    LinkCard,
    ListEntry,
    ListKind,
    ListNode,
    LoweredDocument,
    Media,
    Node,
    Paragraph,
    Quote,
    TableCell,
    TableNode,
    TableOfContents,
    Tabs,
    Toggle,
    ToneName,
    canvas_heading_shift,
)
from skaldr.export_targets import SLACK_TARGET
from skaldr.models import MEDIA_KIND_LABELS, Person
from skaldr.richtext import Link, MarkerStyle, Plain, ScriptPosition
from skaldr.typed_links import date_target_text

# external:slack canvases.create and canvases.edit limit markdown to "1 MiB (1,048,576 characters)"
SLACK_CANVAS_CHARACTER_LIMIT: Final = 1_048_576
CANVAS_ESCAPES: Final = str.maketrans({character: "\\" + character for character in "\\*_`[]<>~"})
ZERO_WIDTH_SPACE: Final = "​"
EMOJI_SHORTCODE_COLON: Final = re.compile(r"(?<!\w):(?=[\w+-]+:)")
CANVAS_FENCE: Final = ":::"
CALLOUT_OPEN: Final = "::: {.callout}"
LAYOUT_OPEN: Final = "::: {.layout}"
COLUMN_OPEN: Final = "::: {.column}"
MATH_LANGUAGE: Final = "latex"
BULLET_MARKER: Final = "*"
BULLET_INDENT: Final = len(BULLET_MARKER) + 1
TEXT_BULLET_MARKER: Final = "• "
TEXT_CHECK_MARKERS: Final = {False: "☐ ", True: "☑ "}
LIST_SEPARATOR: Final = "&nbsp;"
HARD_LINE_BREAK: Final = "\\\n"
LINE_BREAK_ON_ONE_LINE: Final = " "
CELL_BULLET_MARKER: Final = "- "
CELL_TEXT_BULLET: Final = "• "
CELL_TEXT_CHECK: Final = "☐ "
CELL_LIST_INDENT: Final = "  "
FACT_SEPARATOR: Final = " · "
COVER_LINK_LABEL: Final = "Cover image"
Place = Literal["top", "callout", "column"]
OwnFormNode = FactStrip | DefinitionList | Cards | LinkCard
CanvasNode = GenericNode | OwnFormNode


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
        broken = EMOJI_SHORTCODE_COLON.sub(f":{ZERO_WIDTH_SPACE}", text)
        return ENTITY_LOOKALIKE.sub(r"\\&", broken.translate(CANVAS_ESCAPES))

    def date_mention(self, label: str, start: date, end: date | None, /) -> str:
        return label if label.strip() else date_target_text(start, end)

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
class _BareUrl:
    url: str


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
    | _BareUrl
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


def _fact_strip_paragraph(strip: FactStrip) -> Paragraph:
    facts = [with_bold_label(fact.label, fact.value) for fact in strip.facts]
    return Paragraph(
        spaced_runs([fact for fact in facts if fact], FACT_SEPARATOR), authored_at=strip.authored_at
    )


def _canvas_definitions(node: DefinitionList, place: Place) -> list[_CanvasBlock]:
    return [
        block
        for definition in node.definitions
        for block in (
            Paragraph(bold(definition.term), authored_at=node.authored_at),
            *_canvas_blocks(definition.body, place),
        )
    ]


def _card_column(card: Card, path: str | None) -> tuple[_CanvasBlock, ...]:
    note = (Paragraph(plain(card.note), "muted", authored_at=path),) if card.note else ()
    return (Paragraph(card_text(card), authored_at=path), *note)


def _canvas_cards(node: Cards) -> list[_CanvasBlock]:
    blocks: list[_CanvasBlock] = []
    for start in range(0, len(node.cards), CANVAS_LAYOUT_COLUMN_LIMIT):
        row = node.cards[start : start + CANVAS_LAYOUT_COLUMN_LIMIT]
        if len(row) == 1:
            blocks.extend(_card_column(row[0], node.authored_at))
        else:
            blocks.append(_Layout(tuple(_card_column(card, node.authored_at) for card in row)))
    return blocks


def _canvas_link_card(node: LinkCard) -> list[_CanvasBlock]:
    detail = LINK_CARD_SEPARATOR.join(part for part in (node.domain, node.caption) if part)
    return [_BareUrl(node.url), Paragraph(plain(detail), authored_at=node.authored_at)]


def _written_in_its_own_form(node: Node, place: Place) -> TypeGuard[OwnFormNode]:
    match node:
        case FactStrip() | DefinitionList() | LinkCard():
            return True
        case Cards():
            return place == "top"
        case _:
            return False


def _canvas_forms(node: Node, place: Place) -> tuple[CanvasNode, ...]:
    return (node,) if _written_in_its_own_form(node, place) else folded([node])


def _canvas_block(node: CanvasNode, place: Place) -> list[_CanvasBlock]:
    match node:
        case FactStrip():
            return [_fact_strip_paragraph(node)]
        case DefinitionList():
            return _canvas_definitions(node, place)
        case Cards():
            return _canvas_cards(node)
        case LinkCard():
            return _canvas_link_card(node)
        case _:
            return _canvas_generic_block(node, place)


def _canvas_generic_block(node: GenericNode, place: Place) -> list[_CanvasBlock]:
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
    return [
        block for node in nodes for form in _canvas_forms(node, place) for block in _canvas_block(form, place)
    ]


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


def _cell_marker(kind: ListKind, number: int) -> str:
    match kind:
        case "bullet" | "check":
            return CELL_BULLET_MARKER
        case "number":
            return f"{number}. "
        case _:
            assert_never(kind)


def _cell_text_marker(kind: ListKind, number: int) -> str:
    match kind:
        case "bullet":
            return CELL_TEXT_BULLET
        case "number":
            return f"{number}\\. "
        case "check":
            return CELL_TEXT_CHECK
        case _:
            assert_never(kind)


def _text_marker(kind: ListKind, number: int, checked: bool) -> str:
    match kind:
        case "bullet":
            return TEXT_BULLET_MARKER
        case "number":
            return f"{number}. "
        case "check":
            return TEXT_CHECK_MARKERS[checked]
        case _:
            assert_never(kind)


def _cell_lines(
    nodes: Sequence[Node], depth: int, enclosing_kind: ListKind | None
) -> Iterator[tuple[str, ExportRich]]:
    for node in folded(nodes):
        match node:
            case Paragraph():
                yield "", node.text
            case ListNode():
                kind = node.kind if enclosing_kind is None else enclosing_kind
                for number, entry in enumerate(node.entries, start=node.start):
                    marker = _cell_marker(kind, number)
                    own = "" if kind == node.kind else _cell_text_marker(node.kind, number)
                    yield f"{CELL_LIST_INDENT * depth}{marker}{own}", entry.text
                    yield from _cell_lines(entry.children, depth + 1, kind)
            case _:
                raise ExportInvariantError(
                    "a quote or a table cell holds only paragraphs and lists, "
                    f"not a {type(node).__name__}; the lowering should not have put one there"
                )


def _kind_a_canvas_takes_under(parent_kind: ListKind | None, canvas_list: _List) -> ListKind:
    if parent_kind is None or parent_kind == canvas_list.kind:
        return canvas_list.kind
    if parent_kind == "check":
        raise ExportInvariantError(
            f"a Slack canvas nests only check items under a check item, not a {canvas_list.kind} list; "
            "a check list's nested items are check items, so the lowering should not have made one"
        )
    return parent_kind


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
    def __init__(self, heading_shift: int) -> None:
        self.heading_shift = heading_shift
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

    def list_lines(self, canvas_list: _List, parent_kind: ListKind | None = None) -> list[str]:
        kind = _kind_a_canvas_takes_under(parent_kind, canvas_list)
        lines: list[str] = []
        for number, item in enumerate(canvas_list.items, start=FIRST_LIST_NUMBER):
            marker, indent = _list_marker(kind, number, item.checked)
            text = item.text
            if kind != canvas_list.kind:
                text = (Plain(_text_marker(canvas_list.kind, number, item.checked)), *text)
            lines.append(f"{marker} {self.block_text(text)}".rstrip())
            if item.nested is not None:
                lines += indent_lines(self.list_lines(item.nested, kind), " " * indent)
        return lines

    def table_lines(self, table: TableNode) -> list[str]:
        cells = table_width(table) * (1 + len(table.rows))
        if cells > CANVAS_TABLE_CELL_LIMIT:
            raise ExportInvariantError(
                f"a Slack canvas table holds at most {CANVAS_TABLE_CELL_LIMIT} cells, not {cells}; "
                "the export check should have refused it"
            )
        return pipe_table_lines(table, self.table_cell_runs, self.list_cell)

    def list_cell(self, cell: TableCell, tones: Sequence[ToneName]) -> str:
        lines = [self.cell_line(prefix, text) for prefix, text in _cell_lines(cell.blocks, 0, None)]
        text = HTML_LINE_BREAK.join(lines)
        dots = self.table_cell_runs.write_toned(tones, ())
        return f"{dots} {text}" if dots else text

    def cell_line(self, prefix: str, text: ExportRich) -> str:
        return prefix + self.table_cell_runs.write(text)

    def heading_line(self, heading: Heading) -> str:
        level = heading.level - self.heading_shift
        if level > CANVAS_HEADING_LEVEL_LIMIT:
            raise ExportInvariantError(
                f"a Slack canvas holds headings down to level {CANVAS_HEADING_LEVEL_LIMIT}, "
                f"so it has no form for '{export_visible_text(heading.text)}' at level {level}; "
                "the export check should have refused it"
            )
        return heading_line(level, self.inline(heading.text))

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
        parts = [self.block_text(line) for line in quote_lines(quote)]
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
                return [self.heading_line(block)]
            case Paragraph():
                return self.paragraph_lines(block)
            case _Title():
                return self.title_lines(block)
            case _BareUrl():
                return [encode_url(block.url)]
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


def _with_a_list_separator_where_lists_meet(
    rendered: list[tuple[_CanvasBlock, list[str]]], last_before: _CanvasBlock | None
) -> list[tuple[_CanvasBlock, list[str]]]:
    if rendered and isinstance(rendered[0][0], _List) and isinstance(last_before, _List):
        return [(_LIST_SEPARATOR_PARAGRAPH, [LIST_SEPARATOR]), *rendered]
    return rendered


def render_slack_regions(document: LoweredDocument) -> tuple[str, ...]:
    writer = _CanvasWriter(canvas_heading_shift(document.body))
    texts: list[str] = []
    last_block: _CanvasBlock | None = None
    for region in document.regions:
        rendered = writer.rendered(_canvas_blocks(region.nodes, "top"))
        rendered = _with_a_list_separator_where_lists_meet(rendered, last_block)
        texts.append("\n".join(joined([lines for _, lines in rendered])) + "\n" if rendered else "")
        last_block = rendered[-1][0] if rendered else last_block
    return tuple(texts)


def canvas_title(document: LoweredDocument) -> str:
    return f"{document.icon} {document.title}" if document.icon else document.title


def render_slack_document(document: LoweredDocument) -> str:
    cover = (Paragraph((Link(plain(COVER_LINK_LABEL), document.cover),)),) if document.cover else ()
    return render_slack((*cover, *document.body))


def render_slack(nodes: Sequence[Node]) -> str:
    blocks = _canvas_blocks(nodes, "top")
    text = "\n".join(_CanvasWriter(canvas_heading_shift(nodes)).blocks(blocks)) + "\n"
    if len(text) > SLACK_CANVAS_CHARACTER_LIMIT:
        raise _canvas_over_the_size_limit(len(text))
    return text
