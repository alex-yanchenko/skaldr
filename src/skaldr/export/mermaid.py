from typing import NamedTuple

from typing_extensions import assert_never

from skaldr.export.inline import one_line
from skaldr.export.tree import Figure, Graph, GraphNode, PieChart, ToneName, XYChart


class NodeColors(NamedTuple):
    fill: str
    stroke: str


MERMAID_FILL: dict[ToneName, NodeColors] = {
    "success": NodeColors("#e6f4ea", "#1e8e3e"),
    "info": NodeColors("#e8f0fe", "#1a73e8"),
    "warning": NodeColors("#fef7e0", "#b06000"),
    "danger": NodeColors("#fce8e6", "#c5221f"),
    "accent": NodeColors("#f3e8fd", "#8430ce"),
    "teal": NodeColors("#e4f7f6", "#00796b"),
    "sky": NodeColors("#e1f5fe", "#0277bd"),
    "neutral": NodeColors("#f1f3f4", "#5f6368"),
    "muted": NodeColors("#f1f3f4", "#5f6368"),
}
MERMAID_TEXT = "#1f2328"


def _node_label(text: str) -> str:
    return one_line(text).replace('"', "#quot;")


def _quoted_string(text: str) -> str:
    return '"' + one_line(text).replace('"', "'") + '"'


def _node_line(node: GraphNode) -> str:
    label = _node_label(node.label) + (f"<br>{_node_label(node.note)}" if node.note else "")
    tone_class = f":::{node.tone}" if node.tone else ""
    return f'    {node.key}["{label}"]{tone_class}'


def _class_line(tone: ToneName) -> str:
    colors = MERMAID_FILL[tone]
    return f"    classDef {tone} fill:{colors.fill},stroke:{colors.stroke},color:{MERMAID_TEXT}"


def _graph_lines(graph: Graph) -> list[str]:
    lines = [f"flowchart {graph.direction}", *(_node_line(node) for node in graph.nodes)]
    lines += [f"    {edge.source} {'-.->' if edge.dashed else '-->'} {edge.target}" for edge in graph.edges]
    used = {node.tone for node in graph.nodes}
    return [*lines, *(_class_line(tone) for tone in sorted(MERMAID_FILL) if tone in used)]


def _xy_lines(chart: XYChart) -> list[str]:
    axis = "    x-axis [" + ", ".join(_quoted_string(category) for category in chart.categories) + "]"
    marks = [
        f"    {chart.mark} [" + ", ".join(str(value) for value in values) + "]" for values in chart.series
    ]
    return ["xychart-beta", axis, *marks]


def mermaid_source(figure: Figure) -> str:
    match figure:
        case Graph():
            lines = _graph_lines(figure)
        case PieChart():
            lines = ["pie", *(f"    {_quoted_string(item.label)} : {item.value}" for item in figure.slices)]
        case XYChart():
            lines = _xy_lines(figure)
        case _:
            assert_never(figure)
    return "\n".join(lines)


def mermaid_fence_lines(figure: Figure) -> list[str]:
    return ["```mermaid", *mermaid_source(figure).split("\n"), "```"]
