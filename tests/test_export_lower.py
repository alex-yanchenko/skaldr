from typing import Any

import pytest

from skaldr.code_language import code_language
from skaldr.export.inline import bold, italic, plain
from skaldr.export.lower import lower_report, place_legend
from skaldr.export.lower.context import spaced, with_bold_label
from skaldr.export.runs import (
    Break,
    CheckMark,
    Chip,
    DecisionMark,
    ExportRich,
    Gauge,
    IndicatorMark,
    StatusMark,
    SwimlaneMark,
)
from skaldr.export.tree import (
    Callout,
    CodeBlock,
    Columns,
    Diagram,
    DisplayMath,
    Divider,
    Graph,
    GraphEdge,
    GraphNode,
    GridColumn,
    Heading,
    HeadingLevel,
    ListEntry,
    ListNode,
    LoweredDocument,
    Node,
    Paragraph,
    PieChart,
    PieSlice,
    Quote,
    Tab,
    TableCell,
    TableColumn,
    TableNode,
    TableOfContents,
    TableRow,
    Tabs,
    TocEntry,
    Toggle,
    ToneName,
    XYChart,
    capped_heading_level,
    heading_of,
)
from skaldr.models import SwimlaneStepState, parse_report
from skaldr.richtext import (
    AnchorLink,
    Citation,
    Code,
    InlineMath,
    Link,
    Plain,
    Rich,
    ScriptText,
    Styled,
    Tinted,
)
from tests.factories import (
    API_BADGES,
    lowered,
    make_cell,
    make_command_request,
    make_grid,
    make_report,
    make_request,
    make_tab,
    make_table,
    make_tabs,
    make_toggle,
)

API_LEGEND = Toggle(
    (Plain("Legend: badges used on this page"),),
    None,
    (ListNode("bullet", (ListEntry((Chip("api", "blue"), Plain(" "), Plain("the API"))),)),),
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
    ("note", "visible", "runs"),
    [
        pytest.param(
            "see [doc](https://e.com/d)",
            "see doc",
            (Plain("see "), Link((Plain("doc"),), "https://e.com/d")),
            id="web-link",
        ),
        pytest.param(
            "see [count](#count)",
            "see count",
            (Plain("see "), AnchorLink((Plain("count"),), "count")),
            id="anchor",
        ),
        pytest.param(
            "per [^sop]", "per [1]", (Plain("per "), Citation("sop", 1, "https://e.com/sop")), id="citation"
        ),
        pytest.param(
            "**[doc](https://e.com/d)**",
            "doc",
            (Styled("bold", (Link((Plain("doc"),), "https://e.com/d"),)),),
            id="link-inside-bold",
        ),
        pytest.param(
            "per [[^sop]]{tone=info}",
            "per [1]",
            (Plain("per "), Tinted("info", None, (Citation("sop", 1, "https://e.com/sop"),))),
            id="citation-inside-a-color-span",
        ),
        pytest.param(
            "rate $`x_i`$",
            "rate x_i",
            (Plain("rate "), InlineMath("x_i")),
            id="inline-math",
        ),
        pytest.param(
            "about 10^3^",
            "about 103",
            (Plain("about 10"), ScriptText("superscript", "3")),
            id="superscript",
        ),
    ],
)
def test_a_flow_lists_a_step_whose_note_loses_meaning_in_a_plain_label(
    note: str, visible: str, runs: Rich
) -> None:
    flow = {"type": "flow", "numbered": False, "steps": [{"label": "Scan", "note": note}, {"label": "Fix"}]}
    references = {"type": "references", "items": [{"key": "sop", "text": "SOP", "url": "https://e.com/sop"}]}

    diagrams = [
        node
        for node in lowered([{"type": "heading", "text": "Count"}, flow, references])
        if isinstance(node, Diagram)
    ]

    assert diagrams == [
        Diagram(
            Graph("LR", (GraphNode("s1", "Scan", visible), GraphNode("s2", "Fix")), (GraphEdge("s1", "s2"),)),
            (ListNode("bullet", (ListEntry((*bold("Scan"), Plain(": "), *runs)),)),),
        )
    ]


def test_a_fan_lists_a_spoke_whose_note_holds_inline_math() -> None:
    fan = {
        "type": "fan",
        "direction": "out",
        "hub": {"label": "Hub"},
        "spokes": [{"label": "A", "note": "$`a^2`$"}, {"label": "B", "note": "plain"}],
    }

    assert lowered([fan]) == (
        Diagram(
            Graph(
                "LR",
                (GraphNode("hub", "Hub"), GraphNode("s1", "A", "a^2"), GraphNode("s2", "B", "plain")),
                (GraphEdge("hub", "s1"), GraphEdge("hub", "s2")),
            ),
            (ListNode("bullet", (ListEntry((*bold("A"), Plain(": "), InlineMath("a^2"))),)),),
        ),
    )


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
                (GraphNode("hub", "Hub"), GraphNode("s1", "A"), GraphNode("s2", "B")),
                (GraphEdge("hub", "s1"), GraphEdge("hub", "s2")),
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
            Graph("LR", (GraphNode("hub", "Hub"), GraphNode("s1", "A"), GraphNode("s2", "B")), edges),
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
            PieChart((PieSlice("A", 3), PieSlice("B", 1.5))),
            (
                TableNode(
                    _cells("Slice", "Value", "Share"),
                    (
                        TableRow(_cells("A", "3", "67%"), "success"),
                        TableRow(_cells("B", "1.5", "33%")),
                        TableRow(_cells("Total", "4.5", ""), emphasis="total"),
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
                    _cells("Slice", "Value", "Share"),
                    (
                        TableRow(_cells("A", "12.25", "78%")),
                        TableRow(_cells("B", "3.5", "22%")),
                        TableRow(_cells("Total", "15.75", ""), emphasis="total"),
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
                    _cells("Slice", "Value", "Share"),
                    (
                        TableRow(_cells("A", "1,200", "100%")),
                        TableRow(_cells("Total", "1,200", ""), emphasis="total"),
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
            XYChart("line", ("Q1", "Q2"), ((1, 2),)),
            (TableNode(_cells("Series", "Q1", "Q2"), (TableRow(_cells("x", "1", "2"), "danger"),)),),
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
            XYChart("bar", ("Q1",), ((4,),)),
            (TableNode(_cells("Series", "Q1"), (TableRow(_cells("x", "4")),)),),
        ),
    )


TWO_SERIES: list[dict[str, Any]] = [{"label": "x", "values": [1]}, {"label": "y", "values": [2]}]


@pytest.mark.parametrize(
    ("variant", "stacked", "series", "rows"),
    [
        pytest.param("bar", True, TWO_SERIES, [("x", "1"), ("y", "2")], id="stacked-bars"),
        pytest.param(
            "bar", False, TWO_SERIES, [("x", "1"), ("y", "2")], id="grouped-bars-would-overlap-in-mermaid"
        ),
        pytest.param(
            "line", False, TWO_SERIES, [("x", "1"), ("y", "2")], id="lines-would-have-no-legend-in-mermaid"
        ),
        pytest.param("bar", True, TWO_SERIES[:1], [("x", "1")], id="stacked-single-bar"),
    ],
)
def test_a_chart_with_several_series_or_stacked_bars_is_its_table_alone(
    variant: str, stacked: bool, series: list[dict[str, Any]], rows: list[tuple[str, str]]
) -> None:
    chart = {"type": "chart", "variant": variant, "stacked": stacked, "categories": ["Q1"], "series": series}

    assert lowered([chart]) == (
        TableNode(_cells("Series", "Q1"), tuple(TableRow(_cells(*row)) for row in rows)),
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
        Paragraph((*bold("Recorded output"), Plain(": "), Plain("200 OK"))),
        CodeBlock("ok", ""),
        Callout("success", (Paragraph((*bold("Verdict"), Plain(": "), Plain("fine"))),)),
    )


READ_WIDGETS = "curl -i -X GET \\\n  -H 'Accept: application/json' \\\n  'https://{{host}}/widgets'"


def test_a_request_lists_its_labelled_variables_and_shows_a_case_with_no_status_line() -> None:
    request = make_request(
        variables=[{"name": "host", "label": "API host", "example": "api.example.com"}],
        cases=[{"label": "one", "response": {"headers": {"content-type": "text/plain"}, "body": "ok"}}],
    )

    assert lowered([request]) == (
        Paragraph(bold("Read an endpoint")),
        Paragraph(bold("Values you supply")),
        ListNode(
            "bullet",
            (ListEntry((Code("{{host}}"), Plain(" "), Plain("API host: for example api.example.com"))),),
        ),
        Paragraph(italic(plain("one"))),
        CodeBlock(READ_WIDGETS, "bash"),
        Paragraph((*bold("Recorded response"), Plain(": "), Plain("no status line"))),
        CodeBlock("content-type: text/plain\n\nok", "http"),
    )


def test_a_verdict_on_one_case_of_several_sits_in_that_case_tab() -> None:
    request = make_request(
        variables=[],
        url="https://api.example.com/widgets",
        cases=[
            {"label": "missing", "verdict": "a **gap**", "response": {"status": 404, "body": "{}"}},
            {"label": "found", "response": {"status": 200, "body": "[]"}},
        ],
    )
    command = "curl -i -X GET \\\n  -H 'Accept: application/json' \\\n  https://api.example.com/widgets"

    assert lowered([request]) == (
        Paragraph(bold("Read an endpoint")),
        Tabs(
            (
                Tab(
                    (Plain("missing"),),
                    (
                        CodeBlock(command, "bash"),
                        Paragraph((*bold("Recorded response"), Plain(": "), Plain("404 Not Found"))),
                        CodeBlock("{}", "json"),
                        Callout(
                            "warning",
                            (Paragraph((*bold("Verdict"), Plain(": "), Plain("a "), *bold("gap"))),),
                        ),
                    ),
                    "warning",
                ),
                Tab(
                    (Plain("found"),),
                    (
                        CodeBlock(command, "bash"),
                        Paragraph((*bold("Recorded response"), Plain(": "), Plain("200 OK"))),
                        CodeBlock("[]", "json"),
                    ),
                    "success",
                ),
            )
        ),
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
                    (CodeBlock("list", "bash"), Paragraph(bold("Recorded output")), CodeBlock("x", "")),
                    "warning",
                ),
                Tab(
                    (Plain("b"),),
                    (CodeBlock("list", "bash"), Paragraph(bold("Recorded output")), CodeBlock("y", "")),
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
                "captures": [
                    {"name": "token", "json_path": "$.data.access_token"},
                    {"name": "expires", "source": "body"},
                ],
                "cases": [{"label": "one", "response": {"status": 200, "body": "{}"}}],
            },
            {
                "label": "Read",
                "method": "GET",
                "url": "https://{{host}}/r",
                "headers": {"Authorization": "Bearer {{token}}", "X-Expires": "{{expires}}"},
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
                ListEntry((Code("{{host}}"), Plain(" "), Plain("host: for example api.example.com"))),
                ListEntry((Code("{{key}}"), Plain(" "), Plain("key: a secret, supply your own"))),
                ListEntry((Code("{{who}}"), Plain(" "), Plain("who: supply a value"))),
            ),
        ),
        Paragraph(
            (
                *bold("Step 1 of 2: Get token"),
                Plain(", captures "),
                Code("token"),
                Plain(" from "),
                Code("$.data.access_token"),
                Plain(", "),
                Code("expires"),
                Plain(" from the whole response body"),
            )
        ),
        Paragraph(italic(plain("one"))),
        CodeBlock(
            "curl -i -X POST \\\n  -H 'X-Key: {{key}}' \\\n  -H 'X-Who: {{who}}' \\\n  'https://{{host}}/t'",
            "bash",
        ),
        Paragraph((*bold("Recorded response"), Plain(": "), Plain("200 OK"))),
        CodeBlock("{}", "json"),
        Paragraph(bold("Step 2 of 2: Read")),
        Paragraph(italic(plain("one"))),
        CodeBlock(
            "curl -i -X GET \\\n  -H 'Authorization: Bearer {{token}}' \\\n  -H 'X-Expires: {{expires}}' \\\n"
            "  'https://{{host}}/r'",
            "bash",
        ),
        Paragraph((*bold("Recorded response"), Plain(": "), Plain("200 OK"))),
        CodeBlock("content-type: application/json\ncontent-type: charset=utf-8\n\n{}", "http"),
    )


def test_a_walkthrough_step_with_no_sub_is_its_bold_label() -> None:
    walkthrough = {
        "type": "walkthrough",
        "steps": [{"label": "Go", "detail": [{"type": "text", "body": "d"}]}],
    }

    assert lowered([walkthrough]) == (
        ListNode("number", (ListEntry(bold("Go"), children=(Paragraph((Plain("d"),)),)),)),
    )


def test_rich_text_keeps_the_spaces_inside_a_code_span() -> None:
    assert lowered([{"type": "text", "body": "run  `a  b`\nnow"}]) == (
        Paragraph((Plain("run "), Code("a  b"), Plain(" now"))),
    )


@pytest.mark.parametrize(
    ("item", "runs"),
    [
        pytest.param("[a\nb](https://e.com)", (Link((Plain("a b"),), "https://e.com"),), id="link-label"),
        pytest.param("[a\nb](#count)", (AnchorLink((Plain("a b"),), "count"),), id="anchor-link-label"),
        pytest.param("**a\nb**", (Styled("bold", (Plain("a b"),)),), id="styled"),
        pytest.param("[a\nb]{tone=info}", (Tinted("info", None, (Plain("a b"),)),), id="tinted"),
        pytest.param("  x  ", (Plain("x"),), id="outer-spaces-trimmed"),
        pytest.param("  `x`  ", (Code("x"),), id="outer-spaces-around-code-dropped"),
        pytest.param("`x\ry`", (Code("x y"),), id="code-carriage-return"),
        pytest.param("`x\r\ny`", (Code("x y"),), id="code-crlf"),
        pytest.param("`x\n`", (Code("x "),), id="code-ending-in-a-line-break"),
        pytest.param("`\n`", (Code(" "),), id="code-of-only-a-line-break"),
    ],
)
def test_rich_text_lowers_onto_one_line(item: str, runs: Rich) -> None:
    blocks = [{"type": "heading", "text": "Count"}, {"type": "list", "items": [item]}]

    assert lowered(blocks) == (
        Heading(2, (Plain("Count"),), "count"),
        ListNode("bullet", (ListEntry(runs),)),
    )


@pytest.mark.parametrize(
    ("text", "runs"),
    [
        pytest.param("Appendix\n", (Plain("Appendix"),), id="trailing-newline"),
        pytest.param("  a \n b  ", (Plain("a b"),), id="inner-and-outer-whitespace"),
        pytest.param(" \n ", (), id="only-whitespace"),
    ],
)
def test_plain_text_is_trimmed_and_collapsed_to_one_line(text: str, runs: Rich) -> None:
    assert plain(text) == runs


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


def test_a_level_four_heading_keeps_its_level_and_anchor() -> None:
    assert lowered([{"type": "heading", "level": 4, "text": "Bin detail"}]) == (
        Heading(4, (Plain("Bin detail"),), "bin-detail"),
    )


def test_a_level_four_heading_inside_a_section_moves_down_to_level_five() -> None:
    section = {
        "type": "section",
        "title": "Open",
        "collapsed": False,
        "blocks": [{"type": "heading", "text": "Deep", "level": 4}],
    }

    assert lowered([section]) == (Heading(2, (Plain("Open"),), "open"), Heading(5, (Plain("Deep"),), "deep"))


def test_an_open_section_is_a_heading_and_a_level_three_heading_inside_it_moves_to_level_four() -> None:
    section = {
        "type": "section",
        "title": "Open",
        "collapsed": False,
        "blocks": [{"type": "heading", "text": "Deep", "level": 3}],
    }

    assert lowered([section]) == (Heading(2, (Plain("Open"),), "open"), Heading(4, (Plain("Deep"),), "deep"))


@pytest.mark.parametrize(
    ("level", "capped"),
    [
        pytest.param(0, 1, id="below-the-range"),
        pytest.param(1, 1, id="top"),
        pytest.param(5, 5, id="below-the-cap"),
        pytest.param(6, 6, id="the-cap"),
        pytest.param(7, 6, id="past-the-cap"),
    ],
)
def test_a_heading_level_is_capped_to_what_the_writer_supports(level: int, capped: HeadingLevel) -> None:
    assert capped_heading_level(level) == capped


@pytest.mark.parametrize(
    ("node", "heading"),
    [
        pytest.param(Heading(3, (Plain("H"),), "h"), Heading(3, (Plain("H"),), "h"), id="heading"),
        pytest.param(
            Toggle((Plain("T"),), 2, (Paragraph((Plain("x"),)),), "t"),
            Heading(2, (Plain("T"),), "t"),
            id="heading-toggle",
        ),
        pytest.param(Toggle((Plain("T"),), None, ()), None, id="plain-toggle"),
        pytest.param(Paragraph((Plain("p"),)), None, id="paragraph"),
    ],
)
def test_a_heading_or_a_heading_toggle_reads_as_a_heading(node: Node, heading: Heading | None) -> None:
    assert heading_of(node) == heading


def test_muted_text_and_the_provenance_footer_are_muted_paragraphs() -> None:
    blocks = [{"type": "text", "body": "aside", "muted": True}]

    assert lowered(blocks, meta={"title": "T", "source": "SOP v2", "date": "1 Oct"}) == (
        Paragraph((Plain("aside"),), "muted"),
        Paragraph((Plain("SOP v2"), Plain(" · "), Plain("1 Oct")), "muted"),
    )


@pytest.mark.parametrize(
    ("meta", "runs"),
    [
        pytest.param(
            {"source": "commit `abc123` in `app.ts`"},
            (Plain("commit "), Code("abc123"), Plain(" in "), Code("app.ts")),
            id="the-source-is-rich-text",
        ),
        pytest.param(
            {"source": "x", "date": "a `b` + c"},
            (Plain("x"), Plain(" · "), Plain("a `b` + c")),
            id="the-date-and-the-other-facts-stay-plain",
        ),
        pytest.param({"date": "1 Oct"}, (Plain("1 Oct"),), id="no-source"),
        pytest.param({"source": " ", "date": "1 Oct"}, (Plain("1 Oct"),), id="a-blank-source-is-no-source"),
    ],
)
def test_the_provenance_footer_reads_its_source_as_rich_text(meta: dict[str, str], runs: ExportRich) -> None:
    assert lowered([{"type": "text", "body": "x"}], meta={"title": "T", **meta}) == (
        Paragraph((Plain("x"),)),
        Paragraph(runs, "muted"),
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


@pytest.mark.parametrize(
    ("legend_at", "nodes"),
    [
        pytest.param(
            None,
            [API_LEGEND, Paragraph((Plain("a"),)), Paragraph((Plain("b"),)), Paragraph((Plain("table"),))],
            id="no-top-level-table-puts-it-first",
        ),
        pytest.param(
            2,
            [Paragraph((Plain("a"),)), Paragraph((Plain("b"),)), API_LEGEND, Paragraph((Plain("table"),))],
            id="right-before-the-first-top-level-table",
        ),
        pytest.param(
            0,
            [API_LEGEND, Paragraph((Plain("a"),)), Paragraph((Plain("b"),)), Paragraph((Plain("table"),))],
            id="table-first",
        ),
    ],
)
def test_the_badge_legend_goes_where_the_html_puts_it(legend_at: int | None, nodes: list[Node]) -> None:
    blocks = [[Paragraph((Plain("a"),))], [Paragraph((Plain("b"),))], [Paragraph((Plain("table"),))]]

    assert place_legend(blocks, [API_LEGEND], legend_at) == nodes


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
                        Plain(" "),
                        Plain("(90.0%)"),
                        Plain(" "),
                        Plain("▲ +1"),
                        Plain(" "),
                        Chip("api", "blue"),
                    ),
                    children=(Paragraph((Plain("since Monday"),), "muted"),),
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
            (*bold("Lag"), Plain(": "), Plain("3"), Plain(" "), Plain("flat")),
            id="delta-without-direction",
        ),
        pytest.param(
            {"label": "Cost", "value": 5, "delta": {"label": "-8%", "direction": "down", "tone": "success"}},
            (*bold("Cost"), Plain(": "), Plain("5"), Plain(" "), Chip("▼ -8%", "green")),
            id="toned-delta-is-a-colored-chip",
        ),
        pytest.param(
            {"label": "Site", "value": "West", "tone": "danger"},
            (Tinted("danger", None, bold("Site")), Plain(": "), Plain("West")),
            id="tone-colours-the-label-only",
        ),
        pytest.param(
            {"label": "Cost", "value": 5, "tone": "danger", "delta": {"label": "-8%", "tone": "success"}},
            (Tinted("danger", None, bold("Cost")), Plain(": "), Plain("5"), Plain(" "), Chip("-8%", "green")),
            id="a-toned-delta-keeps-its-own-colour-beside-the-coloured-label",
        ),
        pytest.param({"label": " ", "value": 7}, (Plain("7"),), id="blank-label"),
        pytest.param(
            {"label": " ", "value": 7, "tone": "danger"},
            (Plain("7"),),
            id="a-blank-label-has-nothing-to-colour",
        ),
        pytest.param({"label": "Empty", "value": ""}, bold("Empty"), id="empty-value-is-the-label-alone"),
    ],
)
def test_a_card_shows_only_the_parts_it_has(card: dict[str, Any], text: ExportRich) -> None:
    assert lowered([{"type": "cards", "items": [card]}]) == (ListNode("bullet", (ListEntry(text),)),)


def test_a_toned_card_that_shows_a_badge_leaves_the_colour_to_the_badge() -> None:
    card = {"label": "Cost", "value": 5, "tone": "danger", "badges": ["API"]}

    assert lowered([{"type": "cards", "items": [card]}], badges=API_BADGES) == (
        API_LEGEND,
        ListNode(
            "bullet", (ListEntry((*bold("Cost"), Plain(": "), Plain("5"), Plain(" "), Chip("api", "blue"))),)
        ),
    )


def test_a_derived_card_counts_its_badge_in_a_matrix_and_leaves_its_colour_to_the_badge() -> None:
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
                ),
            ),
        ),
        TableNode(
            (TableCell(()), *_cells("c")),
            (
                TableRow((TableCell((Plain("r1"),)), TableCell((Plain("api"),), "info"))),
                TableRow((TableCell((Plain("r2"),)), TableCell(()))),
            ),
            header_column=True,
        ),
    )


def test_a_derived_card_sums_its_tables_and_leaves_its_colour_to_its_badge() -> None:
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
        ListNode("bullet", (ListEntry((Chip("API rows", "blue"), Plain(": 1 (50.0%)"))),)),
        API_LEGEND,
        TableNode(
            _cells("A"),
            (
                TableRow((TableCell((Plain("x"), Plain(" "), Chip("api", "blue"))),)),
                TableRow((TableCell((Plain("y"),)),)),
            ),
        ),
        Paragraph((Chip("api", "blue"), Plain(" "), Plain("1"))),
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
                    (
                        Tinted("warning", None, bold("Zone")),
                        Plain(": "),
                        Gauge(5, 10),
                        Plain(" "),
                        Plain("50.0%"),
                    )
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
                    (
                        Tinted("danger", None, bold("Seg")),
                        Plain(": "),
                        Plain("25.0%"),
                        Plain(", "),
                        Plain("one"),
                    )
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
        ListNode("bullet", (ListEntry((StatusMark("blocked"), Plain(" "), Plain("Vendor"))),)),
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
                    children=(Paragraph((Plain("kick-off"),)),),
                ),
                ListEntry((Plain("Later"),)),
            ),
        ),
    )


@pytest.mark.parametrize(
    "options",
    [pytest.param({}, id="numbering-left-out"), pytest.param({"numbering": "decimal"}, id="decimal")],
)
def test_a_decimal_list_keeps_its_start_and_its_nested_list_counts_from_one(options: dict[str, Any]) -> None:
    block = {
        "type": "list",
        "style": "number",
        "start": 3,
        "items": [{"text": "a", "items": ["b"]}],
        **options,
    }

    assert lowered([block]) == (
        ListNode(
            "number",
            (ListEntry((Plain("a"),), children=(ListNode("number", (ListEntry((Plain("b"),)),)),)),),
            start=3,
        ),
    )


@pytest.mark.parametrize(
    ("numbering", "labels"),
    [
        pytest.param("roman", ("iv. ", "v. ", "i. "), id="roman"),
        pytest.param("letters", ("d. ", "e. ", "a. "), id="letters"),
    ],
)
def test_a_letter_or_roman_list_is_a_bullet_list_led_by_its_labels_and_a_nested_list_starts_over(
    numbering: str, labels: tuple[str, str, str]
) -> None:
    block = {
        "type": "list",
        "style": "number",
        "start": 4,
        "numbering": numbering,
        "items": ["a", {"text": "b", "items": ["c"]}],
    }
    first, second, nested = labels

    assert lowered([block]) == (
        ListNode(
            "bullet",
            (
                ListEntry((Plain(first), Plain("a"))),
                ListEntry(
                    (Plain(second), Plain("b")),
                    children=(ListNode("bullet", (ListEntry((Plain(nested), Plain("c"))),)),),
                ),
            ),
        ),
    )


def test_a_decision_list_is_a_bullet_list_led_by_a_decision_mark_at_every_level() -> None:
    block = {
        "type": "list",
        "style": "decision",
        "items": ["open", {"text": "done", "decided": True, "items": ["sub"]}],
    }

    assert lowered([block]) == (
        ListNode(
            "bullet",
            (
                ListEntry((DecisionMark(decided=False), Plain(" "), Plain("open"))),
                ListEntry(
                    (DecisionMark(decided=True), Plain(" "), Plain("done")),
                    children=(
                        ListNode(
                            "bullet", (ListEntry((DecisionMark(decided=False), Plain(" "), Plain("sub"))),)
                        ),
                    ),
                ),
            ),
        ),
    )


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
                ListEntry(bold("Gap")),
            ),
        ),
    )


@pytest.mark.parametrize(
    ("label", "text", "runs"),
    [
        pytest.param("Site", plain("West"), (*bold("Site"), Plain(": "), Plain("West")), id="label-and-text"),
        pytest.param(
            "Site:",
            plain("West"),
            (*bold("Site"), Plain(": "), Plain("West")),
            id="its-own-colon-is-not-doubled",
        ),
        pytest.param(":", plain("West"), (Plain("West"),), id="a-lone-colon-is-no-label"),
        pytest.param(None, plain("West"), (Plain("West"),), id="no-label"),
        pytest.param("Gap", (), bold("Gap"), id="no-text-leaves-no-dangling-colon"),
    ],
)
def test_a_label_is_bold_and_joined_to_its_text_by_one_colon(
    label: str | None, text: ExportRich, runs: ExportRich
) -> None:
    assert with_bold_label(label, text) == runs


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
            (
                ListNode(
                    "bullet", (ListEntry((Chip("a pi", "blue"), Plain(" "), Plain("the API, - folded"))),)
                ),
            ),
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
            {"content": "gh run list", "lang": "shell"}, (CodeBlock("gh run list", "shell"),), id="lang"
        ),
        pytest.param(
            {"label": "q.sql", "content": "x", "lang": "plain text"},
            (Paragraph((Code("q.sql"),)), CodeBlock("x", "plain text")),
            id="lang-wins-over-the-label-suffix",
        ),
        pytest.param(
            {"content": "+a", "mode": "diff", "lang": "python"},
            (CodeBlock("+a", "diff"),),
            id="diff-mode-wins-over-lang",
        ),
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


@pytest.mark.parametrize(
    ("label", "language"),
    [
        pytest.param("Deploy.SH", "bash", id="an-upper-case-suffix"),
        pytest.param("app.Py", "python", id="a-mixed-case-suffix"),
        pytest.param(None, "", id="no-label"),
        pytest.param("Makefile", "", id="no-suffix"),
    ],
)
def test_a_code_language_ignores_the_case_of_the_label_suffix(label: str | None, language: str) -> None:
    assert code_language(label) == language


def test_a_quote_and_a_note_keep_their_text() -> None:
    blocks = [
        {"type": "quote", "body": "said\n\nagain", "cite": "Ops"},
        {"type": "note", "title": "Aside", "body": "x"},
    ]

    assert lowered(blocks) == (
        Quote(((Plain("said"),), (Plain("again"),)), (Plain("Ops"),)),
        Callout("neutral", (Paragraph(bold("Aside")), Paragraph((Plain("x"),)))),
    )


@pytest.mark.parametrize(
    ("expression", "lowered_expression"),
    [
        pytest.param("E = mc^2", "E = mc^2", id="one-line"),
        pytest.param("\n  a \\\\\n\n  b\n\n", "  a \\\\\n  b", id="blank-lines-dropped"),
    ],
)
def test_a_math_block_keeps_its_expression_without_blank_lines(
    expression: str, lowered_expression: str
) -> None:
    assert lowered([{"type": "math", "expression": expression}]) == (DisplayMath(lowered_expression),)


@pytest.mark.parametrize(
    ("item", "runs"),
    [
        pytest.param("$`a\nb`$", (InlineMath("a b"),), id="line-break-inside"),
        pytest.param("$`a\r\nb`$", (InlineMath("a b"),), id="crlf-inside"),
    ],
)
def test_inline_math_lowers_onto_one_line(item: str, runs: Rich) -> None:
    assert lowered([{"type": "list", "items": [item]}]) == (ListNode("bullet", (ListEntry(runs),)),)


def test_an_untitled_callout_and_note_are_their_body_alone() -> None:
    blocks = [{"type": "callout", "tone": "warning", "body": "careful"}, {"type": "note", "body": "aside"}]

    assert lowered(blocks) == (
        Callout("warning", (Paragraph((Plain("careful"),)),)),
        Callout("neutral", (Paragraph((Plain("aside"),)),)),
    )


def test_a_callout_and_a_note_carry_their_icon() -> None:
    blocks = [
        {"type": "callout", "tone": "success", "icon": "🚀", "title": "Go", "body": "now"},
        {"type": "note", "icon": "📌", "body": "aside"},
    ]

    assert lowered(blocks) == (
        Callout("success", (Paragraph(bold("Go")), Paragraph((Plain("now"),))), icon="🚀"),
        Callout("neutral", (Paragraph((Plain("aside"),)),), icon="📌"),
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
                    (Tinted("info", None, (*bold("Go"), Plain(" "), Styled("italic", (Plain("first"),)))),),
                    children=(Paragraph((Plain("d"),)),),
                ),
            ),
        ),
    )


def test_a_collapsed_toggle_is_a_plain_toggle_with_no_heading_or_anchor() -> None:
    toggle = {"type": "toggle", "title": "Raw counts", "blocks": [{"type": "text", "body": "x"}]}

    assert lowered([toggle]) == (Toggle((Plain("Raw counts"),), None, (Paragraph((Plain("x"),)),)),)


def test_an_open_toggle_is_its_bold_title_over_its_content() -> None:
    toggle = {
        "type": "toggle",
        "title": "Raw counts",
        "collapsed": False,
        "blocks": [{"type": "text", "body": "x"}],
    }

    assert lowered([toggle]) == (Paragraph(bold("Raw counts")), Paragraph((Plain("x"),)))


def test_a_heading_in_a_top_level_toggle_keeps_its_level_and_anchor() -> None:
    toggle = make_toggle({"type": "heading", "level": 3, "text": "Deep", "id": "deep"})

    assert lowered([toggle]) == (Toggle((Plain("More"),), None, (Heading(3, (Plain("Deep"),), "deep"),)),)


def test_a_heading_in_a_toggle_inside_a_section_moves_down_with_the_section_and_keeps_its_anchor() -> None:
    toggle = make_toggle({"type": "heading", "level": 3, "text": "Deep", "id": "deep"})
    section = {"type": "section", "title": "Open", "collapsed": False, "blocks": [toggle]}

    assert lowered([section]) == (
        Heading(2, (Plain("Open"),), "open"),
        Toggle((Plain("More"),), None, (Heading(4, (Plain("Deep"),), "deep"),)),
    )


RAW_COUNTS_TOGGLE = make_toggle({"type": "text", "body": "x"}, title="Raw counts")
RAW_COUNTS_TOGGLE_NODE = Toggle((Plain("Raw counts"),), None, (Paragraph((Plain("x"),)),))


@pytest.mark.parametrize(
    ("block", "nodes"),
    [
        pytest.param(
            make_grid([make_cell(6, [RAW_COUNTS_TOGGLE])]), (RAW_COUNTS_TOGGLE_NODE,), id="grid-cell"
        ),
        pytest.param(
            make_tabs(make_tab("Floor", RAW_COUNTS_TOGGLE), make_tab("System")),
            (
                Tabs(
                    (
                        Tab((Plain("Floor"),), (RAW_COUNTS_TOGGLE_NODE,)),
                        Tab((Plain("System"),), (Paragraph((Plain("System"),)),)),
                    )
                ),
            ),
            id="tab",
        ),
    ],
)
def test_a_toggle_inside_a_grid_cell_or_a_tab_lowers_like_a_top_level_toggle(
    block: dict[str, Any], nodes: tuple[Node, ...]
) -> None:
    assert lowered([block]) == nodes


def test_a_tabs_block_is_the_tabs_node_requests_use_with_each_tab_tone() -> None:
    block = {
        "type": "tabs",
        "tabs": [
            {"label": "Floor", "tone": "warning", "blocks": [{"type": "text", "body": "a"}]},
            {"label": "System", "blocks": [{"type": "heading", "level": 3, "text": "Scan"}]},
        ],
    }

    assert lowered([block]) == (
        Tabs(
            (
                Tab((Plain("Floor"),), (Paragraph((Plain("a"),)),), "warning"),
                Tab((Plain("System"),), (Heading(3, (Plain("Scan"),), "scan"),)),
            )
        ),
    )


def test_a_divider_lowers_to_a_divider_node_between_its_neighbours() -> None:
    blocks = [{"type": "text", "body": "a"}, {"type": "divider"}, {"type": "text", "body": "b"}]

    assert lowered(blocks) == (Paragraph((Plain("a"),)), Divider(), Paragraph((Plain("b"),)))


def _cells(*texts: str) -> tuple[TableCell, ...]:
    return tuple(TableCell((Plain(text),) if text else ()) for text in texts)


@pytest.mark.parametrize(
    ("value", "polarity", "cell"),
    [
        pytest.param(True, "positive", TableCell((CheckMark(checked=True),), "success"), id="yes-is-good"),
        pytest.param(False, "positive", TableCell((CheckMark(checked=False),), "danger"), id="no-is-bad"),
        pytest.param(
            True, "negative", TableCell((CheckMark(checked=True),), "danger"), id="yes-on-a-risk-is-bad"
        ),
        pytest.param(
            False, "negative", TableCell((CheckMark(checked=False),), "success"), id="no-on-a-risk-is-good"
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
        TableNode(
            (TableCell(()), *_cells("A", "B")),
            (
                TableRow(
                    (TableCell((Plain("Risky"),)), cell, TableCell((CheckMark(checked=True),), "success"))
                ),
            ),
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
        TableNode(
            (TableCell(()), TableCell((Plain("A"),)), TableCell((Plain("★ B"),))),
            (
                TableRow(
                    (
                        TableCell((Plain("Note"),)),
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
        TableNode(
            (TableCell(()), *_cells("c1", "c2", "c3", "c4")),
            (
                TableRow(
                    (
                        TableCell((Plain("r1"),)),
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
        TableNode(
            (
                TableCell((Plain("Lane"),)),
                TableCell(
                    (
                        Plain("Plan"),
                        Break(),
                        *italic(plain("wk 1")),
                        Break(),
                        Plain("Q1"),
                        Plain(" "),
                        Plain("(5)"),
                    )
                ),
                TableCell((Plain("Ship"),)),
            ),
            (
                TableRow(
                    (
                        TableCell((Plain("Ops"), Plain(" "), Plain("(5)"))),
                        TableCell(
                            (
                                SwimlaneMark("done"),
                                Plain(" "),
                                *bold("1"),
                                Plain(" "),
                                Plain("Draft"),
                                Plain(" "),
                                Plain("(2)"),
                            )
                        ),
                        TableCell(
                            (
                                SwimlaneMark("blocked"),
                                Plain(" "),
                                *bold("2"),
                                Plain(" "),
                                Plain("Send"),
                                Plain(" "),
                                Plain("(3)"),
                            )
                        ),
                    )
                ),
                TableRow(_cells("Total", "2", "3"), emphasis="total"),
            ),
            header_column=True,
        ),
        Paragraph(
            (
                SwimlaneMark("done"),
                Plain(" "),
                Plain("done"),
                Plain(" · "),
                SwimlaneMark("blocked"),
                Plain(" "),
                Plain("blocked"),
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
        TableNode(
            (
                TableCell((Plain("Lane"),)),
                TableCell((Plain("Plan"), Break(), Plain("A"), Plain(", "), Plain("B"))),
            ),
            (
                TableRow(
                    (
                        TableCell((Plain("Ops"),)),
                        TableCell(
                            (
                                *bold("1"),
                                Plain(" "),
                                Plain("Draft"),
                                Plain(", A"),
                                Break(),
                                *bold("1"),
                                Plain(" "),
                                Plain("Redraft"),
                                Plain(", A"),
                                Break(),
                                SwimlaneMark("deferred"),
                                Plain(" "),
                                Link((Plain("2"),), "https://e.com/2"),
                                Plain(" "),
                                Plain("Send"),
                                Plain(", B"),
                                Plain(" "),
                                *italic(plain("needs 1")),
                            )
                        ),
                    )
                ),
            ),
            header_column=True,
        ),
        Paragraph((SwimlaneMark("deferred"), Plain(" "), Plain("deferred")), "muted"),
    )


@pytest.mark.parametrize(
    ("states", "legend"),
    [
        pytest.param(["done", None], ("done",), id="one-marked-state-beside-unmarked-steps-is-explained"),
        pytest.param(["done", "done"], (), id="one-state-on-every-step-needs-no-legend"),
        pytest.param([None, None], (), id="no-marks-no-legend"),
    ],
)
def test_the_export_legend_explains_every_glyph_that_differs_from_its_neighbours(
    states: list[SwimlaneStepState | None], legend: tuple[SwimlaneStepState, ...]
) -> None:
    steps = [
        {"lane": "Ops", "col": "Plan", "n": str(index), "label": "s", **({"state": state} if state else {})}
        for index, state in enumerate(states)
    ]
    swimlane = {"type": "swimlane", "lanes": ["Ops"], "columns": [{"name": "Plan"}], "steps": steps}

    nodes = lowered([swimlane])

    expected = (
        (
            Paragraph(
                spaced([spaced([(SwimlaneMark(state),), plain(state)]) for state in legend], " · "), "muted"
            ),
        )
        if legend
        else ()
    )
    assert nodes[1:] == expected


def test_a_swimlane_step_with_no_state_has_no_glyph_and_an_explicit_todo_keeps_its_own() -> None:
    swimlane = {
        "type": "swimlane",
        "lanes": ["Ops"],
        "columns": [{"name": "Plan"}],
        "steps": [
            {"lane": "Ops", "col": "Plan", "n": "1", "label": "Unset"},
            {"lane": "Ops", "col": "Plan", "n": "2", "label": "Planned", "state": "todo"},
            {"lane": "Ops", "col": "Plan", "n": "3", "label": "Shipped", "state": "done"},
        ],
    }

    table, legend = lowered([swimlane])

    assert isinstance(table, TableNode)
    assert table.rows[0].cells[1] == TableCell(
        (
            *bold("1"),
            Plain(" "),
            Plain("Unset"),
            Break(),
            SwimlaneMark("todo"),
            Plain(" "),
            *bold("2"),
            Plain(" "),
            Plain("Planned"),
            Break(),
            SwimlaneMark("done"),
            Plain(" "),
            *bold("3"),
            Plain(" "),
            Plain("Shipped"),
        )
    )
    assert legend == Paragraph(
        (
            SwimlaneMark("done"),
            Plain(" "),
            Plain("done"),
            Plain(" · "),
            SwimlaneMark("todo"),
            Plain(" "),
            Plain("todo"),
        ),
        "muted",
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
        TableNode(
            _cells("Issue", "Units"),
            (
                TableRow(
                    (TableCell((Plain("Ours"), Plain(" "), Plain("(2)"))), TableCell(())), emphasis="group"
                ),
                TableRow(
                    (
                        TableCell((Plain("x"), Break(), Plain("of which "), Code("y"), Plain(": 1"))),
                        TableCell((Plain("2"),)),
                    )
                ),
                TableRow(
                    (TableCell((Plain("Theirs"), Plain(" "), Plain("(0)"))), TableCell(())), emphasis="group"
                ),
                TableRow((TableCell(italic(plain("none"))), TableCell(()))),
                TableRow(_cells("Total", "2"), emphasis="total"),
            ),
            columns=(TableColumn(), TableColumn(share=0.1)),
        ),
    )


def test_a_totals_row_puts_its_label_in_the_first_cell_that_is_not_the_total() -> None:
    table = {
        "type": "table",
        "columns": [{"key": "n", "label": "Units", "kind": "number"}, {"key": "a", "label": "Issue"}],
        "totals": {"column": "n"},
        "rows": [{"n": 2, "a": "x"}, {"n": 3, "a": "y"}],
    }

    assert lowered([table]) == (
        TableNode(
            _cells("Units", "Issue"),
            (
                TableRow((TableCell((Plain("2"),)), TableCell((Plain("x"),)))),
                TableRow((TableCell((Plain("3"),)), TableCell((Plain("y"),)))),
                TableRow(_cells("5", "Total"), emphasis="total"),
            ),
            columns=(TableColumn(share=0.1), TableColumn()),
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
        TableNode(
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
        TableNode(
            _cells("Issue", "Risk", "Units"),
            (
                TableRow(
                    (
                        TableCell((Plain("x"), Plain(" "), Chip("api", "blue"))),
                        TableCell((IndicatorMark("warning"),), "warning"),
                        TableCell((Plain("2"), Plain(" "), Plain("(20.0% of total)"))),
                    ),
                    "danger",
                ),
            ),
            columns=(TableColumn(), TableColumn(share=0.07), TableColumn(share=0.1)),
        ),
        Paragraph((*bold("Owners"), Plain(": "), Chip("api", "blue"), Plain(" "), Plain("1"))),
        Paragraph((Plain("Reconciles: 2 + 8 clean = 10."),), "muted"),
        Paragraph((Plain("Reconciles: 2 + 8 clean = 10."),), "muted"),
    )


@pytest.mark.parametrize(
    ("tag", "chips", "tone"),
    [
        pytest.param("API", (Chip("api", "blue"),), "info", id="one-key"),
    ],
)
def test_a_tinted_table_row_takes_the_tone_of_its_badge_key(
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
        TableNode(_cells("A", ""), (TableRow((TableCell((Plain("x"),)), TableCell(chips)), tone),)),
    )


@pytest.mark.parametrize(
    ("columns", "table_columns"),
    [
        pytest.param(
            [{"key": "a", "label": "A", "width": 2}, {"key": "b", "label": "B", "tone": "green", "width": 4}],
            (TableColumn(share=2 / 6), TableColumn("success", 4 / 6)),
            id="tones-and-widths",
        ),
        pytest.param(
            [{"key": "a", "label": "A"}, {"key": "b", "label": "B", "tone": "warning"}],
            (TableColumn(), TableColumn("warning")),
            id="a-tone-alone",
        ),
        pytest.param([{"key": "a", "label": "A"}, {"key": "b", "label": "B"}], (), id="neither"),
    ],
)
def test_a_table_keeps_its_column_tones_and_widths_in_the_order_of_its_cells(
    columns: list[dict[str, Any]], table_columns: tuple[TableColumn, ...]
) -> None:
    table = make_table(
        [*columns, {"key": "t", "label": "", "kind": "badge"}], rows=[{"a": "x", "b": "y", "t": ""}]
    )

    assert lowered([table]) == (
        TableNode(_cells("A", "B"), (TableRow(_cells("x", "y")),), columns=table_columns),
    )


def test_a_number_column_carries_its_default_width_share_beside_an_auto_column() -> None:
    table = make_table(
        [{"key": "a", "label": "A"}, {"key": "b", "label": "B", "kind": "number"}], rows=[{"a": "x", "b": 10}]
    )

    assert lowered([table]) == (
        TableNode(
            _cells("A", "B"), (TableRow(_cells("x", "10")),), columns=(TableColumn(), TableColumn(share=0.1))
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
                GridColumn(25, (Callout("info", (Paragraph((Plain("a"),)),)),)),
                GridColumn(75, (Paragraph((Plain("b"),)),)),
            )
        ),
        Paragraph((Plain("c"),)),
    )


@pytest.mark.parametrize(
    ("spans", "ratios"),
    [
        pytest.param((2, 2, 2), (34, 33, 33), id="three-equal-cells-give-the-one-left-over-to-the-first"),
        pytest.param((1,) * 6, (17, 17, 17, 17, 16, 16), id="six-equal-cells-spread-the-four-left-over"),
        pytest.param(
            (1, 1, 1, 3), (17, 17, 16, 50), id="unequal-cells-give-the-left-over-to-the-largest-remainders"
        ),
    ],
)
def test_grid_cells_get_largest_remainder_ratios_that_add_up_to_a_hundred(
    spans: tuple[int, ...], ratios: tuple[int, ...]
) -> None:
    bodies = "abcdef"[: len(spans)]
    grid = {
        "type": "grid",
        "cells": [
            {"span": span, "blocks": [{"type": "text", "body": body}]}
            for span, body in zip(spans, bodies, strict=True)
        ],
    }

    assert lowered([grid]) == (
        Columns(
            tuple(
                GridColumn(ratio, (Paragraph((Plain(body),)),))
                for ratio, body in zip(ratios, bodies, strict=True)
            )
        ),
    )


def test_a_grid_inside_a_grid_cell_lays_its_cells_one_after_another() -> None:
    inner = {
        "type": "grid",
        "cells": [{"span": 3, "blocks": [{"type": "text", "body": body}]} for body in "bc"],
    }
    grid = {
        "type": "grid",
        "cells": [{"span": 2, "blocks": [{"type": "text", "body": "a"}]}, {"span": 4, "blocks": [inner]}],
    }

    assert lowered([grid]) == (
        Columns(
            (
                GridColumn(33, (Paragraph((Plain("a"),)),)),
                GridColumn(67, (Paragraph((Plain("b"),)), Paragraph((Plain("c"),)))),
            )
        ),
    )


def test_a_toned_one_cell_grid_becomes_its_callout() -> None:
    grid = make_grid([{**make_cell(6, [{"type": "text", "body": "a"}]), "tone": "warning"}])

    assert lowered([grid]) == (Callout("warning", (Paragraph((Plain("a"),)),)),)


def test_a_toned_cell_of_an_inner_grid_becomes_a_callout_inside_the_outer_column() -> None:
    inner = make_grid(
        [
            {**make_cell(3, [{"type": "text", "body": "b"}]), "tone": "danger"},
            make_cell(3, [{"type": "text", "body": "c"}]),
        ]
    )
    grid = make_grid([make_cell(2, [{"type": "text", "body": "a"}]), make_cell(4, [inner])])

    assert lowered([grid]) == (
        Columns(
            (
                GridColumn(33, (Paragraph((Plain("a"),)),)),
                GridColumn(67, (Callout("danger", (Paragraph((Plain("b"),)),)), Paragraph((Plain("c"),)))),
            )
        ),
    )


def test_a_blank_indicator_cell_is_empty_and_untoned() -> None:
    table = make_table(
        [{"key": "a", "label": "Issue"}, {"key": "risk", "label": "Risk", "kind": "indicator"}],
        rows=[{"a": "x", "risk": " "}],
    )

    assert lowered([table]) == (
        TableNode(
            _cells("Issue", "Risk"),
            (TableRow(_cells("x", "")),),
            columns=(TableColumn(), TableColumn(share=0.07)),
        ),
    )


def test_a_rollup_without_a_label_is_its_counts_alone() -> None:
    table = make_table(
        [{"key": "a", "label": "Issue"}, {"key": "tag", "label": "", "kind": "badge", "placement": "cell"}],
        rollup={"by": "tag"},
        rows=[{"a": "x", "tag": "API"}],
    )

    assert lowered([table], badges=API_BADGES) == (
        API_LEGEND,
        TableNode(
            _cells("Issue", ""), (TableRow((TableCell((Plain("x"),)), TableCell((Chip("api", "blue"),)))),)
        ),
        Paragraph((Chip("api", "blue"), Plain(" "), Plain("1"))),
    )


def test_a_grouped_table_with_nothing_to_sum_labels_each_group_by_name_alone() -> None:
    table = make_table(
        [{"key": "a", "label": "Issue"}, {"key": "n", "label": "Units", "kind": "number"}],
        groups=[{"name": "Ours", "rows": [{"a": "x", "n": 2}]}],
    )

    assert lowered([table]) == (
        TableNode(
            _cells("Issue", "Units"),
            (
                TableRow(_cells("Ours", ""), emphasis="group"),
                TableRow(_cells("x", "2")),
            ),
            columns=(TableColumn(), TableColumn(share=0.1)),
        ),
    )
