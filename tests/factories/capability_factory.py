from dataclasses import dataclass
from typing import Any

import pytest

from skaldr.export_targets import ExportTarget
from tests.factories.report_factory import make_report, make_toggle

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
COLOURED_TEXT = [{"type": "text", "body": "Zone C is [behind]{tone=danger}."}]
HIGHLIGHTED_TEXT = [{"type": "text", "body": "The recount is [due Friday]{bg=warning}."}]
COLOURED_AND_HIGHLIGHTED_TEXT = [{"type": "text", "body": "The [vendor lots]{tone=accent bg=sky} stay open."}]
UNDERLINED_TEXT = [{"type": "text", "body": "Every label ends in a ++check digit++."}]
LINK_TO_A_SECTION = [
    {"type": "section", "id": "counts", "title": "Counts", "blocks": [{"type": "text", "body": "Ten."}]},
    {"type": "text", "body": "See [the counts](#counts)."},
]
LINK_TO_ANOTHER_DOCUMENT = [{"type": "text", "body": "It follows [the plan](doc:cold-room-plan#recount)."}]
WITHOUT_THE_COLOUR = "write the text without the colour or export the document elsewhere"
GITHUB_COLOUR_WHY = "GitHub Markdown cannot colour text, so it cannot show the colour of '{text}'"
CANVAS_COLOUR_WHY = "a Slack canvas cannot colour text, so it cannot show the colour of '{text}'"
OWN_HEADING_INSTEAD = "write the heading's name without the link, or export the document elsewhere"
OWN_HEADING_WHY = (
    "{target} cannot link to its own headings, so it cannot show the link 'the counts' to '#counts'"
)
OTHER_DOCUMENT_INSTEAD = "link to the document's https address, or export it elsewhere"
OTHER_DOCUMENT_WHY = (
    "{target} cannot link 'the plan' to the document 'cold-room-plan', "
    "since skaldr has no address for that document there"
)
TEXT_REFUSALS: dict[str, RefusedCase] = {
    "markdown-colour-span": RefusedCase(
        "markdown",
        COLOURED_TEXT,
        GITHUB_COLOUR_WHY.format(text="behind"),
        WITHOUT_THE_COLOUR,
        "at blocks.0.text",
    ),
    "slack-colour-span": RefusedCase(
        "slack",
        COLOURED_TEXT,
        CANVAS_COLOUR_WHY.format(text="behind"),
        WITHOUT_THE_COLOUR,
        "at blocks.0.text",
    ),
    "slack-highlight-span": RefusedCase(
        "slack",
        HIGHLIGHTED_TEXT,
        "a Slack canvas cannot highlight text, so it cannot show the highlight on 'due Friday'",
        "write the text without the highlight or export the document elsewhere",
        "at blocks.0.text",
    ),
    "markdown-colour-and-highlight-span": RefusedCase(
        "markdown",
        COLOURED_AND_HIGHLIGHTED_TEXT,
        GITHUB_COLOUR_WHY.format(text="vendor lots"),
        WITHOUT_THE_COLOUR,
        "at blocks.0.text",
    ),
    "notion-colour-and-highlight-span": RefusedCase(
        "notion",
        COLOURED_AND_HIGHLIGHTED_TEXT,
        "a Notion text run takes a colour or a highlight, not both, so it cannot show both on 'vendor lots'",
        "keep either the colour or the highlight on the text",
        "at blocks.0.text",
    ),
    "slack-colour-and-highlight-span": RefusedCase(
        "slack",
        COLOURED_AND_HIGHLIGHTED_TEXT,
        CANVAS_COLOUR_WHY.format(text="vendor lots"),
        WITHOUT_THE_COLOUR,
        "at blocks.0.text",
    ),
    "slack-underline": RefusedCase(
        "slack",
        UNDERLINED_TEXT,
        "a Slack canvas cannot underline text, so it cannot show the underline on 'check digit'",
        "write the text without the underline or export the document elsewhere",
        "at blocks.0.text",
    ),
    "notion-link-to-a-heading": RefusedCase(
        "notion",
        LINK_TO_A_SECTION,
        OWN_HEADING_WHY.format(target="a Notion page"),
        OWN_HEADING_INSTEAD,
        "at blocks.1.text",
    ),
    "adf-link-to-a-heading": RefusedCase(
        "adf",
        LINK_TO_A_SECTION,
        OWN_HEADING_WHY.format(target="a Jira description"),
        OWN_HEADING_INSTEAD,
        "at blocks.1.text",
    ),
    "slack-link-to-a-heading": RefusedCase(
        "slack",
        LINK_TO_A_SECTION,
        OWN_HEADING_WHY.format(target="a Slack canvas"),
        OWN_HEADING_INSTEAD,
        "at blocks.1.text",
    ),
    "notion-link-to-another-document": RefusedCase(
        "notion",
        LINK_TO_ANOTHER_DOCUMENT,
        OTHER_DOCUMENT_WHY.format(target="Notion"),
        OTHER_DOCUMENT_INSTEAD,
        "at blocks.0.text",
    ),
    "slack-link-to-another-document": RefusedCase(
        "slack",
        LINK_TO_ANOTHER_DOCUMENT,
        OTHER_DOCUMENT_WHY.format(target="a Slack canvas"),
        OTHER_DOCUMENT_INSTEAD,
        "at blocks.0.text",
    ),
    "notion-inline-code-holding-a-backtick": RefusedCase(
        "notion",
        [{"type": "text", "body": "Split on `` a`b `` first."}],
        "Notion cannot show inline code holding a backtick, as in 'a`b'",
        "write the code in a code block, or without the backtick",
        "at blocks.0.text",
    ),
    "notion-inline-code-holding-a-closing-tag-in-a-table-cell": RefusedCase(
        "notion",
        [
            {
                "type": "table",
                "columns": [{"key": "tag", "label": "Tag"}],
                "rows": [{"tag": "Ends with `</td>`."}],
            }
        ],
        "Notion loses a table cell whose inline code holds '</', as in '</td>'",
        "write the code outside the table, or without '</'",
        "at blocks.0.table",
    ),
}
SEEDED_REFUSALS: dict[str, RefusedCase] = {**ADF_REFUSALS, **SLACK_REFUSALS, **TEXT_REFUSALS}
ADF_CASES = [pytest.param(case, id=name) for name, case in SEEDED_REFUSALS.items() if case.target == "adf"]
SEEDED_CASES = [pytest.param(case, id=name) for name, case in SEEDED_REFUSALS.items()]

CLEAN_BLOCKS: list[dict[str, Any]] = [
    {"type": "heading", "text": "Plan"},
    {"type": "text", "body": "1. a\n2. b"},
    {"type": "panel", "title": "Plan", "blocks": [{"type": "text", "body": "Inside."}]},
    make_toggle(TABLE),
    make_toggle(make_toggle()),
    walkthrough_holding({"type": "text", "body": "Lock the aisle."}),
    {
        "type": "section",
        "id": "counts",
        "title": "Counts",
        "fields": {"links": {"relates": ["totals"]}},
        "blocks": [{"type": "text", "body": "Ten."}],
    },
    {"type": "section", "id": "totals", "title": "Totals", "blocks": [{"type": "text", "body": "Twenty."}]},
    {
        "type": "walkthrough",
        "steps": [{"label": "Scan", "tone": "info", "detail": [{"type": "text", "body": "Both aisles."}]}],
    },
]
