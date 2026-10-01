from collections.abc import Sequence
from itertools import pairwise

from skaldr import compute
from skaldr.export.inline import bold, labelled, one_line, plain
from skaldr.export.lower.context import Lowering, bullets, cells
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
    Table,
    TableRow,
    XYChart,
)
from skaldr.models import Chart, Fan, Flow, FlowStep
from skaldr.richtext import visible_text


def _graph_node(key: str, step: FlowStep, lowering: Lowering, prefix: str = "") -> GraphNode:
    note = visible_text(lowering.rich(step.note)) if step.note else ""
    return GraphNode(key, one_line(prefix + step.label), note, step.tone)


def _step_entry(step: FlowStep, lowering: Lowering) -> ListEntry:
    text = labelled(step.label) + lowering.rich(step.note) if step.note else bold(step.label)
    if step.badges:
        text += plain(" ") + lowering.chips(step.badges)
    children: tuple[Node, ...] = ()
    if step.points:
        children = (bullets(ListEntry(lowering.rich(point)) for point in step.points),)
    return ListEntry(text, children=children)


def _supplement(steps: Sequence[FlowStep], lowering: Lowering) -> tuple[Node, ...]:
    detailed = [step for step in steps if step.points or step.badges]
    return (bullets(_step_entry(step, lowering) for step in detailed),) if detailed else ()


def lower_flow(block: Flow, lowering: Lowering) -> list[Node]:
    keys = [f"s{index}" for index in range(1, len(block.steps) + 1)]
    nodes = tuple(
        _graph_node(key, step, lowering, f"{index}: " if block.numbered else "")
        for index, (key, step) in enumerate(zip(keys, block.steps, strict=True), start=1)
    )
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


def lower_chart(block: Chart) -> list[Node]:
    title: list[Node] = [Paragraph(bold(block.title))] if block.title else []
    if block.variant == "donut":
        return [*title, Diagram(PieChart(tuple(PieSlice(item.label, item.value) for item in block.slices)))]
    table = Table(
        cells("Series", *block.categories),
        tuple(TableRow(cells(series.label, *map(compute.fmt, series.values))) for series in block.series),
    )
    if block.stacked:
        return [*title, table]
    chart = XYChart(
        "bar" if block.variant == "bar" else "line",
        tuple(block.categories),
        tuple(tuple(series.values) for series in block.series),
    )
    return [*title, Diagram(chart, (table,) if len(block.series) > 1 else ())]
