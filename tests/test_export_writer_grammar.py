from collections.abc import Callable, Mapping
from typing import get_args

import pytest

from skaldr.errors import ExportInvariantError, ExportRejectedError
from skaldr.export.adf import render_adf
from skaldr.export.inline import plain
from skaldr.export.slack import render_slack
from skaldr.export.tree import (
    Callout,
    CodeBlock,
    Columns,
    Diagram,
    DisplayMath,
    Divider,
    Graph,
    GraphNode,
    GridColumn,
    Heading,
    ListEntry,
    ListNode,
    Media,
    Node,
    Paragraph,
    PieChart,
    PieSlice,
    Quote,
    Tab,
    TableCell,
    TableNode,
    TableOfContents,
    TableRow,
    Tabs,
    Toggle,
)
from skaldr.export_targets import ExportTarget
from tests.factories import check_nodes

Wrap = Callable[[Node], tuple[Node, ...]]

_PARAGRAPH = Paragraph(plain("Count twice."))
_TABLE = TableNode((TableCell(plain("Aisle")),), ())
_TOGGLE = Toggle(plain("More"), None, (_PARAGRAPH,))
SAMPLES: Mapping[str, Node] = {
    "heading": Heading(2, plain("Plan")),
    "paragraph": _PARAGRAPH,
    "list": ListNode("bullet", (ListEntry(plain("a")),)),
    "numbered list starting at 3": ListNode("number", (ListEntry(plain("a")),), start=3),
    "list holding a table": ListNode("bullet", (ListEntry(plain("a"), children=(_TABLE,)),)),
    "checklist holding a toggle": ListNode("check", (ListEntry(plain("a"), children=(_TOGGLE,)),)),
    "table": _TABLE,
    "table over 300 cells": TableNode(
        (TableCell(plain("Aisle")),), tuple(TableRow((TableCell(plain("v")),)) for _ in range(300))
    ),
    "code block": CodeBlock("recount", "sh"),
    "math block": DisplayMath("x^2"),
    "callout": Callout("info", (_PARAGRAPH,)),
    "quote": Quote((plain("Measure twice."),)),
    "quote with only a cite": Quote((), plain("Ops")),
    "empty quote": Quote(()),
    "divider": Divider(),
    "image": Media("image", "https://example.com/aisle.png"),
    "toggle": _TOGGLE,
    "heading toggle": Toggle(plain("Totals"), 2, (_PARAGRAPH,)),
    "grid": Columns((GridColumn(1, (_PARAGRAPH,)), GridColumn(1, (_PARAGRAPH,)))),
    "grid holding a table": Columns((GridColumn(1, (_TABLE,)), GridColumn(1, (_PARAGRAPH,)))),
    "tabs": Tabs((Tab(plain("One"), (_PARAGRAPH,)),)),
    "empty tabs": Tabs(()),
    "flow diagram": Diagram(Graph("LR", (GraphNode("s1", "Scan"),), (), "flow")),
    "chart beside its table": Diagram(PieChart((PieSlice("Done", 3),)), (_TABLE,)),
    "table of contents": TableOfContents(()),
}
ADF_CONTAINERS: Mapping[str, Wrap] = {
    "doc": lambda node: (node,),
    "panel": lambda node: (Callout("info", (node,)),),
    "expand": lambda node: (Toggle(plain("Outer"), None, (node,)),),
    "nested_expand": lambda node: (Toggle(plain("Outer"), None, (Toggle(plain("Inner"), None, (node,)),)),),
}
SLACK_CONTAINERS: Mapping[str, Wrap] = {
    "document": lambda node: (node,),
    "callout": lambda node: (Callout("info", (node,)),),
    "toggle": lambda node: (Toggle(plain("Outer"), None, (node,)),),
    "grid": lambda node: (Columns((GridColumn(1, (node,)), GridColumn(1, (_PARAGRAPH,)))),),
    "list item": lambda node: (ListNode("bullet", (ListEntry(plain("a"), children=(node,)),)),),
    "list item after its nested list": lambda node: (
        ListNode(
            "bullet", (ListEntry(plain("a"), children=(ListNode("bullet", (ListEntry(plain("b")),)), node)),)
        ),
    ),
}


def _check_refuses(nodes: tuple[Node, ...], target: ExportTarget) -> bool:
    try:
        check_nodes(nodes, target)
    except ExportRejectedError:
        return True
    return False


def _writer_refuses(write: Callable[[], object]) -> bool:
    try:
        write()
    except ExportInvariantError:
        return True
    return False


def test_the_samples_hold_every_lowered_node_kind() -> None:
    assert {type(sample) for sample in SAMPLES.values()} == set(get_args(Node))


def test_the_adf_check_and_writer_both_refuse_a_table_in_a_panel() -> None:
    nodes = ADF_CONTAINERS["panel"](SAMPLES["table"])

    assert (_check_refuses(nodes, "adf"), _writer_refuses(lambda: render_adf(nodes))) == (True, True)


def test_the_slack_check_and_writer_both_refuse_a_code_block_in_a_list_item() -> None:
    nodes = SLACK_CONTAINERS["list item"](SAMPLES["code block"])

    assert (_check_refuses(nodes, "slack"), _writer_refuses(lambda: render_slack(nodes))) == (True, True)


@pytest.mark.parametrize("container", ADF_CONTAINERS)
@pytest.mark.parametrize("sample", SAMPLES)
def test_the_adf_check_refuses_a_placement_exactly_when_the_adf_writer_cannot_hold_it(
    sample: str, container: str
) -> None:
    nodes = ADF_CONTAINERS[container](SAMPLES[sample])

    assert _check_refuses(nodes, "adf") == _writer_refuses(lambda: render_adf(nodes))


@pytest.mark.parametrize("container", SLACK_CONTAINERS)
@pytest.mark.parametrize("sample", SAMPLES)
def test_the_slack_check_refuses_a_placement_exactly_when_the_canvas_writer_cannot_hold_it(
    sample: str, container: str
) -> None:
    nodes = SLACK_CONTAINERS[container](SAMPLES[sample])

    assert _check_refuses(nodes, "slack") == _writer_refuses(lambda: render_slack(nodes))
