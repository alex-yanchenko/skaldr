from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from skaldr.export.folds import folded
from skaldr.export.inline import bold, plain
from skaldr.export.runs import Chip, StatusMark, TonedLabel
from skaldr.export.tree import (
    Callout,
    Card,
    Cards,
    Columns,
    Definition,
    DefinitionList,
    Diagram,
    FactStrip,
    GenericNode,
    KeyValueList,
    LabelledValue,
    LinkCard,
    ListEntry,
    ListNode,
    Node,
    Paragraph,
    Quote,
    Tabs,
    Timeline,
    TimelineEvent,
    Toggle,
    with_authored_path,
)
from skaldr.richtext import Link, Plain, Styled
from tests.factories.export_factory import lowered

FOLD_PATH = "blocks.0"
RUNBOOK_URL = "https://example.com/runbook"
UNDERLINED_OPS = (Styled("underline", (Plain("ops"),)),)

Wrap = Callable[[Node], tuple[Node, ...]]


@dataclass(frozen=True)
class FoldCase:
    named: Node
    today: GenericNode


FOLD_CASES: Mapping[str, FoldCase] = {
    "fact strip": FoldCase(
        FactStrip((LabelledValue("Site:", plain("West")), LabelledValue(" ", UNDERLINED_OPS))),
        ListNode(
            "bullet",
            (ListEntry((*bold("Site"), Plain(": "), Plain("West"))), ListEntry(UNDERLINED_OPS)),
        ),
    ),
    "key-value list": FoldCase(
        KeyValueList((LabelledValue("Owner", UNDERLINED_OPS),)),
        ListNode("bullet", (ListEntry((*bold("Owner"), Plain(": "), *UNDERLINED_OPS)),)),
    ),
    "definition list": FoldCase(
        DefinitionList(
            (
                Definition("Fix", (Paragraph(plain("first")), Paragraph(UNDERLINED_OPS))),
                Definition("Gap", ()),
                Definition("Steps", (ListNode("bullet", (ListEntry(plain("one")),)),)),
            )
        ),
        ListNode(
            "bullet",
            (
                ListEntry((*bold("Fix"), Plain(": "), Plain("first")), children=(Paragraph(UNDERLINED_OPS),)),
                ListEntry(bold("Gap")),
                ListEntry(bold("Steps"), children=(ListNode("bullet", (ListEntry(plain("one")),)),)),
            ),
        ),
    ),
    "cards": FoldCase(
        Cards(
            (
                Card(
                    "Clean",
                    (Plain("9"), Plain(" "), Chip("api", "blue")),
                    note="since Monday",
                    tone="success",
                ),
                Card("API rows", plain("1 (50.0%)"), note="live", badge="blue"),
                Card(" ", plain("7")),
                Card("Empty", ()),
                Card("Owner", UNDERLINED_OPS),
            )
        ),
        ListNode(
            "bullet",
            (
                ListEntry(
                    (
                        TonedLabel("success", bold("Clean")),
                        Plain(": "),
                        Plain("9"),
                        Plain(" "),
                        Chip("api", "blue"),
                    ),
                    children=(Paragraph(plain("since Monday"), "muted"),),
                ),
                ListEntry(
                    (Chip("API rows", "blue"), Plain(": 1 (50.0%)")),
                    children=(Paragraph(plain("live"), "muted"),),
                ),
                ListEntry((Plain("7"),)),
                ListEntry(bold("Empty")),
                ListEntry((*bold("Owner"), Plain(": "), *UNDERLINED_OPS)),
            ),
        ),
    ),
    "timeline": FoldCase(
        Timeline(
            (
                TimelineEvent(
                    "Start", time="Mon", state="done", chips=(Chip("api", "blue"),), body=UNDERLINED_OPS
                ),
                TimelineEvent("Later"),
            )
        ),
        ListNode(
            "bullet",
            (
                ListEntry(
                    (
                        StatusMark("done"),
                        Plain(" "),
                        *bold("Mon"),
                        Plain(": "),
                        Plain("Start"),
                        Plain(" "),
                        Chip("api", "blue"),
                    ),
                    children=(Paragraph(UNDERLINED_OPS),),
                ),
                ListEntry((Plain("Later"),)),
            ),
        ),
    ),
    "link card": FoldCase(
        LinkCard("Runbook", RUNBOOK_URL, "card", domain="example.com", caption="Steps"),
        Quote(
            ((Styled("bold", (Link(plain("Runbook"), RUNBOOK_URL),)),),),
            plain("example.com · Steps"),
            authored_as="link card",
        ),
    ),
    "link embed": FoldCase(
        LinkCard("example.com/runbook", RUNBOOK_URL, "embed"),
        Quote(
            ((Styled("bold", (Link(plain("example.com/runbook"), RUNBOOK_URL),)),),),
            authored_as="link embed",
        ),
    ),
}

_BULLETS = ListNode("bullet", (ListEntry(plain("before")),))
FOLD_CONTEXTS: Mapping[str, Wrap] = {
    "alone": lambda node: (node,),
    "after a bullet list": lambda node: (_BULLETS, node),
    "before a bullet list": lambda node: (node, _BULLETS),
    "in a numbered list item": lambda node: (ListNode("number", (ListEntry(plain("a"), children=(node,)),)),),
    "after the text of a list item's nested list": lambda node: (
        ListNode("bullet", (ListEntry(plain("a"), children=(_BULLETS, node)),)),
    ),
    "in a callout": lambda node: (Callout("info", (node,)),),
    "in a toggle": lambda node: (Toggle(plain("More"), None, (node,)),),
    "in a toggle in a toggle": lambda node: (
        Toggle(plain("Outer"), None, (Toggle(plain("Inner"), None, (node,)),)),
    ),
}


def authored(node: Node) -> Node:
    return with_authored_path(node, FOLD_PATH)


def written_today(nodes: Sequence[Node]) -> tuple[GenericNode, ...]:
    return tuple(_written_today_within(node) for node in folded(nodes))


def _written_today_within(node: GenericNode) -> GenericNode:
    match node:
        case ListNode():
            entries = tuple(replace(entry, children=written_today(entry.children)) for entry in node.entries)
            return replace(node, entries=entries)
        case Callout() | Toggle():
            return replace(node, children=written_today(node.children))
        case Columns():
            columns = tuple(
                replace(column, children=written_today(column.children)) for column in node.columns
            )
            return replace(node, columns=columns)
        case Tabs():
            return replace(
                node, tabs=tuple(replace(tab, children=written_today(tab.children)) for tab in node.tabs)
            )
        case Diagram():
            return replace(node, supplement=written_today(node.supplement))
        case _:
            return node


def lowered_as_written_today(blocks: list[dict[str, Any]], **overrides: Any) -> tuple[GenericNode, ...]:
    return written_today(lowered(blocks, **overrides))
