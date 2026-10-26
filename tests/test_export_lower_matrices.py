import pytest

from skaldr.export.inline import bold, italic, plain
from skaldr.export.lower.context import spaced
from skaldr.export.runs import Break, CheckMark, SwimlaneMark
from skaldr.export.tree import Paragraph, TableCell, TableNode, TableRow
from skaldr.models import SwimlaneStepState
from skaldr.richtext import Link, Plain
from tests.factories import API_BADGES, HAVE_BADGE, MATRIX_OF_EVERY_CELL_SHAPE, lowered
from tests.factories.lower_factory import API_LEGEND, cell_texts_of


@pytest.mark.parametrize(
    ("value", "polarity", "cell"),
    [
        pytest.param(True, "positive", TableCell((CheckMark(checked=True),), "success"), id="yes-is-good"),
        pytest.param(False, "positive", TableCell((CheckMark(checked=False),), "danger"), id="no-is-bad"),
        pytest.param(
            True, "negative", TableCell((CheckMark(checked=True),), "danger"), id="yes-on-a-risk-is-bad"
        ),
        pytest.param(
            False, "negative", TableCell((CheckMark(checked=False),), "success"), id="no-on-a-risk-is-good"
        ),
    ],
)
def test_a_comparison_colors_a_boolean_by_its_option_polarity(
    value: bool, polarity: str, cell: TableCell
) -> None:
    comparison = {
        "type": "comparison",
        "options": ["A", "B"],
        "polarity": [polarity, "positive"],
        "rows": [{"feature": "Risky", "values": [value, True]}],
    }

    assert lowered([comparison]) == (
        TableNode(
            (TableCell(()), *cell_texts_of("A", "B")),
            (
                TableRow(
                    (TableCell((Plain("Risky"),)), cell, TableCell((CheckMark(checked=True),), "success"))
                ),
            ),
            header_column=True,
        ),
    )


def test_a_comparison_bolds_its_highlighted_option_and_keeps_text_and_toned_cells() -> None:
    comparison = {
        "type": "comparison",
        "options": ["A", "B"],
        "highlight": 1,
        "rows": [{"feature": "Note", "values": ["plain", {"value": "toned", "tone": "warning"}]}],
    }

    assert lowered([comparison]) == (
        TableNode(
            (TableCell(()), TableCell((Plain("A"),)), TableCell((Plain("★ B"),))),
            (
                TableRow(
                    (
                        TableCell((Plain("Note"),)),
                        TableCell((Plain("plain"),)),
                        TableCell((Plain("toned"),), "warning"),
                    )
                ),
            ),
            header_column=True,
        ),
    )


def test_a_matrix_shows_badge_toned_labelled_and_blank_cells() -> None:
    matrix = {
        "type": "matrix",
        "rows": ["r1"],
        "columns": ["c1", "c2", "c3", "c4"],
        "cells": [
            {"row": "r1", "col": "c1", "badge": "API"},
            {"row": "r1", "col": "c2", "badge": "API", "label": "yes"},
            {"row": "r1", "col": "c3", "label": "n/a", "tone": "neutral"},
        ],
    }

    assert lowered([matrix], badges=API_BADGES) == (
        API_LEGEND,
        TableNode(
            (TableCell(()), *cell_texts_of("c1", "c2", "c3", "c4")),
            (
                TableRow(
                    (
                        TableCell((Plain("r1"),)),
                        TableCell((Plain("api"),), "info"),
                        TableCell((*bold("api"), Plain(" · "), Plain("yes")), "info"),
                        TableCell((Plain("n/a"),), "neutral"),
                        TableCell(()),
                    )
                ),
            ),
            header_column=True,
        ),
    )


def test_a_matrix_cell_with_a_badge_and_a_label_leads_with_the_badge_name() -> None:
    assert lowered([MATRIX_OF_EVERY_CELL_SHAPE], badges=HAVE_BADGE) == (
        TableNode(
            (TableCell(()), *cell_texts_of("Badge", "Both", "Tone", "Label")),
            (
                TableRow(
                    (
                        TableCell((Plain("Receiving"),)),
                        TableCell((Plain("Have"),), "success"),
                        TableCell((*bold("Have"), Plain(" · "), Plain("runbook v2")), "success"),
                        TableCell((Plain("none yet"),), "danger"),
                        TableCell((Plain("n/a"),)),
                    )
                ),
            ),
            header_column=True,
        ),
    )


def test_a_swimlane_shows_a_group_total_once_where_the_group_starts() -> None:
    swimlane = {
        "type": "swimlane",
        "lanes": ["Ops"],
        "columns": [{"name": "Plan", "sub": "wk 1"}, "Ship"],
        "groups": [{"name": "Q1", "color": "blue", "columns": ["Plan", "Ship"]}],
        "steps": [
            {"lane": "Ops", "col": "Plan", "n": "1", "label": "Draft", "value": 2, "state": "done"},
            {"lane": "Ops", "col": "Ship", "n": "2", "label": "Send", "value": 3, "state": "blocked"},
        ],
    }

    assert lowered([swimlane]) == (
        TableNode(
            (
                TableCell((Plain("Lane"),)),
                TableCell(
                    (
                        Plain("Plan"),
                        Break(),
                        *italic(plain("wk 1")),
                        Break(),
                        Plain("Q1"),
                        Plain(" "),
                        Plain("(5)"),
                    )
                ),
                TableCell((Plain("Ship"),)),
            ),
            (
                TableRow(
                    (
                        TableCell((Plain("Ops"), Plain(" "), Plain("(5)"))),
                        TableCell(
                            (
                                SwimlaneMark("done"),
                                Plain(" "),
                                *bold("1"),
                                Plain(" "),
                                Plain("Draft"),
                                Plain(" "),
                                Plain("(2)"),
                            )
                        ),
                        TableCell(
                            (
                                SwimlaneMark("blocked"),
                                Plain(" "),
                                *bold("2"),
                                Plain(" "),
                                Plain("Send"),
                                Plain(" "),
                                Plain("(3)"),
                            )
                        ),
                    )
                ),
                TableRow(cell_texts_of("Total", "2", "3"), emphasis="total"),
            ),
            header_column=True,
        ),
        Paragraph(
            (
                SwimlaneMark("done"),
                Plain(" "),
                Plain("done"),
                Plain(" · "),
                SwimlaneMark("blocked"),
                Plain(" "),
                Plain("blocked"),
            ),
            "muted",
        ),
    )


def test_a_split_swimlane_column_names_each_step_group_and_its_dependencies_once() -> None:
    swimlane = {
        "type": "swimlane",
        "lanes": ["Ops"],
        "columns": ["Plan"],
        "groups": [
            {"name": "A", "color": "blue", "columns": ["Plan"]},
            {"name": "B", "color": "amber", "columns": ["Plan"]},
        ],
        "steps": [
            {
                "lane": "Ops",
                "col": "Plan",
                "n": "2",
                "label": "Send",
                "state": "deferred",
                "group": "B",
                "url": "https://e.com/2",
                "depends_on": ["first", "again"],
            },
            {"id": "first", "lane": "Ops", "col": "Plan", "n": "1", "label": "Draft", "group": "A"},
            {"id": "again", "lane": "Ops", "col": "Plan", "n": "1", "label": "Redraft", "group": "A"},
        ],
    }

    assert lowered([swimlane]) == (
        TableNode(
            (
                TableCell((Plain("Lane"),)),
                TableCell((Plain("Plan"), Break(), Plain("A"), Plain(", "), Plain("B"))),
            ),
            (
                TableRow(
                    (
                        TableCell((Plain("Ops"),)),
                        TableCell(
                            (
                                *bold("1"),
                                Plain(" "),
                                Plain("Draft"),
                                Plain(", A"),
                                Break(),
                                *bold("1"),
                                Plain(" "),
                                Plain("Redraft"),
                                Plain(", A"),
                                Break(),
                                SwimlaneMark("deferred"),
                                Plain(" "),
                                Link((Plain("2"),), "https://e.com/2"),
                                Plain(" "),
                                Plain("Send"),
                                Plain(", B"),
                                Plain(" "),
                                *italic(plain("needs 1")),
                            )
                        ),
                    )
                ),
            ),
            header_column=True,
        ),
        Paragraph((SwimlaneMark("deferred"), Plain(" "), Plain("deferred")), "muted"),
    )


@pytest.mark.parametrize(
    ("states", "legend"),
    [
        pytest.param(["done", None], ("done",), id="one-marked-state-beside-unmarked-steps-is-explained"),
        pytest.param(["done", "done"], (), id="one-state-on-every-step-needs-no-legend"),
        pytest.param([None, None], (), id="no-marks-no-legend"),
    ],
)
def test_the_export_legend_explains_every_glyph_that_differs_from_its_neighbours(
    states: list[SwimlaneStepState | None], legend: tuple[SwimlaneStepState, ...]
) -> None:
    steps = [
        {"lane": "Ops", "col": "Plan", "n": str(index), "label": "s", **({"state": state} if state else {})}
        for index, state in enumerate(states)
    ]
    swimlane = {"type": "swimlane", "lanes": ["Ops"], "columns": [{"name": "Plan"}], "steps": steps}

    nodes = lowered([swimlane])

    expected = (
        (
            Paragraph(
                spaced([spaced([(SwimlaneMark(state),), plain(state)]) for state in legend], " · "), "muted"
            ),
        )
        if legend
        else ()
    )
    assert nodes[1:] == expected


def test_a_swimlane_step_with_no_state_has_no_glyph_and_an_explicit_todo_keeps_its_own() -> None:
    swimlane = {
        "type": "swimlane",
        "lanes": ["Ops"],
        "columns": [{"name": "Plan"}],
        "steps": [
            {"lane": "Ops", "col": "Plan", "n": "1", "label": "Unset"},
            {"lane": "Ops", "col": "Plan", "n": "2", "label": "Planned", "state": "todo"},
            {"lane": "Ops", "col": "Plan", "n": "3", "label": "Shipped", "state": "done"},
        ],
    }

    assert lowered([swimlane]) == (
        TableNode(
            (TableCell((Plain("Lane"),)), TableCell((Plain("Plan"),))),
            (
                TableRow(
                    (
                        TableCell((Plain("Ops"),)),
                        TableCell(
                            (
                                *bold("1"),
                                Plain(" "),
                                Plain("Unset"),
                                Break(),
                                SwimlaneMark("todo"),
                                Plain(" "),
                                *bold("2"),
                                Plain(" "),
                                Plain("Planned"),
                                Break(),
                                SwimlaneMark("done"),
                                Plain(" "),
                                *bold("3"),
                                Plain(" "),
                                Plain("Shipped"),
                            )
                        ),
                    )
                ),
            ),
            header_column=True,
        ),
        Paragraph(
            (
                SwimlaneMark("done"),
                Plain(" "),
                Plain("done"),
                Plain(" · "),
                SwimlaneMark("todo"),
                Plain(" "),
                Plain("todo"),
            ),
            "muted",
        ),
    )
