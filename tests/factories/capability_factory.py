from dataclasses import dataclass
from typing import Any

import pytest

from skaldr.export.capabilities import Feature
from skaldr.export.tree import XYChartMark
from skaldr.export_targets import EXPORT_TARGETS, ExportTarget
from tests.factories.report_factory import in_a_grid_cell, make_report, make_section, make_toggle

TABLE = {"type": "table", "columns": [{"key": "name", "label": "Name"}], "rows": [{"name": "a"}]}
LONG_TABLE = {"type": "table", "columns": [{"key": "name", "label": "Name"}], "rows": [{"name": "v"}] * 300}
LIST_ITEM_WHY = "a Slack canvas list item holds only text and one nested list, so it cannot show {what}"
OUT_OF_THE_LIST = "move it out of the list, after the list"
OUT_OF_THE_STEP = "move it out of the step, after the walkthrough"
PUBLISHED_DOC_ID = "capability-check"


@dataclass(frozen=True)
class RefusedCase:
    target: ExportTarget
    blocks: list[dict[str, Any]]
    why: str
    instead: str
    where: str

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
    in_a_panel(TABLE),
    "ADF cannot place a table inside a panel",
    "move the table out of the panel",
    "at blocks.0.panel.blocks.0.table",
)
ADF_REFUSALS: dict[str, RefusedCase] = {
    "adf-table-in-a-panel": TABLE_IN_A_PANEL,
    "adf-callout-in-a-panel": RefusedCase(
        "adf",
        in_a_panel({"type": "callout", "tone": "info", "body": "x"}),
        "ADF cannot place a callout inside a panel",
        "move the callout out of the panel",
        "at blocks.0.panel.blocks.0.callout",
    ),
    "adf-quote-in-a-panel": RefusedCase(
        "adf",
        in_a_panel({"type": "quote", "body": "Count twice."}),
        "ADF cannot place a quote inside a panel",
        "move the quote out of the panel",
        "at blocks.0.panel.blocks.0.quote",
    ),
    "adf-toggle-in-a-panel": RefusedCase(
        "adf",
        in_a_panel(make_toggle()),
        "ADF cannot place a toggle inside a panel",
        "move the toggle out of the panel",
        "at blocks.0.panel.blocks.0.toggle",
    ),
    "adf-table-in-a-toggle-in-a-toggle": RefusedCase(
        "adf",
        [make_toggle(make_toggle(TABLE))],
        "ADF cannot place a table inside a toggle that is itself inside a toggle",
        "move the table out of the toggle",
        "at blocks.0.toggle.blocks.0.toggle.blocks.0.table",
    ),
    "adf-toggle-in-a-toggle-in-a-toggle": RefusedCase(
        "adf",
        [make_toggle(make_toggle(make_toggle()))],
        "ADF cannot place a toggle inside a toggle that is itself inside a toggle",
        "move the toggle out of the toggle",
        "at blocks.0.toggle.blocks.0.toggle.blocks.0.toggle",
    ),
}
SLACK_REFUSALS: dict[str, RefusedCase] = {
    "slack-block-in-a-list-item": RefusedCase(
        "slack",
        [{"type": "text", "body": "- a\n  - b\n  - c\n\n  1. d\n  2. e\n- f"}],
        LIST_ITEM_WHY.format(what="a second nested list"),
        OUT_OF_THE_LIST,
        "at blocks.0.text",
    ),
    "slack-block-in-a-walkthrough-step": RefusedCase(
        "slack",
        [walkthrough_holding({"type": "code", "content": "recount"})],
        LIST_ITEM_WHY.format(what="a code block"),
        OUT_OF_THE_STEP,
        "at blocks.0.walkthrough.steps.0.detail.0.code",
    ),
    "slack-numbered-list-starting-past-1": RefusedCase(
        "slack",
        [{"type": "text", "body": "3. a\n4. b"}],
        "a Slack canvas numbers every list from 1, so it cannot show a numbered list that starts at 3",
        "number the list from 1, or export it elsewhere",
        "at blocks.0.text",
    ),
    "slack-table-over-300-cells": RefusedCase(
        "slack",
        [{"type": "heading", "text": "Counts"}, LONG_TABLE],
        "a table has 301 cells, over the 300 a Slack canvas table can hold",
        "split it into two tables or export it elsewhere",
        "at blocks.1.table, under the heading 'Counts'",
    ),
    "slack-grid-in-a-walkthrough-step": RefusedCase(
        "slack",
        [walkthrough_holding(text_grid())],
        "a Slack canvas cannot show a grid inside a walkthrough step, "
        "since a canvas list item holds only text",
        "move the grid out of the step, after the walkthrough",
        "at blocks.0.walkthrough.steps.0.detail.0.grid",
    ),
    "slack-script-with-no-unicode-form": RefusedCase(
        "slack",
        [{"type": "text", "body": "x^q^"}],
        "a Slack canvas cannot show the superscript 'q', since 'q' has no Unicode superscript form",
        "write the text without the superscript or export the document elsewhere",
        "at blocks.0.text",
    ),
}
SEEDED_REFUSALS: dict[str, RefusedCase] = {**ADF_REFUSALS, **SLACK_REFUSALS}
ADF_CASES = [pytest.param(case, id=name) for name, case in ADF_REFUSALS.items()]
SEEDED_CASES = [pytest.param(case, id=name) for name, case in SEEDED_REFUSALS.items()]

CLEAN_BLOCKS: list[dict[str, Any]] = [
    {"type": "heading", "text": "Plan"},
    {"type": "text", "body": "1. a\n2. b"},
    {"type": "panel", "title": "Plan", "blocks": [{"type": "text", "body": "Inside."}]},
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
    "{target} cannot show a link, citation, math, subscript or superscript in a flow or fan step's note, "
    "since a diagram label holds plain text only"
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
    "superscript": "about 10^3^",
    "issue-link": "see [WH-1](jira:WH-1)",
    "document-link": "see [the plan](doc:cold-room-plan)",
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


DATA_IMAGE: dict[str, Any] = {"type": "image", "src": "data:image/png;base64,AA==", "alt": "Aisle 12"}
WEB_IMAGE: dict[str, Any] = {"type": "image", "src": "https://example.com/aisle.png", "alt": "Aisle 12"}
HOST_THE_IMAGE = "host the image and give its https address"
MATH_BLOCKS: list[dict[str, Any]] = [
    {"type": "math", "expression": "x^2 + 1"},
    {"type": "text", "body": "rate $`x_i`$ now"},
]
SWAPPED_BLOCKS: dict[Feature, list[dict[str, Any]]] = {
    "chart": [DONUT],
    "chart with several series": [xy_chart("bar", [4, 6], [1, 2])],
    "math block": MATH_BLOCKS[:1],
    "inline math": MATH_BLOCKS[1:],
}


def flow_with_a_note(note: str) -> list[dict[str, Any]]:
    flow = {"type": "flow", "steps": [{"label": "Scan", "note": note}, {"label": "Fix"}]}
    return [{"type": "heading", "text": "Count"}, flow, REFERENCES]


def rich_note_refusal(
    target: ExportTarget, subject: str, blocks: list[dict[str, Any]], where: str
) -> RefusedCase:
    return RefusedCase(target, blocks, RICH_NOTE_WHY.format(target=subject), RICH_NOTE_INSTEAD, where)


@dataclass(frozen=True)
class AcceptedCase:
    target: ExportTarget
    blocks: list[dict[str, Any]]


DIAGRAM_REFUSALS: dict[str, RefusedCase] = {
    "markdown-range": RefusedCase(
        "markdown", [RANGE], "GitHub cannot draw a range bar", USE_A_METER, "at blocks.0.range"
    ),
    "notion-range": RefusedCase(
        "notion", [RANGE], "Notion cannot draw a range bar", USE_A_METER, "at blocks.0.range"
    ),
    "adf-range": RefusedCase("adf", [RANGE], "ADF cannot draw a range bar", USE_A_METER, "at blocks.0.range"),
    "slack-range": RefusedCase(
        "slack", [RANGE], "a Slack canvas cannot draw a range bar", USE_A_METER, "at blocks.0.range"
    ),
    "adf-range-in-a-panel-in-a-section": RefusedCase(
        "adf",
        [make_section("counts", blocks=in_a_panel(RANGE))],
        "ADF cannot draw a range bar",
        USE_A_METER,
        "at blocks.0.section.blocks.0.panel.blocks.0.range",
    ),
    "notion-range-in-a-grid-cell": RefusedCase(
        "notion",
        [in_a_grid_cell([RANGE])],
        "Notion cannot draw a range bar",
        USE_A_METER,
        "at blocks.0.grid.cells.0.blocks.0.range",
    ),
    "adf-flow": RefusedCase(
        "adf", [FLOW], "ADF cannot draw a flow diagram", AS_A_NUMBERED_LIST, "at blocks.0.flow"
    ),
    "slack-flow": RefusedCase(
        "slack", [FLOW], "a Slack canvas cannot draw a flow diagram", AS_A_NUMBERED_LIST, "at blocks.0.flow"
    ),
    "adf-fan": RefusedCase("adf", [FAN], "ADF cannot draw a fan diagram", AS_A_LIST, "at blocks.0.fan"),
    "slack-fan": RefusedCase(
        "slack", [FAN], "a Slack canvas cannot draw a fan diagram", AS_A_LIST, "at blocks.0.fan"
    ),
    "slack-flow-in-a-toggle": RefusedCase(
        "slack",
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
    "notion-fan-hub-note-inline-math": rich_note_refusal(
        "notion",
        "Notion",
        [{**FAN, "hub": {"label": "Count", "note": RICH_NOTES["inline-math"]}}],
        "at blocks.0.fan",
    ),
    "notion-data-image": RefusedCase(
        "notion",
        [DATA_IMAGE],
        "Notion cannot show an image from a data: URI",
        HOST_THE_IMAGE,
        "at blocks.0.image",
    ),
    "adf-data-image": RefusedCase(
        "adf",
        [DATA_IMAGE],
        "ADF cannot show an image from a data: URI, since Jira embeds only files attached to the issue",
        HOST_THE_IMAGE,
        "at blocks.0.image",
    ),
    "slack-data-image": RefusedCase(
        "slack",
        [DATA_IMAGE],
        "a Slack canvas cannot show an image from a data: URI",
        "upload the image to Slack and give its permalink",
        "at blocks.0.image",
    ),
    "notion-data-image-in-a-tab": RefusedCase(
        "notion",
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
    "adf-flow-with-a-rich-note-is-refused-as-a-flow": RefusedCase(
        "adf",
        flow_with_a_note(RICH_NOTES["web-link"]),
        "ADF cannot draw a flow diagram",
        AS_A_NUMBERED_LIST,
        "at blocks.1.flow",
    ),
}
DIAGRAM_ACCEPTED: dict[str, AcceptedCase] = {
    "markdown-flow": AcceptedCase("markdown", [FLOW]),
    "notion-flow": AcceptedCase("notion", [FLOW]),
    "markdown-fan": AcceptedCase("markdown", [FAN]),
    "notion-fan": AcceptedCase("notion", [FAN]),
    "markdown-flow-with-a-styled-note": AcceptedCase("markdown", flow_with_a_note("by **aisle** and `bin`")),
    "notion-flow-with-a-styled-note": AcceptedCase("notion", flow_with_a_note("by *aisle* [now]{tone=info}")),
    **{
        f"{target}-chart-{name}": AcceptedCase(target, [chart])
        for target in EXPORT_TARGETS
        for name, chart in {**ONE_SERIES_CHARTS, **SEVERAL_SERIES_CHARTS}.items()
    },
    **{f"{target}-math": AcceptedCase(target, MATH_BLOCKS) for target in EXPORT_TARGETS},
    "markdown-data-image": AcceptedCase("markdown", [DATA_IMAGE]),
    **{f"{target}-web-image": AcceptedCase(target, [WEB_IMAGE]) for target in EXPORT_TARGETS},
}
DIAGRAM_CASES = [pytest.param(case, id=name) for name, case in DIAGRAM_REFUSALS.items()]
DIAGRAM_ACCEPTED_CASES = [pytest.param(case, id=name) for name, case in DIAGRAM_ACCEPTED.items()]
