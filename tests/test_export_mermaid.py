import pytest

from skaldr.export.mermaid import mermaid_fence_lines, mermaid_source
from skaldr.export.tree import Graph, GraphEdge, GraphNode, PieChart, PieSlice, XYChart


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

    assert mermaid_source(graph).splitlines() == [
        "flowchart TB",
        '    s1["Say #quot;hi#quot;<br>then stop"]:::warning',
        '    s2["Fix"]:::info',
        '    s3["Plain"]',
        "    s1 --> s2",
        "    s3 -.-> s1",
        "    classDef info fill:#e8f0fe,stroke:#1a73e8,color:#1f2328",
        "    classDef warning fill:#fef7e0,stroke:#b06000,color:#1f2328",
    ]


@pytest.mark.parametrize(
    ("label", "written"),
    [
        pytest.param("GET /bins/<id>", "GET /bins/#lt;id#gt;", id="angle-brackets-are-not-html"),
        pytest.param("Issue #12; done", "Issue #35;12; done", id="hash-is-not-an-entity"),
        pytest.param("%%{init: {}}%% x", "#37;#37;{init: {}}#37;#37; x", id="percent-is-not-a-directive"),
        pytest.param("`api`", "#96;api#96;", id="backticks-are-not-markdown"),
    ],
)
def test_a_node_label_keeps_characters_mermaid_would_read_as_syntax(label: str, written: str) -> None:
    graph = Graph("LR", (GraphNode("s1", label),), ())

    assert mermaid_source(graph).splitlines() == ["flowchart LR", f'    s1["{written}"]']


def test_a_pie_quotes_its_labels_and_writes_values_without_an_exponent() -> None:
    pie = PieChart((PieSlice('a "b"', 3), PieSlice("c", 1.5), PieSlice("tiny", 0.00005)))

    assert mermaid_source(pie).splitlines() == [
        "pie",
        '    "a #quot;b#quot;" : 3',
        '    "c" : 1.5',
        '    "tiny" : 0.00005',
    ]


def test_an_xy_chart_quotes_its_categories_and_writes_large_values_in_full() -> None:
    chart = XYChart("line", ('Q "1"', "Q2"), ((1, 2.5), (1e16, 4)))

    assert mermaid_source(chart).splitlines() == [
        "xychart-beta",
        '    x-axis ["Q #quot;1#quot;", "Q2"]',
        "    line [1, 2.5]",
        "    line [10000000000000000, 4]",
    ]


def test_a_mermaid_fence_wraps_the_source_lines() -> None:
    assert mermaid_fence_lines(PieChart((PieSlice("a", 1),))) == ["```mermaid", "pie", '    "a" : 1', "```"]
