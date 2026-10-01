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


def nested_nodes(node: Node) -> tuple[Node, ...]:
    match node:
        case ListNode():
            return tuple(child for entry in node.entries for child in entry.children)
        case Callout() | Toggle():
            return node.children
        case Heading() | Paragraph() | CodeBlock() | Quote() | TableOfContents():
            return ()
