from skaldr.compute import (
    first_table_index,
    fmt,
    heading_slugs,
    provenance_footer,
    reconcile_line,
    reference_numbers,
    swimlane_layout,
    toc_entries,
    used_badges,
)
from skaldr.models import Swimlane, Table, parse_report
from tests.factories import make_cell, make_grid, make_reconciled_table, make_report


def _swimlane(**overrides: object) -> Swimlane:
    block = parse_report(make_report(blocks=[{"type": "swimlane", **overrides}])).blocks[0]
    assert isinstance(block, Swimlane)
    return block


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
        {"label": "S1", "line_start": 2, "line_end": 3, "row_start": 2, "row_end": 3},
        {"label": "S2", "line_start": 3, "line_end": 6, "row_start": 2, "row_end": 3},
        {"label": "S3", "line_start": 6, "line_end": 7, "row_start": 2, "row_end": 3},
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
            "steps": [{"n": "1", "label": "a", "value": None, "url": None, "muted": False, "deps": []}],
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
            "steps": [{"n": "2", "label": "b", "value": None, "url": None, "muted": False, "deps": []}],
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
        "steps": [{"n": "1", "label": "a", "value": 2.5, "url": None, "muted": False, "deps": []}],
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


def test_swimlane_layout_a_muted_step_value_still_counts_in_totals() -> None:
    """`muted` only de-emphasises visually — the step's value is still summed into the totals, so a
    muted step must not silently drop out of the column/lane sums."""
    block = _swimlane(
        lanes=["A"],
        columns=["C1"],
        steps=[
            {"lane": "A", "col": "C1", "n": "1", "label": "a", "value": 3},
            {"lane": "A", "col": "C1", "n": "2", "label": "b", "value": 4, "muted": True},
        ],
    )

    layout = swimlane_layout(block)

    # 3 + 4: the muted step's 4 is included
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
        {"n": "2", "label": "b", "value": None, "url": None, "muted": False, "deps": ["1"]}
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


def test_fmt_variants() -> None:
    assert fmt(1500) == "1,500"
    assert fmt(1500.0) == "1,500"
    assert fmt(1500.5) == "1,500.5"
    assert fmt("HEALTHY") == "HEALTHY"
    assert fmt(True) == "True"


def test_heading_slugs_dedup_collisions() -> None:
    report = parse_report(
        make_report(
            meta={"title": "T", "toc": True},
            blocks=[{"type": "heading", "text": "Details"}, {"type": "heading", "text": "Details"}],
        )
    )

    assert sorted(heading_slugs(report).values()) == ["details", "details-2"]


def test_toc_uses_deduped_slugs() -> None:
    report = parse_report(
        make_report(
            meta={"title": "T", "toc": True},
            blocks=[{"type": "heading", "text": "Details"}, {"type": "heading", "text": "Details"}],
        )
    )

    assert toc_entries(report, heading_slugs(report)) == [("details", "Details"), ("details-2", "Details")]


def test_toc_empty_when_toc_disabled() -> None:
    report = parse_report(make_report(blocks=[{"type": "heading", "text": "X"}]))

    assert toc_entries(report, heading_slugs(report)) == []


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


def test_first_table_index() -> None:
    report = parse_report(make_report(blocks=[{"type": "text", "body": "x"}, make_reconciled_table()]))

    assert first_table_index(report) == 1


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
