from typing import Any

import pytest

from skaldr.export.inline import bold, italic, plain
from skaldr.export.lower import lower_report
from skaldr.export.runs import Break, Chip, Gauge, Mark
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
    LoweredDocument,
    Node,
    Paragraph,
    PieChart,
    PieSlice,
    Quote,
    Tab,
    Table,
    TableCell,
    TableOfContents,
    TableRow,
    Tabs,
    TocEntry,
    Toggle,
    XYChart,
)
from skaldr.models import parse_report
from skaldr.richtext import Code, Link, Plain, Styled
from tests.factories import API_BADGES, lowered, make_command_request, make_report

API_LEGEND = Toggle(
    (Plain("Legend: badges used on this page"),),
    None,
    (ListNode("bullet", (ListEntry((Chip("api", "blue"), Plain(" the API"))),)),),
)


def _cells(*texts: str) -> tuple[TableCell, ...]:
    return tuple(TableCell((Plain(text),) if text else ()) for text in texts)


def test_a_report_lowers_to_its_title_and_body() -> None:
    report = parse_report(make_report(meta={"title": "Count", "subtitle": ["Sub **bold** {{blank}}"]}))

    assert lower_report(report) == LoweredDocument(
        "Count",
        (Paragraph((Plain("Sub **bold** {{blank}}"),), "muted"), Paragraph((Plain("Hello."),))),
    )


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


def test_rich_text_keeps_the_spaces_inside_a_code_span() -> None:
    assert lowered([{"type": "text", "body": "run  `a  b`\nnow"}]) == (
        Paragraph((Plain("run "), Code("a  b"), Plain(" now"))),
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

    assert lowered(blocks, meta={"title": "T", "toc": True}) == (
        TableOfContents(
            (TocEntry("overview", (Plain("Overview"),)), TocEntry("appendix", (Plain("Appendix"),)))
        ),
        Heading(2, (Plain("Overview"),), "overview"),
        Heading(3, (Plain("Detail"),), "detail"),
        Toggle((Plain("Appendix"),), 2, (Paragraph((Plain("x"),)),), "appendix"),
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


def test_a_donut_is_a_pie_and_every_xy_chart_keeps_its_table_with_series_tones() -> None:
    donut = {
        "type": "chart",
        "variant": "donut",
        "slices": [{"label": "A", "value": 3}, {"label": "B", "value": 1}],
    }
    line = {
        "type": "chart",
        "variant": "line",
        "title": "Open",
        "categories": ["Q1", "Q2"],
        "series": [{"label": "x", "tone": "danger", "values": [1, 2]}],
    }

    assert lowered([donut, line]) == (
        Diagram(PieChart((PieSlice("A", 3), PieSlice("B", 1)))),
        Paragraph(bold("Open")),
        Diagram(
            XYChart("line", ("Q1", "Q2"), ((1, 2),)),
            (Table(_cells("Series", "Q1", "Q2"), (TableRow(_cells("x", "1", "2"), "danger"),)),),
        ),
    )


def test_a_stacked_chart_is_its_table_alone() -> None:
    chart = {
        "type": "chart",
        "variant": "bar",
        "stacked": True,
        "categories": ["Q1"],
        "series": [{"label": "x", "values": [1]}, {"label": "y", "values": [2]}],
    }

    assert lowered([chart]) == (
        Table(_cells("Series", "Q1"), (TableRow(_cells("x", "1")), TableRow(_cells("y", "2")))),
    )


def test_a_comparison_marks_a_true_on_a_negative_row_as_bad() -> None:
    comparison = {
        "type": "comparison",
        "options": ["A", "B"],
        "highlight": 1,
        "polarity": ["positive", "negative"],
        "rows": [
            {"feature": "Risky", "values": [True, True]},
            {"feature": "Note", "values": ["plain", {"value": "toned", "tone": "warning"}]},
        ],
    }

    assert lowered([comparison]) == (
        Table(
            (TableCell(()), TableCell((Plain("A"),)), TableCell(bold("★ B"))),
            (
                TableRow(
                    (
                        TableCell(bold("Risky")),
                        TableCell((Mark("check", "yes"),), "success"),
                        TableCell((Mark("check", "yes"),), "danger"),
                    )
                ),
                TableRow(
                    (
                        TableCell(bold("Note")),
                        TableCell((Plain("plain"),)),
                        TableCell((Plain("toned"),), "warning"),
                    )
                ),
            ),
            header_column=True,
        ),
    )


def test_a_matrix_shows_badge_toned_and_blank_cells() -> None:
    matrix = {
        "type": "matrix",
        "rows": ["r1"],
        "columns": ["c1", "c2", "c3"],
        "cells": [
            {"row": "r1", "col": "c1", "badge": "API"},
            {"row": "r1", "col": "c2", "label": "n/a", "tone": "neutral"},
        ],
    }

    assert lowered([matrix], badges=API_BADGES) == (
        Table(
            (TableCell(()), *_cells("c1", "c2", "c3")),
            (
                TableRow(
                    (
                        TableCell(bold("r1")),
                        TableCell((Plain("api"),), "info"),
                        TableCell((Plain("n/a"),), "neutral"),
                        TableCell(()),
                    )
                ),
            ),
            header_column=True,
        ),
        API_LEGEND,
    )


@pytest.mark.parametrize(
    ("cards_and_source", "entry"),
    [
        pytest.param(
            [
                {"type": "cards", "items": [{"badge": "API", "of_matrix": "m"}]},
                {
                    "type": "matrix",
                    "id": "m",
                    "rows": ["r1", "r2"],
                    "columns": ["c"],
                    "cells": [{"row": "r1", "col": "c", "badge": "API"}],
                },
            ],
            ListEntry((Chip("api", "blue"), Plain(": 1 (50.0%)"))),
            id="of-matrix",
        ),
        pytest.param(
            [
                {"type": "cards", "items": [{"badge": "API", "of_tables": ["t"], "label": "API rows"}]},
                {
                    "type": "table",
                    "id": "t",
                    "columns": [{"key": "a", "label": "A"}, {"key": "tag", "label": "", "kind": "badge"}],
                    "rollup": {"by": "tag"},
                    "rows": [
                        {"a": "x", "tag": "API"},
                        {"a": "y", "tag": ""},
                        {"a": "z", "tag": ""},
                        {"a": "w", "tag": ""},
                    ],
                },
            ],
            ListEntry((Chip("API rows", "blue"), Plain(": 1 (25.0%)"))),
            id="of-tables",
        ),
    ],
)
def test_a_derived_card_counts_its_badge_in_its_source(
    cards_and_source: list[dict[str, Any]], entry: ListEntry
) -> None:
    assert lowered(cards_and_source, badges=API_BADGES)[0] == ListNode("bullet", (entry,))


def test_a_card_shows_its_share_delta_badges_and_note() -> None:
    card = {
        "label": "Clean",
        "value": 9,
        "of": 10,
        "tone": "success",
        "delta": {"label": "+1", "direction": "up"},
        "badges": ["API"],
        "note": "since Monday",
    }

    assert lowered([{"type": "cards", "items": [card]}], badges=API_BADGES) == (
        ListNode(
            "bullet",
            (
                ListEntry(
                    (
                        *bold("Clean"),
                        Plain(": "),
                        Plain("9"),
                        Plain(" (90.0%)"),
                        Plain(" "),
                        Mark("delta", "up"),
                        Plain(" +1"),
                        Plain(" "),
                        Chip("api", "blue"),
                    ),
                    children=(Paragraph((Plain("since Monday"),), "muted"),),
                    tone="success",
                ),
            ),
        ),
        API_LEGEND,
    )


def test_a_meter_reading_is_a_gauge_with_its_share_and_tone() -> None:
    meter = {"type": "meter", "items": [{"label": "Zone", "value": 5, "max": 10, "tone": "warning"}]}

    assert lowered([meter]) == (
        ListNode(
            "bullet",
            (
                ListEntry(
                    (*bold("Zone"), Plain(": "), Gauge(5, 10), Plain(" 50.0% (5 of 10)")), tone="warning"
                ),
            ),
        ),
    )


def test_a_range_shows_its_axis_and_each_segment_share() -> None:
    block = {
        "type": "range",
        "axis": {"min": "Jan"},
        "segments": [
            {"label": "Seg", "span": 1, "tone": "danger", "sub": "one"},
            {"label": "Rest", "span": 3},
        ],
    }

    assert lowered([block]) == (
        Paragraph((Plain("From Jan to end"),), "muted"),
        ListNode(
            "bullet",
            (
                ListEntry(
                    (*bold("Seg"), Plain(": "), Plain("1 (25.0%)"), Plain(", "), Plain("one")), tone="danger"
                ),
                ListEntry((*bold("Rest"), Plain(": "), Plain("3 (75.0%)"))),
            ),
        ),
    )


def test_status_and_timeline_entries_lead_with_their_state_mark() -> None:
    blocks = [
        {"type": "status_list", "items": [{"state": "blocked", "text": "Vendor"}]},
        {
            "type": "timeline",
            "items": [{"time": "Mon", "title": "Start", "state": "done"}, {"title": "Later"}],
        },
    ]

    assert lowered(blocks) == (
        ListNode("bullet", (ListEntry((Mark("status", "blocked"), Plain(" "), Plain("Vendor"))),)),
        ListNode(
            "bullet",
            (
                ListEntry((Mark("timeline", "done"), Plain(" "), *bold("Mon"), Plain(": "), Plain("Start"))),
                ListEntry((Plain("Later"),)),
            ),
        ),
    )


def test_definitions_badge_groups_and_references_are_lists() -> None:
    blocks = [
        {"type": "def_list", "items": [{"term": "Fix", "body": "first\n\nsecond"}]},
        {"type": "badge_row", "groups": [{"label": "Owners:", "items": [{"label": "ops", "tone": "teal"}]}]},
        {
            "type": "references",
            "items": [{"key": "a", "text": "SOP", "url": "https://e.com"}, {"key": "b", "text": "Memo"}],
        },
    ]

    assert lowered(blocks) == (
        ListNode(
            "bullet",
            (
                ListEntry(
                    (*bold("Fix"), Plain(": "), Plain("first")), children=(Paragraph((Plain("second"),)),)
                ),
            ),
        ),
        ListNode("bullet", (ListEntry((*bold("Owners"), Plain(": "), Chip("ops", "teal"))),)),
        ListNode(
            "bullet",
            (
                ListEntry(
                    (
                        Plain("[1]"),
                        Plain(" "),
                        Plain("SOP"),
                        Plain(" "),
                        Link((Plain("source"),), "https://e.com"),
                    )
                ),
                ListEntry((Plain("[2]"), Plain(" "), Plain("Memo"))),
            ),
        ),
    )


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
                        TableCell(
                            (Mark("swimlane", "done"), Plain(" "), *bold("1"), Plain(" Draft"), Plain(" (2)"))
                        ),
                        TableCell(
                            (
                                Mark("swimlane", "blocked"),
                                Plain(" "),
                                *bold("2"),
                                Plain(" Send"),
                                Plain(" (3)"),
                            )
                        ),
                    )
                ),
                TableRow((TableCell(bold("Total")), *_cells("2", "3")), emphasis="total"),
            ),
            header_column=True,
        ),
        Paragraph(
            (
                Mark("swimlane", "done"),
                Plain(" done"),
                Plain(" · "),
                Mark("swimlane", "blocked"),
                Plain(" blocked"),
            ),
            "muted",
        ),
    )


def test_a_swimlane_without_values_names_dependencies_once_and_links_step_numbers() -> None:
    swimlane = {
        "type": "swimlane",
        "lanes": ["Ops"],
        "columns": ["Plan"],
        "groups": [
            {"name": "A", "color": "blue", "columns": ["Plan"]},
            {"name": "B", "color": "amber", "columns": ["Plan"]},
        ],
        "steps": [
            {"id": "first", "lane": "Ops", "col": "Plan", "n": "1", "label": "Draft", "group": "A"},
            {"id": "again", "lane": "Ops", "col": "Plan", "n": "1", "label": "Redraft", "group": "A"},
            {
                "lane": "Ops",
                "col": "Plan",
                "n": "2",
                "label": "Send",
                "state": "deferred",
                "group": "B",
                "url": "https://e.com/2",
                "depends_on": ["first", "again"],
            },
        ],
    }

    (table, legend) = lowered([swimlane])

    assert (table, legend) == (
        Table(
            (
                TableCell((Plain("Lane"),)),
                TableCell((*bold("Plan"), Break(), Plain("A"), Plain(", "), Plain("B"))),
            ),
            (
                TableRow(
                    (
                        TableCell(bold("Ops")),
                        TableCell(
                            (
                                Mark("swimlane", "todo"),
                                Plain(" "),
                                *bold("1"),
                                Plain(" Draft"),
                                Break(),
                                Mark("swimlane", "todo"),
                                Plain(" "),
                                *bold("1"),
                                Plain(" Redraft"),
                                Break(),
                                Mark("swimlane", "deferred"),
                                Plain(" "),
                                Link((Plain("2"),), "https://e.com/2"),
                                Plain(" Send"),
                                *italic(plain(" needs 1")),
                            )
                        ),
                    )
                ),
            ),
            header_column=True,
        ),
        Paragraph(
            (
                Mark("swimlane", "todo"),
                Plain(" todo"),
                Plain(" · "),
                Mark("swimlane", "deferred"),
                Plain(" deferred"),
            ),
            "muted",
        ),
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
            _cells("Issue", "Units"),
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


def test_a_reconciled_table_shows_indicators_shares_its_rollup_and_the_reconcile_line() -> None:
    table = {
        "type": "table",
        "columns": [
            {"key": "a", "label": "Issue"},
            {"key": "risk", "label": "Risk", "kind": "indicator"},
            {"key": "n", "label": "Units", "kind": "number", "pct_of_total": True},
            {"key": "tag", "label": "", "kind": "badge", "placement": "title"},
        ],
        "reconcile": {"total": 10, "column": "n", "handled": {"label": "Clean", "value": 8}},
        "rollup": {"by": "tag", "label": "Owners:"},
        "rows": [{"a": "x", "risk": "warning", "n": 2, "tag": "API", "tone": "danger"}],
        "tint_by": "tag",
    }

    assert lowered([table], badges=API_BADGES) == (
        Table(
            _cells("Issue", "Risk", "Units"),
            (
                TableRow(
                    (
                        TableCell((Plain("x"), Plain(" "), Chip("api", "blue"))),
                        TableCell((Mark("indicator", "warning"),), "warning"),
                        TableCell((Plain("2"), Plain(" (20.0% of total)"))),
                    ),
                    "danger",
                ),
            ),
        ),
        Paragraph((*bold("Owners"), Plain(": "), Chip("api", "blue"), Plain(" 1"))),
        Paragraph((Plain("Reconciles: 2 + 8 clean = 10."),), "muted"),
        API_LEGEND,
        Paragraph((Plain("Reconciles: 2 + 8 clean = 10."),), "muted"),
    )


def test_a_tinted_table_row_takes_its_first_badge_tone_and_a_cell_badge_column_gets_its_own_cell() -> None:
    table = {
        "type": "table",
        "columns": [
            {"key": "a", "label": "A"},
            {"key": "tag", "label": "", "kind": "badge", "placement": "cell"},
        ],
        "tint_by": "tag",
        "rows": [{"a": "x", "tag": "API"}],
    }

    assert lowered([table], badges=API_BADGES) == (
        Table(
            _cells("A", ""),
            (TableRow((TableCell((Plain("x"),)), TableCell((Chip("api", "blue"),))), "info"),),
        ),
        API_LEGEND,
    )


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
    label: tuple[Node, ...] = (Paragraph((Code(code["label"]),)),) if "label" in code else ()

    assert lowered([{"type": "code", **code}]) == (*label, CodeBlock(code["content"].rstrip("\n"), language))


def test_a_quote_and_a_note_keep_their_text() -> None:
    blocks = [
        {"type": "quote", "body": "said\n\nagain", "cite": "Ops"},
        {"type": "note", "title": "Aside", "body": "x"},
    ]

    assert lowered(blocks) == (
        Quote(((Plain("said"),), (Plain("again"),)), (Plain("Ops"),)),
        Callout("neutral", (Paragraph(bold("Aside")), Paragraph((Plain("x"),)))),
    )


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


def test_a_panel_and_a_walkthrough_carry_their_content() -> None:
    blocks = [
        {"type": "panel", "title": "Next", "blocks": [{"type": "text", "body": "p"}]},
        {
            "type": "walkthrough",
            "steps": [
                {"label": "Go", "sub": "first", "tone": "info", "detail": [{"type": "text", "body": "d"}]}
            ],
        },
    ]

    assert lowered(blocks) == (
        Callout("neutral", (Paragraph(bold("Next")), Paragraph((Plain("p"),)))),
        ListNode(
            "number",
            (
                ListEntry(
                    (*bold("Go"), Plain(" "), Styled("italic", (Plain("first"),))),
                    children=(Paragraph((Plain("d"),)),),
                    tone="info",
                ),
            ),
        ),
    )


def test_a_request_with_one_case_shows_its_label_note_status_and_verdict() -> None:
    request = make_command_request(
        command_note="needs the vault",
        cases=[{"label": "all", "verdict": "fine", "response": {"status": 200, "body": "ok"}}],
    )

    assert lowered([request]) == (
        Paragraph(bold("Tier mappings on the partner API")),
        Paragraph(italic(plain("all"))),
        CodeBlock(request["command"], "bash"),
        Paragraph(italic((Plain("needs the vault"),)), "muted"),
        Paragraph((*bold("Response"), Plain(": "), Plain("200 OK"))),
        CodeBlock("ok", ""),
        Callout("success", (Paragraph((*bold("Verdict"), Plain(": "), Plain("fine"))),)),
    )


def test_a_request_with_several_cases_is_tabs() -> None:
    request = make_command_request(
        command="list",
        cases=[
            {"label": "a", "tone": "warning", "response": {"body": "x"}},
            {"label": "b", "tone": "success", "response": {"body": "y"}},
        ],
    )

    assert lowered([request]) == (
        Paragraph(bold("Tier mappings on the partner API")),
        Tabs(
            (
                Tab(
                    (Plain("a"),),
                    (CodeBlock("list", "bash"), Paragraph(bold("Output")), CodeBlock("x", "")),
                    "warning",
                ),
                Tab(
                    (Plain("b"),),
                    (CodeBlock("list", "bash"), Paragraph(bold("Output")), CodeBlock("y", "")),
                    "success",
                ),
            )
        ),
    )


def test_a_request_flow_names_each_step_and_what_it_captures() -> None:
    flow = {
        "type": "request_flow",
        "label": "Token then read",
        "variables": [
            {"name": "host", "example": "api.example.com"},
            {"name": "key", "secret": True},
            {"name": "who"},
        ],
        "steps": [
            {
                "label": "Get token",
                "method": "POST",
                "url": "https://{{host}}/t",
                "headers": {"X-Key": "{{key}}", "X-Who": "{{who}}"},
                "captures": [{"name": "token", "source": "body"}],
                "cases": [{"label": "one", "response": {"status": 200, "body": "{}"}}],
            },
            {
                "label": "Read",
                "method": "GET",
                "url": "https://{{host}}/r",
                "headers": {"Authorization": "Bearer {{token}}"},
                "cases": [
                    {
                        "label": "one",
                        "response": {
                            "status": 200,
                            "headers": {"content-type": "application/json"},
                            "body": "{}",
                        },
                    }
                ],
            },
        ],
    }

    nodes = lowered([flow])

    assert nodes[:3] == (
        Paragraph(bold("Token then read")),
        Paragraph(bold("Values you supply")),
        ListNode(
            "bullet",
            (
                ListEntry((Code("{{host}}"), Plain(" host: for example api.example.com"))),
                ListEntry((Code("{{key}}"), Plain(" key: a secret, supply your own"))),
                ListEntry((Code("{{who}}"), Plain(" who: supply a value"))),
            ),
        ),
    )
    assert nodes[3] == Paragraph((*bold("Step 1 of 2: Get token"), Plain(", captures "), Code("token")))
    assert nodes[-1] == CodeBlock("content-type: application/json\n\n{}", "http")
