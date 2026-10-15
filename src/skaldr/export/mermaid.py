from collections.abc import Mapping
from decimal import Decimal
from typing import Final, NamedTuple, NoReturn

from typing_extensions import assert_never

from skaldr.errors import ExportInvariantError
from skaldr.export.capabilities import in_unicode_script_form
from skaldr.export.inline import one_line
from skaldr.export.runs import ExportVisibleText, write_export_runs
from skaldr.export.swaps import mermaid_cannot_draw
from skaldr.export.tree import Figure, Graph, GraphNode, PieChart, ToneName, XYChart
from skaldr.richtext import Citation, ScriptPosition


class NodeColors(NamedTuple):
    fill: str
    stroke: str


MERMAID_FILL: Final[Mapping[ToneName, NodeColors]] = {
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
MERMAID_TEXT: Final = "#1f2328"
MERMAID_ENTITY: Final[Mapping[str, str]] = {
    "#": "#35;",
    "&": "#38;",
    '"': "#quot;",
    "%": "#37;",
    "<": "#lt;",
    ">": "#gt;",
    "`": "#96;",
}
MERMAID_ESCAPES: Final = str.maketrans(MERMAID_ENTITY)


def _mermaid_text(text: str) -> str:
    return one_line(text).translate(MERMAID_ESCAPES)


def _quoted_string(text: str) -> str:
    return f'"{_mermaid_text(text)}"'


def _without_negative_zero(value: float) -> float:
    return abs(value) if value == 0 else value


def _mermaid_number(value: float) -> str:
    return format(Decimal(repr(_without_negative_zero(value))), "f")


def _no_label_form_for(what: str) -> NoReturn:
    raise ExportInvariantError(
        f"a Mermaid label has no form for {what}; the export check should have refused it"
    )


class _LabelText(ExportVisibleText):
    def script(self, position: ScriptPosition, text: str, /) -> str:
        return in_unicode_script_form(position, text, "a Mermaid label")

    def link(self, _label: str, _url: str, /) -> NoReturn:
        _no_label_form_for("a link")

    def anchor_link(self, _label: str, _anchor: str, /) -> NoReturn:
        _no_label_form_for("a link to a heading")

    def issue_link(self, _label: str, _key: str, _url: str | None, /) -> NoReturn:
        _no_label_form_for("an issue link")

    def document_link(self, _label: str, _doc_id: str, _section: str | None, /) -> NoReturn:
        _no_label_form_for("a document link")

    def citation(self, _run: Citation, /) -> NoReturn:
        _no_label_form_for("a citation")

    def math(self, _expression: str, /) -> NoReturn:
        _no_label_form_for("math")


def _node_line(node: GraphNode) -> str:
    note = write_export_runs(node.note, _LabelText())
    label = _mermaid_text(node.label) + (f"<br>{_mermaid_text(note)}" if note else "")
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
    if mermaid_cannot_draw(chart):
        raise ExportInvariantError(
            "a Mermaid xy chart cannot tell several series apart; "
            "the export should have written its data table"
        )
    axis = "    x-axis [" + ", ".join(_quoted_string(category) for category in chart.categories) + "]"
    marks = [f"    {chart.mark} [" + ", ".join(map(_mermaid_number, values)) + "]" for values in chart.series]
    return ["xychart-beta", axis, *marks]


def _mermaid_lines(figure: Figure) -> list[str]:
    match figure:
        case Graph():
            return _graph_lines(figure)
        case PieChart():
            slices = (
                f"    {_quoted_string(item.label)} : {_mermaid_number(item.value)}" for item in figure.slices
            )
            return ["pie", *slices]
        case XYChart():
            return _xy_lines(figure)
        case _:
            assert_never(figure)


def mermaid_fence_lines(figure: Figure) -> list[str]:
    return ["```mermaid", *_mermaid_lines(figure), "```"]
