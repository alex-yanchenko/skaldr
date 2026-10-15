from dataclasses import dataclass
from typing import Any

import pytest

from skaldr.export.capabilities import Feature
from skaldr.export.tree import ToneName
from skaldr.export_targets import ExportTarget
from tests.factories.report_factory import make_report, make_request, make_tabs, make_toggle

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
        "a table has 301 cells, over the 300 a Slack canvas table can hold",
        "split it into two tables or export it elsewhere",
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
        "a Slack canvas column layout cannot nest, so it cannot show a grid inside a grid cell",
        "write the inner grid's cells as cells of the outer grid",
        "at blocks.0.grid.cells.1.blocks.0.grid",
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
    make_toggle(TABLE),
    make_toggle(make_toggle()),
    walkthrough_holding({"type": "text", "body": "Lock the aisle."}),
]
