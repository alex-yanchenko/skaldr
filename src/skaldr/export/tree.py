from dataclasses import dataclass
from typing import Final, Literal, get_args

from skaldr.export.runs import ExportRich
from skaldr.models import ListStyle, ToneLiteral

ToneName = Literal[ToneLiteral, "muted"]
ListKind = ListStyle
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
    heading_level: HeadingLevel | None
    children: "tuple[Node, ...]"
    anchor: str | None = None


@dataclass(frozen=True)
class TocEntry:
    anchor: str
    title: ExportRich


@dataclass(frozen=True)
class TableOfContents:
    entries: tuple[TocEntry, ...]


Node = Heading | Paragraph | ListNode | CodeBlock | Callout | Quote | Toggle | TableOfContents


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
        case Heading() | Paragraph() | CodeBlock() | Quote() | TableOfContents():
            return ()
