from skaldr.export.mermaid import mermaid_source
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


def test_a_pie_and_an_xy_chart_quote_their_labels() -> None:
    pie = PieChart((PieSlice('a "b"', 3), PieSlice("c", 1.5)))
    chart = XYChart("bar", ('Q "1"', "Q2"), ((1, 2), (3, 4)))

    assert (mermaid_source(pie).splitlines(), mermaid_source(chart).splitlines()) == (
        ["pie", "    \"a 'b'\" : 3", '    "c" : 1.5'],
        ["xychart-beta", '    x-axis ["Q \'1\'", "Q2"]', "    bar [1, 2]", "    bar [3, 4]"],
    )
