from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from itertools import chain
from typing import Final

from typing_extensions import assert_never

from skaldr.errors import ExportInvariantError, ExportRejectedError
from skaldr.export.capabilities import (
    CANVAS_TABLE_CELL_LIMIT,
    CAPABILITIES,
    FEATURE_DETAILS,
    FIRST_LIST_NUMBER,
    PLACEMENTS,
    CellCount,
    Container,
    Details,
    Feature,
    Held,
    HeldByAListItem,
    ListStart,
    NoDetails,
    Placement,
    Rejection,
    ScriptForm,
    character_without_a_unicode_form,
)
from skaldr.export.lower import assemble_page, lower_regions, lowering_for
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
    StatusMark,
    SwimlaneMark,
    export_visible_text,
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
from skaldr.models import InnerGrid, Report, Walkthrough, walk_located_block
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


@dataclass(frozen=True)
class FeatureHit:
    feature: Feature
    details: Details = field(default_factory=NoDetails)
    path: str | None = None
    heading: str = ""

    def __post_init__(self) -> None:
        expected = FEATURE_DETAILS[self.feature]
        if not isinstance(self.details, expected):
            raise ExportInvariantError(
                f"the feature '{self.feature}' takes {expected.__name__} details, "
                f"not {type(self.details).__name__}"
            )


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

    def in_a_callout(self, name: str) -> "_Place":
        return replace(self, container="callout", callout_name=name)

    def in_a_toggle(self, name: str) -> "_Place":
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


def _scripts(runs: Iterable[ExportRun]) -> Iterator[ScriptText]:
    for run in runs:
        match run:
            case ScriptText():
                yield run
            case Link() | AnchorLink() | DateMention() | PersonMention() | IssueLink() | DocumentLink():
                yield from _scripts(run.label)
            case Styled() | Tinted():
                yield from _scripts(run.runs)
            case (
                Plain()
                | Code()
                | Citation()
                | Placeholder()
                | InlineMath()
                | Break()
                | StatusMark()
                | SwimlaneMark()
                | IndicatorMark()
                | CheckMark()
                | DecisionMark()
                | Gauge()
                | Chip()
            ):
                pass
            case _:
                assert_never(run)


def _item_feature(child: Node, holder: ListNode) -> Feature:
    authored_on_its_own = child.authored_at != holder.authored_at
    return "block inside a walkthrough step" if authored_on_its_own else "block inside a list item"


class _TreeWalk:
    def __init__(self) -> None:
        self.heading = ""

    def note_heading(self, text: ExportRich) -> None:
        self.heading = export_visible_text(text).strip() or self.heading

    def hit(self, feature: Feature, path: str | None, details: Details) -> FeatureHit:
        return FeatureHit(feature, details, path, self.heading)

    def nodes(self, nodes: Iterable[Node], place: _Place) -> Iterator[FeatureHit]:
        for node in nodes:
            yield from self.node(node, place)

    def script_hits(self, node: Node) -> Iterator[FeatureHit]:
        for script in (script for text in _own_texts(node) for script in _scripts(text)):
            character = character_without_a_unicode_form(script.position, script.text)
            if character is not None:
                details = ScriptForm(script.position, script.text, character)
                yield self.hit("subscript or superscript with no Unicode form", node.authored_at, details)

    def node(self, node: Node, place: _Place) -> Iterator[FeatureHit]:
        yield from self.script_hits(node)
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
            details = Placement(_term(node), place.holder(), place.holder_name())
            yield self.hit(feature, node.authored_at, details)

    def list_hits(self, node: ListNode, place: _Place) -> Iterator[FeatureHit]:
        if node.kind == "number" and node.start != FIRST_LIST_NUMBER:
            yield self.hit("numbered list starting past 1", node.authored_at, ListStart(node.start))
        for entry in node.entries:
            yield from self.entry_hits(entry, node, place)

    def entry_hits(self, entry: ListEntry, holder: ListNode, place: _Place) -> Iterator[FeatureHit]:
        holds_a_list = False
        for child in entry.children:
            what = _what_a_list_item_cannot_hold(child, holds_a_list)
            if what is not None:
                yield self.hit(_item_feature(child, holder), child.authored_at, HeldByAListItem(what))
            holds_a_list = holds_a_list or isinstance(child, ListNode)
            yield from self.node(child, place)

    def table_hits(self, node: TableNode) -> Iterator[FeatureHit]:
        cells = table_width(node) * (1 + len(node.rows))
        if cells > CANVAS_TABLE_CELL_LIMIT:
            yield self.hit("table over 300 cells", node.authored_at, CellCount(cells))


def _tree_hits(nodes: Sequence[Node]) -> Iterator[FeatureHit]:
    yield from _TreeWalk().nodes(nodes, _Place())


def _grids_in_walkthrough_steps(path: str, walkthrough: Walkthrough) -> Iterator[FeatureHit]:
    for step_index, step in enumerate(walkthrough.steps):
        for index, detail in enumerate(step.detail):
            if isinstance(detail, InnerGrid):
                where = f"{path}.steps.{step_index}.detail.{index}.{detail.type}"
                yield FeatureHit("grid inside a walkthrough step", path=where)


def _model_hits(report: Report, document: LoweredDocument) -> Iterator[FeatureHit]:
    for region in document.regions:
        if not isinstance(region, BlockRegion):
            continue
        for path, block in walk_located_block(region.source_index, report.blocks[region.source_index]):
            if isinstance(block, Walkthrough):
                yield from _grids_in_walkthrough_steps(path, block)


def _where(hit: FeatureHit, rejection: Rejection) -> str | None:
    places = [f"at {hit.path}"] if hit.path else []
    if rejection.names_the_heading and hit.heading:
        places.append(f"under the heading '{hit.heading}'")
    return ", ".join(places) or None


def _raise_the_first_rejection(hits: Iterable[FeatureHit], target: ExportTarget) -> None:
    for hit in hits:
        capability = CAPABILITIES[hit.feature][target]
        if isinstance(capability, Rejection):
            details = vars(hit.details)
            raise ExportRejectedError(
                target,
                capability.why.format_map(details),
                capability.instead.format_map(details),
                _where(hit, capability),
            )


def reject_unshowable_nodes(nodes: Sequence[Node], target: ExportTarget) -> None:
    _raise_the_first_rejection(_tree_hits(nodes), target)


def reject_what_the_target_cannot_show(
    report: Report, document: LoweredDocument, target: ExportTarget
) -> None:
    _raise_the_first_rejection(chain(_model_hits(report, document), _tree_hits(document.body)), target)


def reject_what_the_publish_targets_cannot_show(report: Report) -> None:
    if report.publish is None:
        return
    lowering = lowering_for(report)
    regions = lower_regions(lowering)
    for publish_target in report.publish.targets:
        chosen = [region for region in regions if publish_target.builds_from(region.section_id)]
        page = assemble_page(chosen, lowering)
        reject_what_the_target_cannot_show(report, page, publish_target.export_target())
