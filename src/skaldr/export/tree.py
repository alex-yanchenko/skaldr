from dataclasses import dataclass, field
from typing import Literal

from skaldr.export.inline import Rich

ToneName = Literal["neutral", "info", "success", "warning", "danger", "accent", "teal", "sky", "muted"]


@dataclass(frozen=True)
class Heading:
    level: int
    text: Rich


@dataclass(frozen=True)
class Paragraph:
    text: Rich
    tone: ToneName | None = None


@dataclass(frozen=True)
class ListEntry:
    text: Rich
    checked: bool = False
    children: "tuple[Node, ...]" = ()


@dataclass(frozen=True)
class ListNode:
    kind: Literal["bullet", "number", "check"]
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
class Divider:
    pass


@dataclass(frozen=True)
class Toggle:
    title: Rich
    heading_level: int | None
    children: "tuple[Node, ...]"


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
class Diagram:
    mermaid: str
    fallback: "tuple[Node, ...]"
    supplement: "tuple[Node, ...]" = field(default=())


@dataclass(frozen=True)
class Image:
    url: str
    caption: Rich


@dataclass(frozen=True)
class TableOfContents:
    pass


Node = (
    Heading
    | Paragraph
    | ListNode
    | Table
    | CodeBlock
    | Callout
    | Quote
    | Divider
    | Toggle
    | Columns
    | Tabs
    | Diagram
    | Image
    | TableOfContents
)
