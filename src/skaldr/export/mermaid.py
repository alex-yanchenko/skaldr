from typing_extensions import assert_never

from skaldr.export.tree import Figure, Graph, GraphNode, PieChart, ToneName, XYChart

MERMAID_FILL: dict[ToneName, tuple[str, str]] = {
    "success": ("#e6f4ea", "#1e8e3e"),
    "info": ("#e8f0fe", "#1a73e8"),
    "warning": ("#fef7e0", "#b06000"),
    "danger": ("#fce8e6", "#c5221f"),
    "accent": ("#f3e8fd", "#8430ce"),
    "teal": ("#e4f7f6", "#00796b"),
    "sky": ("#e1f5fe", "#0277bd"),
    "neutral": ("#f1f3f4", "#5f6368"),
    "muted": ("#f1f3f4", "#5f6368"),
}
MERMAID_TEXT = "#1f2328"


def _label(text: str) -> str:
    return " ".join(text.split()).replace('"', "#quot;")


def _quoted(text: str) -> str:
    return '"' + " ".join(text.split()).replace('"', "'") + '"'


def _node_line(node: GraphNode) -> str:
    label = _label(node.label) + (f"<br>{_label(node.note)}" if node.note else "")
    tone_class = f":::{node.tone}" if node.tone else ""
    return f'    {node.key}["{label}"]{tone_class}'


def _class_line(tone: ToneName) -> str:
    fill, stroke = MERMAID_FILL[tone]
    return f"    classDef {tone} fill:{fill},stroke:{stroke},color:{MERMAID_TEXT}"


def _graph_lines(graph: Graph) -> list[str]:
    lines = [f"flowchart {graph.direction}", *(_node_line(node) for node in graph.nodes)]
    lines += [f"    {edge.source} {'-.->' if edge.dashed else '-->'} {edge.target}" for edge in graph.edges]
    used = {node.tone for node in graph.nodes}
    return [*lines, *(_class_line(tone) for tone in sorted(MERMAID_FILL) if tone in used)]


def _xy_lines(chart: XYChart) -> list[str]:
    axis = "    x-axis [" + ", ".join(_quoted(category) for category in chart.categories) + "]"
    marks = [
        f"    {chart.mark} [" + ", ".join(str(value) for value in values) + "]" for values in chart.series
    ]
    return ["xychart-beta", axis, *marks]


def mermaid_source(figure: Figure) -> str:
    match figure:
        case Graph():
            lines = _graph_lines(figure)
        case PieChart():
            lines = ["pie", *(f"    {_quoted(item.label)} : {item.value}" for item in figure.slices)]
        case XYChart():
            lines = _xy_lines(figure)
        case _:
            assert_never(figure)
    return "\n".join(lines)


def mermaid_fence_lines(figure: Figure) -> list[str]:
    return ["```mermaid", *mermaid_source(figure).split("\n"), "```"]
