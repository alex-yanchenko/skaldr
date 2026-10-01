from dataclasses import dataclass
from typing import Literal

from skaldr.export.runs import ExportRich

ToneName = Literal["neutral", "info", "success", "warning", "danger", "accent", "teal", "sky", "muted"]
ListKind = Literal["bullet", "number", "check"]


@dataclass(frozen=True)
class Heading:
    level: int
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
    lines: tuple[ExportRich, ...]
    cite: ExportRich = ()


@dataclass(frozen=True)
class Toggle:
    title: ExportRich
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
class TocEntry:
    anchor: str
    title: ExportRich


@dataclass(frozen=True)
class TableOfContents:
    entries: tuple[TocEntry, ...]


Node = (
    Heading | Paragraph | ListNode | Table | CodeBlock | Callout | Quote | Toggle | Columns | TableOfContents
)


@dataclass(frozen=True)
class LoweredDocument:
    title: str
    body: tuple[Node, ...]


def nested_nodes(node: Node) -> tuple[Node, ...]:
    match node:
        case ListNode():
            return tuple(child for entry in node.entries for child in entry.children)
        case Callout() | Toggle():
            return node.children
        case Columns():
            return tuple(child for column in node.columns for child in column.children)
        case Heading() | Paragraph() | Table() | CodeBlock() | Quote() | TableOfContents():
            return ()
