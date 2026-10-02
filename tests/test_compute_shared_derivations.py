from typing import Any

import pytest

from skaldr.compute import (
    DerivedCardTally,
    MatrixCellDisplay,
    derived_card_tally,
    matrix_cell_display,
    matrix_tallies,
    swimlane_state_legend,
    swimlane_totals,
    table_tallies,
)
from skaldr.models import Card, Cards, Comparison, MatrixCell, Swimlane, Table, parse_report
from tests.factories import API_BADGES, make_report, make_swimlane, make_table, parsed_block

Q1_ON_PLAN: list[dict[str, Any]] = [{"name": "Q1", "color": "blue", "columns": ["Plan"]}]
TAGGED_COLUMNS: list[dict[str, Any]] = [
    {"key": "a", "label": "A"},
    {"key": "tag", "label": "", "kind": "badge", "placement": "cell"},
]


def test_a_swimlane_with_no_values_has_no_totals() -> None:
    swimlane = parsed_block(
        Swimlane, make_swimlane([{"lane": "Ops", "col": "Plan", "n": "1", "label": "a"}], groups=Q1_ON_PLAN)
    )

    assert swimlane_totals(swimlane) is None


def test_swimlane_totals_sum_each_lane_column_and_group_counting_a_missing_value_as_zero() -> None:
    steps = [
        {"lane": "Ops", "col": "Plan", "n": "1", "label": "a", "value": 2},
        {"lane": "Dev", "col": "Plan", "n": "2", "label": "b", "value": 3},
        {"lane": "Dev", "col": "Ship", "n": "3", "label": "c"},
    ]

    assert swimlane_totals(parsed_block(Swimlane, make_swimlane(steps, groups=Q1_ON_PLAN))) == {
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
    legends = [
        swimlane_state_legend(parsed_block(Swimlane, make_swimlane(steps)))
        for steps in (one_state, three_states)
    ]

    assert legends == [[], ["done", "blocked", "deferred"]]


def test_a_derived_card_tally_reads_a_matrix_or_sums_its_tables() -> None:
    tagged = make_table(TAGGED_COLUMNS, rollup={"by": "tag"})
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
    matrices, tables = matrix_tallies(report), table_tallies(report)

    assert [derived_card_tally(card, "API", matrices, tables) for card in cards.items] == [
        DerivedCardTally(counted=1, total=2),
        DerivedCardTally(counted=2, total=3),
    ]


def test_a_derived_card_takes_the_semantic_twin_of_its_badge_colour_unless_it_sets_a_tone() -> None:
    badge = parse_report(make_report(badges=API_BADGES)).badges["API"]
    cards = [Card(badge="API", of_matrix="m"), Card(badge="API", of_matrix="m", tone="danger")]

    assert [card.tone_with(badge) for card in cards] == ["info", "danger"]


def test_a_table_titles_its_first_text_column_and_sums_its_reconcile_or_totals_column() -> None:
    blocks = [
        make_table(
            [{"key": "n", "label": "N", "kind": "number"}, {"key": "r", "label": "R", "kind": "rich"}],
            totals={"column": "n"},
            rows=[{"n": 1, "r": "x"}],
        ),
        make_table(
            [
                {"key": "r", "label": "R", "kind": "rich"},
                {"key": "t", "label": "T"},
                {"key": "n", "label": "N", "kind": "number"},
            ],
            reconcile={"total": 3, "column": "n", "handled": {"label": "Clean", "value": 2}},
            rows=[{"r": "x", "t": "y", "n": 1}],
        ),
        make_table([{"key": "t", "label": "T"}], rows=[{"t": "y"}]),
    ]
    tables = [parsed_block(Table, block) for block in blocks]

    assert [(table.title_key, table.sum_key) for table in tables] == [("r", "n"), ("t", "n"), ("t", None)]


def test_a_row_tints_by_the_first_key_of_its_tint_column_and_a_blank_first_key_tints_nothing() -> None:
    table = parsed_block(
        Table, make_table(TAGGED_COLUMNS, tint_by="tag", rows=[{"a": "x", "tag": "API"}]), badges=API_BADGES
    )
    rows: list[dict[str, Any]] = [{"tag": " API "}, {"tag": ["API", ""]}, {"tag": ["", "API"]}, {}]

    assert [table.row_tint_key(row) for row in rows] == ["API", "API", "", ""]


def test_a_badge_cell_reads_one_key_or_a_list_trimmed_with_blanks_dropped() -> None:
    table = parsed_block(
        Table, make_table(TAGGED_COLUMNS, rows=[{"a": "x", "tag": "API"}]), badges=API_BADGES
    )
    rows: list[dict[str, Any]] = [
        {"tag": " API "},
        {"tag": ["API", " ", "OPS "]},
        {"tag": ""},
        {"tag": None},
        {},
    ]

    assert [table.badge_keys(row, "tag") for row in rows] == [["API"], ["API", "OPS"], [], [], []]


def test_a_swimlane_places_each_step_by_lane_column_and_resolved_group() -> None:
    steps = [
        {"lane": "Ops", "col": "Plan", "n": "1", "label": "a"},
        {"lane": "Ops", "col": "Ship", "n": "2", "label": "b"},
        {"lane": "Ops", "col": "Plan", "n": "3", "label": "c"},
    ]
    swimlane = parsed_block(Swimlane, make_swimlane(steps, groups=Q1_ON_PLAN))
    first, second, third = swimlane.steps

    assert (
        swimlane.steps_at("Ops", "Plan", "Q1"),
        swimlane.steps_at("Ops", "Ship", None),
        swimlane.steps_at("Ops", "Plan", None),
    ) == ((first, third), (second,), ())


def test_a_swimlane_group_spans_its_first_and_last_subcolumn() -> None:
    steps = [
        {"lane": "Ops", "col": "Plan", "n": "1", "label": "a", "group": "A"},
        {"lane": "Ops", "col": "Build", "n": "2", "label": "b", "group": "B"},
        {"lane": "Ops", "col": "Ship", "n": "3", "label": "c"},
    ]
    groups = [
        {"name": "A", "color": "blue", "columns": ["Plan", "Build"]},
        {"name": "B", "color": "amber", "columns": ["Build"]},
    ]

    assert parsed_block(Swimlane, make_swimlane(steps, groups=groups)).group_spans == {
        "A": (0, 1),
        "B": (2, 2),
    }


def test_a_swimlane_column_spans_its_first_and_last_segment() -> None:
    steps = [
        {"lane": "Ops", "col": "Plan", "n": "1", "label": "a", "group": "A"},
        {"lane": "Ops", "col": "Build", "n": "2", "label": "b", "group": "B"},
        {"lane": "Ops", "col": "Ship", "n": "3", "label": "c"},
    ]
    groups = [
        {"name": "A", "color": "blue", "columns": ["Plan", "Build"]},
        {"name": "B", "color": "amber", "columns": ["Build"]},
    ]

    assert parsed_block(Swimlane, make_swimlane(steps, groups=groups)).column_spans == {
        "Plan": (0, 0),
        "Build": (1, 2),
        "Ship": (3, 3),
    }


@pytest.mark.parametrize(
    ("polarity", "negative"),
    [
        pytest.param(None, [False, False], id="no-polarity-is-all-positive"),
        pytest.param(["negative", "positive"], [True, False], id="per-option"),
    ],
)
def test_a_comparison_option_is_negative_only_when_its_polarity_says_so(
    polarity: list[str] | None, negative: list[bool]
) -> None:
    block = {
        "type": "comparison",
        "options": ["A", "B"],
        "rows": [{"feature": "Risky", "values": [True, False]}],
        **({"polarity": polarity} if polarity else {}),
    }
    comparison = parsed_block(Comparison, block)

    assert [comparison.is_negative(index) for index in range(len(comparison.options))] == negative


def test_a_step_needs_the_numbers_of_its_dependencies_once_each_in_order() -> None:
    steps = [
        {"id": "a", "lane": "Ops", "col": "Plan", "n": "1", "label": "a"},
        {"id": "b", "lane": "Ops", "col": "Plan", "n": "1", "label": "b"},
        {"id": "c", "lane": "Ops", "col": "Plan", "n": "2", "label": "c"},
        {"lane": "Ops", "col": "Plan", "n": "3", "label": "d", "depends_on": ["c", "a", "b"]},
    ]
    swimlane = parsed_block(Swimlane, make_swimlane(steps))

    assert swimlane.dependency_numbers(swimlane.steps[3]) == ["2", "1"]


def test_a_matrix_cell_shows_its_badge_tone_and_label_unless_it_names_its_own() -> None:
    badges = parse_report(make_report(badges=API_BADGES)).badges
    cells = [
        MatrixCell(row="r", col="c", badge="API"),
        MatrixCell(row="r", col="c", badge="API", label="yes"),
        MatrixCell(row="r", col="c", tone="amber"),
        MatrixCell(row="r", col="c", label="n/a"),
    ]

    assert [matrix_cell_display(cell, badges) for cell in cells] == [
        MatrixCellDisplay(tone="blue", text="api"),
        MatrixCellDisplay(tone="blue", text="yes"),
        MatrixCellDisplay(tone="amber", text=""),
        MatrixCellDisplay(tone=None, text="n/a"),
    ]
