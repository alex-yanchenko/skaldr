from dataclasses import dataclass, field
from typing import Any

import pytest

from skaldr.export.capabilities import RICH_STEP_NOTE, Feature
from skaldr.export.tree import ToneName, XYChartMark
from skaldr.export_targets import EXPORT_TARGETS, ExportTarget
from tests.factories.report_factory import (
    in_a_grid_cell,
    make_report,
    make_request,
    make_section,
    make_tabs,
    make_toggle,
)

TABLE = {"type": "table", "columns": [{"key": "name", "label": "Name"}], "rows": [{"name": "a"}]}
LONG_TABLE = {"type": "table", "columns": [{"key": "name", "label": "Name"}], "rows": [{"name": "v"}] * 300}
LIST_ITEM_WHY = "a Slack canvas list item holds only text and one nested list, so it cannot show {what}"
OUT_OF_THE_LIST = "move it out of the list, after the list"
OUT_OF_THE_STEP = "move it out of the step, after the walkthrough"
PUBLISHED_DOC_ID = "capability-check"


@dataclass(frozen=True)
class RefusedCase:
    target: ExportTarget
    feature: Feature
    blocks: list[dict[str, Any]]
    why: str
    instead: str
    where: str
    also_refused_by: tuple[ExportTarget, ...] = ()

    def rejection(self) -> dict[str, str]:
        return {"target": self.target, "why": self.why, "instead": self.instead, "where": self.where}

    def message(self) -> str:
        return f"{self.why}, {self.where}; {self.instead}"


def in_a_panel(block: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"type": "panel", "title": "Plan", "blocks": [block]}]


def walkthrough_holding(detail: dict[str, Any]) -> dict[str, Any]:
    return {"type": "walkthrough", "steps": [{"label": "Scan", "detail": [detail]}]}


def text_grid() -> dict[str, Any]:
    return {
        "type": "grid",
        "cells": [
            {"span": 3, "blocks": [{"type": "text", "body": "Left"}]},
            {"span": 3, "blocks": [{"type": "text", "body": "Right"}]},
        ],
    }


def published_report(blocks: list[dict[str, Any]], *targets: dict[str, Any]) -> dict[str, Any]:
    return make_report(publish={"doc_id": PUBLISHED_DOC_ID, "targets": list(targets)}, blocks=blocks)


TABLE_IN_A_PANEL = RefusedCase(
    "adf",
    "table inside a callout",
    in_a_panel(TABLE),
    "ADF cannot place a table inside a panel",
    "move the table out of the panel",
    "at blocks.0.panel.blocks.0.table",
    also_refused_by=("slack",),
)
QUOTE_IN_A_PANEL = RefusedCase(
    "adf",
    "quote inside a callout",
    in_a_panel({"type": "quote", "body": "Count twice."}),
    "ADF cannot place a quote inside a panel",
    "move the quote out of the panel",
    "at blocks.0.panel.blocks.0.quote",
)
ADF_REFUSALS: dict[str, RefusedCase] = {
    "adf-table-in-a-panel": TABLE_IN_A_PANEL,
    "adf-callout-in-a-panel": RefusedCase(
        "adf",
        "callout inside a callout",
        in_a_panel({"type": "callout", "tone": "info", "body": "x"}),
        "ADF cannot place a callout inside a panel",
        "move the callout out of the panel",
        "at blocks.0.panel.blocks.0.callout",
        also_refused_by=("slack",),
    ),
    "adf-quote-in-a-panel": QUOTE_IN_A_PANEL,
    "adf-toggle-in-a-panel": RefusedCase(
        "adf",
        "toggle inside a callout",
        in_a_panel(make_toggle()),
        "ADF cannot place a toggle inside a panel",
        "move the toggle out of the panel",
        "at blocks.0.panel.blocks.0.toggle",
        also_refused_by=("slack",),
    ),
    "adf-table-in-a-toggle-in-a-toggle": RefusedCase(
        "adf",
        "table inside a toggle inside a toggle",
        [make_toggle(make_toggle(TABLE))],
        "ADF cannot place a table inside a toggle that is itself inside a toggle",
        "move the table out of the toggle",
        "at blocks.0.toggle.blocks.0.toggle.blocks.0.table",
    ),
    "adf-toggle-in-a-toggle-in-a-toggle": RefusedCase(
        "adf",
        "toggle inside a toggle inside a toggle",
        [make_toggle(make_toggle(make_toggle()))],
        "ADF cannot place a toggle inside a toggle that is itself inside a toggle",
        "move the toggle out of the toggle",
        "at blocks.0.toggle.blocks.0.toggle.blocks.0.toggle",
    ),
}
SLACK_REFUSALS: dict[str, RefusedCase] = {
    "slack-block-in-a-list-item": RefusedCase(
        "slack",
        "block inside a list item",
        [{"type": "text", "body": "- a\n  - b\n  - c\n\n  1. d\n  2. e\n- f"}],
        LIST_ITEM_WHY.format(what="a second nested list"),
        OUT_OF_THE_LIST,
        "at blocks.0.text",
    ),
    "slack-block-in-a-walkthrough-step": RefusedCase(
        "slack",
        "block inside a walkthrough step",
        [walkthrough_holding({"type": "code", "content": "recount"})],
        LIST_ITEM_WHY.format(what="a code block"),
        OUT_OF_THE_STEP,
        "at blocks.0.walkthrough.steps.0.detail.0.code",
    ),
    "slack-numbered-list-starting-past-1": RefusedCase(
        "slack",
        "numbered list starting past 1",
        [{"type": "text", "body": "3. a\n4. b"}],
        "a Slack canvas numbers every list from 1, so it cannot show a numbered list that starts at 3",
        "number the list from 1, or export it elsewhere",
        "at blocks.0.text",
    ),
    "slack-table-over-300-cells": RefusedCase(
        "slack",
        "table over 300 cells",
        [{"type": "heading", "text": "Counts"}, LONG_TABLE],
        "the table takes 301 cells as a Slack canvas table, over the 300 such a table can hold",
        "split the table in two or export it elsewhere",
        "at blocks.1.table, under the heading 'Counts'",
    ),
    "slack-grid-in-a-walkthrough-step": RefusedCase(
        "slack",
        "grid inside a walkthrough step",
        [walkthrough_holding(text_grid())],
        "a Slack canvas cannot show a grid inside a walkthrough step, "
        "since a canvas list item holds only text",
        "move the grid out of the step, after the walkthrough",
        "at blocks.0.walkthrough.steps.0.detail.0.grid",
    ),
    "slack-script-with-no-unicode-form": RefusedCase(
        "slack",
        "subscript or superscript with no Unicode form",
        [{"type": "text", "body": "x^q^"}],
        "a Slack canvas cannot show the superscript 'q', since 'q' has no Unicode superscript form",
        "write the text without the superscript or export the document elsewhere",
        "at blocks.0.text",
    ),
}
CANVAS_CALLOUT_WHY = (
    "a Slack canvas callout holds only text, headings, lists, quotes, code blocks and images, "
    "so it cannot show the {held} inside a panel"
)
CANVAS_COLUMN_WHY = (
    "a Slack canvas column holds no table, callout or divider, so it cannot show the {held} "
    "inside a grid cell"
)
INNER_GRID_WHY = "a Slack canvas cannot show a grid's columns inside a grid cell"
INNER_GRID_INSTEAD = "write the inner grid's cells as cells of the outer grid"
IMAGE = {"type": "image", "src": "https://example.com/shelf.png", "alt": "Shelf"}
BAR_CHART = {
    "type": "chart",
    "variant": "bar",
    "categories": ["Q1", "Q2"],
    "series": [{"label": "Bins", "values": [3, 5]}],
}


def two_cell_grid(*second_cell_blocks: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "grid",
        "cells": [
            {"span": 3, "blocks": [{"type": "text", "body": "Left"}]},
            {"span": 3, "blocks": list(second_cell_blocks)},
        ],
    }


def one_cell_grid(*blocks: dict[str, Any]) -> dict[str, Any]:
    return {"type": "grid", "cells": [{"span": 6, "blocks": list(blocks)}]}


def request_flow_of_two(*cases: dict[str, Any]) -> dict[str, Any]:
    step = {"label": "Read", "method": "GET", "url": "https://api.example.com/widgets", "cases": list(cases)}
    return {"type": "request_flow", "label": "Walk", "steps": [step, step]}


def toned_two_cell_grid(tone: ToneName) -> dict[str, Any]:
    grid = two_cell_grid({"type": "text", "body": "Right"})
    grid["cells"][1]["tone"] = tone
    return grid


def _in_a_panel_refused_by_a_canvas(
    feature: Feature, block: dict[str, Any], held: str, *others: ExportTarget
) -> RefusedCase:
    return RefusedCase(
        "slack",
        feature,
        in_a_panel(block),
        CANVAS_CALLOUT_WHY.format(held=held),
        f"move the {held} out of the panel",
        f"at blocks.0.panel.blocks.0.{block['type']}",
        also_refused_by=others,
    )


def _in_a_grid_cell_refused_by_a_canvas(
    feature: Feature, block: dict[str, Any], held: str, *others: ExportTarget
) -> RefusedCase:
    return RefusedCase(
        "slack",
        feature,
        [two_cell_grid(block)],
        CANVAS_COLUMN_WHY.format(held=held),
        f"move the {held} out of the grid",
        f"at blocks.0.grid.cells.1.blocks.0.{block['type']}",
        also_refused_by=others,
    )


CONTAINER_ADF_REFUSALS: dict[str, RefusedCase] = {
    "adf-divider-in-a-walkthrough-step": RefusedCase(
        "adf",
        "divider inside a walkthrough step",
        [walkthrough_holding({"type": "divider"})],
        "ADF cannot place a divider inside a walkthrough step, since Jira writes a step as a list item",
        "move the divider out of the step, after the walkthrough",
        "at blocks.0.walkthrough.steps.0.detail.0.divider",
        also_refused_by=("slack",),
    ),
}
CONTAINER_SLACK_REFUSALS: dict[str, RefusedCase] = {
    "slack-table-in-a-panel": _in_a_panel_refused_by_a_canvas(
        "table inside a callout", TABLE, "table", "adf"
    ),
    "slack-note-in-a-panel": _in_a_panel_refused_by_a_canvas(
        "callout inside a callout", {"type": "note", "body": "x"}, "note", "adf"
    ),
    "slack-toggle-in-a-panel": _in_a_panel_refused_by_a_canvas(
        "toggle inside a callout", make_toggle(), "toggle", "adf"
    ),
    "slack-tabs-in-a-panel": _in_a_panel_refused_by_a_canvas(
        "toggle inside a callout", make_tabs(), "set of tabs", "adf"
    ),
    "slack-chart-in-a-panel": _in_a_panel_refused_by_a_canvas(
        "table inside a callout", BAR_CHART, "chart", "adf"
    ),
    "slack-chart-in-a-grid-cell": _in_a_grid_cell_refused_by_a_canvas(
        "table inside a grid cell", BAR_CHART, "chart"
    ),
    "slack-request-with-a-verdict-in-a-panel": _in_a_panel_refused_by_a_canvas(
        "callout inside a callout",
        make_request(cases=[{"label": "a", "verdict": "fine", "response": {"body": "1"}}]),
        "request",
        "adf",
    ),
    "slack-request-step-with-a-verdict-in-a-panel": RefusedCase(
        "slack",
        "callout inside a callout",
        in_a_panel(request_flow_of_two({"label": "a", "verdict": "fine", "response": {"body": "1"}})),
        CANVAS_CALLOUT_WHY.format(held="request step"),
        "move the request step out of the panel",
        "at blocks.0.panel.blocks.0.request_flow.steps.0",
        also_refused_by=("adf",),
    ),
    "slack-request-step-with-two-cases-in-a-panel": RefusedCase(
        "slack",
        "toggle inside a callout",
        in_a_panel(
            request_flow_of_two(
                {"label": "a", "response": {"body": "1"}}, {"label": "b", "response": {"body": "2"}}
            )
        ),
        CANVAS_CALLOUT_WHY.format(held="request step"),
        "move the request step out of the panel",
        "at blocks.0.panel.blocks.0.request_flow.steps.0",
        also_refused_by=("adf",),
    ),
    "slack-divider-in-a-panel-under-a-heading": RefusedCase(
        "slack",
        "divider inside a callout",
        [{"type": "heading", "text": "Shelf"}, *in_a_panel({"type": "divider"})],
        CANVAS_CALLOUT_WHY.format(held="divider"),
        "move the divider out of the panel",
        "at blocks.1.panel.blocks.0.divider, under the heading 'Shelf'",
    ),
    "slack-grid-of-four-cells": RefusedCase(
        "slack",
        "grid with more than three cells",
        [
            {
                "type": "grid",
                "cells": [{"span": 1, "blocks": [{"type": "text", "body": name}]} for name in "abcd"],
            }
        ],
        "a Slack canvas column layout holds at most 3 columns, so it cannot show a grid of 4 cells",
        "split the grid into grids of at most 3 cells",
        "at blocks.0.grid",
    ),
    "slack-table-in-a-grid-cell": _in_a_grid_cell_refused_by_a_canvas(
        "table inside a grid cell", TABLE, "table"
    ),
    "slack-callout-in-a-grid-cell": _in_a_grid_cell_refused_by_a_canvas(
        "callout inside a grid cell", {"type": "callout", "tone": "info", "body": "x"}, "callout"
    ),
    "slack-divider-in-a-grid-cell": _in_a_grid_cell_refused_by_a_canvas(
        "divider inside a grid cell", {"type": "divider"}, "divider"
    ),
    "slack-toned-grid-cell": RefusedCase(
        "slack",
        "toned grid cell",
        [toned_two_cell_grid("warning")],
        "a Slack canvas column has no tone, so it cannot show a grid cell with the tone 'warning'",
        "drop the tone from the grid cell",
        "at blocks.0.grid.cells.1",
    ),
    "slack-grid-in-a-grid-cell": RefusedCase(
        "slack",
        "grid inside a grid cell",
        [two_cell_grid(text_grid())],
        INNER_GRID_WHY,
        INNER_GRID_INSTEAD,
        "at blocks.0.grid.cells.1.blocks.0.grid",
    ),
    "slack-grid-in-the-cell-of-a-one-cell-grid": RefusedCase(
        "slack",
        "grid inside a grid cell",
        [one_cell_grid(text_grid())],
        INNER_GRID_WHY,
        INNER_GRID_INSTEAD,
        "at blocks.0.grid.cells.0.blocks.0.grid",
    ),
    "slack-table-in-a-one-cell-grid-in-a-grid-cell": RefusedCase(
        "slack",
        "table inside a grid cell",
        [two_cell_grid(one_cell_grid(TABLE))],
        CANVAS_COLUMN_WHY.format(held="table"),
        "move the table out of the grid",
        "at blocks.0.grid.cells.1.blocks.0.grid.cells.0.blocks.0.table",
    ),
    "slack-code-in-a-one-cell-grid-in-a-walkthrough-step": RefusedCase(
        "slack",
        "block inside a walkthrough step",
        [walkthrough_holding(one_cell_grid({"type": "code", "content": "recount"}))],
        LIST_ITEM_WHY.format(what="a code block"),
        OUT_OF_THE_STEP,
        "at blocks.0.walkthrough.steps.0.detail.0.grid.cells.0.blocks.0.code",
    ),
}
SEEDED_REFUSALS: dict[str, RefusedCase] = {
    **ADF_REFUSALS,
    **SLACK_REFUSALS,
    **CONTAINER_ADF_REFUSALS,
    **CONTAINER_SLACK_REFUSALS,
}
ADF_CASES = [pytest.param(case, id=name) for name, case in {**ADF_REFUSALS, **CONTAINER_ADF_REFUSALS}.items()]
SEEDED_CASES = [pytest.param(case, id=name) for name, case in SEEDED_REFUSALS.items()]

CLEAN_BLOCKS: list[dict[str, Any]] = [
    {"type": "heading", "text": "Plan"},
    {"type": "text", "body": "1. a\n2. b"},
    {"type": "panel", "title": "Plan", "blocks": [{"type": "text", "body": "Inside."}]},
    {
        "type": "panel",
        "title": "Shelf",
        "blocks": [
            {"type": "heading", "text": "Shelf photos"},
            IMAGE,
            {"type": "media", "kind": "video", "src": "https://example.com/shelf.mp4"},
        ],
    },
    one_cell_grid(TABLE),
    two_cell_grid(one_cell_grid({"type": "text", "body": "Inner"})),
    walkthrough_holding(one_cell_grid({"type": "text", "body": "Inner"})),
    make_toggle(TABLE),
    make_toggle(make_toggle()),
    walkthrough_holding({"type": "text", "body": "Lock the aisle."}),
]

RANGE: dict[str, Any] = {
    "type": "range",
    "segments": [{"label": "Counted", "span": 3}, {"label": "Left", "span": 1}],
}
USE_A_METER = "use a meter or a table"
FLOW: dict[str, Any] = {
    "type": "flow",
    "loop": True,
    "steps": [{"label": "Scan", "tone": "info"}, {"label": "Count", "points": ["twice"]}],
}
FAN: dict[str, Any] = {
    "type": "fan",
    "hub": {"label": "Count", "tone": "accent"},
    "spokes": [{"label": "Scans"}, {"label": "Recounts", "note": "overflow only"}],
}
AS_A_NUMBERED_LIST = "write the steps as a numbered list"
AS_A_LIST = "write the hub and its spokes as a list"
RICH_NOTE_WHY = (
    "{subject} cannot show a link, citation, math, struck-through text, or a subscript or superscript "
    "with no Unicode form in a flow or fan step's note, since a diagram label holds plain text only"
)
RICH_NOTE_INSTEAD = "write the note as plain text and put the rest in a text block after the diagram"
REFERENCES: dict[str, Any] = {
    "type": "references",
    "items": [{"key": "sop", "text": "SOP", "url": "https://example.com/sop"}],
}
RICH_NOTES: dict[str, str] = {
    "web-link": "see [doc](https://example.com/d)",
    "anchor": "see [count](#count)",
    "citation": "per [^sop]",
    "link-inside-bold": "**[doc](https://example.com/d)**",
    "citation-inside-a-color-span": "per [[^sop]]{tone=info}",
    "inline-math": "rate $`x_i`$",
    "superscript-with-no-unicode-form": "about 10^q^",
    "subscript-with-no-unicode-form": "zone C~b~",
    "issue-link": "see [WH-1](jira:WH-1)",
    "document-link": "see [the plan](doc:cold-room-plan)",
    "strikethrough": "was ~~40~~ now 30 bins",
    "strikethrough-inside-italic": "*was ~~40~~ now 30*",
}


def xy_chart(variant: XYChartMark, *series: list[float], stacked: bool = False) -> dict[str, Any]:
    labelled = [{"label": f"Zone {index}", "values": values} for index, values in enumerate(series, start=1)]
    return {
        "type": "chart",
        "variant": variant,
        "stacked": stacked,
        "categories": ["Mon", "Tue"],
        "series": labelled,
    }


DONUT: dict[str, Any] = {
    "type": "chart",
    "variant": "donut",
    "slices": [{"label": "Fixed", "value": 9, "tone": "success"}, {"label": "Open", "value": 3}],
}
ONE_SERIES_CHARTS: dict[str, dict[str, Any]] = {
    "donut": DONUT,
    "one-series-bar": xy_chart("bar", [4, 6]),
    "one-series-line": xy_chart("line", [4, 6]),
    "one-series-stacked-bar": xy_chart("bar", [4, 6], stacked=True),
}
SEVERAL_SERIES_CHARTS: dict[str, dict[str, Any]] = {
    "two-series-bar": xy_chart("bar", [4, 6], [1, 2]),
    "two-series-line": xy_chart("line", [4, 6], [1, 2]),
    "two-series-stacked-bar": xy_chart("bar", [4, 6], [1, 2], stacked=True),
}
EVERY_CHART: dict[str, dict[str, Any]] = {**ONE_SERIES_CHARTS, **SEVERAL_SERIES_CHARTS}
LONG_CHART: dict[str, Any] = {
    "type": "chart",
    "variant": "bar",
    "categories": [f"Day {day}" for day in range(1, 161)],
    "series": [{"label": "Zone 1", "values": [1] * 160}],
}


DATA_IMAGE: dict[str, Any] = {"type": "image", "src": "data:image/png;base64,AA==", "alt": "Aisle 12"}
WEB_IMAGE: dict[str, Any] = {"type": "image", "src": "https://example.com/aisle.png", "alt": "Aisle 12"}
HTTP_IMAGE: dict[str, Any] = {**WEB_IMAGE, "src": "http://example.com/aisle.png"}
HTTP_IMAGE_MARKDOWN = "![Aisle 12](http://example.com/aisle.png)\n"
HOST_THE_IMAGE = "host the image and give its https address"
MATH_BLOCKS: list[dict[str, Any]] = [
    {"type": "math", "expression": "x^2 + 1"},
    {"type": "text", "body": "rate $`x_i`$ now"},
]
SWAPPED_BLOCKS: dict[Feature, list[dict[str, Any]]] = {
    "chart": [xy_chart("line", [4, 6])],
    "chart with several series": [xy_chart("bar", [4, 6], [1, 2])],
    "math block": MATH_BLOCKS[:1],
    "inline math": MATH_BLOCKS[1:],
}


def flow_with_a_note(note: str) -> list[dict[str, Any]]:
    flow = {"type": "flow", "steps": [{"label": "Scan", "note": note}, {"label": "Fix"}]}
    return [{"type": "heading", "text": "Count"}, flow, REFERENCES]


def flow_with_a_note_on_its_last_step(note: str) -> list[dict[str, Any]]:
    flow = {"type": "flow", "steps": [{"label": "Scan"}, {"label": "Fix"}, {"label": "Check", "note": note}]}
    return [flow, REFERENCES]


def fan_with_a_note_on_a_spoke(note: str) -> list[dict[str, Any]]:
    return [{**FAN, "spokes": [{"label": "Scans"}, {"label": "Recounts", "note": note}]}, REFERENCES]


def rich_note_refusal(
    target: ExportTarget, subject: str, blocks: list[dict[str, Any]], where: str
) -> RefusedCase:
    return RefusedCase(
        target, RICH_STEP_NOTE, blocks, RICH_NOTE_WHY.format(subject=subject), RICH_NOTE_INSTEAD, where
    )


@dataclass(frozen=True)
class AcceptedCase:
    target: ExportTarget
    blocks: list[dict[str, Any]]
    written: str | None = None
    meta: dict[str, Any] = field(default_factory=lambda: {"title": "Plan"})

    def report(self) -> dict[str, Any]:
        return make_report(meta=self.meta, blocks=self.blocks)


MERMAID_SUBJECTS: tuple[tuple[ExportTarget, str], ...] = (("markdown", "GitHub"), ("notion", "Notion"))
PEOPLE_META: dict[str, Any] = {"title": "Plan", "people": {"ada": {}}}
SCRIPTED_NOTE_FLOW: dict[str, Any] = {
    "type": "flow",
    "numbered": False,
    "steps": [{"label": "Scan", "note": "about 10^3^ bins of H~2~O"}, {"label": "Fix"}],
}
SCRIPTED_NOTE_MERMAID = (
    '```mermaid\nflowchart LR\n    s1["Scan<br>about 10³ bins of H₂O"]\n    s2["Fix"]\n    s1 --> s2\n```\n'
)
CODE_NOTE_FLOW: dict[str, Any] = {
    "type": "flow",
    "numbered": False,
    "steps": [{"label": "Scan", "note": "bin `B-12` first"}, {"label": "Fix"}],
}
CODE_NOTE_MERMAID = (
    '```mermaid\nflowchart LR\n    s1["Scan<br>bin B-12 first"]\n    s2["Fix"]\n    s1 --> s2\n```\n'
)
MENTION_NOTE_FLOW: dict[str, Any] = {
    "type": "flow",
    "numbered": False,
    "steps": [{"label": "Scan", "note": "[Ada](user:ada) by [1 Oct](date:2026-10-01)"}, {"label": "Fix"}],
}
MENTION_NOTE_MERMAID = (
    '```mermaid\nflowchart LR\n    s1["Scan<br>Ada by 1 Oct"]\n    s2["Fix"]\n    s1 --> s2\n```\n'
)


DIAGRAM_REFUSALS: dict[str, RefusedCase] = {
    "markdown-range": RefusedCase(
        "markdown", "range", [RANGE], "GitHub cannot draw a range bar", USE_A_METER, "at blocks.0.range"
    ),
    "notion-range": RefusedCase(
        "notion", "range", [RANGE], "Notion cannot draw a range bar", USE_A_METER, "at blocks.0.range"
    ),
    "adf-range": RefusedCase(
        "adf", "range", [RANGE], "ADF cannot draw a range bar", USE_A_METER, "at blocks.0.range"
    ),
    "slack-range": RefusedCase(
        "slack", "range", [RANGE], "a Slack canvas cannot draw a range bar", USE_A_METER, "at blocks.0.range"
    ),
    "adf-range-in-a-panel-in-a-section": RefusedCase(
        "adf",
        "range",
        [make_section("counts", blocks=in_a_panel(RANGE))],
        "ADF cannot draw a range bar",
        USE_A_METER,
        "at blocks.0.section.blocks.0.panel.blocks.0.range",
    ),
    "notion-range-in-a-grid-cell": RefusedCase(
        "notion",
        "range",
        [in_a_grid_cell([RANGE])],
        "Notion cannot draw a range bar",
        USE_A_METER,
        "at blocks.0.grid.cells.0.blocks.0.range",
    ),
    "adf-flow": RefusedCase(
        "adf",
        "flow diagram",
        [FLOW],
        "ADF cannot draw a flow diagram",
        AS_A_NUMBERED_LIST,
        "at blocks.0.flow",
    ),
    "slack-flow": RefusedCase(
        "slack",
        "flow diagram",
        [FLOW],
        "a Slack canvas cannot draw a flow diagram",
        AS_A_NUMBERED_LIST,
        "at blocks.0.flow",
    ),
    "adf-fan": RefusedCase(
        "adf", "fan diagram", [FAN], "ADF cannot draw a fan diagram", AS_A_LIST, "at blocks.0.fan"
    ),
    "slack-fan": RefusedCase(
        "slack",
        "fan diagram",
        [FAN],
        "a Slack canvas cannot draw a fan diagram",
        AS_A_LIST,
        "at blocks.0.fan",
    ),
    "slack-flow-in-a-toggle": RefusedCase(
        "slack",
        "flow diagram",
        [make_toggle(FLOW)],
        "a Slack canvas cannot draw a flow diagram",
        AS_A_NUMBERED_LIST,
        "at blocks.0.toggle.blocks.0.flow",
    ),
    **{
        f"markdown-flow-note-{name}": rich_note_refusal(
            "markdown", "GitHub", flow_with_a_note(note), "at blocks.1.flow"
        )
        for name, note in RICH_NOTES.items()
    },
    "notion-flow-note-web-link": rich_note_refusal(
        "notion", "Notion", flow_with_a_note(RICH_NOTES["web-link"]), "at blocks.1.flow"
    ),
    "notion-flow-note-strikethrough": rich_note_refusal(
        "notion", "Notion", flow_with_a_note(RICH_NOTES["strikethrough"]), "at blocks.1.flow"
    ),
    "notion-fan-hub-note-inline-math": rich_note_refusal(
        "notion",
        "Notion",
        [{**FAN, "hub": {"label": "Count", "note": RICH_NOTES["inline-math"]}}],
        "at blocks.0.fan",
    ),
    **{
        f"{target}-flow-last-step-note-citation": rich_note_refusal(
            target, subject, flow_with_a_note_on_its_last_step(RICH_NOTES["citation"]), "at blocks.0.flow"
        )
        for target, subject in MERMAID_SUBJECTS
    },
    **{
        f"{target}-fan-spoke-note-web-link": rich_note_refusal(
            target, subject, fan_with_a_note_on_a_spoke(RICH_NOTES["web-link"]), "at blocks.0.fan"
        )
        for target, subject in MERMAID_SUBJECTS
    },
    "markdown-data-image": RefusedCase(
        "markdown",
        "image from a data: URI",
        [DATA_IMAGE],
        "GitHub cannot show an image from a data: URI",
        HOST_THE_IMAGE,
        "at blocks.0.image",
    ),
    "notion-data-image": RefusedCase(
        "notion",
        "image from a data: URI",
        [DATA_IMAGE],
        "Notion cannot show an image from a data: URI",
        HOST_THE_IMAGE,
        "at blocks.0.image",
    ),
    "adf-data-image": RefusedCase(
        "adf",
        "image from a data: URI",
        [DATA_IMAGE],
        "ADF cannot show an image from a data: URI, since Jira embeds only files attached to the issue",
        HOST_THE_IMAGE,
        "at blocks.0.image",
    ),
    "slack-data-image": RefusedCase(
        "slack",
        "image from a data: URI",
        [DATA_IMAGE],
        "a Slack canvas cannot show an image from a data: URI",
        "upload the image to Slack and give its permalink",
        "at blocks.0.image",
    ),
    "notion-data-image-in-a-tab": RefusedCase(
        "notion",
        "image from a data: URI",
        [
            {
                "type": "tabs",
                "tabs": [
                    {"label": "Photo", "blocks": [DATA_IMAGE]},
                    {"label": "Notes", "blocks": [{"type": "text", "body": "Overflow bins."}]},
                ],
            }
        ],
        "Notion cannot show an image from a data: URI",
        HOST_THE_IMAGE,
        "at blocks.0.tabs.tabs.0.blocks.0.image",
    ),
    "slack-chart-whose-data-table-is-over-300-cells": RefusedCase(
        "slack",
        "table over 300 cells",
        [{"type": "heading", "text": "Counts"}, LONG_CHART],
        "the chart takes 322 cells as a Slack canvas table, over the 300 such a table can hold",
        "split the chart in two or export it elsewhere",
        "at blocks.1.chart, under the heading 'Counts'",
    ),
    "adf-flow-with-a-rich-note-is-refused-as-a-flow": RefusedCase(
        "adf",
        "flow diagram",
        flow_with_a_note(RICH_NOTES["web-link"]),
        "ADF cannot draw a flow diagram",
        AS_A_NUMBERED_LIST,
        "at blocks.1.flow",
    ),
}
DIAGRAM_ACCEPTED: dict[str, AcceptedCase] = {
    "markdown-flow": AcceptedCase(
        "markdown",
        [FLOW],
        "# Plan\n\n```mermaid\nflowchart LR\n"
        '    s1["1: Scan"]:::info\n    s2["2: Count"]\n    s1 --> s2\n    s2 -.-> s1\n'
        "    classDef info fill:#e8f0fe,stroke:#1a73e8,color:#1f2328\n```\n\n- **Count**\n  - twice\n",
    ),
    "notion-flow": AcceptedCase("notion", [FLOW]),
    "markdown-fan": AcceptedCase("markdown", [FAN]),
    "notion-fan": AcceptedCase(
        "notion",
        [FAN],
        '```mermaid\nflowchart LR\n    hub["Count"]:::accent\n    s1["Scans"]\n'
        '    s2["Recounts<br>overflow only"]\n    s1 --> hub\n    s2 --> hub\n'
        "    classDef accent fill:#f3e8fd,stroke:#8430ce,color:#1f2328\n```\n",
    ),
    "markdown-flow-with-a-styled-note": AcceptedCase("markdown", flow_with_a_note("by **aisle** and `bin`")),
    "notion-flow-with-a-styled-note": AcceptedCase("notion", flow_with_a_note("by *aisle* [now]{tone=info}")),
    "markdown-flow-note-with-unicode-scripts": AcceptedCase(
        "markdown", [SCRIPTED_NOTE_FLOW], f"# Plan\n\n{SCRIPTED_NOTE_MERMAID}"
    ),
    "notion-flow-note-with-unicode-scripts": AcceptedCase(
        "notion", [SCRIPTED_NOTE_FLOW], SCRIPTED_NOTE_MERMAID
    ),
    "markdown-flow-note-with-inline-code-keeps-its-characters": AcceptedCase(
        "markdown", [CODE_NOTE_FLOW], f"# Plan\n\n{CODE_NOTE_MERMAID}"
    ),
    "notion-flow-note-with-inline-code-keeps-its-characters": AcceptedCase(
        "notion", [CODE_NOTE_FLOW], CODE_NOTE_MERMAID
    ),
    "markdown-flow-note-with-a-mention-and-a-date": AcceptedCase(
        "markdown", [MENTION_NOTE_FLOW], f"# Plan\n\n{MENTION_NOTE_MERMAID}", PEOPLE_META
    ),
    "notion-flow-note-with-a-mention-and-a-date": AcceptedCase(
        "notion", [MENTION_NOTE_FLOW], MENTION_NOTE_MERMAID, PEOPLE_META
    ),
    **{
        f"{target}-chart-{name}": AcceptedCase(target, [chart])
        for target in EXPORT_TARGETS
        for name, chart in EVERY_CHART.items()
    },
    "markdown-chart-donut": AcceptedCase(
        "markdown",
        [DONUT],
        '# Plan\n\n```mermaid\npie\n    "Fixed" : 9\n    "Open" : 3\n```\n\n'
        "| Slice | Value | Share |\n| --- | --- | --- |\n"
        "| Fixed | 9 | 75% |\n| Open | 3 | 25% |\n| **Total** | **12** |  |\n",
    ),
    "slack-chart-two-series-stacked-bar": AcceptedCase(
        "slack",
        [SEVERAL_SERIES_CHARTS["two-series-stacked-bar"]],
        "| Series | Mon | Tue |\n| --- | --- | --- |\n"
        "| Zone 1 | 4 | 6 |\n| Zone 2 | 1 | 2 |\n| **Total** | **5** | **8** |\n",
    ),
    **{f"{target}-math": AcceptedCase(target, MATH_BLOCKS) for target in EXPORT_TARGETS},
    "markdown-math": AcceptedCase(
        "markdown", MATH_BLOCKS, "# Plan\n\n```math\nx^2 + 1\n```\n\nrate $`x_i`$ now\n"
    ),
    "slack-math": AcceptedCase("slack", MATH_BLOCKS, "```latex\nx^2 + 1\n```\n\nrate `x_i` now\n"),
    **{f"{target}-web-image": AcceptedCase(target, [WEB_IMAGE]) for target in EXPORT_TARGETS},
    "notion-http-image": AcceptedCase("notion", [HTTP_IMAGE], HTTP_IMAGE_MARKDOWN),
    "slack-http-image": AcceptedCase("slack", [HTTP_IMAGE], HTTP_IMAGE_MARKDOWN),
    "adf-http-image": AcceptedCase("adf", [HTTP_IMAGE]),
}
ALL_REFUSALS: dict[str, RefusedCase] = {**SEEDED_REFUSALS, **DIAGRAM_REFUSALS}
DIAGRAM_CASES = [pytest.param(case, id=name) for name, case in DIAGRAM_REFUSALS.items()]
DIAGRAM_ACCEPTED_CASES = [pytest.param(case, id=name) for name, case in DIAGRAM_ACCEPTED.items()]
