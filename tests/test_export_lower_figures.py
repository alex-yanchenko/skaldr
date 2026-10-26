from typing import Any

import pytest

from skaldr.export.inline import bold
from skaldr.export.runs import Chip, ExportRich, Gauge, StatusMark, TonedLabel
from skaldr.export.tree import (
    Card,
    Cards,
    FactStrip,
    KeyValueList,
    LabelledValue,
    ListEntry,
    ListNode,
    Paragraph,
    TableCell,
    TableNode,
    TableRow,
    Timeline,
    TimelineEvent,
    Toggle,
)
from skaldr.models import ToneLiteral
from skaldr.richtext import Plain, Styled
from tests.factories import API_BADGES, lowered, lowered_as_written_today
from tests.factories.lower_factory import API_LEGEND, cell_texts_of


def test_a_card_shows_its_share_delta_badges_and_note() -> None:
    card = {
        "label": "Clean",
        "value": 9,
        "of": 10,
        "tone": "success",
        "delta": {"label": "+1", "direction": "up"},
        "badges": ["API"],
        "note": "since Monday",
    }

    assert lowered_as_written_today([{"type": "cards", "items": [card]}], badges=API_BADGES) == (
        API_LEGEND,
        ListNode(
            "bullet",
            (
                ListEntry(
                    (
                        TonedLabel("success", bold("Clean")),
                        Plain(": "),
                        Plain("9"),
                        Plain(" "),
                        Plain("(90.0%)"),
                        Plain(" "),
                        Plain("▲ +1"),
                        Plain(" "),
                        Chip("api", "blue"),
                    ),
                    children=(Paragraph((Plain("since Monday"),), "muted"),),
                ),
            ),
        ),
    )


@pytest.mark.parametrize(
    ("card", "text"),
    [
        pytest.param(
            {"label": "Site", "value": "West"}, (*bold("Site"), Plain(": "), Plain("West")), id="text-value"
        ),
        pytest.param(
            {"label": "Lag", "value": 3, "delta": {"label": "flat"}},
            (*bold("Lag"), Plain(": "), Plain("3"), Plain(" "), Plain("flat")),
            id="delta-without-direction",
        ),
        pytest.param(
            {"label": "Cost", "value": 5, "delta": {"label": "-8%", "direction": "down", "tone": "success"}},
            (*bold("Cost"), Plain(": "), Plain("5"), Plain(" "), Chip("▼ -8%", "green")),
            id="toned-delta-is-a-colored-chip",
        ),
        pytest.param(
            {"label": "Site", "value": "West", "tone": "danger"},
            (TonedLabel("danger", bold("Site")), Plain(": "), Plain("West")),
            id="tone-colours-the-label-only",
        ),
        pytest.param(
            {"label": "Cost", "value": 5, "tone": "danger", "delta": {"label": "-8%", "tone": "success"}},
            (TonedLabel("danger", bold("Cost")), Plain(": "), Plain("5"), Plain(" "), Chip("-8%", "green")),
            id="a-toned-delta-keeps-its-own-colour-beside-the-coloured-label",
        ),
        pytest.param({"label": " ", "value": 7}, (Plain("7"),), id="blank-label"),
        pytest.param(
            {"label": " ", "value": 7, "tone": "danger"},
            (Plain("7"),),
            id="a-blank-label-has-nothing-to-colour",
        ),
        pytest.param({"label": "Empty", "value": ""}, bold("Empty"), id="empty-value-is-the-label-alone"),
    ],
)
def test_a_card_shows_only_the_parts_it_has(card: dict[str, Any], text: ExportRich) -> None:
    assert lowered_as_written_today([{"type": "cards", "items": [card]}]) == (
        ListNode("bullet", (ListEntry(text),)),
    )


@pytest.mark.parametrize(
    ("tone", "label"),
    [
        pytest.param("info", bold("Cost"), id="a-badge-of-the-same-colour-carries-the-tone"),
        pytest.param(
            "danger", (TonedLabel("danger", bold("Cost")),), id="a-badge-of-another-colour-does-not"
        ),
    ],
)
def test_a_toned_card_leaves_its_colour_only_to_a_badge_of_the_same_colour(
    tone: ToneLiteral, label: ExportRich
) -> None:
    card = {"label": "Cost", "value": 5, "tone": tone, "badges": ["API"]}

    assert lowered_as_written_today([{"type": "cards", "items": [card]}], badges=API_BADGES) == (
        API_LEGEND,
        ListNode("bullet", (ListEntry((*label, Plain(": "), Plain("5"), Plain(" "), Chip("api", "blue"))),)),
    )


def test_a_derived_card_counts_its_badge_in_a_matrix_and_leaves_its_colour_to_the_badge() -> None:
    blocks = [
        {"type": "cards", "items": [{"badge": "API", "of_matrix": "m", "note": "live"}]},
        {
            "type": "matrix",
            "id": "m",
            "rows": ["r1", "r2"],
            "columns": ["c"],
            "cells": [{"row": "r1", "col": "c", "badge": "API"}],
        },
    ]

    assert lowered_as_written_today(blocks, badges=API_BADGES) == (
        API_LEGEND,
        ListNode(
            "bullet",
            (
                ListEntry(
                    (Chip("api", "blue"), Plain(": 1 (50.0%)")),
                    children=(Paragraph((Plain("live"),), "muted"),),
                ),
            ),
        ),
        TableNode(
            (TableCell(()), *cell_texts_of("c")),
            (
                TableRow((TableCell((Plain("r1"),)), TableCell((Plain("api"),), "info"))),
                TableRow((TableCell((Plain("r2"),)), TableCell(()))),
            ),
            header_column=True,
        ),
    )


def test_a_derived_card_sums_its_tables_and_leaves_its_colour_to_its_badge() -> None:
    blocks = [
        {
            "type": "cards",
            "items": [{"badge": "API", "of_tables": ["t"], "label": "API rows", "tone": "danger"}],
        },
        {
            "type": "table",
            "id": "t",
            "columns": [{"key": "a", "label": "A"}, {"key": "tag", "label": "", "kind": "badge"}],
            "rollup": {"by": "tag"},
            "rows": [{"a": "x", "tag": "API"}, {"a": "y", "tag": ""}],
        },
    ]

    assert lowered_as_written_today(blocks, badges=API_BADGES) == (
        ListNode("bullet", (ListEntry((Chip("API rows", "blue"), Plain(": 1 (50.0%)"))),)),
        API_LEGEND,
        TableNode(
            cell_texts_of("A"),
            (
                TableRow((TableCell((Plain("x"), Plain(" "), Chip("api", "blue"))),)),
                TableRow((TableCell((Plain("y"),)),)),
            ),
        ),
        Paragraph((Chip("api", "blue"), Plain(" "), Plain("1"))),
    )


def test_a_fact_strip_and_a_key_value_block_lower_to_their_labelled_values() -> None:
    blocks = [
        {
            "type": "fact_strip",
            "facts": [{"label": "Site:", "value": "West  wing"}, {"label": " ", "value": "x"}],
        },
        {"type": "key_value", "pairs": [{"label": "Owner", "value": "**ops**"}]},
    ]

    assert lowered(blocks) == (
        FactStrip((LabelledValue("Site:", (Plain("West wing"),)), LabelledValue(" ", (Plain("x"),)))),
        KeyValueList((LabelledValue("Owner", (Styled("bold", (Plain("ops"),)),)),)),
    )


def test_cards_lower_to_a_card_per_item_with_a_derived_card_led_by_its_badge_colour() -> None:
    blocks = [
        {
            "type": "cards",
            "items": [
                {
                    "label": "Clean",
                    "value": 9,
                    "of": 10,
                    "tone": "success",
                    "delta": {"label": "+1", "direction": "up"},
                    "badges": ["API"],
                    "note": "since Monday",
                },
                {"label": "Cost", "value": 5, "tone": "info", "badges": ["API"]},
                {"badge": "API", "of_matrix": "m", "note": "live"},
            ],
        },
        {
            "type": "matrix",
            "id": "m",
            "rows": ["r1", "r2"],
            "columns": ["c"],
            "cells": [{"row": "r1", "col": "c", "badge": "API"}],
        },
    ]

    assert lowered(blocks, badges=API_BADGES)[1] == Cards(
        (
            Card(
                "Clean",
                (
                    Plain("9"),
                    Plain(" "),
                    Plain("(90.0%)"),
                    Plain(" "),
                    Plain("▲ +1"),
                    Plain(" "),
                    Chip("api", "blue"),
                ),
                note="since Monday",
                tone="success",
            ),
            Card("Cost", (Plain("5"), Plain(" "), Chip("api", "blue"))),
            Card("api", (Plain("1 (50.0%)"),), note="live", badge="blue"),
        )
    )


def test_a_timeline_lowers_to_its_events_with_their_state_chips_and_body() -> None:
    block = {
        "type": "timeline",
        "items": [
            {"time": "Mon", "title": "Start", "state": "done", "badges": ["API"], "body": "kick-off"},
            {"title": "Later"},
        ],
    }

    assert lowered([block], badges=API_BADGES)[1] == Timeline(
        (
            TimelineEvent(
                "Start", time="Mon", state="done", chips=(Chip("api", "blue"),), body=(Plain("kick-off"),)
            ),
            TimelineEvent("Later"),
        )
    )


def test_fact_strip_and_key_value_entries_are_labelled_bullets() -> None:
    blocks = [
        {
            "type": "fact_strip",
            "facts": [{"label": "Site:", "value": "West  wing"}, {"label": " ", "value": "x"}],
        },
        {"type": "key_value", "pairs": [{"label": "Owner", "value": "**ops**"}]},
    ]

    assert lowered_as_written_today(blocks) == (
        ListNode(
            "bullet",
            (ListEntry((*bold("Site"), Plain(": "), Plain("West wing"))), ListEntry((Plain("x"),))),
        ),
        ListNode("bullet", (ListEntry((*bold("Owner"), Plain(": "), Styled("bold", (Plain("ops"),)))),)),
    )


def test_a_meter_reading_is_a_gauge_with_its_share_and_tone() -> None:
    meter = {"type": "meter", "items": [{"label": "Zone", "value": 5, "max": 10, "tone": "warning"}]}

    assert lowered([meter]) == (
        ListNode(
            "bullet",
            (
                ListEntry(
                    (
                        TonedLabel("warning", bold("Zone")),
                        Plain(": "),
                        Gauge(5, 10),
                        Plain(" "),
                        Plain("50.0%"),
                    )
                ),
            ),
        ),
    )


def test_a_range_lowers_to_no_node() -> None:
    block = {
        "type": "range",
        "axis": {"min": "Jan", "max": "Dec"},
        "segments": [
            {"label": "Seg", "span": 1, "tone": "danger", "sub": "one"},
            {"label": "Rest", "span": 3},
        ],
    }

    assert lowered([{"type": "text", "body": "Before."}, block]) == (Paragraph((Plain("Before."),)),)


def test_status_and_timeline_entries_lead_with_their_state_mark() -> None:
    blocks = [
        {"type": "status_list", "items": [{"state": "blocked", "text": "Vendor"}]},
        {
            "type": "timeline",
            "items": [
                {"time": "Mon", "title": "Start", "state": "done", "badges": ["API"], "body": "kick-off"},
                {"title": "Later"},
            ],
        },
    ]

    assert lowered_as_written_today(blocks, badges=API_BADGES) == (
        API_LEGEND,
        ListNode("bullet", (ListEntry((StatusMark("blocked"), Plain(" "), Plain("Vendor"))),)),
        ListNode(
            "bullet",
            (
                ListEntry(
                    (
                        StatusMark("done"),
                        Plain(" "),
                        *bold("Mon"),
                        Plain(": "),
                        Plain("Start"),
                        Plain(" "),
                        Chip("api", "blue"),
                    ),
                    children=(Paragraph((Plain("kick-off"),)),),
                ),
                ListEntry((Plain("Later"),)),
            ),
        ),
    )


def test_a_definition_keeps_its_later_paragraphs_and_an_empty_body_is_its_term_alone() -> None:
    block = {
        "type": "def_list",
        "items": [{"term": "Fix", "body": "first\n\nsecond"}, {"term": "Gap", "body": " "}],
    }

    assert lowered_as_written_today([block]) == (
        ListNode(
            "bullet",
            (
                ListEntry(
                    (*bold("Fix"), Plain(": "), Plain("first")), children=(Paragraph((Plain("second"),)),)
                ),
                ListEntry(bold("Gap")),
            ),
        ),
    )


def test_a_badge_row_is_a_labelled_line_and_its_groups_are_labelled_bullets() -> None:
    blocks = [
        {
            "type": "badge_row",
            "label": "Affects:",
            "items": [{"key": "API"}, {"label": "two\nlines", "tone": "red"}],
        },
        {"type": "badge_row", "groups": [{"label": "Owners:", "items": [{"label": "ops", "tone": "teal"}]}]},
    ]

    assert lowered(blocks, badges=API_BADGES) == (
        API_LEGEND,
        Paragraph((*bold("Affects"), Plain(": "), Chip("api", "blue"), Plain(" "), Chip("two lines", "red"))),
        ListNode("bullet", (ListEntry((*bold("Owners"), Plain(": "), Chip("ops", "teal"))),)),
    )


def test_a_badge_label_or_legend_with_a_line_break_stays_on_one_line() -> None:
    badges = {"API": {"label": "a\npi", "tone": "blue", "legend": "the API,\n- folded\n"}}

    assert lowered([{"type": "badge_row", "items": [{"key": "API"}]}], badges=badges) == (
        Toggle(
            (Plain("Legend: badges used on this page"),),
            None,
            (
                ListNode(
                    "bullet", (ListEntry((Chip("a pi", "blue"), Plain(" "), Plain("the API, - folded"))),)
                ),
            ),
        ),
        Paragraph((Chip("a pi", "blue"),)),
    )
