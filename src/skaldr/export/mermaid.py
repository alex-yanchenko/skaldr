import json
from collections.abc import Mapping
from decimal import Decimal
from typing import Final, NamedTuple, NoReturn

from typing_extensions import assert_never

from skaldr.charts import chart_light_colour
from skaldr.errors import ExportInvariantError
from skaldr.export.capabilities import character_without_a_unicode_form, in_unicode_script_form
from skaldr.export.glyphs import mark_glyph
from skaldr.export.inline import one_line
from skaldr.export.runs import (
    Chip,
    ExportRich,
    ExportRun,
    ExportVisibleText,
    IndicatorMark,
    every_run_within,
    write_export_runs,
)
from skaldr.export.swaps import mermaid_cannot_draw
from skaldr.export.tree import Figure, Graph, GraphNode, PieChart, ToneName, XYChart
from skaldr.models import BADGE_COLOR_TONE
from skaldr.richtext import (
    AnchorLink,
    Citation,
    DocumentLink,
    InlineMath,
    IssueLink,
    Link,
    ScriptPosition,
    ScriptText,
    Styled,
    StyleName,
)

RUNS_A_DIAGRAM_LABEL_CANNOT_HOLD: Final[tuple[type[ExportRun], ...]] = (
    Link,
    AnchorLink,
    IssueLink,
    DocumentLink,
    Citation,
    InlineMath,
)
POINT_MARKER: Final = "• "
PIE_COLOUR_COUNT: Final = 12


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

    def styled(self, style: StyleName, inner: str, /) -> str:
        if style == "strike":
            _no_label_form_for("struck-through text")
        return inner

    def chip(self, run: Chip, /) -> str:
        return f"{mark_glyph(IndicatorMark(BADGE_COLOR_TONE[run.tone]))} {run.label}"


def _a_diagram_label_cannot_hold(run: ExportRun) -> bool:
    match run:
        case ScriptText():
            return character_without_a_unicode_form(run.position, run.text) is not None
        case Styled():
            return run.style == "strike"
        case _:
            return isinstance(run, RUNS_A_DIAGRAM_LABEL_CANNOT_HOLD)


def loses_meaning_in_a_diagram_label(runs: ExportRich) -> bool:
    return any(map(_a_diagram_label_cannot_hold, every_run_within(runs)))


def step_details_fit_their_labels(graph: Graph) -> bool:
    return not any(loses_meaning_in_a_diagram_label(point) for node in graph.nodes for point in node.points)


def step_has_details(node: GraphNode) -> bool:
    return bool(node.points or node.badges)


def _detail_lines(node: GraphNode) -> list[str]:
    points = [POINT_MARKER + write_export_runs(point, _LabelText()) for point in node.points]
    return [*points, write_export_runs(node.badges, _LabelText())] if node.badges else points


def _node_line(node: GraphNode, *, with_details: bool) -> str:
    note = write_export_runs(node.note, _LabelText())
    details = _detail_lines(node) if with_details else []
    lines = [node.label, *([note] if note else []), *details]
    label = "<br>".join(_mermaid_text(line) for line in lines)
    tone_class = f":::{node.tone}" if node.tone else ""
    return f'    {node.key}["{label}"]{tone_class}'


def _class_line(tone: ToneName) -> str:
    colors = MERMAID_FILL[tone]
    return f"    classDef {tone} fill:{colors.fill},stroke:{colors.stroke},color:{MERMAID_TEXT}"


def _graph_lines(graph: Graph, *, with_details: bool) -> list[str]:
    lines = [
        f"flowchart {graph.direction}",
        *(_node_line(node, with_details=with_details) for node in graph.nodes),
    ]
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


def _init_line(theme_variables: Mapping[str, object]) -> str:
    return "%%{init: " + json.dumps({"theme": "base", "themeVariables": theme_variables}) + "}%%"


def _pie_init_line(chart: PieChart) -> str:
    coloured = enumerate(chart.slices[:PIE_COLOUR_COUNT], start=1)
    return _init_line(
        {f"pie{number}": chart_light_colour(item.tone, number - 1) for number, item in coloured}
    )


def _xy_init_line(chart: XYChart) -> str:
    tones = chart.series_tones or (None,) * len(chart.series)
    palette = ", ".join(chart_light_colour(tone, index) for index, tone in enumerate(tones))
    return _init_line({"xyChart": {"plotColorPalette": palette}})


def _mermaid_lines(figure: Figure, *, with_step_details: bool, with_page_palette: bool) -> list[str]:
    match figure:
        case Graph():
            return _graph_lines(figure, with_details=with_step_details)
        case PieChart():
            slices = (
                f"    {_quoted_string(item.label)} : {_mermaid_number(item.value)}" for item in figure.slices
            )
            return [*([_pie_init_line(figure)] if with_page_palette else []), "pie", *slices]
        case XYChart():
            return [*([_xy_init_line(figure)] if with_page_palette else []), *_xy_lines(figure)]
        case _:
            assert_never(figure)


def mermaid_fence_lines(
    figure: Figure, *, with_step_details: bool = False, with_page_palette: bool = False
) -> list[str]:
    lines = _mermaid_lines(figure, with_step_details=with_step_details, with_page_palette=with_page_palette)
    return ["```mermaid", *lines, "```"]
