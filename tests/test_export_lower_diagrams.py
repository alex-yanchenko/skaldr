from typing import Any

import pytest

from skaldr.export.inline import bold
from skaldr.export.runs import Chip
from skaldr.export.tree import (
    Diagram,
    Graph,
    GraphEdge,
    GraphNode,
    ListEntry,
    ListNode,
    Paragraph,
    PieChart,
    PieSlice,
    TableNode,
    TableRow,
    XYChart,
    XYChartMark,
)
from skaldr.richtext import AnchorLink, Citation, InlineMath, Link, Plain, Rich, ScriptText, Styled, Tinted
from tests.factories import API_BADGES, lowered
from tests.factories.lower_factory import API_LEGEND, cell_texts_of


def test_a_flow_step_label_with_a_line_break_stays_one_mermaid_label() -> None:
    flow = {"type": "flow", "numbered": False, "steps": [{"label": "one\nthree"}, {"label": "two"}]}

    assert lowered([flow]) == (
        Diagram(
            Graph(
                "LR", (GraphNode("s1", "one three"), GraphNode("s2", "two")), (GraphEdge("s1", "s2"),), "flow"
            )
        ),
    )


def test_a_numbered_looping_flow_is_a_top_to_bottom_graph_with_a_dashed_return() -> None:
    flow = {
        "type": "flow",
        "style": "steps",
        "loop": True,
        "steps": [{"label": "Scan", "tone": "info", "note": "by **aisle**"}, {"label": "Fix"}],
    }

    assert lowered([flow]) == (
        Diagram(
            Graph(
                "TB",
                (
                    GraphNode("s1", "1: Scan", (Plain("by "), Styled("bold", (Plain("aisle"),))), "info"),
                    GraphNode("s2", "2: Fix"),
                ),
                (GraphEdge("s1", "s2"), GraphEdge("s2", "s1", dashed=True)),
                "flow",
            )
        ),
    )


def test_a_flow_lists_the_points_and_badges_its_diagram_cannot_show() -> None:
    flow = {
        "type": "flow",
        "numbered": False,
        "steps": [
            {"label": "Scan", "note": "first", "points": ["by aisle"], "badges": ["API"]},
            {"label": "Fix"},
        ],
    }

    assert lowered([flow], badges=API_BADGES) == (
        API_LEGEND,
        Diagram(
            Graph(
                "LR",
                (
                    GraphNode(
                        "s1",
                        "Scan",
                        (Plain("first"),),
                        points=((Plain("by aisle"),),),
                        badges=(Chip("api", "blue"),),
                    ),
                    GraphNode("s2", "Fix"),
                ),
                (GraphEdge("s1", "s2"),),
                "flow",
            ),
            (
                ListNode(
                    "bullet",
                    (
                        ListEntry(
                            (*bold("Scan"), Plain(": "), Plain("first"), Plain(" "), Chip("api", "blue")),
                            children=(ListNode("bullet", (ListEntry((Plain("by aisle"),)),)),),
                        ),
                    ),
                ),
            ),
        ),
    )


@pytest.mark.parametrize(
    ("note", "runs"),
    [
        pytest.param(
            "see [doc](https://e.com/d)",
            (Plain("see "), Link((Plain("doc"),), "https://e.com/d")),
            id="web-link",
        ),
        pytest.param(
            "see [count](#count)", (Plain("see "), AnchorLink((Plain("count"),), "count")), id="anchor"
        ),
        pytest.param("per [^sop]", (Plain("per "), Citation("sop", 1, "https://e.com/sop")), id="citation"),
        pytest.param(
            "per [[^sop]]{tone=info}",
            (Plain("per "), Tinted("info", None, (Citation("sop", 1, "https://e.com/sop"),))),
            id="citation-inside-a-color-span",
        ),
        pytest.param("rate $`x_i`$", (Plain("rate "), InlineMath("x_i")), id="inline-math"),
        pytest.param("about 10^3^", (Plain("about 10"), ScriptText("superscript", "3")), id="superscript"),
    ],
)
def test_a_graph_node_keeps_the_runs_of_its_note_and_a_note_alone_adds_no_step_list(
    note: str, runs: Rich
) -> None:
    flow = {"type": "flow", "numbered": False, "steps": [{"label": "Scan", "note": note}, {"label": "Fix"}]}
    references = {"type": "references", "items": [{"key": "sop", "text": "SOP", "url": "https://e.com/sop"}]}

    diagrams = [
        node
        for node in lowered([{"type": "heading", "text": "Count"}, flow, references])
        if isinstance(node, Diagram)
    ]

    graph = Graph(
        "LR", (GraphNode("s1", "Scan", runs), GraphNode("s2", "Fix")), (GraphEdge("s1", "s2"),), "flow"
    )

    assert diagrams == [Diagram(graph)]


def test_a_fan_lists_the_points_and_badges_of_its_hub_before_its_spokes() -> None:
    fan = {
        "type": "fan",
        "direction": "out",
        "hub": {"label": "Hub", "points": ["owns the queue"], "badges": ["API"]},
        "spokes": [{"label": "A", "points": ["one"]}, {"label": "B"}],
    }

    assert lowered([fan], badges=API_BADGES) == (
        API_LEGEND,
        Diagram(
            Graph(
                "LR",
                (
                    GraphNode(
                        "hub",
                        "Hub",
                        points=((Plain("owns the queue"),),),
                        badges=(Chip("api", "blue"),),
                    ),
                    GraphNode("s1", "A", points=((Plain("one"),),)),
                    GraphNode("s2", "B"),
                ),
                (GraphEdge("hub", "s1"), GraphEdge("hub", "s2")),
                "fan",
            ),
            (
                ListNode(
                    "bullet",
                    (
                        ListEntry(
                            (*bold("Hub"), Plain(" "), Chip("api", "blue")),
                            children=(ListNode("bullet", (ListEntry((Plain("owns the queue"),)),)),),
                        ),
                        ListEntry(bold("A"), children=(ListNode("bullet", (ListEntry((Plain("one"),)),)),)),
                    ),
                ),
            ),
        ),
    )


@pytest.mark.parametrize(
    ("direction", "edges"),
    [
        pytest.param("in", (GraphEdge("s1", "hub"), GraphEdge("s2", "hub")), id="in"),
        pytest.param("out", (GraphEdge("hub", "s1"), GraphEdge("hub", "s2")), id="out"),
    ],
)
def test_a_fan_points_its_edges_the_way_it_says(direction: str, edges: tuple[GraphEdge, ...]) -> None:
    fan = {
        "type": "fan",
        "direction": direction,
        "hub": {"label": "Hub"},
        "spokes": [{"label": "A", "points": ["one"]}, {"label": "B"}],
    }

    assert lowered([fan]) == (
        Diagram(
            Graph(
                "LR",
                (
                    GraphNode("hub", "Hub"),
                    GraphNode("s1", "A", points=((Plain("one"),),)),
                    GraphNode("s2", "B"),
                ),
                edges,
                "fan",
            ),
            (
                ListNode(
                    "bullet",
                    (ListEntry(bold("A"), children=(ListNode("bullet", (ListEntry((Plain("one"),)),)),)),),
                ),
            ),
        ),
    )


def test_a_donut_is_a_pie_over_a_table_of_its_values_shares_and_total() -> None:
    donut = {
        "type": "chart",
        "variant": "donut",
        "slices": [{"label": "A", "value": 3, "tone": "success"}, {"label": "B", "value": 1.5}],
    }

    assert lowered([donut]) == (
        Diagram(
            PieChart((PieSlice("A", 3, "success"), PieSlice("B", 1.5))),
            (
                TableNode(
                    cell_texts_of("Slice", "Value", "Share"),
                    (
                        TableRow(cell_texts_of("A", "3", "67%"), tint="success"),
                        TableRow(cell_texts_of("B", "1.5", "33%")),
                        TableRow(cell_texts_of("Total", "4.5", ""), emphasis="total"),
                    ),
                ),
            ),
        ),
    )


def test_a_donut_total_is_written_with_the_precision_of_its_values() -> None:
    donut = {
        "type": "chart",
        "variant": "donut",
        "slices": [{"label": "A", "value": 12.25}, {"label": "B", "value": 3.5}],
    }

    assert lowered([donut]) == (
        Diagram(
            PieChart((PieSlice("A", 12.25), PieSlice("B", 3.5))),
            (
                TableNode(
                    cell_texts_of("Slice", "Value", "Share"),
                    (
                        TableRow(cell_texts_of("A", "12.25", "78%")),
                        TableRow(cell_texts_of("B", "3.5", "22%")),
                        TableRow(cell_texts_of("Total", "15.75", ""), emphasis="total"),
                    ),
                ),
            ),
        ),
    )


def test_a_titled_donut_writes_its_title_above_the_pie() -> None:
    donut = {"type": "chart", "variant": "donut", "title": "Mix", "slices": [{"label": "A", "value": 1200}]}

    assert lowered([donut]) == (
        Paragraph(bold("Mix")),
        Diagram(
            PieChart((PieSlice("A", 1200),)),
            (
                TableNode(
                    cell_texts_of("Slice", "Value", "Share"),
                    (
                        TableRow(cell_texts_of("A", "1,200", "100%")),
                        TableRow(cell_texts_of("Total", "1,200", ""), emphasis="total"),
                    ),
                ),
            ),
        ),
    )


def test_a_single_series_line_chart_keeps_its_table_with_the_series_tone() -> None:
    line = {
        "type": "chart",
        "variant": "line",
        "title": "Open",
        "categories": ["Q1", "Q2"],
        "series": [{"label": "x", "tone": "danger", "values": [1, 2]}],
    }

    assert lowered([line]) == (
        Paragraph(bold("Open")),
        Diagram(
            XYChart("line", ("Q1", "Q2"), ((1, 2),), stacked=False, series_tones=("danger",)),
            (
                TableNode(
                    cell_texts_of("Series", "Q1", "Q2"),
                    (TableRow(cell_texts_of("x", "1", "2"), tint="danger"),),
                ),
            ),
        ),
    )


def test_an_untitled_single_series_bar_chart_is_a_bar_diagram_over_its_table() -> None:
    chart = {
        "type": "chart",
        "variant": "bar",
        "categories": ["Q1"],
        "series": [{"label": "x", "values": [4]}],
    }

    assert lowered([chart]) == (
        Diagram(
            XYChart("bar", ("Q1",), ((4,),), stacked=False, series_tones=(None,)),
            (TableNode(cell_texts_of("Series", "Q1"), (TableRow(cell_texts_of("x", "4")),)),),
        ),
    )


TWO_SERIES: list[dict[str, Any]] = [{"label": "x", "values": [1]}, {"label": "y", "values": [2]}]


@pytest.mark.parametrize(
    ("variant", "stacked", "series", "total"),
    [
        pytest.param("bar", True, TWO_SERIES, ("Total", "3"), id="stacked-bars-with-a-total-row"),
        pytest.param("bar", False, TWO_SERIES, None, id="bars"),
        pytest.param("line", False, TWO_SERIES, None, id="lines"),
        pytest.param("bar", True, TWO_SERIES[:1], None, id="one-stacked-bar-without-a-total-row"),
    ],
)
def test_an_xy_chart_keeps_its_stacking_over_a_table_of_its_series(
    variant: XYChartMark, stacked: bool, series: list[dict[str, Any]], total: tuple[str, str] | None
) -> None:
    chart = {"type": "chart", "variant": variant, "stacked": stacked, "categories": ["Q1"], "series": series}
    values = tuple((float(item["values"][0]),) for item in series)
    rows = tuple(TableRow(cell_texts_of(item["label"], str(item["values"][0]))) for item in series)
    totals = () if total is None else (TableRow(cell_texts_of(*total), emphasis="total"),)

    assert lowered([chart]) == (
        Diagram(
            XYChart(variant, ("Q1",), values, stacked, series_tones=(None,) * len(series)),
            (TableNode(cell_texts_of("Series", "Q1"), (*rows, *totals)),),
        ),
    )
