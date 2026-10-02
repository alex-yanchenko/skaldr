from dataclasses import dataclass
from typing import Final, Literal, get_args

from skaldr.models import ListStyle, ToneLiteral
from skaldr.richtext import Rich

ToneName = Literal[ToneLiteral, "muted"]
ListKind = ListStyle
HeadingLevel = Literal[1, 2, 3, 4]
HEADING_LEVELS: Final[tuple[HeadingLevel, ...]] = get_args(HeadingLevel)


@dataclass(frozen=True)
class Heading:
    level: HeadingLevel
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
    heading_level: HeadingLevel | None
    children: "tuple[Node, ...]"
    anchor: str | None = None


@dataclass(frozen=True)
class TocEntry:
    anchor: str
    title: Rich


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


def nested_nodes(node: Node) -> tuple[Node, ...]:
    match node:
        case ListNode():
            return tuple(child for entry in node.entries for child in entry.children)
        case Callout() | Toggle():
            return node.children
        case Heading() | Paragraph() | CodeBlock() | Quote() | TableOfContents():
            return ()
