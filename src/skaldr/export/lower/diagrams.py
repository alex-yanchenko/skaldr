from collections.abc import Sequence
from itertools import pairwise
from typing import Final

from typing_extensions import assert_never

from skaldr import compute
from skaldr.charts import chart_legend, donut_total
from skaldr.export.inline import bold, one_line
from skaldr.export.lower.context import Lowering, bullets, plain_cells, spaced, with_bold_label
from skaldr.export.tree import (
    Diagram,
    Graph,
    GraphEdge,
    GraphNode,
    ListEntry,
    Node,
    Paragraph,
    PieChart,
    PieSlice,
    TableNode,
    TableRow,
    XYChart,
)
from skaldr.models import Chart, Fan, Flow, FlowStep
from skaldr.richtext import (
    AnchorLink,
    Citation,
    Code,
    Link,
    Placeholder,
    Plain,
    Run,
    ScriptText,
    Styled,
    Tinted,
    visible_text,
)

SERIES_COLUMN: Final = "Series"
DONUT_COLUMNS: Final = ("Slice", "Value", "Share")
TOTAL_LABEL: Final = "Total"


def _graph_node(key: str, step: FlowStep, lowering: Lowering, prefix: str = "") -> GraphNode:
    note = visible_text(lowering.rich(step.note)) if step.note else ""
    return GraphNode(key, one_line(prefix + step.label), note, step.tone)


def _step_entry(step: FlowStep, lowering: Lowering) -> ListEntry:
    text = with_bold_label(step.label, lowering.rich(step.note)) if step.note else bold(step.label)
    if step.badges:
        text = spaced([text, lowering.chips(step.badges)])
    children: tuple[Node, ...] = ()
    if step.points:
        children = (bullets(ListEntry(lowering.rich(point)) for point in step.points),)
    return ListEntry(text, children=children)


def _links_somewhere(run: Run) -> bool:
    match run:
        case Link() | AnchorLink() | Citation():
            return True
        case Styled() | Tinted():
            return any(map(_links_somewhere, run.runs))
        case Plain() | Code() | Placeholder() | ScriptText():
            return False
        case _:
            assert_never(run)


def _diagram_cannot_show_all_of(step: FlowStep, lowering: Lowering) -> bool:
    note_links = any(map(_links_somewhere, lowering.rich(step.note))) if step.note else False
    return bool(step.points or step.badges) or note_links


def _supplement(steps: Sequence[FlowStep], lowering: Lowering) -> tuple[Node, ...]:
    detailed = [step for step in steps if _diagram_cannot_show_all_of(step, lowering)]
    return (bullets(_step_entry(step, lowering) for step in detailed),) if detailed else ()


def lower_flow(block: Flow, lowering: Lowering) -> list[Node]:
    nodes = tuple(
        _graph_node(f"s{index}", step, lowering, f"{index}: " if block.numbered else "")
        for index, step in enumerate(block.steps, start=1)
    )
    keys = [node.key for node in nodes]
    edges = [GraphEdge(source, target) for source, target in pairwise(keys)]
    if block.loop:
        edges.append(GraphEdge(keys[-1], keys[0], dashed=True))
    graph = Graph("TB" if block.style == "steps" else "LR", nodes, tuple(edges))
    return [Diagram(graph, _supplement(block.steps, lowering))]


def lower_fan(block: Fan, lowering: Lowering) -> list[Node]:
    spokes = tuple(
        _graph_node(f"s{index}", spoke, lowering) for index, spoke in enumerate(block.spokes, start=1)
    )
    edges = tuple(
        GraphEdge(spoke.key, "hub") if block.direction == "in" else GraphEdge("hub", spoke.key)
        for spoke in spokes
    )
    graph = Graph("LR", (_graph_node("hub", block.hub, lowering), *spokes), edges)
    return [Diagram(graph, _supplement([block.hub, *block.spokes], lowering))]


def _donut_table(block: Chart) -> TableNode:
    rows = tuple(
        TableRow(plain_cells(item.label, compute.fmt(item.value), legend["note"] or ""), item.tone)
        for item, legend in zip(block.slices, chart_legend(block), strict=True)
    )
    total = TableRow(plain_cells(TOTAL_LABEL, compute.fmt(donut_total(block)), ""), emphasis="total")
    return TableNode(plain_cells(*DONUT_COLUMNS), (*rows, total))


def _mermaid_cannot_label_its_series(block: Chart) -> bool:
    return block.stacked or len(block.series) > 1


def lower_chart(block: Chart) -> list[Node]:
    title: list[Node] = [Paragraph(bold(block.title))] if block.title else []
    if block.variant == "donut":
        pie = PieChart(tuple(PieSlice(item.label, item.value) for item in block.slices))
        return [*title, Diagram(pie, (_donut_table(block),))]
    table = TableNode(
        plain_cells(SERIES_COLUMN, *block.categories),
        tuple(
            TableRow(plain_cells(series.label, *map(compute.fmt, series.values)), series.tone)
            for series in block.series
        ),
    )
    if _mermaid_cannot_label_its_series(block):
        return [*title, table]
    chart = XYChart(
        "bar" if block.variant == "bar" else "line",
        tuple(block.categories),
        tuple(tuple(series.values) for series in block.series),
    )
    return [*title, Diagram(chart, (table,))]
