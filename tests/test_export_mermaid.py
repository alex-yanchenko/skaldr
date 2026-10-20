import re
from collections.abc import Iterator
from typing import get_args

import pytest

from skaldr import charts
from skaldr.charts import chart_light_colour, tone_light_colours
from skaldr.errors import ExportInvariantError
from skaldr.export.mermaid import mermaid_fence_lines
from skaldr.export.tree import Graph, GraphEdge, GraphNode, PieChart, PieSlice, ToneName, XYChart
from skaldr.models import ToneLiteral
from skaldr.richtext import (
    AnchorLink,
    Citation,
    DocumentLink,
    InlineMath,
    IssueLink,
    Link,
    Plain,
    Run,
    Styled,
)
from tests.factories.capability_factory import PIE_TEXT_VARIABLES_JSON

LIGHT_PALETTE: dict[ToneLiteral, tuple[str, str]] = {
    "neutral": ("#f1f5f9", "#475569"),
    "info": ("#eff6ff", "#1d4ed8"),
    "success": ("#ecfdf5", "#15803d"),
    "warning": ("#fef3c7", "#b45309"),
    "danger": ("#fee2e2", "#b91c1c"),
    "accent": ("#f3e8ff", "#7c3aed"),
    "teal": ("#f0fdfa", "#0f766e"),
    "sky": ("#e0f2fe", "#0369a1"),
}


def test_a_graph_writes_its_nodes_edges_and_one_class_per_tone_used() -> None:
    graph = Graph(
        "TB",
        (
            GraphNode("s1", 'Say "hi"', (Plain("then\n"), Styled("bold", (Plain("stop"),))), "warning"),
            GraphNode("s2", "Fix", tone="info"),
            GraphNode("s3", "Plain"),
        ),
        (GraphEdge("s1", "s2"), GraphEdge("s3", "s1", dashed=True)),
        "flow",
    )

    assert mermaid_fence_lines(graph) == [
        "```mermaid",
        "flowchart TB",
        '    s1["Say #quot;hi#quot;<br>then stop"]:::warning',
        '    s2["Fix"]:::info',
        '    s3["Plain"]',
        "    s1 --> s2",
        "    s3 -.-> s1",
        f"    classDef info {_stylesheet_node_colours('info')},color:#1f2328",
        f"    classDef warning {_stylesheet_node_colours('warning')},color:#1f2328",
        "```",
    ]


def _stylesheet_node_colours(tone: ToneName) -> str:
    fill, stroke = tone_light_colours("neutral" if tone == "muted" else tone)
    return f"fill:{fill},stroke:{stroke}"


@pytest.mark.parametrize("tone", get_args(ToneName))
def test_every_tone_has_a_node_class(tone: ToneName) -> None:
    graph = Graph("LR", (GraphNode("s1", "x", tone=tone),), (), "flow")

    assert mermaid_fence_lines(graph) == [
        "```mermaid",
        "flowchart LR",
        f'    s1["x"]:::{tone}',
        f"    classDef {tone} {_stylesheet_node_colours(tone)},color:#1f2328",
        "```",
    ]


@pytest.mark.parametrize("tone", get_args(ToneLiteral))
def test_the_stylesheet_reader_returns_the_pinned_light_palette(tone: ToneLiteral) -> None:
    assert tone_light_colours(tone) == LIGHT_PALETTE[tone]


def test_the_pinned_light_palette_covers_exactly_the_tones() -> None:
    assert sorted(LIGHT_PALETTE) == sorted(get_args(ToneLiteral))


@pytest.fixture
def palette_read_afresh() -> Iterator[None]:
    charts.light_palette.cache_clear()
    yield
    charts.light_palette.cache_clear()


def _stylesheet_with_only_an_info_foreground(_name: str) -> str:
    return "--info-fg:light-dark(#010203,#aaaaaa);"


@pytest.mark.usefixtures("palette_read_afresh")
def test_a_tone_the_stylesheet_has_no_colour_for_stops_the_export_naming_the_tone_and_the_role(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(charts, "package_text", _stylesheet_with_only_an_info_foreground)

    with pytest.raises(
        ExportInvariantError,
        match=re.escape("styles.css declares no light-theme 'bg' colour for the tone 'info'"),
    ):
        tone_light_colours("info")


@pytest.mark.parametrize(
    ("label", "written"),
    [
        pytest.param("GET /bins/<id>", "GET /bins/#lt;id#gt;", id="angle-brackets-are-not-html"),
        pytest.param("Issue #12; done", "Issue #35;12; done", id="hash-is-not-an-entity"),
        pytest.param("%%{init: {}}%% x", "#37;#37;{init: {}}#37;#37; x", id="percent-is-not-a-directive"),
        pytest.param("`api`", "#96;api#96;", id="backticks-are-not-markdown"),
        pytest.param("R&amp;D", "R#38;amp;D", id="ampersand-is-not-an-entity"),
        pytest.param("&lt;id&gt;", "#38;lt;id#38;gt;", id="escaped-angle-brackets-stay-escaped"),
    ],
)
def test_a_node_label_keeps_characters_mermaid_would_read_as_syntax(label: str, written: str) -> None:
    graph = Graph("LR", (GraphNode("s1", label),), (), "flow")

    assert mermaid_fence_lines(graph) == ["```mermaid", "flowchart LR", f'    s1["{written}"]', "```"]


def test_a_pie_quotes_its_labels_and_writes_values_without_an_exponent() -> None:
    pie = PieChart((PieSlice('a "b"', 3), PieSlice("c", 1.5), PieSlice("tiny", 0.00005), PieSlice("none", 0)))

    assert mermaid_fence_lines(pie) == [
        "```mermaid",
        "pie",
        '    "a #quot;b#quot;" : 3',
        '    "c" : 1.5',
        '    "tiny" : 0.00005',
        '    "none" : 0',
        "```",
    ]


def test_an_xy_chart_quotes_its_categories_and_writes_large_values_in_full() -> None:
    chart = XYChart("line", ('Q "1"', "Q2"), ((1e16, 2.5),), stacked=False, series_tones=(None,))

    assert mermaid_fence_lines(chart) == [
        "```mermaid",
        "xychart-beta",
        '    x-axis ["Q #quot;1#quot;", "Q2"]',
        "    line [10000000000000000, 2.5]",
        "```",
    ]


def test_a_stacked_xy_chart_with_one_series_is_drawn_as_an_unstacked_one() -> None:
    chart = XYChart("bar", ("Q1", "Q2"), ((1, 2),), stacked=True, series_tones=(None,))

    assert mermaid_fence_lines(chart) == [
        "```mermaid",
        "xychart-beta",
        '    x-axis ["Q1", "Q2"]',
        "    bar [1, 2]",
        "```",
    ]


@pytest.mark.parametrize(
    ("run", "what"),
    [
        pytest.param(Link((Plain("docs"),), "https://example.com/docs"), "a link", id="link"),
        pytest.param(AnchorLink((Plain("above"),), "plan"), "a link to a heading", id="anchor-link"),
        pytest.param(IssueLink((Plain("SHOP-12"),), "SHOP-12", None), "an issue link", id="issue-link"),
        pytest.param(DocumentLink((Plain("plan"),), "plan", None), "a document link", id="document-link"),
        pytest.param(Citation("audit", 1), "a citation", id="citation"),
        pytest.param(InlineMath("x^2"), "math", id="math"),
        pytest.param(Styled("strike", (Plain("40"),)), "struck-through text", id="strike"),
    ],
)
def test_a_note_holding_a_run_the_check_refuses_in_a_mermaid_label_is_an_internal_error(
    run: Run, what: str
) -> None:
    graph = Graph("TB", (GraphNode("s1", "Scan", (Plain("see "), run)),), (), "flow")

    with pytest.raises(ExportInvariantError) as raised:
        mermaid_fence_lines(graph)

    assert str(raised.value) == (
        f"a Mermaid label has no form for {what}; the export check should have refused it"
    )


@pytest.mark.parametrize("stacked", [False, True])
def test_an_xy_chart_with_several_series_is_an_internal_error_since_the_export_swaps_it(
    stacked: bool,
) -> None:
    chart = XYChart("bar", ("Q1",), ((1,), (2,)), stacked=stacked, series_tones=(None, None))

    with pytest.raises(ExportInvariantError) as raised:
        mermaid_fence_lines(chart)

    assert str(raised.value) == (
        "a Mermaid xy chart cannot tell several series apart; the export should have written its data table"
    )


def test_an_xy_chart_writes_zero_and_negative_zero_without_a_sign() -> None:
    chart = XYChart("bar", ("Q1", "Q2", "Q3"), ((0, 0.0, -0.0),), stacked=False, series_tones=(None,))

    assert mermaid_fence_lines(chart) == [
        "```mermaid",
        "xychart-beta",
        '    x-axis ["Q1", "Q2", "Q3"]',
        "    bar [0, 0.0, 0.0]",
        "```",
    ]


def test_a_pie_with_the_page_palette_writes_each_slice_colour_from_its_tone_or_the_page_cycle() -> None:
    pie = PieChart((PieSlice("a", 3), PieSlice("b", 1, "danger"), PieSlice("c", 2)))

    assert mermaid_fence_lines(pie, with_page_palette=True) == [
        "```mermaid",
        '%%{init: {"theme": "base", "themeVariables": '
        '{"pie1": "#1d4ed8", "pie2": "#b91c1c", "pie3": "#b45309", ' + PIE_TEXT_VARIABLES_JSON + "}}}%%",
        "pie",
        '    "a" : 3',
        '    "b" : 1',
        '    "c" : 2',
        "```",
    ]


def test_a_pie_numbers_its_colours_in_the_order_the_slices_are_written_not_by_value() -> None:
    pie = PieChart(
        (PieSlice("small", 1, "danger"), PieSlice("big", 5, "success"), PieSlice("mid", 3, "info"))
    )

    assert mermaid_fence_lines(pie, with_page_palette=True)[1:6] == [
        '%%{init: {"theme": "base", "themeVariables": '
        '{"pie1": "#b91c1c", "pie2": "#15803d", "pie3": "#1d4ed8", ' + PIE_TEXT_VARIABLES_JSON + "}}}%%",
        "pie",
        '    "small" : 1',
        '    "big" : 5',
        '    "mid" : 3',
    ]


def test_a_pie_colours_at_most_the_twelve_slices_mermaid_has_a_colour_variable_for() -> None:
    pie = PieChart(tuple(PieSlice(f"s{index}", 1) for index in range(14)))
    cycle = ["#1d4ed8", "#15803d", "#b45309", "#b91c1c", "#7c3aed", "#475569"]
    colours = ", ".join(f'"pie{number}": "{cycle[(number - 1) % 6]}"' for number in range(1, 13))

    assert mermaid_fence_lines(pie, with_page_palette=True)[1] == (
        '%%{init: {"theme": "base", "themeVariables": {' + colours + ", " + PIE_TEXT_VARIABLES_JSON + "}}}%%"
    )


@pytest.mark.parametrize("tone", get_args(ToneLiteral))
def test_every_tone_resolves_to_its_light_theme_colour_in_the_page_stylesheet(tone: ToneLiteral) -> None:
    assert chart_light_colour(tone, 0) == LIGHT_PALETTE[tone][1]


def test_a_single_series_xy_chart_with_the_page_palette_writes_the_series_colour() -> None:
    chart = XYChart("bar", ("Q1", "Q2"), ((1, 2),), stacked=False, series_tones=("teal",))

    assert mermaid_fence_lines(chart, with_page_palette=True) == [
        "```mermaid",
        '%%{init: {"theme": "base", "themeVariables": {"xyChart": {"plotColorPalette": "#0f766e"}}}}%%',
        "xychart-beta",
        '    x-axis ["Q1", "Q2"]',
        "    bar [1, 2]",
        "```",
    ]


def test_an_xy_chart_series_with_no_tone_takes_the_first_colour_of_the_page_cycle() -> None:
    chart = XYChart("line", ("Q1",), ((1,),), stacked=False, series_tones=(None,))

    assert mermaid_fence_lines(chart, with_page_palette=True)[1] == (
        '%%{init: {"theme": "base", "themeVariables": {"xyChart": {"plotColorPalette": "#1d4ed8"}}}}%%'
    )


def test_a_flowchart_has_no_init_line_with_the_page_palette() -> None:
    graph = Graph("TB", (GraphNode("s1", "Scan"),), (), "flow")

    assert mermaid_fence_lines(graph, with_page_palette=True) == mermaid_fence_lines(graph)
