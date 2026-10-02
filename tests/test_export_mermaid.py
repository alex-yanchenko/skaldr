from typing import get_args

import pytest

from skaldr.export.mermaid import MERMAID_FILL, mermaid_fence_lines
from skaldr.export.tree import Graph, GraphEdge, GraphNode, PieChart, PieSlice, ToneName, XYChart


def test_a_graph_writes_its_nodes_edges_and_one_class_per_tone_used() -> None:
    graph = Graph(
        "TB",
        (
            GraphNode("s1", 'Say "hi"', "then\nstop", "warning"),
            GraphNode("s2", "Fix", tone="info"),
            GraphNode("s3", "Plain"),
        ),
        (GraphEdge("s1", "s2"), GraphEdge("s3", "s1", dashed=True)),
    )

    assert mermaid_fence_lines(graph) == [
        "```mermaid",
        "flowchart TB",
        '    s1["Say #quot;hi#quot;<br>then stop"]:::warning',
        '    s2["Fix"]:::info',
        '    s3["Plain"]',
        "    s1 --> s2",
        "    s3 -.-> s1",
        "    classDef info fill:#e8f0fe,stroke:#1a73e8,color:#1f2328",
        "    classDef warning fill:#fef7e0,stroke:#b06000,color:#1f2328",
        "```",
    ]


@pytest.mark.parametrize(
    ("tone", "colors"),
    [
        pytest.param("success", "fill:#e6f4ea,stroke:#1e8e3e", id="success"),
        pytest.param("info", "fill:#e8f0fe,stroke:#1a73e8", id="info"),
        pytest.param("warning", "fill:#fef7e0,stroke:#b06000", id="warning"),
        pytest.param("danger", "fill:#fce8e6,stroke:#c5221f", id="danger"),
        pytest.param("accent", "fill:#f3e8fd,stroke:#8430ce", id="accent"),
        pytest.param("teal", "fill:#e4f7f6,stroke:#00796b", id="teal"),
        pytest.param("sky", "fill:#e1f5fe,stroke:#0277bd", id="sky"),
        pytest.param("neutral", "fill:#f1f3f4,stroke:#5f6368", id="neutral"),
        pytest.param("muted", "fill:#f1f3f4,stroke:#5f6368", id="muted"),
    ],
)
def test_every_tone_has_a_node_class(tone: ToneName, colors: str) -> None:
    graph = Graph("LR", (GraphNode("s1", "x", tone=tone),), ())

    assert mermaid_fence_lines(graph) == [
        "```mermaid",
        "flowchart LR",
        f'    s1["x"]:::{tone}',
        f"    classDef {tone} {colors},color:#1f2328",
        "```",
    ]


def test_every_tone_has_a_mermaid_fill() -> None:
    assert sorted(MERMAID_FILL) == sorted(get_args(ToneName))


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
    graph = Graph("LR", (GraphNode("s1", label),), ())

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
    chart = XYChart("line", ('Q "1"', "Q2"), ((1, 2.5), (1e16, 4)))

    assert mermaid_fence_lines(chart) == [
        "```mermaid",
        "xychart-beta",
        '    x-axis ["Q #quot;1#quot;", "Q2"]',
        "    line [1, 2.5]",
        "    line [10000000000000000, 4]",
        "```",
    ]


def test_an_xy_chart_writes_zero_and_negative_zero_without_a_sign() -> None:
    chart = XYChart("bar", ("Q1", "Q2", "Q3"), ((0, 0.0, -0.0),))

    assert mermaid_fence_lines(chart) == [
        "```mermaid",
        "xychart-beta",
        '    x-axis ["Q1", "Q2", "Q3"]',
        "    bar [0, 0.0, 0.0]",
        "```",
    ]
