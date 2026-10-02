from dataclasses import dataclass
from typing import Final, Literal, get_args

from skaldr.export.runs import ExportRich
from skaldr.models import ToneLiteral

ToneName = Literal[ToneLiteral, "muted"]
ListKind = Literal["bullet", "number", "check"]
HeadingLevel = Literal[1, 2, 3, 4]
HEADING_LEVELS: Final[tuple[HeadingLevel, ...]] = get_args(HeadingLevel)


@dataclass(frozen=True)
class Heading:
    level: HeadingLevel
    text: ExportRich
    anchor: str | None = None


@dataclass(frozen=True)
class Paragraph:
    text: ExportRich
    tone: ToneName | None = None


@dataclass(frozen=True)
class ListEntry:
    text: ExportRich
    checked: bool = False
    children: "tuple[Node, ...]" = ()
    tone: ToneName | None = None


@dataclass(frozen=True)
class ListNode:
    kind: ListKind
    entries: tuple[ListEntry, ...]
    start: int = 1


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


@dataclass(frozen=True)
class CodeBlock:
    content: str
    language: str = ""


@dataclass(frozen=True)
class Callout:
    tone: ToneName
    children: "tuple[Node, ...]"
    icon: str | None = None


@dataclass(frozen=True)
class Quote:
    lines: tuple[ExportRich, ...]
    cite: ExportRich = ()


@dataclass(frozen=True)
class Toggle:
    title: ExportRich
    heading_level: HeadingLevel | None
    children: "tuple[Node, ...]"
    anchor: str | None = None


@dataclass(frozen=True)
class GridColumn:
    ratio: int
    children: "tuple[Node, ...]"


@dataclass(frozen=True)
class Columns:
    columns: tuple[GridColumn, ...]


@dataclass(frozen=True)
class Tab:
    title: ExportRich
    children: "tuple[Node, ...]"
    tone: ToneName | None = None


@dataclass(frozen=True)
class Tabs:
    tabs: tuple[Tab, ...]


@dataclass(frozen=True)
class GraphNode:
    key: str
    label: str
    note: str = ""
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


@dataclass(frozen=True)
class PieSlice:
    label: str
    value: float


@dataclass(frozen=True)
class PieChart:
    slices: tuple[PieSlice, ...]


@dataclass(frozen=True)
class XYChart:
    mark: Literal["bar", "line"]
    categories: tuple[str, ...]
    series: tuple[tuple[float, ...], ...]


Figure = Graph | PieChart | XYChart


@dataclass(frozen=True)
class Diagram:
    figure: Figure
    supplement: "tuple[Node, ...]" = ()


@dataclass(frozen=True)
class TocEntry:
    anchor: str
    title: ExportRich


@dataclass(frozen=True)
class TableOfContents:
    entries: tuple[TocEntry, ...]


Node = (
    Heading
    | Paragraph
    | ListNode
    | TableNode
    | CodeBlock
    | Callout
    | Quote
    | Toggle
    | Columns
    | Tabs
    | Diagram
    | TableOfContents
)


@dataclass(frozen=True)
class LoweredDocument:
    title: str
    body: tuple[Node, ...]


def capped_heading_level(level: int) -> HeadingLevel:
    return HEADING_LEVELS[max(1, min(level, len(HEADING_LEVELS))) - 1]


def heading_of(node: Node) -> Heading | None:
    if isinstance(node, Heading):
        return node
    if isinstance(node, Toggle) and node.heading_level is not None:
        return Heading(node.heading_level, node.title, node.anchor)
    return None


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
        case Heading() | Paragraph() | TableNode() | CodeBlock() | Quote() | TableOfContents():
            return ()
