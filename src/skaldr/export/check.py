from collections import deque
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, replace
from itertools import chain
from typing import Final

from typing_extensions import Self, assert_never

from skaldr import models
from skaldr.errors import ExportRejectedError
from skaldr.export.capabilities import (
    BACKTICK,
    CANVAS_TABLE_CELL_LIMIT,
    CAPABILITIES,
    CLOSING_TAG_OPENER,
    FIRST_LIST_NUMBER,
    PLACEMENTS,
    CellCount,
    Container,
    Details,
    FencedInAListItem,
    FencedInAListItemFeature,
    GridInAStep,
    Held,
    HeldByAListItem,
    InlineCode,
    ListInAQuote,
    ListItemFeature,
    ListStart,
    MarkedText,
    OtherDocumentLink,
    Placement,
    Rejection,
    SameDocumentLink,
    ScriptForm,
    TextMarkFeature,
    TextNumbering,
    character_without_a_unicode_form,
)
from skaldr.export.inline import one_line
from skaldr.export.markup import table_width
from skaldr.export.runs import (
    Break,
    CheckMark,
    Chip,
    DecisionMark,
    ExportRich,
    ExportRun,
    Gauge,
    IndicatorMark,
    SectionLink,
    SpanKind,
    StatusMark,
    SwimlaneMark,
    TonedLabel,
    export_visible_text,
    nested_runs,
    tint_kind,
)
from skaldr.export.tree import (
    AuthoredNode,
    BlockRegion,
    Callout,
    CodeBlock,
    Columns,
    Diagram,
    DisplayMath,
    Divider,
    Heading,
    ListEntry,
    ListNode,
    LoweredDocument,
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
from skaldr.export_targets import ExportTarget
from skaldr.models import InnerGrid, ListBlock, Report, Walkthrough, walk_located_block
from skaldr.prose_blocks import ProseList, prose_blocks
from skaldr.richtext import (
    AnchorLink,
    Citation,
    Code,
    DateMention,
    DocumentLink,
    InlineMath,
    IssueLink,
    Link,
    PersonMention,
    Placeholder,
    Plain,
    ScriptText,
    Styled,
    Tinted,
)

_NODE_TERMS: Final[Mapping[type, str]] = {
    Heading: "heading",
    Paragraph: "text",
    ListNode: "list",
    TableNode: "table",
    CodeBlock: "code block",
    DisplayMath: "math block",
    Callout: "callout",
    Quote: "quote",
    Divider: "divider",
    Media: "media block",
    Toggle: "toggle",
    Columns: "grid",
    Tabs: "set of tabs",
    Diagram: "diagram",
}


DocumentPosition = tuple[tuple[int, int, str], ...]
LocatedDetails = tuple[str, Details]


@dataclass(frozen=True)
class FeatureHit:
    details: Details
    path: str | None = None
    heading: str = ""


@dataclass(frozen=True)
class _Place:
    container: Container = "document"
    callout_name: str = _NODE_TERMS[Callout]
    toggle_names: tuple[str, ...] = ()

    def holder(self) -> str:
        match self.container:
            case "callout":
                return f"a {self.callout_name}"
            case "toggle":
                return f"a {self.toggle_names[-1]}"
            case "toggle inside a toggle":
                return f"a {self.toggle_names[-1]} that is itself inside a {self.toggle_names[-2]}"
            case "document":
                return "the document"
            case _:
                assert_never(self.container)

    def holder_name(self) -> str:
        match self.container:
            case "callout":
                return self.callout_name
            case "toggle" | "toggle inside a toggle":
                return self.toggle_names[-1]
            case "document":
                return "document"
            case _:
                assert_never(self.container)

    def in_a_callout(self, name: str) -> Self:
        return replace(self, container="callout", callout_name=name)

    def in_a_toggle(self, name: str) -> Self:
        nested = self.container in ("toggle", "toggle inside a toggle")
        return replace(
            self,
            container="toggle inside a toggle" if nested else "toggle",
            toggle_names=(*self.toggle_names, name),
        )


def _term(node: Node) -> str:
    named = node.authored_as if isinstance(node, AuthoredNode) else None
    return named or _NODE_TERMS[type(node)]


def _held(node: Node) -> Held | None:
    match node:
        case TableNode():
            return "table"
        case Callout():
            return "callout"
        case Quote() if any(node.lines) or node.cite:
            return "quote"
        case Toggle():
            return "toggle"
        case Tabs() if node.tabs:
            return "toggle"
        case _:
            return None


def _what_a_list_item_cannot_hold(child: Node, holds_a_list: bool) -> str | None:
    match child:
        case Paragraph():
            return "a paragraph after its nested list" if holds_a_list and child.text else None
        case ListNode():
            return "a second nested list" if holds_a_list else None
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
            assert_never(child)


def _own_texts(node: Node) -> Iterator[ExportRich]:
    match node:
        case Heading() | Paragraph():
            yield node.text
        case ListNode():
            yield from (entry.text for entry in node.entries)
        case TableNode():
            yield from (cell.text for cell in node.header)
            yield from (cell.text for row in node.rows for cell in row.cells)
        case Media():
            yield from (node.description, node.caption)
        case Quote():
            yield from (*node.lines, node.cite)
        case Toggle():
            yield node.title
        case Tabs():
            yield from (tab.title for tab in node.tabs)
        case Callout() | CodeBlock() | DisplayMath() | Divider() | Columns() | Diagram() | TableOfContents():
            return
        case _:
            assert_never(node)


def _visible_text(runs: ExportRich) -> str:
    return one_line(export_visible_text(runs))


@dataclass(frozen=True)
class _RunPlace:
    in_a_table_cell: bool
    span: SpanKind | None = None
    span_is_generated: bool = False

    def around(self, run: ExportRun) -> Self:
        match run:
            case Tinted():
                return replace(self, span=tint_kind(run), span_is_generated=False)
            case TonedLabel():
                return replace(self, span="colour", span_is_generated=True)
            case _:
                return self


def _tint_features(run: Tinted, place: _RunPlace) -> Iterator[TextMarkFeature]:
    if run.tone is not None and run.background is not None:
        yield "colour and highlight span"
        return
    kind = tint_kind(run)
    yield "colour span" if kind == "colour" else "highlight span"
    if place.span is None or place.span == kind:
        return
    if place.span_is_generated:
        yield "highlight span inside a toned walkthrough step title"
    else:
        yield "colour and highlight span"


def _code_details(code: Code, place: _RunPlace) -> Iterator[InlineCode]:
    if BACKTICK in code.text:
        yield InlineCode("inline code holding a backtick", code.text)
    elif CLOSING_TAG_OPENER not in code.text:
        return
    elif place.in_a_table_cell:
        yield InlineCode("inline code holding a closing tag in a table cell", code.text)
    elif place.span is not None:
        yield InlineCode("inline code holding a closing tag in a coloured or highlighted span", code.text)


def _inline_details(run: ExportRun, place: _RunPlace) -> Iterator[Details]:
    match run:
        case Code():
            yield from _code_details(run, place)
        case ScriptText():
            character = character_without_a_unicode_form(run.position, run.text)
            if character is not None:
                yield ScriptForm(run.position, run.text, character)
        case Tinted():
            text = _visible_text(run.runs)
            yield from (MarkedText(feature, text) for feature in _tint_features(run, place))
        case Styled() if run.style == "underline":
            yield MarkedText("underline", _visible_text(run.runs))
        case AnchorLink():
            yield SameDocumentLink(_visible_text(run.label), run.as_written())
        case DocumentLink():
            yield OtherDocumentLink(_visible_text(run.label), run.doc_id)
        case (
            Plain()
            | Link()
            | DateMention()
            | PersonMention()
            | IssueLink()
            | Citation()
            | Placeholder()
            | Styled()
            | InlineMath()
            | Break()
            | StatusMark()
            | SwimlaneMark()
            | IndicatorMark()
            | CheckMark()
            | DecisionMark()
            | Gauge()
            | SectionLink()
            | TonedLabel()
            | Chip()
        ):
            return
        case _:
            assert_never(run)


def _inline_details_in(runs: Iterable[ExportRun], place: _RunPlace) -> Iterator[Details]:
    for run in runs:
        yield from _inline_details(run, place)
        yield from _inline_details_in(nested_runs(run), place.around(run))


def _authored_on_its_own(child: Node, holder: ListNode) -> bool:
    return child.authored_at != holder.authored_at


def _item_feature(child: Node, holder: ListNode) -> ListItemFeature:
    in_a_step = _authored_on_its_own(child, holder)
    return "block inside a walkthrough step" if in_a_step else "block inside a list item"


def _fenced_item_feature(child: Node, holder: ListNode) -> FencedInAListItemFeature:
    if _authored_on_its_own(child, holder):
        return "table, callout, heading, quote, toggle or divider inside a walkthrough step"
    return "table, callout, heading, quote, toggle or divider inside a list item"


def _fenced_off_from_a_jira_list_item(child: Node) -> Iterator[Node]:
    match child:
        case Heading() | TableNode() | Callout() | Divider() | Toggle():
            yield child
        case Quote() if any(child.lines) or child.cite:
            yield child
        case Tabs() if child.tabs:
            yield child
        case Columns() | Diagram():
            for nested in nested_nodes(child):
                yield from _fenced_off_from_a_jira_list_item(nested)
        case (
            Paragraph()
            | ListNode()
            | CodeBlock()
            | DisplayMath()
            | Media()
            | Quote()
            | Tabs()
            | TableOfContents()
        ):
            return
        case _:
            assert_never(child)


def _document_position(path: str) -> DocumentPosition:
    return tuple((0, int(part), "") if part.isdigit() else (1, 0, part) for part in path.split("."))


class _TreeWalk:
    def __init__(self, located: Iterable[LocatedDetails]) -> None:
        self.heading = ""
        self.located = deque(sorted(located, key=lambda each: _document_position(each[0])))

    def note_heading(self, text: ExportRich) -> None:
        self.heading = export_visible_text(text).strip() or self.heading

    def hit(self, details: Details, path: str | None) -> FeatureHit:
        return FeatureHit(details, path, self.heading)

    def located_hits_before(self, node: Node) -> Iterator[FeatureHit]:
        if node.authored_at is None:
            return
        position = _document_position(node.authored_at)
        while self.located and _document_position(self.located[0][0]) <= position:
            path, details = self.located.popleft()
            yield self.hit(details, path)

    def document(self, body: Iterable[Node]) -> Iterator[FeatureHit]:
        yield from self.nodes(body, _Place())
        while self.located:
            path, details = self.located.popleft()
            yield self.hit(details, path)

    def nodes(self, nodes: Iterable[Node], place: _Place) -> Iterator[FeatureHit]:
        for node in nodes:
            yield from self.node(node, place)

    def inline_hits(self, node: Node) -> Iterator[FeatureHit]:
        place = _RunPlace(in_a_table_cell=isinstance(node, TableNode))
        for details in _inline_details_in(chain.from_iterable(_own_texts(node)), place):
            yield self.hit(details, node.authored_at)

    def node(self, node: Node, place: _Place) -> Iterator[FeatureHit]:
        yield from self.located_hits_before(node)
        yield from self.inline_hits(node)
        match node:
            case Heading():
                self.note_heading(node.text)
            case ListNode():
                yield from self.list_hits(node, place)
            case TableNode():
                yield from self.table_hits(node)
            case Callout():
                yield from self.nodes(node.children, place.in_a_callout(_term(node)))
            case Toggle():
                if node.heading_level is not None:
                    self.note_heading(node.title)
                yield from self.nodes(node.children, place.in_a_toggle(_term(node)))
            case Tabs():
                inside = place.in_a_toggle(_term(node))
                for tab in node.tabs:
                    yield from self.nodes(tab.children, inside)
            case Columns() | Diagram():
                yield from self.nodes(nested_nodes(node), place)
            case (
                Paragraph() | CodeBlock() | DisplayMath() | Media() | Quote() | Divider() | TableOfContents()
            ):
                pass
            case _:
                assert_never(node)
        yield from self.placement_hits(node, place)

    def placement_hits(self, node: Node, place: _Place) -> Iterator[FeatureHit]:
        held = _held(node)
        container = place.container
        if held is None or container in ("document", "toggle"):
            return
        feature = PLACEMENTS.get((container, held))
        if feature is not None:
            details = Placement(feature, _term(node), place.holder(), place.holder_name())
            yield self.hit(details, node.authored_at)

    def list_hits(self, node: ListNode, place: _Place) -> Iterator[FeatureHit]:
        if node.kind == "number" and node.start != FIRST_LIST_NUMBER:
            yield self.hit(ListStart(node.start), node.authored_at)
        for entry in node.entries:
            yield from self.entry_hits(entry, node, place)

    def entry_hits(self, entry: ListEntry, holder: ListNode, place: _Place) -> Iterator[FeatureHit]:
        holds_a_list = False
        for child in entry.children:
            yield from self.located_hits_before(child)
            what = _what_a_list_item_cannot_hold(child, holds_a_list)
            if what is not None:
                yield self.hit(HeldByAListItem(_item_feature(child, holder), what), child.authored_at)
            fenced = next(_fenced_off_from_a_jira_list_item(child), None)
            if fenced is not None:
                details = FencedInAListItem(_fenced_item_feature(child, holder), _term(fenced))
                yield self.hit(details, fenced.authored_at)
            holds_a_list = holds_a_list or isinstance(child, ListNode)
            yield from self.node(child, place)

    def table_hits(self, node: TableNode) -> Iterator[FeatureHit]:
        cells = table_width(node) * (1 + len(node.rows))
        if cells > CANVAS_TABLE_CELL_LIMIT:
            yield self.hit(CellCount(cells), node.authored_at)


def _grids_in_walkthrough_steps(path: str, walkthrough: Walkthrough) -> Iterator[LocatedDetails]:
    for step_index, step in enumerate(walkthrough.steps):
        for index, detail in enumerate(step.detail):
            if isinstance(detail, InnerGrid):
                yield f"{path}.steps.{step_index}.detail.{index}.{detail.type}", GridInAStep()


def _text_numbering_hits(path: str, block: ListBlock) -> Iterator[LocatedDetails]:
    match block.numbering:
        case "letters":
            yield path, TextNumbering("letters")
        case "roman":
            yield path, TextNumbering("roman numerals")
        case "decimal" | None:
            return
        case _:
            assert_never(block.numbering)


def _holds_a_list(prose: str) -> bool:
    return any(isinstance(part, ProseList) for part in prose_blocks(prose))


def _model_hits(report: Report, document: LoweredDocument) -> Iterator[LocatedDetails]:
    located = (
        located_block
        for region in document.regions
        if isinstance(region, BlockRegion)
        for located_block in walk_located_block(region.source_index, report.blocks[region.source_index])
    )
    for path, block in located:
        if isinstance(block, Walkthrough):
            yield from _grids_in_walkthrough_steps(path, block)
        if isinstance(block, ListBlock):
            yield from _text_numbering_hits(path, block)
        if isinstance(block, models.Quote) and _holds_a_list(block.body):
            yield path, ListInAQuote()


def _where(hit: FeatureHit, rejection: Rejection) -> str | None:
    places = [f"at {hit.path}"] if hit.path else []
    if rejection.names_the_heading and hit.heading:
        places.append(f"under the heading '{hit.heading}'")
    return ", ".join(places) or None


def _raise_the_first_rejection(hits: Iterable[FeatureHit], target: ExportTarget) -> None:
    for hit in hits:
        capability = CAPABILITIES[hit.details.feature][target]
        if isinstance(capability, Rejection):
            details = vars(hit.details)
            raise ExportRejectedError(
                target,
                capability.why.format_map(details),
                capability.instead.format_map(details),
                _where(hit, capability),
            )


def reject_what_the_target_cannot_show(
    report: Report, document: LoweredDocument, target: ExportTarget
) -> None:
    walk = _TreeWalk(_model_hits(report, document))
    _raise_the_first_rejection(walk.document(document.body), target)
