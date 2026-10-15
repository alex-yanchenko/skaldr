from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from skaldr.export.folds import cell_text, folded
from skaldr.export.inline import bold, plain
from skaldr.export.runs import Break, Chip, StatusMark, TonedLabel
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
    Heading,
    KeyValueList,
    LabelledValue,
    LinkCard,
    ListEntry,
    ListNode,
    Node,
    Paragraph,
    Quote,
    TableCell,
    TableNode,
    TableRow,
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
_OPEN_TOGGLE_CHILDREN: tuple[GenericNode, ...] = (
    Heading(2, plain("Inside")),
    Paragraph(UNDERLINED_OPS),
    ListNode("bullet", (ListEntry(plain("after")),)),
)
_NUMBERED_FROM_THREE = ListNode("number", (ListEntry(plain("x")),), start=3)
_NESTED_BULLETS = ListNode("bullet", (ListEntry(plain("z")),))

Wrap = Callable[[tuple[Node, ...]], tuple[Node, ...]]


@dataclass(frozen=True)
class FoldCase:
    named: Node
    today: tuple[GenericNode, ...]


def fold_case(named: Node, *today: GenericNode) -> FoldCase:
    return FoldCase(named, today)


FOLD_CASES: Mapping[str, FoldCase] = {
    "fact strip": fold_case(
        FactStrip((LabelledValue("Site:", plain("West")), LabelledValue(" ", UNDERLINED_OPS))),
        ListNode(
            "bullet",
            (ListEntry((*bold("Site"), Plain(": "), Plain("West"))), ListEntry(UNDERLINED_OPS)),
        ),
    ),
    "key-value list": fold_case(
        KeyValueList((LabelledValue("Owner", UNDERLINED_OPS),)),
        ListNode("bullet", (ListEntry((*bold("Owner"), Plain(": "), *UNDERLINED_OPS)),)),
    ),
    "definition list": fold_case(
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
    "cards": fold_case(
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
    "timeline": fold_case(
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
    "link card": fold_case(
        LinkCard("Runbook", RUNBOOK_URL, "card", domain="example.com", caption="Steps"),
        Quote(
            (Paragraph((Styled("bold", (Link(plain("Runbook"), RUNBOOK_URL),)),)),),
            plain("example.com · Steps"),
            authored_as="link card",
        ),
    ),
    "link embed": fold_case(
        LinkCard("example.com/runbook", RUNBOOK_URL, "embed"),
        Quote(
            (Paragraph((Styled("bold", (Link(plain("example.com/runbook"), RUNBOOK_URL),)),)),),
            authored_as="link embed",
        ),
    ),
    "open toggle": fold_case(
        Toggle(plain("More"), None, _OPEN_TOGGLE_CHILDREN, authored_as="toggle", open=True),
        Paragraph(bold("More")),
        *_OPEN_TOGGLE_CHILDREN,
    ),
    "roman list": fold_case(
        ListNode(
            "number",
            (
                ListEntry(UNDERLINED_OPS),
                ListEntry(
                    plain("b"), children=(ListNode("number", (ListEntry(plain("c")),), numbering="roman"),)
                ),
            ),
            start=4,
            numbering="roman",
        ),
        ListNode(
            "bullet",
            (
                ListEntry((Plain("iv. "), *UNDERLINED_OPS)),
                ListEntry(
                    (Plain("v. "), Plain("b")),
                    children=(ListNode("bullet", (ListEntry((Plain("i. "), Plain("c"))),)),),
                ),
            ),
        ),
    ),
    "quote holding lists": fold_case(
        Quote(
            (
                Paragraph(plain("Said:")),
                ListNode("bullet", (ListEntry(UNDERLINED_OPS, children=(_NUMBERED_FROM_THREE,)),)),
                ListNode("bullet", (ListEntry(plain("y"), children=(_NESTED_BULLETS,)),)),
            ),
            plain("Ana"),
        ),
        Quote(
            (
                Paragraph(plain("Said:")),
                Paragraph((Plain("• "), *UNDERLINED_OPS)),
                Paragraph((Plain("3. "), Plain("x"))),
                Paragraph((Plain("• "), Plain("y"))),
                Paragraph((Plain("◦ "), Plain("z"))),
            ),
            plain("Ana"),
        ),
    ),
    "table cell holding a list": fold_case(
        TableNode(
            (TableCell(plain("Steps")),),
            (
                TableRow(
                    (
                        TableCell(
                            (),
                            blocks=(
                                Paragraph(plain("Fix:")),
                                ListNode("bullet", (ListEntry(UNDERLINED_OPS),)),
                            ),
                        ),
                    )
                ),
            ),
        ),
        TableNode(
            (TableCell(plain("Steps")),),
            (TableRow((TableCell((Plain("Fix:"), Break(), Plain("• "), *UNDERLINED_OPS)),)),),
        ),
    ),
    "long list cell beside a short cell": fold_case(
        TableNode(
            (TableCell(plain("Steps")), TableCell(plain("Owner"))),
            (
                TableRow(
                    (
                        TableCell(
                            (),
                            blocks=(
                                ListNode(
                                    "bullet",
                                    (
                                        ListEntry(plain("Recount every bin in the cold room by hand")),
                                        ListEntry(plain("Post the variance to the shared sheet")),
                                    ),
                                ),
                            ),
                        ),
                        TableCell(plain("Ops")),
                    )
                ),
            ),
        ),
        TableNode(
            (TableCell(plain("Steps")), TableCell(plain("Owner"))),
            (
                TableRow(
                    (
                        TableCell(
                            (
                                Plain("• "),
                                Plain("Recount every bin in the cold room by hand"),
                                Break(),
                                Plain("• "),
                                Plain("Post the variance to the shared sheet"),
                            )
                        ),
                        TableCell(plain("Ops")),
                    )
                ),
            ),
        ),
    ),
    "letter list": fold_case(
        ListNode("number", (ListEntry(plain("y")), ListEntry(UNDERLINED_OPS)), start=26, numbering="letters"),
        ListNode(
            "bullet", (ListEntry((Plain("z. "), Plain("y"))), ListEntry((Plain("aa. "), *UNDERLINED_OPS)))
        ),
    ),
}

_BULLETS = ListNode("bullet", (ListEntry(plain("before")),))
FOLD_CONTEXTS: Mapping[str, Wrap] = {
    "alone": lambda nodes: nodes,
    "after a bullet list": lambda nodes: (_BULLETS, *nodes),
    "before a bullet list": lambda nodes: (*nodes, _BULLETS),
    "in a numbered list item": lambda nodes: (ListNode("number", (ListEntry(plain("a"), children=nodes),)),),
    "after a list item's nested list": lambda nodes: (
        ListNode("bullet", (ListEntry(plain("a"), children=(_BULLETS, *nodes)),)),
    ),
    "in a callout": lambda nodes: (Callout("info", nodes),),
    "in a toggle": lambda nodes: (Toggle(plain("More"), None, nodes),),
    "in a toggle in a toggle": lambda nodes: (
        Toggle(plain("Outer"), None, (Toggle(plain("Inner"), None, nodes),)),
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
        case TableNode():
            rows = tuple(replace(row, cells=tuple(map(_cell_written_today, row.cells))) for row in node.rows)
            return replace(node, header=tuple(map(_cell_written_today, node.header)), rows=rows)
        case _:
            return node


def _cell_written_today(cell: TableCell) -> TableCell:
    return TableCell(cell_text(cell), cell.tone)


def lowered_as_written_today(blocks: list[dict[str, Any]], **overrides: Any) -> tuple[GenericNode, ...]:
    return written_today(lowered(blocks, **overrides))
