from dataclasses import dataclass, field, replace
from typing import Final, Literal, get_args

from skaldr.export.runs import ExportRich
from skaldr.models import MediaKind, ToneLiteral

ToneName = Literal[ToneLiteral, "muted"]
ListKind = Literal["bullet", "number", "check"]
AuthoredName = Literal[
    "panel",
    "grid cell",
    "note",
    "callout",
    "toggle",
    "section",
    "part",
    "legend",
    "link card",
    "link embed",
    "chart",
    "comparison",
    "matrix",
    "swimlane",
    "request",
    "request step",
    "request verdict",
]
MediaNodeKind = Literal["image", MediaKind]
HeadingLevel = Literal[1, 2, 3, 4, 5, 6]
XYChartMark = Literal["bar", "line"]
GraphKind = Literal["flow", "fan"]
HEADING_LEVELS: Final[tuple[HeadingLevel, ...]] = get_args(HeadingLevel)
COLUMN_RATIO_TOTAL: Final = 100


@dataclass(frozen=True)
class Heading:
    level: HeadingLevel
    text: ExportRich
    anchor: str | None = None
    authored_at: str | None = field(default=None, compare=False)


@dataclass(frozen=True)
class Paragraph:
    text: ExportRich
    tone: ToneName | None = None
    authored_at: str | None = field(default=None, compare=False)


@dataclass(frozen=True)
class ListEntry:
    text: ExportRich
    checked: bool = False
    children: "tuple[Node, ...]" = ()


@dataclass(frozen=True)
class ListNode:
    kind: ListKind
    entries: tuple[ListEntry, ...]
    start: int = 1
    authored_at: str | None = field(default=None, compare=False)


@dataclass(frozen=True)
class TableCell:
    text: ExportRich
    tone: ToneName | None = None


@dataclass(frozen=True)
class TableRow:
    cells: tuple[TableCell, ...]
    tone: ToneName | None = None
    emphasis: Literal["group", "total"] | None = None


@dataclass(frozen=True)
class TableColumn:
    tone: ToneName | None = None
    share: float | None = None


@dataclass(frozen=True)
class TableNode:
    header: tuple[TableCell, ...]
    rows: tuple[TableRow, ...]
    header_column: bool = False
    columns: tuple[TableColumn, ...] = ()
    authored_as: AuthoredName | None = field(default=None, compare=False)
    authored_at: str | None = field(default=None, compare=False)


@dataclass(frozen=True)
class CodeBlock:
    content: str
    language: str = ""
    authored_at: str | None = field(default=None, compare=False)


@dataclass(frozen=True)
class DisplayMath:
    expression: str
    authored_at: str | None = field(default=None, compare=False)


@dataclass(frozen=True)
class Media:
    kind: MediaNodeKind
    url: str
    description: ExportRich = ()
    caption: ExportRich = ()
    authored_at: str | None = field(default=None, compare=False)


@dataclass(frozen=True)
class Callout:
    tone: ToneName
    children: "tuple[Node, ...]"
    icon: str | None = None
    shows_icon: bool = True
    authored_as: AuthoredName | None = field(default=None, compare=False)
    authored_at: str | None = field(default=None, compare=False)


@dataclass(frozen=True)
class Quote:
    lines: tuple[ExportRich, ...]
    cite: ExportRich = ()
    authored_as: AuthoredName | None = field(default=None, compare=False)
    authored_at: str | None = field(default=None, compare=False)


@dataclass(frozen=True)
class Divider:
    authored_at: str | None = field(default=None, compare=False)


@dataclass(frozen=True)
class Toggle:
    title: ExportRich
    heading_level: HeadingLevel | None
    children: "tuple[Node, ...]"
    anchor: str | None = None
    authored_as: AuthoredName | None = field(default=None, compare=False)
    authored_at: str | None = field(default=None, compare=False)


@dataclass(frozen=True)
class GridColumn:
    ratio: int
    children: "tuple[Node, ...]"


@dataclass(frozen=True)
class Columns:
    columns: tuple[GridColumn, ...]
    authored_at: str | None = field(default=None, compare=False)


@dataclass(frozen=True)
class Tab:
    title: ExportRich
    children: "tuple[Node, ...]"
    tone: ToneName | None = None


@dataclass(frozen=True)
class Tabs:
    tabs: tuple[Tab, ...]
    authored_as: AuthoredName | None = field(default=None, compare=False)
    authored_at: str | None = field(default=None, compare=False)


@dataclass(frozen=True)
class GraphNode:
    key: str
    label: str
    note: ExportRich = ()
    tone: ToneName | None = None


@dataclass(frozen=True)
class GraphEdge:
    source: str
    target: str
    dashed: bool = False


@dataclass(frozen=True)
class Graph:
    direction: Literal["TB", "LR"]
    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...]
    kind: GraphKind = "flow"


@dataclass(frozen=True)
class PieSlice:
    label: str
    value: float


@dataclass(frozen=True)
class PieChart:
    slices: tuple[PieSlice, ...]


@dataclass(frozen=True)
class XYChart:
    mark: XYChartMark
    categories: tuple[str, ...]
    series: tuple[tuple[float, ...], ...]
    stacked: bool = False


Figure = Graph | PieChart | XYChart


@dataclass(frozen=True)
class Diagram:
    figure: Figure
    supplement: "tuple[Node, ...]" = ()
    authored_at: str | None = field(default=None, compare=False)


@dataclass(frozen=True)
class TocEntry:
    anchor: str
    title: ExportRich


@dataclass(frozen=True)
class TableOfContents:
    entries: tuple[TocEntry, ...]
    authored_at: str | None = field(default=None, compare=False)


Node = (
    Heading
    | Paragraph
    | ListNode
    | TableNode
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
)

AuthoredNode = Callout | Quote | TableNode | Tabs | Toggle


PagePartKind = Literal["header", "legend", "footer"]


@dataclass(frozen=True)
class PagePart:
    kind: PagePartKind
    nodes: tuple[Node, ...]


@dataclass(frozen=True)
class BlockRegion:
    source_index: int
    nodes: tuple[Node, ...]
    section_id: str | None = None
    anchor: str | None = None


Region = PagePart | BlockRegion


@dataclass(frozen=True)
class LoweredDocument:
    title: str
    regions: tuple[Region, ...]
    icon: str | None = None
    cover: str | None = None

    @property
    def body(self) -> tuple[Node, ...]:
        return tuple(node for region in self.regions for node in region.nodes)


def capped_heading_level(level: int) -> HeadingLevel:
    return HEADING_LEVELS[max(1, min(level, len(HEADING_LEVELS))) - 1]


def heading_of(node: Node) -> Heading | None:
    if isinstance(node, Heading):
        return node
    if isinstance(node, Toggle) and node.heading_level is not None:
        return Heading(node.heading_level, node.title, node.anchor)
    return None


def _all_authored_at(nodes: tuple[Node, ...], path: str) -> tuple[Node, ...]:
    return tuple(with_authored_path(node, path) for node in nodes)


def with_authored_path(node: Node, path: str | None) -> Node:
    if path is None or node.authored_at is not None:
        return node
    match node:
        case ListNode():
            entries = tuple(
                replace(entry, children=_all_authored_at(entry.children, path)) for entry in node.entries
            )
            return replace(node, entries=entries, authored_at=path)
        case Callout() | Toggle():
            return replace(node, children=_all_authored_at(node.children, path), authored_at=path)
        case Columns():
            columns = tuple(
                replace(column, children=_all_authored_at(column.children, path)) for column in node.columns
            )
            return replace(node, columns=columns, authored_at=path)
        case Tabs():
            tabs = tuple(replace(tab, children=_all_authored_at(tab.children, path)) for tab in node.tabs)
            return replace(node, tabs=tabs, authored_at=path)
        case Diagram():
            return replace(node, supplement=_all_authored_at(node.supplement, path), authored_at=path)
        case (
            Heading()
            | Paragraph()
            | TableNode()
            | CodeBlock()
            | DisplayMath()
            | Media()
            | Quote()
            | Divider()
            | TableOfContents()
        ):
            return replace(node, authored_at=path)


def nested_nodes(node: Node) -> tuple[Node, ...]:
    match node:
        case ListNode():
            return tuple(child for entry in node.entries for child in entry.children)
        case Callout() | Toggle():
            return node.children
        case Columns():
            return tuple(child for column in node.columns for child in column.children)
        case Tabs():
            return tuple(child for tab in node.tabs for child in tab.children)
        case Diagram():
            return node.supplement
        case (
            Heading()
            | Paragraph()
            | TableNode()
            | CodeBlock()
            | DisplayMath()
            | Media()
            | Quote()
            | Divider()
            | TableOfContents()
        ):
            return ()
