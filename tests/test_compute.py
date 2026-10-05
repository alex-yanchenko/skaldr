import re
import subprocess
from http import HTTPStatus
from pathlib import Path
from typing import get_args

import pytest

from skaldr.compute import (
    DELTA_GLYPHS,
    Strip,
    StripLabel,
    anchor_slugs,
    command_for,
    first_table_index,
    fmt,
    list_label,
    paragraphs,
    produced_names,
    provenance_footer,
    reason_phrase,
    reconcile_line,
    reference_numbers,
    request_wire,
    status_line,
    strip_registry,
    swimlane_layout,
    table_rollup,
    toc_entries,
    used_badges,
    variable_parts,
)
from skaldr.errors import ReportError
from skaldr.models import (
    DeltaDirection,
    ListNumbering,
    Request,
    RequestFlow,
    Swimlane,
    Table,
    parse_report,
)
from tests.factories import (
    make_cell,
    make_command_request,
    make_flow,
    make_grid,
    make_reconciled_table,
    make_report,
    make_tab,
    make_table,
    make_tabs,
    make_toggle,
)


def _swimlane(**overrides: object) -> Swimlane:
    block = parse_report(make_report(blocks=[{"type": "swimlane", **overrides}])).blocks[0]
    assert isinstance(block, Swimlane)
    return block


def test_swimlane_layout_state_legend_lists_used_states_in_canonical_order() -> None:
    """The auto legend lists exactly the states used, in canonical progress order (done→…→deferred),
    de-duplicated, never authoring order, and never a state no step carries (todo/current absent here)."""
    block = _swimlane(
        lanes=["A"],
        columns=["C1", "C2", "C3", "C4"],
        steps=[
            {"lane": "A", "col": "C1", "n": "1", "label": "a", "state": "deferred"},
            {"lane": "A", "col": "C2", "n": "2", "label": "b", "state": "done"},
            {"lane": "A", "col": "C3", "n": "3", "label": "c", "state": "blocked"},
            {"lane": "A", "col": "C4", "n": "4", "label": "d", "state": "done"},
        ],
    )

    assert swimlane_layout(block)["state_legend"] == ["done", "blocked", "deferred"]


def test_swimlane_layout_n_width_is_the_widest_step_number_char_count() -> None:
    """Every badge sizes to the widest step number so labels align; n_width is that max CHARACTER count
    (so '2b' counts as 2 and '618' as 3), never a numeric value."""
    block = _swimlane(
        lanes=["A"],
        columns=["C1", "C2", "C3"],
        steps=[
            {"lane": "A", "col": "C1", "n": "1", "label": "a"},
            {"lane": "A", "col": "C2", "n": "618", "label": "b"},
            {"lane": "A", "col": "C3", "n": "2b", "label": "c"},
        ],
    )

    assert swimlane_layout(block)["n_width"] == 3


@pytest.mark.parametrize("only_state", [None, "blocked"])
def test_swimlane_layout_state_legend_is_empty_for_a_single_state_grid(only_state: str | None) -> None:
    """A swimlane whose steps are all ONE state needs no key — the legend is suppressed so a one-colour
    grid doesn't carry a pointless swatch. The gate is state-count, not "is it the default", so an
    all-`blocked` grid is suppressed exactly like an all-default-`todo` one."""
    step_state = {"state": only_state} if only_state is not None else {}
    block = _swimlane(
        lanes=["A"],
        columns=["C1", "C2"],
        steps=[
            {"lane": "A", "col": "C1", "n": "1", "label": "a", **step_state},
            {"lane": "A", "col": "C2", "n": "2", "label": "b", **step_state},
        ],
    )

    assert swimlane_layout(block)["state_legend"] == []


def test_swimlane_layout_plain_has_no_poke_rows_caps_or_dashes() -> None:
    """A groupless swimlane: header + lanes only, one sub-column per column, all boundaries solid."""
    block = _swimlane(
        lanes=["A", "B"],
        columns=["C1", "C2"],
        steps=[
            {"lane": "A", "col": "C1", "n": "1", "label": "x"},
            {"lane": "B", "col": "C2", "n": "2", "label": "y"},
        ],
    )

    layout = swimlane_layout(block)

    assert layout["has_groups"] is False
    assert layout["col_template"] == "max-content repeat(2, var(--swim-col))"
    assert layout["row_template"] == "auto auto auto"  # header + 2 lanes, no poke zones
    assert layout["caps"] == []
    assert layout["caps_bottom"] == []
    assert layout["vdash"] == []
    # gutter seam (line 2) + one column boundary (line 3), both table-rows; neither pokes (no caps).
    assert layout["vsolid"] == [
        {"col_start": 2, "col_end": 3, "poke": False, "row_start": 1, "row_end": 4},
        {"col_start": 3, "col_end": 4, "poke": False, "row_start": 1, "row_end": 4},
    ]
    # header/body divider spans the data columns only (col_start 2); the A/B lane divider is full-width
    assert layout["hdiv"] == [{"row": 2, "col_start": 2}, {"row": 3, "col_start": 1}]
    # the frame wraps the whole table incl. the gutter (line 1 → right edge)
    assert layout["tbl"] == {"line_start": 1, "line_end": 4, "row_start": 1, "row_end": 4}


def test_swimlane_layout_places_caps_tints_and_dashes_for_a_split_column() -> None:
    """MVP spans S1-S2, Beta and GA split S2, GA continues to S3 — the prototype's shape. Caps span
    their sub-columns; the two S2-internal boundaries are dashed (full height), the rest solid."""
    block = _swimlane(
        lanes=["R"],
        columns=["S1", "S2", "S3"],
        groups=[
            {"name": "MVP", "color": "blue", "columns": ["S1", "S2"]},
            {"name": "Beta", "color": "amber", "columns": ["S2"]},
            {"name": "GA", "color": "violet", "columns": ["S2", "S3"]},
        ],
        steps=[
            {"lane": "R", "col": "S1", "n": "1", "label": "a"},
            {"lane": "R", "col": "S2", "group": "Beta", "n": "2", "label": "b"},
            {"lane": "R", "col": "S3", "n": "3", "label": "c"},
        ],
    )

    layout = swimlane_layout(block)

    assert layout["has_groups"] is True
    assert (
        layout["row_template"] == "var(--swim-poke) auto auto var(--swim-pokeb)"
    )  # poke + header + 1 lane + poke
    # 4 sub-columns → cols S1/MVP, S2/MVP, S2/Beta, S2/GA, S3/GA = 5 sub-columns
    assert [(sub["col"], sub["group"], sub["tone"]) for sub in layout["subcols"]] == [
        ("S1", "MVP", "blue"),
        ("S2", "MVP", "blue"),
        ("S2", "Beta", "amber"),
        ("S2", "GA", "violet"),
        ("S3", "GA", "violet"),
    ]
    # one header label per column, spanning that column's sub-columns (S2 spans its 3-way split)
    assert layout["headers"] == [
        {"label": "S1", "sub": None, "line_start": 2, "line_end": 3, "row_start": 2, "row_end": 3},
        {"label": "S2", "sub": None, "line_start": 3, "line_end": 6, "row_start": 2, "row_end": 3},
        {"label": "S3", "sub": None, "line_start": 6, "line_end": 7, "row_start": 2, "row_end": 3},
    ]
    # a tinted header sub-cell per sub-column
    assert layout["header_tints"] == [
        {"tone": "blue", "line_start": 2, "line_end": 3, "row_start": 2, "row_end": 3},
        {"tone": "blue", "line_start": 3, "line_end": 4, "row_start": 2, "row_end": 3},
        {"tone": "amber", "line_start": 4, "line_end": 5, "row_start": 2, "row_end": 3},
        {"tone": "violet", "line_start": 5, "line_end": 6, "row_start": 2, "row_end": 3},
        {"tone": "violet", "line_start": 6, "line_end": 7, "row_start": 2, "row_end": 3},
    ]
    assert layout["gutter"] == [{"lane": "R", "total": None, "row_start": 3, "row_end": 4}]
    # the frame wraps the whole table incl. the gutter (line 1 → right edge 7)
    assert layout["tbl"] == {"line_start": 1, "line_end": 7, "row_start": 2, "row_end": 4}
    # caps: MVP over its 2 sub-columns (lines 2-4, leftmost → left edge), Beta 1 (4-5, interior),
    # GA 2 (5-7, rightmost → right edge); bottom caps mirror them
    assert layout["caps"] == [
        {
            "label": "MVP",
            "color": "blue",
            "edges": "left",
            "total": None,
            "line_start": 2,
            "line_end": 4,
            "row_start": 1,
            "row_end": 2,
        },
        {
            "label": "Beta",
            "color": "amber",
            "edges": "",
            "total": None,
            "line_start": 4,
            "line_end": 5,
            "row_start": 1,
            "row_end": 2,
        },
        {
            "label": "GA",
            "color": "violet",
            "edges": "right",
            "total": None,
            "line_start": 5,
            "line_end": 7,
            "row_start": 1,
            "row_end": 2,
        },
    ]
    assert layout["caps_bottom"] == [
        {"color": "blue", "edges": "left", "line_start": 2, "line_end": 4, "row_start": 4, "row_end": 5},
        {"color": "amber", "edges": "", "line_start": 4, "line_end": 5, "row_start": 4, "row_end": 5},
        {"color": "violet", "edges": "right", "line_start": 5, "line_end": 7, "row_start": 4, "row_end": 5},
    ]
    # dashes (full height rows 1-5) at the two S2-internal splits: MVP|Beta (line 4), Beta|GA (line 5)
    assert layout["vdash"] == [
        {"col_start": 4, "col_end": 5, "row_start": 1, "row_end": 5},
        {"col_start": 5, "col_end": 6, "row_start": 1, "row_end": 5},
    ]
    # gutter seam (2) + sprint boundaries S1|S2 (3) and S2|S3 (6), all table-rows and NOT poking:
    # MVP spans S1|S2 and GA spans S2|S3, so each boundary sits inside one cap (no separator needed).
    assert layout["vsolid"] == [
        {"col_start": 2, "col_end": 3, "poke": False, "row_start": 2, "row_end": 4},
        {"col_start": 3, "col_end": 4, "poke": False, "row_start": 2, "row_end": 4},
        {"col_start": 6, "col_end": 7, "poke": False, "row_start": 2, "row_end": 4},
    ]
    # interior horizontal line only: the header/body divider across the data columns (col_start 2).
    assert layout["hdiv"] == [{"row": 3, "col_start": 2}]


def test_swimlane_layout_separates_adjacent_caps_at_a_sprint_boundary() -> None:
    """When two different groups each own a whole column (caps meet at a sprint boundary), that solid
    boundary pokes through the poke zone (full height) to separate the caps — unlike a cap that spans
    a boundary, which keeps a table-rows-only line so it reads as continuous."""
    block = parse_report(
        make_report(
            blocks=[
                {
                    "type": "swimlane",
                    "lanes": ["R"],
                    "columns": ["S1", "S2"],
                    "groups": [
                        {"name": "A", "color": "blue", "columns": ["S1"]},
                        {"name": "B", "color": "amber", "columns": ["S2"]},
                    ],
                    "steps": [
                        {"lane": "R", "col": "S1", "n": "1", "label": "a"},
                        {"lane": "R", "col": "S2", "n": "2", "label": "b"},
                    ],
                }
            ]
        )
    ).blocks[0]
    assert isinstance(block, Swimlane)

    layout = swimlane_layout(block)

    # gutter seam (table-rows, no poke) + the S1|S2 boundary between caps A and B (full height, poking)
    assert layout["vsolid"] == [
        {"col_start": 2, "col_end": 3, "poke": False, "row_start": 2, "row_end": 4},
        {"col_start": 3, "col_end": 4, "poke": True, "row_start": 1, "row_end": 5},
    ]
    # both outer columns carry a cap, so the rightmost cap's right border squares the frame's corners
    assert layout["frame_square_right"] is True


def test_swimlane_layout_routes_each_step_to_its_resolved_subcolumn() -> None:
    """A step with no explicit group lands in the sole covering group's sub-column; an explicit group
    routes to that sub-column; the other sub-columns of the split are empty."""
    block = _swimlane(
        lanes=["R"],
        columns=["S1", "S2"],
        groups=[
            {"name": "MVP", "color": "blue", "columns": ["S1", "S2"]},
            {"name": "Beta", "color": "amber", "columns": ["S2"]},
        ],
        steps=[
            {"lane": "R", "col": "S1", "n": "1", "label": "a"},
            {"lane": "R", "col": "S2", "group": "Beta", "n": "2", "label": "b"},
        ],
    )

    layout = swimlane_layout(block)

    # whole-object: geometry + tint + resolved steps per cell (one lane R over 3 sub-columns)
    assert layout["cells"] == [
        {
            "tone": "blue",
            "line_start": 2,
            "line_end": 3,
            "row_start": 3,
            "row_end": 4,
            "steps": [{"n": "1", "label": "a", "value": None, "url": None, "state": "todo", "deps": []}],
        },  # S1/MVP — inferred group
        {
            "tone": "blue",
            "line_start": 3,
            "line_end": 4,
            "row_start": 3,
            "row_end": 4,
            "steps": [],
        },  # S2/MVP — empty (the step named Beta)
        {
            "tone": "amber",
            "line_start": 4,
            "line_end": 5,
            "row_start": 3,
            "row_end": 4,
            "steps": [{"n": "2", "label": "b", "value": None, "url": None, "state": "todo", "deps": []}],
        },  # S2/Beta
    ]


def test_swimlane_layout_ungrouped_outer_column_is_untinted_with_no_right_edge() -> None:
    """A trailing ungrouped column carries no tone and no cap. The Push cap (leftmost) gets a left
    edge; because the rightmost column is ungrouped, no cap gets a right edge."""
    block = _swimlane(
        lanes=["R"],
        columns=["Early", "Mid", "Late"],
        groups=[{"name": "Push", "color": "blue", "columns": ["Early", "Mid"]}],
        steps=[
            {"lane": "R", "col": "Early", "n": "1", "label": "a"},
            {"lane": "R", "col": "Mid", "n": "2", "label": "b"},
            {"lane": "R", "col": "Late", "n": "3", "label": "c"},
        ],
    )

    layout = swimlane_layout(block)

    assert [(sub["col"], sub["group"], sub["tone"]) for sub in layout["subcols"]] == [
        ("Early", "Push", "blue"),
        ("Mid", "Push", "blue"),
        ("Late", None, None),
    ]
    # Push spans the first two sub-columns; it is leftmost (left edge) but not rightmost (Late ungrouped)
    assert [(cap["label"], cap["edges"], cap["line_start"], cap["line_end"]) for cap in layout["caps"]] == [
        ("Push", "left", 2, 4)
    ]
    # the Mid|Late boundary is grouped-vs-ungrouped: only one cap, so it stays table-rows only (poke
    # False) — a full-height line there would jut into the poke zone with nothing beside it.
    assert layout["vsolid"] == [
        {"col_start": 2, "col_end": 3, "poke": False, "row_start": 2, "row_end": 4},  # gutter seam
        {"col_start": 3, "col_end": 4, "poke": False, "row_start": 2, "row_end": 4},  # Early|Mid (same cap)
        {"col_start": 4, "col_end": 5, "poke": False, "row_start": 2, "row_end": 4},  # Mid|Late (cap|none)
    ]
    # rightmost column is ungrouped, so the frame keeps its rounded right corners
    assert layout["frame_square_right"] is False


def test_swimlane_layout_group_spanning_every_column_gets_both_edges() -> None:
    """A single group covering all columns is both leftmost and rightmost, so its cap carries both
    outer edges (`edges == "left right"`)."""
    block = _swimlane(
        lanes=["R"],
        columns=["C1", "C2"],
        groups=[{"name": "All", "color": "green", "columns": ["C1", "C2"]}],
        steps=[
            {"lane": "R", "col": "C1", "n": "1", "label": "a"},
            {"lane": "R", "col": "C2", "n": "2", "label": "b"},
        ],
    )

    layout = swimlane_layout(block)

    assert layout["caps"] == [
        {
            "label": "All",
            "color": "green",
            "edges": "left right",
            "total": None,
            "line_start": 2,
            "line_end": 4,
            "row_start": 1,
            "row_end": 2,
        }
    ]


def test_swimlane_layout_sums_values_into_column_lane_and_group_totals() -> None:
    """When steps carry `value`, a footer row holds per-column sums, the gutter carries per-lane sums,
    and each cap carries its group's sum (an ungrouped step counts toward column/lane but no group).
    The footer is a real table row, so it extends table_rows and shifts the bottom poke zone down."""
    block = _swimlane(
        lanes=["R"],
        columns=["S1", "S2", "S3"],
        groups=[{"name": "Push", "color": "blue", "columns": ["S1", "S2"]}],
        steps=[
            {"lane": "R", "col": "S1", "n": "1", "label": "a", "value": 3},
            {"lane": "R", "col": "S2", "n": "2", "label": "b", "value": 5},
            {"lane": "R", "col": "S3", "n": "3", "label": "c", "value": 2},
        ],
    )

    layout = swimlane_layout(block)

    # header + lane + footer + poke zones → one extra `auto` track vs the no-value case
    assert layout["row_template"] == "var(--swim-poke) auto auto auto var(--swim-pokeb)"
    # per-column footer (row 4-5), each cell spanning its column's sub-columns
    assert layout["foot"] == {
        "label": "Total",
        "banded": True,  # no column is split across groups → keeps the panel band
        "row_start": 4,
        "row_end": 5,
        "cells": [
            {"total": 3, "line_start": 2, "line_end": 3, "row_start": 4, "row_end": 5},
            {"total": 5, "line_start": 3, "line_end": 4, "row_start": 4, "row_end": 5},
            {"total": 2, "line_start": 4, "line_end": 5, "row_start": 4, "row_end": 5},
        ],
    }
    # per-lane total beside the label
    assert layout["gutter"] == [{"lane": "R", "total": 10, "row_start": 3, "row_end": 4}]
    # Push's cap total is 3+5 (S3 is ungrouped, so its 2 is excluded)
    assert layout["caps"] == [
        {
            "label": "Push",
            "color": "blue",
            "edges": "left",
            "total": 8,
            "line_start": 2,
            "line_end": 4,
            "row_start": 1,
            "row_end": 2,
        }
    ]
    # the footer is inside the table (frame wraps it), and the bottom cap sits below it
    assert layout["tbl"] == {"line_start": 1, "line_end": 5, "row_start": 2, "row_end": 5}
    assert layout["caps_bottom"][0]["row_start"] == 5


def test_swimlane_layout_without_values_has_no_footer_or_totals() -> None:
    """No step carries a value → no footer row (row_template unchanged), and every lane/group total is
    None so the macro renders nothing extra."""
    block = _swimlane(
        lanes=["R"],
        columns=["S1", "S2"],
        groups=[{"name": "All", "color": "green", "columns": ["S1", "S2"]}],
        steps=[
            {"lane": "R", "col": "S1", "n": "1", "label": "a"},
            {"lane": "R", "col": "S2", "n": "2", "label": "b"},
        ],
    )

    layout = swimlane_layout(block)

    assert layout["foot"] is None
    assert layout["row_template"] == "var(--swim-poke) auto auto var(--swim-pokeb)"
    assert [gut["total"] for gut in layout["gutter"]] == [None]
    assert [cap["total"] for cap in layout["caps"]] == [None]
    # table stops at the lane row (no footer): header + 1 lane = rows 2-4
    assert layout["tbl"]["row_end"] == 4


def test_swimlane_layout_totals_partition_by_lane_and_handle_zero_and_fractional() -> None:
    """Per-lane totals partition across ≥2 lanes; a `value: 0` still activates totals (0 is not None)
    and is summed; fractional values are preserved through the sums."""
    block = _swimlane(
        lanes=["A", "B"],
        columns=["C1", "C2"],
        steps=[
            {"lane": "A", "col": "C1", "n": "1", "label": "a", "value": 2.5},
            {"lane": "A", "col": "C2", "n": "2", "label": "b", "value": 0},
            {"lane": "B", "col": "C1", "n": "3", "label": "c", "value": 4},
            {"lane": "B", "col": "C2", "n": "4", "label": "d", "value": 1.5},
        ],
    )

    layout = swimlane_layout(block)

    # groupless + totals → header + 2 lanes + footer, no poke tracks
    assert layout["row_template"] == "auto auto auto auto"
    assert layout["gutter"] == [
        {"lane": "A", "total": 2.5, "row_start": 2, "row_end": 3},
        {"lane": "B", "total": 5.5, "row_start": 3, "row_end": 4},
    ]
    # the fractional value flows onto its cell's step
    assert layout["cells"][0] == {
        "tone": None,
        "line_start": 2,
        "line_end": 3,
        "row_start": 2,
        "row_end": 3,
        "steps": [{"n": "1", "label": "a", "value": 2.5, "url": None, "state": "todo", "deps": []}],
    }
    # footer sums each column across both lanes; fractional preserved, zero included
    assert layout["foot"] == {
        "label": "Total",
        "banded": True,
        "row_start": 4,
        "row_end": 5,
        "cells": [
            {"total": 6.5, "line_start": 2, "line_end": 3, "row_start": 4, "row_end": 5},
            {"total": 1.5, "line_start": 3, "line_end": 4, "row_start": 4, "row_end": 5},
        ],
    }
    # header/body divider (data cols), inter-lane divider (full width), footer divider (full width)
    assert layout["hdiv"] == [
        {"row": 2, "col_start": 2},
        {"row": 3, "col_start": 1},
        {"row": 4, "col_start": 1},
    ]
    assert layout["tbl"] == {"line_start": 1, "line_end": 4, "row_start": 1, "row_end": 5}


def test_swimlane_layout_a_lone_zero_value_still_activates_totals() -> None:
    """A single step whose only value is 0 turns totals on (0 is not None); a truthy check would miss it
    and silently drop the totals row."""
    block = _swimlane(
        lanes=["A"],
        columns=["C1"],
        steps=[{"lane": "A", "col": "C1", "n": "1", "label": "a", "value": 0}],
    )

    layout = swimlane_layout(block)

    assert layout["foot"] == {
        "label": "Total",
        "banded": True,
        "row_start": 3,
        "row_end": 4,
        "cells": [{"total": 0, "line_start": 2, "line_end": 3, "row_start": 3, "row_end": 4}],
    }
    assert layout["gutter"] == [{"lane": "A", "total": 0, "row_start": 2, "row_end": 3}]


def test_swimlane_layout_split_column_with_values_drops_band_and_trims_dashes() -> None:
    """A column split across groups: the footer sums across all its sub-columns, the band is dropped
    (banded False), the group-split dashes stop at the footer's top edge, and a divider sits above the
    totals row."""
    block = _swimlane(
        lanes=["R"],
        columns=["S1", "S2", "S3"],
        groups=[
            {"name": "MVP", "color": "blue", "columns": ["S1", "S2"]},
            {"name": "Beta", "color": "amber", "columns": ["S2"]},
            {"name": "GA", "color": "violet", "columns": ["S2", "S3"]},
        ],
        steps=[
            {"lane": "R", "col": "S1", "n": "1", "label": "a", "value": 4},
            {"lane": "R", "col": "S2", "group": "MVP", "n": "2", "label": "b", "value": 3},
            {"lane": "R", "col": "S2", "group": "Beta", "n": "3", "label": "c", "value": 6},
            {"lane": "R", "col": "S2", "group": "GA", "n": "4", "label": "d", "value": 2},
            {"lane": "R", "col": "S3", "n": "5", "label": "e", "value": 5},
        ],
    )

    layout = swimlane_layout(block)

    # band dropped, and S2's footer cell spans its 3 sub-columns summing all three (3+6+2)
    assert layout["foot"] == {
        "label": "Total",
        "banded": False,
        "row_start": 4,
        "row_end": 5,
        "cells": [
            {"total": 4, "line_start": 2, "line_end": 3, "row_start": 4, "row_end": 5},
            {"total": 11, "line_start": 3, "line_end": 6, "row_start": 4, "row_end": 5},
            {"total": 5, "line_start": 6, "line_end": 7, "row_start": 4, "row_end": 5},
        ],
    }
    # the two S2-internal dashes stop at the footer's top edge (row_end 4), not through it
    assert layout["vdash"] == [
        {"col_start": 4, "col_end": 5, "row_start": 1, "row_end": 4},
        {"col_start": 5, "col_end": 6, "row_start": 1, "row_end": 4},
    ]
    # header/body divider (data cols) + a full-width divider above the totals row
    assert layout["hdiv"] == [{"row": 3, "col_start": 2}, {"row": 4, "col_start": 1}]


def test_swimlane_layout_a_de_emphasised_step_value_still_counts_in_totals() -> None:
    """`state` only de-emphasises visually — the step's value is still summed into the totals, so a
    low/blocked step must not silently drop out of the column/lane sums."""
    block = _swimlane(
        lanes=["A"],
        columns=["C1"],
        steps=[
            {"lane": "A", "col": "C1", "n": "1", "label": "a", "value": 3},
            {"lane": "A", "col": "C1", "n": "2", "label": "b", "value": 4, "state": "blocked"},
        ],
    )

    layout = swimlane_layout(block)

    # 3 + 4: the blocked step's 4 is included
    assert layout["foot"] == {
        "label": "Total",
        "banded": True,
        "row_start": 3,
        "row_end": 4,
        "cells": [{"total": 7, "line_start": 2, "line_end": 3, "row_start": 3, "row_end": 4}],
    }
    assert layout["gutter"] == [{"lane": "A", "total": 7, "row_start": 2, "row_end": 3}]


def test_swimlane_layout_resolves_depends_on_ids_to_the_dependency_numbers() -> None:
    """A step's `depends_on` (ids) resolves to the referenced steps' numbers on the rendered step, so
    the reader sees "needs 1", not an internal id."""
    block = _swimlane(
        lanes=["A"],
        columns=["C1", "C2"],
        steps=[
            {"lane": "A", "col": "C1", "n": "1", "label": "a", "id": "x"},
            {"lane": "A", "col": "C2", "n": "2", "label": "b", "depends_on": ["x"]},
        ],
    )

    layout = swimlane_layout(block)

    # C2's step carries the dependency's NUMBER (1), not its id ("x")
    assert layout["cells"][1]["steps"] == [
        {"n": "2", "label": "b", "value": None, "url": None, "state": "todo", "deps": ["1"]}
    ]


def test_swimlane_layout_dedupes_repeated_dependency_numbers() -> None:
    """Two distinct ids sharing a display number, both depended on, collapse to one entry — the marker
    never reads "needs 1, 1"."""
    block = _swimlane(
        lanes=["A"],
        columns=["C1", "C2", "C3"],
        steps=[
            {"lane": "A", "col": "C1", "n": "1", "label": "a", "id": "x"},
            {"lane": "A", "col": "C2", "n": "1", "label": "b", "id": "y"},  # same number, different id
            {"lane": "A", "col": "C3", "n": "3", "label": "c", "depends_on": ["x", "y"]},
        ],
    )

    layout = swimlane_layout(block)

    assert layout["cells"][2]["steps"][0]["deps"] == ["1"]


def test_swimlane_layout_groups_and_headers_use_column_ids_and_subs() -> None:
    """Groups and steps address a split column by its id (not display name); the header spanning that
    split column still carries its `sub` caption."""
    block = _swimlane(
        lanes=["R"],
        columns=[
            {"id": "a", "name": "Alpha"},
            {"id": "b", "name": "Beta col", "sub": "→ MVP demo"},
        ],
        groups=[
            {"name": "G1", "color": "blue", "columns": ["a", "b"]},
            {"name": "G2", "color": "amber", "columns": ["b"]},
        ],
        steps=[
            {"lane": "R", "col": "a", "n": "1", "label": "x"},
            {"lane": "R", "col": "b", "group": "G1", "n": "2", "label": "y"},
            {"lane": "R", "col": "b", "group": "G2", "n": "3", "label": "z"},
        ],
    )

    layout = swimlane_layout(block)

    # sub-columns key on the column id "b" (split across G1/G2), not the display name
    assert [(sub["col"], sub["group"]) for sub in layout["subcols"]] == [
        ("a", "G1"),
        ("b", "G1"),
        ("b", "G2"),
    ]
    # headers show display names; the split column's header carries its sub caption
    assert [(header["label"], header["sub"]) for header in layout["headers"]] == [
        ("Alpha", None),
        ("Beta col", "→ MVP demo"),
    ]


@pytest.mark.parametrize(
    ("text", "parts"),
    [
        pytest.param("a\n\nb", ["a", "b"], id="blank-line"),
        pytest.param("a\n\n\n\nb", ["a", "b"], id="run-of-blank-lines"),
        pytest.param("  a \n\n  \n", ["a"], id="trimmed-and-whitespace-dropped"),
        pytest.param("one\nline", ["one\nline"], id="single-newline-stays"),
        pytest.param("\n\n", [], id="only-blank-lines"),
    ],
)
def test_paragraphs_split_on_blank_lines_and_drop_empty_ones(text: str, parts: list[str]) -> None:
    assert paragraphs(text) == parts


@pytest.mark.parametrize(
    ("index", "numbering", "label"),
    [
        pytest.param(4, "decimal", "4", id="decimal"),
        pytest.param(1, "letters", "a", id="first-letter"),
        pytest.param(4, "letters", "d", id="a-letter"),
        pytest.param(26, "letters", "z", id="last-letter"),
        pytest.param(27, "letters", "aa", id="letters-roll-over-to-two"),
        pytest.param(52, "letters", "az", id="two-letters"),
        pytest.param(703, "letters", "aaa", id="letters-roll-over-to-three"),
        pytest.param(1, "roman", "i", id="first-roman"),
        pytest.param(4, "roman", "iv", id="roman"),
        pytest.param(3999, "roman", "mmmcmxcix", id="largest-roman"),
        pytest.param(4000, "roman", "4000", id="roman-past-its-range-is-decimal"),
    ],
)
def test_a_list_label_is_the_marker_a_browser_shows_for_that_numbering(
    index: int, numbering: ListNumbering, label: str
) -> None:
    assert list_label(index, numbering) == label


def test_fmt_variants() -> None:
    assert fmt(1500) == "1,500"
    assert fmt(1500.0) == "1,500"
    assert fmt(1500.5) == "1,500.5"
    assert fmt("HEALTHY") == "HEALTHY"
    assert fmt(True) == "True"


def test_anchor_slugs_dedup_collisions_across_headings_and_sections() -> None:
    # a heading and a section that share a title share the de-dup namespace, so their anchors differ
    report = parse_report(
        make_report(
            meta={"title": "T", "toc": True},
            blocks=[
                {"type": "heading", "text": "Details"},
                {"type": "section", "title": "Details", "blocks": [{"type": "text", "body": "x"}]},
            ],
        )
    )

    assert sorted(anchor_slugs(report).values()) == ["details", "details-2"]


def test_anchor_slugs_covers_a_section_and_its_inner_heading() -> None:
    # the Section branch self-yields AND recurses, so the section and a heading inside it both get
    # their own distinct anchor slug.
    report = parse_report(
        make_report(
            blocks=[
                {
                    "type": "section",
                    "title": "Appendix",
                    "blocks": [{"type": "heading", "level": 3, "text": "Notes"}],
                }
            ],
        )
    )

    assert sorted(anchor_slugs(report).values()) == ["appendix", "notes"]


def test_anchor_slugs_uses_an_author_id_verbatim_and_yields_the_derived_slug_to_it() -> None:
    # the explicit id is reserved, so a later heading whose text derives the same base takes `-2`
    report = parse_report(
        make_report(
            blocks=[
                {"type": "heading", "text": "Results", "id": "overview"},
                {"type": "heading", "text": "Overview"},
            ],
        )
    )

    assert list(anchor_slugs(report).values()) == ["overview", "overview-2"]


def test_anchor_slugs_yield_to_the_ids_the_page_itself_uses() -> None:
    report = parse_report(
        make_report(
            blocks=[
                {"type": "heading", "text": "Skaldr source"},
                {"type": "heading", "text": "SC menu"},
                {"type": "heading", "text": "Ref a"},
                {"type": "heading", "text": "Fnref a"},
                {"type": "heading", "text": "Ref b"},
                {"type": "references", "items": [{"key": "a", "text": "A"}]},
            ],
        )
    )

    assert list(anchor_slugs(report).values()) == [
        "skaldr-source-2",
        "sc-menu-2",
        "ref-a-2",
        "fnref-a-2",
        "ref-b",
    ]


@pytest.mark.parametrize("author_id", ["skaldr-source", "sc-menu", "ref-a", "fnref-a"])
def test_anchor_slugs_refuse_an_author_id_the_page_itself_uses(author_id: str) -> None:
    report = parse_report(
        make_report(
            blocks=[
                {"type": "heading", "text": "A", "id": author_id},
                {"type": "references", "items": [{"key": "a", "text": "A"}]},
            ],
        )
    )

    with pytest.raises(ReportError) as raised:
        anchor_slugs(report)

    assert str(raised.value) == (
        f"anchor id '{author_id}' is one the page itself uses (the source block, the settings menu, or a "
        "reference and its citation); give the heading or section another id"
    )


@pytest.mark.parametrize(
    ("text", "slug"),
    [
        pytest.param("Über uns", "über-uns", id="accented-latin"),
        pytest.param("日本語の見出し", "日本語の見出し", id="japanese"),
        pytest.param("Ünïcödé — and ASCII 2", "ünïcödé-and-ascii-2", id="mixed"),
        pytest.param("snake_case name", "snake-case-name", id="underscore"),
        pytest.param("Über", "über", id="decomposed"),
        pytest.param("हिन्दी भाषा", "हिन्दी-भाषा", id="devanagari-vowel-signs"),
        pytest.param("สวัสดี ครับ", "สวัสดี-ครับ", id="thai-combining-vowels"),
        pytest.param("İstanbul", "i̇stanbul", id="dotted-capital-i"),
        pytest.param("Price: 5 € / unit_cost", "price-5-unit-cost", id="symbols-and-underscore"),
        pytest.param("!!!", "section", id="no-letters"),
    ],
)
def test_anchor_slugs_keep_letters_and_digits_from_any_script(text: str, slug: str) -> None:
    report = parse_report(make_report(blocks=[{"type": "heading", "text": text}]))

    assert list(anchor_slugs(report).values()) == [slug]


def test_anchor_slugs_rejects_a_duplicate_author_id() -> None:
    report = parse_report(
        make_report(
            blocks=[
                {"type": "heading", "text": "A", "id": "dup"},
                {"type": "section", "title": "B", "id": "dup", "blocks": [{"type": "text", "body": "x"}]},
            ],
        )
    )

    with pytest.raises(ReportError, match=r"duplicate anchor id 'dup'"):
        anchor_slugs(report)


def test_toc_uses_an_author_id_as_the_anchor_target() -> None:
    report = parse_report(
        make_report(
            meta={"title": "T", "toc": True},
            blocks=[{"type": "heading", "text": "Discrepancies & Fixes", "id": "fixes"}],
        )
    )

    assert toc_entries(report, anchor_slugs(report)) == [("fixes", "Discrepancies & Fixes")]


def test_toc_uses_deduped_slugs() -> None:
    report = parse_report(
        make_report(
            meta={"title": "T", "toc": True},
            blocks=[{"type": "heading", "text": "Details"}, {"type": "heading", "text": "Details"}],
        )
    )

    assert toc_entries(report, anchor_slugs(report)) == [("details", "Details"), ("details-2", "Details")]


def test_toc_includes_sections_interleaved_in_document_order() -> None:
    report = parse_report(
        make_report(
            meta={"title": "T", "toc": True},
            blocks=[
                {"type": "heading", "text": "Overview"},
                {"type": "section", "title": "Appendix", "blocks": [{"type": "text", "body": "x"}]},
                {"type": "heading", "text": "Wrap-up"},
            ],
        )
    )

    assert toc_entries(report, anchor_slugs(report)) == [
        ("overview", "Overview"),
        ("appendix", "Appendix"),
        ("wrap-up", "Wrap-up"),
    ]


@pytest.mark.parametrize("level", [pytest.param(3, id="level-3"), pytest.param(4, id="level-4")])
def test_a_sub_heading_gets_an_anchor_but_no_toc_entry(level: int) -> None:
    report = parse_report(
        make_report(
            meta={"title": "T", "toc": True},
            blocks=[
                {"type": "heading", "text": "Overview"},
                {"type": "heading", "level": level, "text": "Bins"},
            ],
        )
    )
    slugs = anchor_slugs(report)

    assert (sorted(slugs.values()), toc_entries(report, slugs)) == (
        ["bins", "overview"],
        [("overview", "Overview")],
    )


def test_the_strip_registry_names_every_tab_strip_and_case_strip_in_document_order() -> None:
    cases = [
        {"label": "a", "tone": "warning", "response": {"body": "x"}},
        {"label": "b", "tone": "success", "response": {"body": "y"}},
    ]
    inner = make_tabs(make_tab("Inner", tone="info"), make_tab("Other"))
    blocks = [
        make_tabs(make_tab("Outer", inner), make_tab("Second")),
        make_command_request(cases=cases),
        make_toggle(make_flow()),
    ]

    strips = strip_registry(parse_report(make_report(blocks=blocks)))

    assert list(strips.values()) == [
        Strip("tb0", (StripLabel("Outer", None), StripLabel("Second", None))),
        Strip("tb1", (StripLabel("Inner", "info"), StripLabel("Other", None))),
        Strip("rq0", (StripLabel("a", "warning"), StripLabel("b", "success"))),
        Strip("rq1", (StripLabel("one", "success"),)),
        Strip("rq2", (StripLabel("one", "success"),)),
    ]


def test_toc_empty_when_toc_disabled() -> None:
    report = parse_report(make_report(blocks=[{"type": "heading", "text": "X"}]))

    assert toc_entries(report, anchor_slugs(report)) == []


def test_used_badges_returns_referenced_in_declaration_order() -> None:
    table = make_reconciled_table(
        columns=[
            {"key": "issue", "label": "I", "kind": "text"},
            {"key": "tag", "label": "", "kind": "badge"},
            {"key": "count", "label": "C", "kind": "number"},
        ],
        reconcile={"total": 30, "column": "count"},
        # Rows reference B before A, but declaration order (A, B) must win; C is declared, unused.
        groups=[
            {
                "name": "g",
                "rows": [{"issue": "x", "tag": "B", "count": 10}, {"issue": "y", "tag": "A", "count": 20}],
            }
        ],
    )
    badges = {
        "A": {"label": "A", "tone": "amber", "legend": "la"},
        "B": {"label": "B", "tone": "blue", "legend": "lb"},
        "C": {"label": "C", "tone": "green", "legend": "lc"},
    }

    report = parse_report(make_report(badges=badges, blocks=[table]))

    assert [key for key, _ in used_badges(report)] == ["A", "B"]


def test_reconcile_line_with_and_without_handled() -> None:
    with_handled = parse_report(make_report(blocks=[make_reconciled_table()])).blocks[0]
    without_handled = parse_report(
        make_report(
            blocks=[
                make_reconciled_table(
                    reconcile={"total": 10, "column": "count"},
                    groups=[{"name": "g", "rows": [{"issue": "x", "count": 10}]}],
                )
            ]
        )
    ).blocks[0]

    assert isinstance(with_handled, Table)
    assert isinstance(without_handled, Table)
    assert reconcile_line(with_handled) == "Reconciles: 10 + 90 clean = 100."
    assert reconcile_line(without_handled) == "Reconciles: 10 = 10."


def test_provenance_footer_recurses_into_sections() -> None:
    section = {"type": "section", "title": "Appendix", "blocks": [make_reconciled_table()]}
    report = parse_report(make_report(meta={"title": "T", "source": "src"}, blocks=[section]))

    footer = provenance_footer(report)

    assert footer == "src · Reconciles: 10 + 90 clean = 100."


def test_provenance_footer_includes_updated_after_the_date() -> None:
    report = parse_report(
        make_report(meta={"title": "T", "source": "src", "date": "Q3 2026", "updated": "18 Jul 2026"})
    )

    assert provenance_footer(report) == "src · Q3 2026 · updated 18 Jul 2026"


def test_provenance_footer_updated_alone() -> None:
    report = parse_report(make_report(meta={"title": "T", "updated": "18 Jul 2026"}))

    assert provenance_footer(report) == "updated 18 Jul 2026"


def test_provenance_footer_omits_updated_when_absent() -> None:
    report = parse_report(make_report(meta={"title": "T", "source": "src"}))

    assert provenance_footer(report) == "src"


def test_provenance_footer_omits_updated_when_blank() -> None:
    # a blank string is absent: no stray "updated " segment in the footer
    report = parse_report(make_report(meta={"title": "T", "source": "src", "updated": ""}))

    assert provenance_footer(report) == "src"


def test_table_rollup_counts_rows_by_the_badge_column_in_first_appearance_order() -> None:
    # PENDING appears first but ends with the LOWER count — so this distinguishes first-appearance
    # order (the contract) from a count-descending sort, which would flip the two buckets.
    table = Table.model_validate(
        make_table(
            columns=[
                {"key": "item", "label": "Item", "kind": "text"},
                {"key": "status", "label": "", "kind": "badge"},
            ],
            rows=[
                {"item": "a", "status": "PENDING"},
                {"item": "b", "status": "DONE"},
                {"item": "c", "status": "DONE"},
            ],
            rollup={"by": "status"},
        )
    )

    assert table_rollup(table) == [{"key": "PENDING", "count": 1}, {"key": "DONE", "count": 2}]


def test_table_rollup_sums_a_value_across_groups() -> None:
    table = Table.model_validate(
        make_table(
            columns=[
                {"key": "item", "label": "Item", "kind": "text"},
                {"key": "status", "label": "", "kind": "badge"},
            ],
            groups=[
                {"name": "A", "rows": [{"item": "a", "status": "DONE"}]},
                {"name": "B", "rows": [{"item": "b", "status": "DONE"}, {"item": "c", "status": "OPEN"}]},
            ],
            rollup={"by": "status"},
        )
    )

    assert table_rollup(table) == [{"key": "DONE", "count": 2}, {"key": "OPEN", "count": 1}]


def test_table_rollup_is_none_without_a_rollup() -> None:
    table = Table.model_validate(
        make_table(columns=[{"key": "item", "label": "I", "kind": "text"}], rows=[{"item": "a"}])
    )

    assert table_rollup(table) is None


def test_table_rollup_skips_blank_badge_values() -> None:
    table = Table.model_validate(
        make_table(
            columns=[
                {"key": "item", "label": "I", "kind": "text"},
                {"key": "status", "label": "", "kind": "badge"},
            ],
            rows=[{"item": "a", "status": "DONE"}, {"item": "b", "status": ""}],
            rollup={"by": "status"},
        )
    )

    assert table_rollup(table) == [{"key": "DONE", "count": 1}]


def test_first_table_index() -> None:
    report = parse_report(make_report(blocks=[{"type": "text", "body": "x"}, make_reconciled_table()]))

    assert first_table_index(report) == 1


def test_a_table_nested_in_a_section_leaves_the_legend_at_the_top() -> None:
    section = {"type": "section", "title": "S", "blocks": [make_reconciled_table()]}

    assert (
        first_table_index(parse_report(make_report(blocks=[{"type": "text", "body": "x"}, section]))) is None
    )


def test_every_delta_direction_has_a_glyph() -> None:
    assert set(DELTA_GLYPHS) == set(get_args(DeltaDirection))


def test_reference_numbers_are_in_document_order_across_blocks_and_sections() -> None:
    first = {"type": "references", "items": [{"key": "a", "text": "A"}, {"key": "b", "text": "B"}]}
    nested = {"type": "references", "items": [{"key": "c", "text": "C"}, {"key": "d", "text": "D"}]}
    report = parse_report(
        make_report(blocks=[first, {"type": "section", "title": "More", "blocks": [nested]}])
    )

    assert reference_numbers(report) == {"a": 1, "b": 2, "c": 3, "d": 4}


def test_reference_numbers_reach_a_references_block_nested_in_a_grid_cell() -> None:
    refs = {"type": "references", "items": [{"key": "a", "text": "A"}]}
    grid = make_grid([make_cell(6, [refs])])
    report = parse_report(make_report(blocks=[grid]))

    assert reference_numbers(report) == {"a": 1}


def test_reconciled_table_in_a_walkthrough_step_detail_reaches_the_footer() -> None:
    step = {"label": "S", "detail": [make_reconciled_table()]}
    report = parse_report(
        make_report(
            meta={"title": "T", "source": "src"},
            blocks=[{"type": "walkthrough", "steps": [step]}],
        )
    )

    assert provenance_footer(report) == "src · Reconciles: 10 + 90 clean = 100."


def test_reference_numbers_reach_a_references_block_in_a_walkthrough_step_detail() -> None:
    refs = {"type": "references", "items": [{"key": "a", "text": "A"}]}
    step = {"label": "S", "detail": [refs]}
    report = parse_report(make_report(blocks=[{"type": "walkthrough", "steps": [step]}]))

    assert reference_numbers(report) == {"a": 1}


@pytest.mark.parametrize(
    "payload",
    ["'", "'lead", "trail'", "a''b", "x'; echo owned; '", "$(id)", "`id`", "a\nb", "a;rm -rf ~", "plain"],
    ids=[
        "only",
        "leading",
        "trailing",
        "adjacent",
        "injection",
        "subshell",
        "backtick",
        "newline",
        "metacharacters",
        "safe",
    ],
)
def test_a_body_reaches_curl_as_one_word_carrying_its_payload(payload: str) -> None:
    block = _request_block(method="POST", headers={}, body=payload)
    command = command_for(block, block.cases[0])

    result = subprocess.run(
        ["bash", "-c", f'curl() {{ printf %s "$5"; }}\n{command}'],
        capture_output=True,
        text=True,
        check=False,
    )

    assert (result.returncode, result.stdout, result.stderr) == (0, payload, "")


@pytest.mark.parametrize(
    ("text", "parts"),
    [
        ("https://{{host}}/api/{{id}}", [("https://", "host"), ("/api/", "id"), ("", "")]),
        ("https://api.example.com", [("https://api.example.com", "")]),
        ("{{a}}{{b}}", [("", "a"), ("", "b"), ("", "")]),
        ("{{a}}rest", [("", "a"), ("rest", "")]),
        ("", [("", "")]),
    ],
    ids=["two-tokens", "no-token", "adjacent", "leading", "empty"],
)
def test_variable_parts_splits_around_each_token(text: str, parts: list[tuple[str, str]]) -> None:
    assert variable_parts(text) == parts


def _request_block(**overrides: object) -> Request:
    defaults: dict[str, object] = {
        "label": "R",
        "method": "GET",
        "url": "https://{{host}}/widgets",
        "headers": {"Accept": "application/json"},
        "variables": [{"name": "host", "example": "api.example.com"}],
        "cases": [{"label": "one", "response": {"status": 200, "body": "[]"}}],
    }
    block = parse_report(make_report(blocks=[{"type": "request", **defaults, **overrides}])).blocks[0]
    assert isinstance(block, Request)
    return block


def test_a_command_quotes_the_url_the_headers_and_the_body() -> None:
    block = _request_block(method="POST", body='{"q":"it\'s"}')

    command = command_for(block, block.cases[0])

    assert "-H 'Accept: application/json'" in command
    assert '--data \'{"q":"it\'"\'"\'s"}\'' in command
    assert "'https://{{host}}/widgets'" in command


def test_a_url_made_only_of_safe_characters_is_left_bare_in_the_command() -> None:
    block = _request_block(url="https://api.example.com/widgets", headers={}, variables=[])

    assert command_for(block, block.cases[0]) == "curl -i -X GET \\\n  https://api.example.com/widgets"


def test_an_omitted_reason_phrase_is_filled_in_from_the_status() -> None:
    block = _request_block(cases=[{"label": "one", "response": {"status": 503, "body": "{}"}}])

    assert status_line(block.cases[0].response) == "503 Service Unavailable"


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        pytest.param(307, "307 Temporary Redirect", id="temporary-redirect"),
        pytest.param(206, "206 Partial Content", id="partial-content"),
        pytest.param(501, "501 Not Implemented", id="not-implemented"),
        pytest.param(413, f"413 {HTTPStatus(413).phrase}", id="renamed-in-3-13-content-too-large"),
        pytest.param(422, f"422 {HTTPStatus(422).phrase}", id="renamed-in-3-13-unprocessable"),
        pytest.param(299, "299", id="unassigned"),
    ],
)
def test_every_standard_status_gets_its_reason_phrase_and_an_unassigned_one_stays_bare(
    status: int, expected: str
) -> None:
    block = _request_block(cases=[{"label": "one", "response": {"status": status, "body": "{}"}}])

    assert status_line(block.cases[0].response) == expected


def test_an_authored_reason_phrase_wins_over_the_standard_text() -> None:
    block = _request_block(
        cases=[{"label": "one", "response": {"status": 200, "reason": "Grand", "body": "{}"}}]
    )

    assert status_line(block.cases[0].response) == "200 Grand"


def test_a_case_label_carrying_a_quote_cannot_break_out_of_the_command() -> None:
    """The case axis resolves into each word before that word is quoted. Resolving afterwards drops the
    label inside an already-open quote, and a label is ordinary authored text."""
    block = _request_block(
        url="https://api.example.com/{{resource}}",
        headers={},
        variables=[],
        case_variable="resource",
        cases=[{"label": "x'; echo owned; '", "response": {"status": 200, "body": "{}"}}],
    )

    word = command_for(block, block.cases[0]).splitlines()[-1].strip()
    shell = subprocess.run(
        ["bash", "-c", f'set -- {word}; printf "%s|%s" "$#" "$1"'], capture_output=True, text=True
    )

    assert shell.stdout == "1|https://api.example.com/x'; echo owned; '"


def test_a_body_carries_its_tokens_through_to_the_command_unresolved() -> None:
    block = _request_block(
        method="POST",
        body='{"user":"{{user}}","secret":"{{token}}"}',
        variables=[
            {"name": "host", "example": "a"},
            {"name": "user", "example": "sam"},
            {"name": "token", "secret": True},
        ],
    )

    command = command_for(block, block.cases[0])

    assert '--data \'{"user":"{{user}}","secret":"{{token}}"}\'' in command
    assert "{{user}}" in request_wire(block, block.cases[0])


def _flow(**overrides: object) -> RequestFlow:
    defaults: dict[str, object] = {
        "label": "Token, then read",
        "variables": [{"name": "host", "example": "api.example.com"}],
        "steps": [
            {
                "label": "Get a token",
                "method": "POST",
                "url": "https://{{host}}/auth",
                "captures": [{"name": "token", "json_path": "$.accessToken"}],
                "cases": [{"label": "ok", "response": {"status": 200, "body": "{}"}}],
            },
            {
                "label": "Use it",
                "method": "GET",
                "url": "https://{{host}}/me",
                "headers": {"Authorization": "Bearer {{token}}"},
                "cases": [{"label": "ok", "response": {"status": 200, "body": "{}"}}],
            },
        ],
    }
    block = parse_report(make_report(blocks=[{"type": "request_flow", **defaults, **overrides}])).blocks[0]
    assert isinstance(block, RequestFlow)
    return block


def test_produced_names_pairs_each_capture_with_the_step_that_makes_it() -> None:
    flow = _flow()

    assert produced_names(flow) == [(flow.steps[0].captures[0], 1)]


_PHRASES_PYTHON_RENAMED: dict[int, frozenset[str]] = {
    422: frozenset({"Unprocessable Entity", "Unprocessable Content"}),
}


def test_the_reason_table_in_the_browser_script_agrees_with_the_phrases_the_page_renders() -> None:
    script = Path("src/skaldr/components/_request.html.j2").read_text(encoding="utf-8")
    literal = re.search(r"var REASONS = \{(.*?)\};", script, re.DOTALL)
    assert literal is not None

    in_browser = {int(code): text for code, text in re.findall(r'(\d{3}):\s*"([^"]+)"', literal.group(1))}
    disagreeing = {
        code: text
        for code, text in in_browser.items()
        if text != reason_phrase(code)
        and not {text, reason_phrase(code)} <= _PHRASES_PYTHON_RENAMED.get(code, frozenset[str]())
    }

    assert (sorted(in_browser), disagreeing) == (
        [
            200,
            201,
            202,
            204,
            301,
            302,
            304,
            400,
            401,
            403,
            404,
            405,
            409,
            410,
            415,
            422,
            429,
            500,
            502,
            503,
            504,
        ],
        {},
    )
