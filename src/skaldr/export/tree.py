from dataclasses import dataclass
from typing import Literal

from skaldr.richtext import Rich

ToneName = Literal["neutral", "info", "success", "warning", "danger", "accent", "teal", "sky", "muted"]
ListKind = Literal["bullet", "number", "check"]


@dataclass(frozen=True)
class Heading:
    level: int
    text: Rich
    anchor: str | None = None


@dataclass(frozen=True)
class Paragraph:
    text: Rich
    tone: ToneName | None = None


@dataclass(frozen=True)
class ListEntry:
    text: Rich
    checked: bool = False
    children: "tuple[Node, ...]" = ()
    tone: ToneName | None = None


@dataclass(frozen=True)
class ListNode:
    kind: ListKind
    entries: tuple[ListEntry, ...]


@dataclass(frozen=True)
class TableCell:
    text: Rich
    tone: ToneName | None = None


@dataclass(frozen=True)
class TableRow:
    cells: tuple[TableCell, ...]
    tone: ToneName | None = None
    emphasis: Literal["group", "total"] | None = None


@dataclass(frozen=True)
class Table:
    header: tuple[TableCell, ...]
    rows: tuple[TableRow, ...]
    header_column: bool = False


@dataclass(frozen=True)
class CodeBlock:
    content: str
    language: str = ""


@dataclass(frozen=True)
class Callout:
    tone: ToneName
    children: "tuple[Node, ...]"


@dataclass(frozen=True)
class Quote:
    lines: tuple[Rich, ...]
    cite: Rich = ()


@dataclass(frozen=True)
class Toggle:
    title: Rich
    heading_level: int | None
    children: "tuple[Node, ...]"
    anchor: str | None = None


@dataclass(frozen=True)
class Column:
    ratio: int
    children: "tuple[Node, ...]"


@dataclass(frozen=True)
class Columns:
    columns: tuple[Column, ...]


@dataclass(frozen=True)
class Tab:
    title: Rich
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
    title: Rich


@dataclass(frozen=True)
class TableOfContents:
    entries: tuple[TocEntry, ...]


Node = (
    Heading
    | Paragraph
    | ListNode
    | Table
    | CodeBlock
    | Callout
    | Quote
    | Toggle
    | Columns
    | Tabs
    | Diagram
    | TableOfContents
)


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
        case Heading() | Paragraph() | Table() | CodeBlock() | Quote() | TableOfContents():
            return ()
