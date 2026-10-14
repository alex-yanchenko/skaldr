from dataclasses import dataclass
from typing import Any

import pytest

from skaldr.export_targets import ExportTarget
from tests.factories.report_factory import make_report, make_toggle

TABLE = {"type": "table", "columns": [{"key": "name", "label": "Name"}], "rows": [{"name": "a"}]}
LONG_TABLE = {"type": "table", "columns": [{"key": "name", "label": "Name"}], "rows": [["v"]] * 300}
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
ADF_CASES = [
    pytest.param(TABLE_IN_A_PANEL, id="adf-table-in-a-callout"),
    pytest.param(
        RefusedCase(
            "adf",
            in_a_panel({"type": "callout", "tone": "info", "body": "x"}),
            "ADF cannot place a callout inside a panel",
            "move the callout out of the panel",
            "at blocks.0.panel.blocks.0.callout",
        ),
        id="adf-callout-in-a-callout",
    ),
    pytest.param(
        RefusedCase(
            "adf",
            in_a_panel({"type": "quote", "body": "Count twice."}),
            "ADF cannot place a quote inside a panel",
            "move the quote out of the panel",
            "at blocks.0.panel.blocks.0.quote",
        ),
        id="adf-quote-in-a-callout",
    ),
    pytest.param(
        RefusedCase(
            "adf",
            in_a_panel(make_toggle()),
            "ADF cannot place a toggle inside a panel",
            "move the toggle out of the panel",
            "at blocks.0.panel.blocks.0.toggle",
        ),
        id="adf-toggle-in-a-callout",
    ),
    pytest.param(
        RefusedCase(
            "adf",
            [make_toggle(make_toggle(TABLE))],
            "ADF cannot place a table inside a toggle that is itself inside a toggle",
            "move the table out of the toggle",
            "at blocks.0.toggle.blocks.0.toggle.blocks.0.table",
        ),
        id="adf-table-in-a-toggle-in-a-toggle",
    ),
    pytest.param(
        RefusedCase(
            "adf",
            [make_toggle(make_toggle(make_toggle()))],
            "ADF cannot place a toggle inside a toggle that is itself inside a toggle",
            "move the toggle out of the toggle",
            "at blocks.0.toggle.blocks.0.toggle.blocks.0.toggle",
        ),
        id="adf-toggle-in-a-toggle-in-a-toggle",
    ),
]
SLACK_CASES = [
    pytest.param(
        RefusedCase(
            "slack",
            [{"type": "text", "body": "- a\n  - b\n  - c\n\n  1. d\n  2. e\n- f"}],
            LIST_ITEM_WHY.format(what="a second nested list"),
            OUT_OF_THE_LIST,
            "at blocks.0.text",
        ),
        id="slack-block-in-a-list-item",
    ),
    pytest.param(
        RefusedCase(
            "slack",
            [walkthrough_holding({"type": "code", "content": "recount"})],
            LIST_ITEM_WHY.format(what="a code block"),
            OUT_OF_THE_STEP,
            "at blocks.0.walkthrough.steps.0.detail.0.code",
        ),
        id="slack-block-in-a-walkthrough-step",
    ),
    pytest.param(
        RefusedCase(
            "slack",
            [{"type": "text", "body": "3. a\n4. b"}],
            "a Slack canvas numbers every list from 1, so it cannot show a numbered list that starts at 3",
            "number the list from 1, or export it elsewhere",
            "at blocks.0.text",
        ),
        id="slack-numbered-list-starting-past-1",
    ),
    pytest.param(
        RefusedCase(
            "slack",
            [{"type": "heading", "text": "Counts"}, LONG_TABLE],
            "a table has 301 cells, over the 300 a Slack canvas table can hold",
            "split it into two tables or export it elsewhere",
            "at blocks.1.table, under the heading 'Counts'",
        ),
        id="slack-table-over-300-cells",
    ),
    pytest.param(
        RefusedCase(
            "slack",
            [walkthrough_holding(text_grid())],
            "a Slack canvas cannot show a grid inside a walkthrough step, "
            "since a canvas list item holds only text",
            "move the grid out of the step, after the walkthrough",
            "at blocks.0.walkthrough.steps.0.detail.0.grid",
        ),
        id="slack-grid-in-a-walkthrough-step",
    ),
]
SEEDED_CASES = [*ADF_CASES, *SLACK_CASES]

CLEAN_BLOCKS: list[dict[str, Any]] = [
    {"type": "heading", "text": "Plan"},
    {"type": "text", "body": "1. a\n2. b"},
    {"type": "panel", "title": "Plan", "blocks": [{"type": "text", "body": "Inside."}]},
    make_toggle(TABLE),
    make_toggle(make_toggle()),
    walkthrough_holding({"type": "text", "body": "Lock the aisle."}),
]
