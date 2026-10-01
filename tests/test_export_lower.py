from typing import Any

import pytest

from skaldr.export.inline import bold, italic, plain
from skaldr.export.tree import (
    Callout,
    CodeBlock,
    Column,
    Columns,
    Diagram,
    Graph,
    GraphEdge,
    GraphNode,
    Heading,
    ListEntry,
    ListNode,
    Node,
    Paragraph,
    PieChart,
    PieSlice,
    Table,
    TableCell,
    TableOfContents,
    TableRow,
    TocEntry,
    Toggle,
    XYChart,
)
from skaldr.richtext import Break, Chip, Code, Plain
from tests.factories import lowered

BADGES = {"API": {"label": "api", "tone": "blue", "legend": "the API"}}


def _without_legend(nodes: tuple[Node, ...]) -> tuple[Node, ...]:
    return tuple(node for node in nodes if not (isinstance(node, Toggle) and node.heading_level is None))


def test_text_with_line_breaks_stays_one_heading_and_one_mermaid_label() -> None:
    blocks = [
        {"type": "heading", "text": "First\n## Injected"},
        {"type": "flow", "numbered": False, "steps": [{"label": "one\nthree"}, {"label": "two"}]},
    ]

    assert lowered(blocks) == (
        Heading(2, (Plain("First ## Injected"),), "first-injected"),
        Diagram(
            Graph("LR", (GraphNode("s1", "one three"), GraphNode("s2", "two")), (GraphEdge("s1", "s2"),))
        ),
    )


def test_an_author_heading_id_becomes_the_anchor() -> None:
    assert lowered([{"type": "heading", "text": "Count", "id": "tally"}]) == (
        Heading(2, (Plain("Count"),), "tally"),
    )


def test_the_table_of_contents_lists_what_the_html_lists() -> None:
    blocks = [
        {"type": "heading", "text": "Overview"},
        {"type": "heading", "text": "Detail", "level": 3},
        {"type": "section", "title": "Appendix", "blocks": [{"type": "text", "body": "x"}]},
    ]

    assert lowered(blocks, meta={"title": "T", "toc": True})[0] == TableOfContents(
        (TocEntry("overview", (Plain("Overview"),)), TocEntry("appendix", (Plain("Appendix"),)))
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
                (GraphNode("s1", "1: Scan", "by aisle", "info"), GraphNode("s2", "2: Fix")),
                (GraphEdge("s1", "s2"), GraphEdge("s2", "s1", dashed=True)),
            )
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
        "spokes": [{"label": "A"}, {"label": "B"}],
    }

    assert lowered([fan]) == (
        Diagram(Graph("LR", (GraphNode("hub", "Hub"), GraphNode("s1", "A"), GraphNode("s2", "B")), edges)),
    )


def test_a_donut_is_a_pie_and_a_two_series_bar_chart_keeps_its_table() -> None:
    donut = {
        "type": "chart",
        "variant": "donut",
        "slices": [{"label": "A", "value": 3}, {"label": "B", "value": 1}],
    }
    bars = {
        "type": "chart",
        "variant": "bar",
        "categories": ["Q1", "Q2"],
        "series": [{"label": "x", "values": [1, 2]}, {"label": "y", "values": [3, 4]}],
    }
    table = Table(
        (TableCell((Plain("Series"),)), TableCell((Plain("Q1"),)), TableCell((Plain("Q2"),))),
        (
            TableRow((TableCell((Plain("x"),)), TableCell((Plain("1"),)), TableCell((Plain("2"),)))),
            TableRow((TableCell((Plain("y"),)), TableCell((Plain("3"),)), TableCell((Plain("4"),)))),
        ),
    )

    assert lowered([donut, bars]) == (
        Diagram(PieChart((PieSlice("A", 3), PieSlice("B", 1)))),
        Diagram(XYChart("bar", ("Q1", "Q2"), ((1, 2), (3, 4))), (table,)),
    )


def test_a_stacked_chart_is_its_table_alone() -> None:
    chart = {
        "type": "chart",
        "variant": "bar",
        "stacked": True,
        "categories": ["Q1"],
        "series": [{"label": "x", "values": [1]}, {"label": "y", "values": [2]}],
    }

    assert [type(node) for node in lowered([chart])] == [Table]


def test_a_comparison_marks_a_true_on_a_negative_row_as_bad() -> None:
    comparison = {
        "type": "comparison",
        "options": ["A", "B"],
        "highlight": 1,
        "polarity": ["positive", "negative"],
        "rows": [{"feature": "Risky", "values": [True, True]}],
    }

    assert lowered([comparison]) == (
        Table(
            (TableCell(()), TableCell((Plain("A"),)), TableCell(bold("★ B"))),
            (
                TableRow(
                    (
                        TableCell(bold("Risky")),
                        TableCell((Plain("✓"),), "success"),
                        TableCell((Plain("✓"),), "danger"),
                    )
                ),
            ),
            header_column=True,
        ),
    )


def test_a_card_counted_from_a_matrix_shows_its_share() -> None:
    blocks = [
        {"type": "cards", "items": [{"badge": "API", "of_matrix": "m"}]},
        {
            "type": "matrix",
            "id": "m",
            "rows": ["r1", "r2"],
            "columns": ["c"],
            "cells": [{"row": "r1", "col": "c", "badge": "API"}],
        },
    ]

    assert _without_legend(lowered(blocks, badges=BADGES))[0] == ListNode(
        "bullet", (ListEntry((Chip("api", "blue"), Plain(": 1 (50.0%)"))),)
    )


def test_meter_card_range_and_walkthrough_tones_reach_their_list_entries() -> None:
    blocks = [
        {"type": "meter", "items": [{"label": "Zone", "value": 5, "max": 10, "tone": "warning"}]},
        {"type": "cards", "items": [{"label": "Clean", "value": 9, "tone": "success"}]},
        {"type": "range", "segments": [{"label": "Seg", "span": 1, "tone": "danger"}]},
        {
            "type": "walkthrough",
            "steps": [{"label": "Go", "tone": "info", "detail": [{"type": "text", "body": "x"}]}],
        },
    ]

    assert [
        entry.tone for node in lowered(blocks) if isinstance(node, ListNode) for entry in node.entries
    ] == [
        "warning",
        "success",
        "danger",
        "info",
    ]


def test_a_swimlane_with_values_totals_lanes_groups_and_columns_like_the_html() -> None:
    swimlane = {
        "type": "swimlane",
        "lanes": ["Ops"],
        "columns": ["Plan", "Ship"],
        "groups": [{"name": "Q1", "color": "blue", "columns": ["Plan", "Ship"]}],
        "steps": [
            {"lane": "Ops", "col": "Plan", "n": "1", "label": "Draft", "value": 2, "state": "done"},
            {"lane": "Ops", "col": "Ship", "n": "2", "label": "Send", "value": 3, "state": "blocked"},
        ],
    }

    assert lowered([swimlane]) == (
        Table(
            (
                TableCell((Plain("Lane"),)),
                TableCell((*bold("Plan"), Break(), Plain("Q1"), Plain(" (5)"))),
                TableCell((*bold("Ship"), Break(), Plain("Q1"), Plain(" (5)"))),
            ),
            (
                TableRow(
                    (
                        TableCell((*bold("Ops"), Plain(" (5)"))),
                        TableCell((Plain("✅ "), *bold("1"), Plain(" Draft"), Plain(" (2)"))),
                        TableCell((Plain("⛔ "), *bold("2"), Plain(" Send"), Plain(" (3)"))),
                    )
                ),
                TableRow(
                    (TableCell(bold("Total")), TableCell((Plain("2"),)), TableCell((Plain("3"),))),
                    emphasis="total",
                ),
            ),
            header_column=True,
        ),
        Paragraph((Plain("✅ done · ⛔ blocked"),), "muted"),
    )


def test_a_grouped_table_sums_each_group_and_marks_an_empty_one() -> None:
    table: dict[str, Any] = {
        "type": "table",
        "columns": [{"key": "a", "label": "Issue"}, {"key": "n", "label": "Units", "kind": "number"}],
        "totals": {"column": "n"},
        "groups": [
            {
                "name": "Ours",
                "rows": [{"a": "x", "n": 2, "subrows": [{"label": "of which `y`", "value": 1}]}],
            },
            {"name": "Theirs", "rows": []},
        ],
    }

    assert lowered([table]) == (
        Table(
            (TableCell((Plain("Issue"),)), TableCell((Plain("Units"),))),
            (
                TableRow((TableCell((*bold("Ours"), Plain(" (2)"))), TableCell(())), emphasis="group"),
                TableRow(
                    (
                        TableCell((Plain("x"), Break(), Plain("of which "), Code("y"), Plain(": 1"))),
                        TableCell((Plain("2"),)),
                    )
                ),
                TableRow((TableCell((*bold("Theirs"), Plain(" (0)"))), TableCell(())), emphasis="group"),
                TableRow((TableCell(italic(plain("none"))), TableCell(()))),
                TableRow((TableCell(bold("Total")), TableCell(bold("2"))), emphasis="total"),
            ),
        ),
    )


def test_a_tinted_table_row_takes_its_first_badge_tone() -> None:
    table = {
        "type": "table",
        "columns": [{"key": "a", "label": "A"}, {"key": "tag", "label": "", "kind": "badge"}],
        "tint_by": "tag",
        "rows": [{"a": "x", "tag": "API"}],
    }

    assert [row.tone for row in _first_table(lowered([table], badges=BADGES)).rows] == ["info"]


def _first_table(nodes: tuple[Node, ...]) -> Table:
    return next(node for node in nodes if isinstance(node, Table))


def test_an_embedded_image_becomes_its_caption() -> None:
    image = {"type": "image", "src": "data:image/png;base64,AA==", "alt": "chart", "caption": "Fig 1"}

    assert lowered([image]) == (Paragraph(italic((Plain("Image: "), Plain("Fig 1"))), "muted"),)


@pytest.mark.parametrize(
    ("code", "language"),
    [
        pytest.param({"label": "q.sql", "content": "select 1\n"}, "sql", id="suffix"),
        pytest.param({"label": "fix.ts", "content": "+a", "mode": "diff"}, "diff", id="diff"),
        pytest.param({"content": "plain"}, "", id="no-label"),
    ],
)
def test_a_code_block_language_comes_from_its_label_or_mode(code: dict[str, Any], language: str) -> None:
    assert lowered([{"type": "code", **code}])[-1] == CodeBlock(code["content"].rstrip("\n"), language)


def test_a_collapsed_section_is_a_toggle_heading_with_its_updated_line() -> None:
    section = {
        "type": "section",
        "title": "Raw",
        "updated": "1 Jan",
        "blocks": [{"type": "text", "body": "x"}],
    }

    assert lowered([section]) == (
        Toggle(
            (Plain("Raw"),),
            2,
            (Paragraph(italic(plain("updated 1 Jan")), "muted"), Paragraph((Plain("x"),))),
            "raw",
        ),
    )


def test_a_toned_grid_cell_becomes_a_callout_column_and_a_one_cell_grid_flattens() -> None:
    two = {
        "type": "grid",
        "cells": [
            {"span": 1, "tone": "info", "blocks": [{"type": "text", "body": "a"}]},
            {"span": 3, "blocks": [{"type": "text", "body": "b"}]},
        ],
    }
    one = {"type": "grid", "cells": [{"span": 6, "blocks": [{"type": "text", "body": "c"}]}]}

    assert lowered([two, one]) == (
        Columns(
            (
                Column(25, (Callout("info", (Paragraph((Plain("a"),)),)),)),
                Column(75, (Paragraph((Plain("b"),)),)),
            )
        ),
        Paragraph((Plain("c"),)),
    )
