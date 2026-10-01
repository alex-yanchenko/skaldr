from typing import Any

from skaldr.compute import (
    derived_card_tally,
    matrix_tallies,
    swimlane_state_legend,
    swimlane_totals,
    table_tallies,
)
from skaldr.models import Cards, Swimlane, Table, parse_report
from tests.factories import API_BADGES, make_report


def _swimlane(steps: list[dict[str, Any]]) -> Swimlane:
    block = {
        "type": "swimlane",
        "lanes": list(dict.fromkeys(step["lane"] for step in steps)),
        "columns": list(dict.fromkeys(step["col"] for step in steps)),
        "groups": [{"name": "Q1", "color": "blue", "columns": ["Plan"]}],
        "steps": steps,
    }
    swimlane = parse_report(make_report(blocks=[block])).blocks[0]
    assert isinstance(swimlane, Swimlane)
    return swimlane


def test_a_swimlane_with_no_values_has_no_totals() -> None:
    assert swimlane_totals(_swimlane([{"lane": "Ops", "col": "Plan", "n": "1", "label": "a"}])) is None


def test_swimlane_totals_sum_each_lane_column_and_group_counting_a_missing_value_as_zero() -> None:
    steps = [
        {"lane": "Ops", "col": "Plan", "n": "1", "label": "a", "value": 2},
        {"lane": "Dev", "col": "Plan", "n": "2", "label": "b", "value": 3},
        {"lane": "Dev", "col": "Ship", "n": "3", "label": "c"},
    ]

    assert swimlane_totals(_swimlane(steps)) == {
        "lanes": {"Ops": 2, "Dev": 3},
        "columns": {"Plan": 5, "Ship": 0},
        "groups": {"Q1": 5},
    }


def test_the_swimlane_state_legend_lists_two_or_more_states_in_canonical_order() -> None:
    one_state = [{"lane": "Ops", "col": "Plan", "n": "1", "label": "a", "state": "done"}]
    three_states = [
        {"lane": "Ops", "col": "Plan", "n": "1", "label": "a", "state": "blocked"},
        {"lane": "Ops", "col": "Ship", "n": "2", "label": "b", "state": "done"},
        {"lane": "Dev", "col": "Ship", "n": "3", "label": "c", "state": "deferred"},
    ]

    assert (swimlane_state_legend(_swimlane(one_state)), swimlane_state_legend(_swimlane(three_states))) == (
        [],
        ["done", "blocked", "deferred"],
    )


def test_a_derived_card_tally_reads_a_matrix_or_sums_its_tables() -> None:
    tagged = {
        "type": "table",
        "columns": [{"key": "a", "label": "A"}, {"key": "tag", "label": "", "kind": "badge"}],
        "rollup": {"by": "tag"},
    }
    report = parse_report(
        make_report(
            badges=API_BADGES,
            blocks=[
                {
                    "type": "cards",
                    "items": [
                        {"badge": "API", "of_matrix": "m"},
                        {"badge": "API", "of_tables": ["t1", "t2"]},
                    ],
                },
                {
                    "type": "matrix",
                    "id": "m",
                    "rows": ["r1", "r2"],
                    "columns": ["c"],
                    "cells": [{"row": "r1", "col": "c", "badge": "API"}],
                },
                {**tagged, "id": "t1", "rows": [{"a": "x", "tag": "API"}, {"a": "y", "tag": ""}]},
                {**tagged, "id": "t2", "rows": [{"a": "z", "tag": "API"}]},
            ],
        )
    )
    cards = report.blocks[0]
    assert isinstance(cards, Cards)

    assert [
        derived_card_tally(card, matrix_tallies(report), table_tallies(report)) for card in cards.items
    ] == [
        (1, 2),
        (2, 3),
    ]


def test_a_table_titles_its_first_text_column_and_sums_its_reconcile_or_totals_column() -> None:
    blocks = [
        {
            "type": "table",
            "columns": [
                {"key": "n", "label": "N", "kind": "number"},
                {"key": "r", "label": "R", "kind": "rich"},
            ],
            "totals": {"column": "n"},
            "rows": [{"n": 1, "r": "x"}],
        },
        {
            "type": "table",
            "columns": [
                {"key": "r", "label": "R", "kind": "rich"},
                {"key": "t", "label": "T"},
                {"key": "n", "label": "N", "kind": "number"},
            ],
            "reconcile": {"total": 3, "column": "n", "handled": {"label": "Clean", "value": 2}},
            "rows": [{"r": "x", "t": "y", "n": 1}],
        },
        {"type": "table", "columns": [{"key": "t", "label": "T"}], "rows": [{"t": "y"}]},
    ]
    tables = parse_report(make_report(blocks=blocks)).blocks

    assert [(table.title_key, table.sum_key) for table in tables if isinstance(table, Table)] == [
        ("r", "n"),
        ("t", "n"),
        ("t", None),
    ]
