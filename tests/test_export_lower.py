from typing import Any, get_args

import pytest

from skaldr.export.inline import bold, italic, plain
from skaldr.export.lower import lower_report
from skaldr.export.markup import MARK_GLYPH
from skaldr.export.runs import Break, Chip, ExportRich, Gauge, Mark, MarkScheme
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
    ToneName,
    XYChart,
)
from skaldr.models import StatusState, TimelineState, parse_report
from skaldr.richtext import Code, Link, Plain, Styled
from tests.factories import API_BADGES, lowered, make_command_request, make_report

API_LEGEND = Toggle(
    (Plain("Legend: badges used on this page"),),
    None,
    (ListNode("bullet", (ListEntry((Chip("api", "blue"), Plain(" the API"))),)),),
)


def test_a_report_lowers_to_its_title_and_body() -> None:
    report = parse_report(make_report(meta={"title": "Count", "subtitle": ["Sub **bold** {{blank}}"]}))

    assert lower_report(report) == LoweredDocument(
        "Count",
        (Paragraph((Plain("Sub **bold** {{blank}}"),), "muted"), Paragraph((Plain("Hello."),))),
    )


def test_a_flow_step_label_with_a_line_break_stays_one_mermaid_label() -> None:
    flow = {"type": "flow", "numbered": False, "steps": [{"label": "one\nthree"}, {"label": "two"}]}

    assert lowered([flow]) == (
        Diagram(
            Graph("LR", (GraphNode("s1", "one three"), GraphNode("s2", "two")), (GraphEdge("s1", "s2"),))
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
                (GraphNode("s1", "1: Scan", "by aisle", "info"), GraphNode("s2", "2: Fix")),
                (GraphEdge("s1", "s2"), GraphEdge("s2", "s1", dashed=True)),
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
            Graph("LR", (GraphNode("s1", "Scan", "first"), GraphNode("s2", "Fix")), (GraphEdge("s1", "s2"),)),
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
            Graph("LR", (GraphNode("hub", "Hub"), GraphNode("s1", "A"), GraphNode("s2", "B")), edges),
            (
                ListNode(
                    "bullet",
                    (ListEntry(bold("A"), children=(ListNode("bullet", (ListEntry((Plain("one"),)),)),)),),
                ),
            ),
        ),
    )


def test_a_donut_is_a_pie_and_a_line_chart_keeps_its_table_with_series_tones() -> None:
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


def test_an_untitled_single_series_bar_chart_is_a_bar_diagram_over_its_table() -> None:
    chart = {
        "type": "chart",
        "variant": "bar",
        "categories": ["Q1"],
        "series": [{"label": "x", "values": [4]}],
    }

    assert lowered([chart]) == (
        Diagram(
            XYChart("bar", ("Q1",), ((4,),)), (Table(_cells("Series", "Q1"), (TableRow(_cells("x", "4")),)),)
        ),
    )


@pytest.mark.parametrize(
    "stacked",
    [pytest.param(True, id="stacked"), pytest.param(False, id="grouped-bars-would-overlap-in-mermaid")],
)
def test_a_bar_chart_with_several_series_is_its_table_alone(stacked: bool) -> None:
    chart = {
        "type": "chart",
        "variant": "bar",
        "stacked": stacked,
        "categories": ["Q1"],
        "series": [{"label": "x", "values": [1]}, {"label": "y", "values": [2]}],
    }

    assert lowered([chart]) == (
        Table(_cells("Series", "Q1"), (TableRow(_cells("x", "1")), TableRow(_cells("y", "2")))),
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


def test_a_request_flow_names_each_step_its_captures_and_never_shows_a_secret_value() -> None:
    flow = {
        "type": "request_flow",
        "label": "Token then read",
        "variables": [
            {"name": "host", "example": "api.example.com"},
            {"name": "key", "secret": True, "example": "do-not-print"},
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
                            "headers": {"content-type": ["application/json", "charset=utf-8"]},
                            "body": "{}",
                        },
                    }
                ],
            },
        ],
    }

    assert lowered([flow]) == (
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
        Paragraph((*bold("Step 1 of 2: Get token"), Plain(", captures "), Code("token"))),
        Paragraph(italic(plain("one"))),
        CodeBlock(
            "curl -i -X POST \\\n  -H 'X-Key: {{key}}' \\\n  -H 'X-Who: {{who}}' \\\n  'https://{{host}}/t'",
            "bash",
        ),
        Paragraph((*bold("Response"), Plain(": "), Plain("200 OK"))),
        CodeBlock("{}", "json"),
        Paragraph(bold("Step 2 of 2: Read")),
        Paragraph(italic(plain("one"))),
        CodeBlock(
            "curl -i -X GET \\\n  -H 'Authorization: Bearer {{token}}' \\\n  'https://{{host}}/r'", "bash"
        ),
        Paragraph((*bold("Response"), Plain(": "), Plain("200 OK"))),
        CodeBlock("content-type: application/json\ncontent-type: charset=utf-8\n\n{}", "http"),
    )


def test_rich_text_keeps_the_spaces_inside_a_code_span() -> None:
    assert lowered([{"type": "text", "body": "run  `a  b`\nnow"}]) == (
        Paragraph((Plain("run "), Code("a  b"), Plain(" now"))),
    )


def test_an_author_heading_id_becomes_the_anchor() -> None:
    assert lowered([{"type": "heading", "text": "Count", "id": "tally"}]) == (
        Heading(2, (Plain("Count"),), "tally"),
    )


def test_a_heading_with_a_line_break_stays_one_heading() -> None:
    assert lowered([{"type": "heading", "text": "First\n## Injected"}]) == (
        Heading(2, (Plain("First ## Injected"),), "first-injected"),
    )


def test_a_heading_sub_is_a_muted_italic_line_under_it() -> None:
    assert lowered([{"type": "heading", "text": "Count", "sub": "by **aisle**"}]) == (
        Heading(2, (Plain("Count"),), "count"),
        Paragraph((Styled("italic", (Plain("by "), Styled("bold", (Plain("aisle"),)))),), "muted"),
    )


def test_an_open_section_is_a_heading_and_nesting_never_goes_past_level_four() -> None:
    section = {
        "type": "section",
        "title": "Open",
        "collapsed": False,
        "blocks": [{"type": "heading", "text": "Deep", "level": 3}],
    }

    assert lowered([section]) == (Heading(2, (Plain("Open"),), "open"), Heading(4, (Plain("Deep"),), "deep"))


def test_muted_text_and_the_provenance_footer_are_muted_paragraphs() -> None:
    blocks = [{"type": "text", "body": "aside", "muted": True}]

    assert lowered(blocks, meta={"title": "T", "source": "SOP v2", "date": "1 Oct"}) == (
        Paragraph((Plain("aside"),), "muted"),
        Paragraph((Plain("SOP v2 · 1 Oct"),), "muted"),
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


def test_references_are_bullets_led_by_their_number_with_a_source_link() -> None:
    references = {
        "type": "references",
        "items": [{"key": "a", "text": "SOP", "url": "https://e.com"}, {"key": "b", "text": "Memo"}],
    }

    assert lowered([references]) == (
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


def test_the_badge_legend_comes_right_after_the_table_of_contents_when_the_page_has_no_table() -> None:
    blocks = [{"type": "heading", "text": "A"}, {"type": "badge_row", "items": [{"key": "API"}]}]

    assert lowered(blocks, meta={"title": "T", "toc": True}, badges=API_BADGES) == (
        TableOfContents((TocEntry("a", (Plain("A"),)),)),
        API_LEGEND,
        Heading(2, (Plain("A"),), "a"),
        Paragraph((Chip("api", "blue"),)),
    )


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
        API_LEGEND,
        ListNode(
            "bullet",
            (
                ListEntry(
                    (
                        *bold("Clean"),
                        Plain(": "),
                        Plain("9"),
                        Plain(" (90.0%)"),
                        Plain(" ▲ +1"),
                        Plain(" "),
                        Chip("api", "blue"),
                    ),
                    children=(Paragraph((Plain("since Monday"),), "muted"),),
                    tone="success",
                ),
            ),
        ),
    )


@pytest.mark.parametrize(
    ("card", "text"),
    [
        pytest.param(
            {"label": "Site", "value": "West"}, (*bold("Site"), Plain(": "), Plain("West")), id="text-value"
        ),
        pytest.param(
            {"label": "Lag", "value": 3, "delta": {"label": "flat"}},
            (*bold("Lag"), Plain(": "), Plain("3"), Plain(" flat")),
            id="delta-without-direction",
        ),
        pytest.param(
            {"label": "Cost", "value": 5, "delta": {"label": "-8%", "direction": "down", "tone": "success"}},
            (*bold("Cost"), Plain(": "), Plain("5"), Plain(" "), Chip("▼ -8%", "green")),
            id="toned-delta-is-a-colored-chip",
        ),
    ],
)
def test_a_card_shows_only_the_parts_it_has(card: dict[str, Any], text: ExportRich) -> None:
    assert lowered([{"type": "cards", "items": [card]}]) == (ListNode("bullet", (ListEntry(text),)),)


def test_a_derived_card_counts_its_badge_in_a_matrix_and_takes_the_badge_tone() -> None:
    blocks = [
        {"type": "cards", "items": [{"badge": "API", "of_matrix": "m", "note": "live"}]},
        {
            "type": "matrix",
            "id": "m",
            "rows": ["r1", "r2"],
            "columns": ["c"],
            "cells": [{"row": "r1", "col": "c", "badge": "API"}],
        },
    ]

    assert lowered(blocks, badges=API_BADGES) == (
        API_LEGEND,
        ListNode(
            "bullet",
            (
                ListEntry(
                    (Chip("api", "blue"), Plain(": 1 (50.0%)")),
                    children=(Paragraph((Plain("live"),), "muted"),),
                    tone="info",
                ),
            ),
        ),
        Table(
            (TableCell(()), *_cells("c")),
            (
                TableRow((TableCell(bold("r1")), TableCell((Plain("api"),), "info"))),
                TableRow((TableCell(bold("r2")), TableCell(()))),
            ),
            header_column=True,
        ),
    )


def test_a_derived_card_sums_its_tables_and_keeps_an_explicit_tone() -> None:
    blocks = [
        {
            "type": "cards",
            "items": [{"badge": "API", "of_tables": ["t"], "label": "API rows", "tone": "danger"}],
        },
        {
            "type": "table",
            "id": "t",
            "columns": [{"key": "a", "label": "A"}, {"key": "tag", "label": "", "kind": "badge"}],
            "rollup": {"by": "tag"},
            "rows": [{"a": "x", "tag": "API"}, {"a": "y", "tag": ""}],
        },
    ]

    assert lowered(blocks, badges=API_BADGES) == (
        ListNode("bullet", (ListEntry((Chip("API rows", "blue"), Plain(": 1 (50.0%)")), tone="danger"),)),
        API_LEGEND,
        Table(
            _cells("A"),
            (
                TableRow((TableCell((Plain("x"), Plain(" "), Chip("api", "blue"))),)),
                TableRow((TableCell((Plain("y"),)),)),
            ),
        ),
        Paragraph((Chip("api", "blue"), Plain(" 1"))),
    )


def test_fact_strip_and_key_value_entries_are_labelled_bullets() -> None:
    blocks = [
        {
            "type": "fact_strip",
            "facts": [{"label": "Site:", "value": "West  wing"}, {"label": " ", "value": "x"}],
        },
        {"type": "key_value", "pairs": [{"label": "Owner", "value": "**ops**"}]},
    ]

    assert lowered(blocks) == (
        ListNode(
            "bullet",
            (ListEntry((*bold("Site"), Plain(": "), Plain("West wing"))), ListEntry((Plain("x"),))),
        ),
        ListNode("bullet", (ListEntry((*bold("Owner"), Plain(": "), Styled("bold", (Plain("ops"),)))),)),
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


@pytest.mark.parametrize(
    ("axis", "note"),
    [
        pytest.param({"min": "Jan"}, (Paragraph((Plain("From Jan"),), "muted"),), id="start-only"),
        pytest.param({"max": "Dec"}, (Paragraph((Plain("To Dec"),), "muted"),), id="end-only"),
        pytest.param({"min": "Jan", "max": "Dec"}, (Paragraph((Plain("Jan to Dec"),), "muted"),), id="both"),
        pytest.param(
            {"min": "  ", "max": "Dec"}, (Paragraph((Plain("To Dec"),), "muted"),), id="blank-start"
        ),
        pytest.param(None, (), id="no-axis"),
    ],
)
def test_a_range_shows_the_axis_ends_it_has_and_each_segment_share(
    axis: dict[str, str] | None, note: tuple[Node, ...]
) -> None:
    block = {
        "type": "range",
        "segments": [
            {"label": "Seg", "span": 1, "tone": "danger", "sub": "one"},
            {"label": "Rest", "span": 3},
        ],
        **({"axis": axis} if axis else {}),
    }

    assert lowered([block]) == (
        *note,
        ListNode(
            "bullet",
            (
                ListEntry(
                    (*bold("Seg"), Plain(": "), Plain("25.0%"), Plain(", "), Plain("one")), tone="danger"
                ),
                ListEntry((*bold("Rest"), Plain(": "), Plain("75.0%"))),
            ),
        ),
    )


def test_status_and_timeline_entries_lead_with_their_state_mark() -> None:
    blocks = [
        {"type": "status_list", "items": [{"state": "blocked", "text": "Vendor"}]},
        {
            "type": "timeline",
            "items": [
                {"time": "Mon", "title": "Start", "state": "done", "badges": ["API"], "body": "kick-off"},
                {"title": "Later"},
            ],
        },
    ]

    assert lowered(blocks, badges=API_BADGES) == (
        API_LEGEND,
        ListNode("bullet", (ListEntry((Mark("status", "blocked"), Plain(" "), Plain("Vendor"))),)),
        ListNode(
            "bullet",
            (
                ListEntry(
                    (
                        Mark("timeline", "done"),
                        Plain(" "),
                        *bold("Mon"),
                        Plain(": "),
                        Plain("Start"),
                        Plain(" "),
                        Chip("api", "blue"),
                    ),
                    children=(Paragraph((Plain("kick-off"),)),),
                ),
                ListEntry((Plain("Later"),)),
            ),
        ),
    )


@pytest.mark.parametrize(
    ("state", "scheme"),
    [
        *(pytest.param(state, "status", id=f"status-{state}") for state in get_args(StatusState)),
        *(pytest.param(state, "timeline", id=f"timeline-{state}") for state in get_args(TimelineState)),
    ],
)
def test_every_state_a_block_allows_has_a_glyph(state: str, scheme: MarkScheme) -> None:
    assert MARK_GLYPH[scheme][state]


def test_a_definition_keeps_its_later_paragraphs_and_an_empty_body_is_its_term_alone() -> None:
    block = {
        "type": "def_list",
        "items": [{"term": "Fix", "body": "first\n\nsecond"}, {"term": "Gap", "body": " "}],
    }

    assert lowered([block]) == (
        ListNode(
            "bullet",
            (
                ListEntry(
                    (*bold("Fix"), Plain(": "), Plain("first")), children=(Paragraph((Plain("second"),)),)
                ),
                ListEntry((*bold("Gap"), Plain(": "))),
            ),
        ),
    )


def test_a_badge_row_is_a_labelled_line_and_its_groups_are_labelled_bullets() -> None:
    blocks = [
        {
            "type": "badge_row",
            "label": "Affects:",
            "items": [{"key": "API"}, {"label": "two\nlines", "tone": "red"}],
        },
        {"type": "badge_row", "groups": [{"label": "Owners:", "items": [{"label": "ops", "tone": "teal"}]}]},
    ]

    assert lowered(blocks, badges=API_BADGES) == (
        API_LEGEND,
        Paragraph((*bold("Affects"), Plain(": "), Chip("api", "blue"), Plain(" "), Chip("two lines", "red"))),
        ListNode("bullet", (ListEntry((*bold("Owners"), Plain(": "), Chip("ops", "teal"))),)),
    )


def test_a_badge_label_or_legend_with_a_line_break_stays_on_one_line() -> None:
    badges = {"API": {"label": "a\npi", "tone": "blue", "legend": "the API,\n- folded\n"}}

    assert lowered([{"type": "badge_row", "items": [{"key": "API"}]}], badges=badges) == (
        Toggle(
            (Plain("Legend: badges used on this page"),),
            None,
            (ListNode("bullet", (ListEntry((Chip("a pi", "blue"), Plain(" the API, - folded "))),)),),
        ),
        Paragraph((Chip("a pi", "blue"),)),
    )


@pytest.mark.parametrize(
    ("image", "caption"),
    [
        pytest.param(
            {"caption": "Fig **1** [^x]"}, "Fig **1** [^x]", id="caption-stays-literal-like-the-html"
        ),
        pytest.param({}, "chart", id="no-caption-falls-back-to-alt"),
    ],
)
def test_an_embedded_image_becomes_its_caption(image: dict[str, Any], caption: str) -> None:
    block = {"type": "image", "src": "data:image/png;base64,AA==", "alt": "chart", **image}

    assert lowered([block]) == (Paragraph((Styled("italic", (Plain(f"Image: {caption}"),)),), "muted"),)


@pytest.mark.parametrize(
    ("code", "nodes"),
    [
        pytest.param(
            {"label": "q.sql", "content": "select 1\n\n"},
            (Paragraph((Code("q.sql"),)), CodeBlock("select 1", "sql")),
            id="suffix",
        ),
        pytest.param(
            {"label": "fix.ts", "content": "+a", "mode": "diff"},
            (Paragraph((Code("fix.ts"),)), CodeBlock("+a", "diff")),
            id="diff",
        ),
        pytest.param(
            {"label": "notes.unknown", "content": "x"},
            (Paragraph((Code("notes.unknown"),)), CodeBlock("x", "")),
            id="unmapped-suffix",
        ),
        pytest.param({"content": "plain"}, (CodeBlock("plain", ""),), id="no-label"),
        pytest.param(
            {"label": "run.sh\n# injected", "content": "x"},
            (Paragraph((Code("run.sh # injected"),)), CodeBlock("x", "")),
            id="label-stays-on-one-line",
        ),
    ],
)
def test_a_code_block_language_comes_from_its_label_or_mode(
    code: dict[str, Any], nodes: tuple[Node, ...]
) -> None:
    assert lowered([{"type": "code", **code}]) == nodes


def test_a_quote_and_a_note_keep_their_text() -> None:
    blocks = [
        {"type": "quote", "body": "said\n\nagain", "cite": "Ops"},
        {"type": "note", "title": "Aside", "body": "x"},
    ]

    assert lowered(blocks) == (
        Quote(((Plain("said"),), (Plain("again"),)), (Plain("Ops"),)),
        Callout("neutral", (Paragraph(bold("Aside")), Paragraph((Plain("x"),)))),
    )


def test_an_untitled_callout_and_note_are_their_body_alone() -> None:
    blocks = [{"type": "callout", "tone": "warning", "body": "careful"}, {"type": "note", "body": "aside"}]

    assert lowered(blocks) == (
        Callout("warning", (Paragraph((Plain("careful"),)),)),
        Callout("neutral", (Paragraph((Plain("aside"),)),)),
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


def _cells(*texts: str) -> tuple[TableCell, ...]:
    return tuple(TableCell((Plain(text),) if text else ()) for text in texts)


@pytest.mark.parametrize(
    ("value", "polarity", "cell"),
    [
        pytest.param(True, "positive", TableCell((Mark("check", "yes"),), "success"), id="yes-is-good"),
        pytest.param(False, "positive", TableCell((Mark("check", "no"),), "danger"), id="no-is-bad"),
        pytest.param(
            True, "negative", TableCell((Mark("check", "yes"),), "danger"), id="yes-on-a-risk-is-bad"
        ),
        pytest.param(
            False, "negative", TableCell((Mark("check", "no"),), "success"), id="no-on-a-risk-is-good"
        ),
    ],
)
def test_a_comparison_colors_a_boolean_by_its_option_polarity(
    value: bool, polarity: str, cell: TableCell
) -> None:
    comparison = {
        "type": "comparison",
        "options": ["A", "B"],
        "polarity": [polarity, "positive"],
        "rows": [{"feature": "Risky", "values": [value, True]}],
    }

    assert lowered([comparison]) == (
        Table(
            (TableCell(()), *_cells("A", "B")),
            (TableRow((TableCell(bold("Risky")), cell, TableCell((Mark("check", "yes"),), "success"))),),
            header_column=True,
        ),
    )


def test_a_comparison_bolds_its_highlighted_option_and_keeps_text_and_toned_cells() -> None:
    comparison = {
        "type": "comparison",
        "options": ["A", "B"],
        "highlight": 1,
        "rows": [{"feature": "Note", "values": ["plain", {"value": "toned", "tone": "warning"}]}],
    }

    assert lowered([comparison]) == (
        Table(
            (TableCell(()), TableCell((Plain("A"),)), TableCell(bold("★ B"))),
            (
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


def test_a_matrix_shows_badge_toned_labelled_and_blank_cells() -> None:
    matrix = {
        "type": "matrix",
        "rows": ["r1"],
        "columns": ["c1", "c2", "c3", "c4"],
        "cells": [
            {"row": "r1", "col": "c1", "badge": "API"},
            {"row": "r1", "col": "c2", "badge": "API", "label": "yes"},
            {"row": "r1", "col": "c3", "label": "n/a", "tone": "neutral"},
        ],
    }

    assert lowered([matrix], badges=API_BADGES) == (
        API_LEGEND,
        Table(
            (TableCell(()), *_cells("c1", "c2", "c3", "c4")),
            (
                TableRow(
                    (
                        TableCell(bold("r1")),
                        TableCell((Plain("api"),), "info"),
                        TableCell((Plain("yes"),), "info"),
                        TableCell((Plain("n/a"),), "neutral"),
                        TableCell(()),
                    )
                ),
            ),
            header_column=True,
        ),
    )


def test_a_swimlane_shows_a_group_total_once_where_the_group_starts() -> None:
    swimlane = {
        "type": "swimlane",
        "lanes": ["Ops"],
        "columns": [{"name": "Plan", "sub": "wk 1"}, "Ship"],
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
                TableCell(
                    (*bold("Plan"), Break(), *italic(plain("wk 1")), Break(), Plain("Q1"), Plain(" (5)"))
                ),
                TableCell(bold("Ship")),
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


def test_a_split_swimlane_column_names_each_step_group_and_its_dependencies_once() -> None:
    swimlane = {
        "type": "swimlane",
        "lanes": ["Ops"],
        "columns": ["Plan"],
        "groups": [
            {"name": "A", "color": "blue", "columns": ["Plan"]},
            {"name": "B", "color": "amber", "columns": ["Plan"]},
        ],
        "steps": [
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
            {"id": "first", "lane": "Ops", "col": "Plan", "n": "1", "label": "Draft", "group": "A"},
            {"id": "again", "lane": "Ops", "col": "Plan", "n": "1", "label": "Redraft", "group": "A"},
        ],
    }

    assert lowered([swimlane]) == (
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
                                Plain(", A"),
                                Break(),
                                Mark("swimlane", "todo"),
                                Plain(" "),
                                *bold("1"),
                                Plain(" Redraft"),
                                Plain(", A"),
                                Break(),
                                Mark("swimlane", "deferred"),
                                Plain(" "),
                                Link((Plain("2"),), "https://e.com/2"),
                                Plain(" Send"),
                                Plain(", B"),
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


def test_a_blank_title_cell_starts_with_its_badge_or_subrow_not_a_break() -> None:
    table = {
        "type": "table",
        "columns": [
            {"key": "a", "label": "Issue"},
            {"key": "tag", "label": "", "kind": "badge", "placement": "title"},
        ],
        "rows": [{"a": "", "tag": "API"}, {"a": "", "tag": "", "subrows": [{"label": "s", "value": 2}]}],
    }

    assert lowered([table], badges=API_BADGES) == (
        API_LEGEND,
        Table(
            _cells("Issue"),
            (
                TableRow((TableCell((Chip("api", "blue"),)),)),
                TableRow((TableCell((Plain("s"), Plain(": 2"))),)),
            ),
        ),
    )


def test_a_reconciled_table_shows_its_rollup_and_reconcile_line_which_the_footer_repeats_as_in_html() -> None:
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
        API_LEGEND,
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
        Paragraph((Plain("Reconciles: 2 + 8 clean = 10."),), "muted"),
    )


@pytest.mark.parametrize(
    ("tag", "chips", "tone"),
    [
        pytest.param("API", (Chip("api", "blue"),), "info", id="one-key"),
        pytest.param(
            ["API", "OPS"],
            (Chip("api", "blue"), Plain(" "), Chip("ops", "red")),
            "info",
            id="first-of-a-list",
        ),
        pytest.param(
            ["", "API"],
            (Chip("api", "blue"),),
            None,
            id="blank-first-key-leaves-the-row-untinted-like-the-html",
        ),
    ],
)
def test_a_tinted_table_row_takes_the_tone_of_its_first_badge_key(
    tag: str | list[str], chips: ExportRich, tone: ToneName | None
) -> None:
    badges = {**API_BADGES, "OPS": {"label": "ops", "tone": "red", "legend": False}}
    table = {
        "type": "table",
        "columns": [
            {"key": "a", "label": "A"},
            {"key": "tag", "label": "", "kind": "badge", "placement": "cell"},
        ],
        "tint_by": "tag",
        "rows": [{"a": "x", "tag": tag}],
    }

    assert lowered([table], badges=badges) == (
        API_LEGEND,
        Table(_cells("A", ""), (TableRow((TableCell((Plain("x"),)), TableCell(chips)), tone),)),
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


def test_three_equal_grid_cells_get_ratios_that_add_up_to_a_hundred() -> None:
    grid = {"type": "grid", "cells": [{"span": 2, "blocks": [{"type": "text", "body": x}]} for x in "abc"]}

    assert lowered([grid]) == (
        Columns(
            tuple(
                Column(ratio, (Paragraph((Plain(x),)),)) for ratio, x in zip((33, 33, 34), "abc", strict=True)
            )
        ),
    )


def test_a_grid_inside_a_grid_cell_lays_its_cells_one_after_another() -> None:
    inner = {
        "type": "grid",
        "cells": [{"span": 3, "blocks": [{"type": "text", "body": x}]} for x in "bc"],
    }
    grid = {
        "type": "grid",
        "cells": [{"span": 2, "blocks": [{"type": "text", "body": "a"}]}, {"span": 4, "blocks": [inner]}],
    }

    assert lowered([grid]) == (
        Columns(
            (
                Column(33, (Paragraph((Plain("a"),)),)),
                Column(67, (Paragraph((Plain("b"),)), Paragraph((Plain("c"),)))),
            )
        ),
    )
