from typing import TypedDict

from skaldr.models import Swimlane, SwimlaneStepState


class _SwimBox(TypedDict):
    """A rectangle on the grid, as 1-based start/end grid line numbers (column then row)."""

    line_start: int
    line_end: int
    row_start: int
    row_end: int


class SwimStep(TypedDict):
    n: str
    label: str
    value: float | None  # the step's own value, shown on the ticket's trailing edge; None → hidden
    url: str | None  # optional link; the number becomes an <a> when set
    state: SwimlaneStepState  # done | current | todo (default) | blocked (dashed) | deferred (warm hollow)
    deps: list[str]  # the numbers (n) of the steps this one depends on, for a compact blocked-by marker


class SwimSubcol(TypedDict):
    col: str
    group: str | None
    tone: str | None  # the group's palette colour name (a BadgeColor), or None for an ungrouped column
    line_start: int
    line_end: int


class SwimHeader(_SwimBox):
    label: str  # one per column, spanning that column's sub-columns
    sub: str | None  # optional secondary caption under the header label


class SwimTint(_SwimBox):
    tone: str | None  # a header sub-cell, tinted by its group's palette colour (or None, untinted)


class SwimGutter(TypedDict):
    lane: str
    total: float | None  # the lane's summed step values, shown beside the label; None when off
    row_start: int
    row_end: int


class SwimCell(_SwimBox):
    tone: str | None  # the group's palette colour, or None for an ungrouped column
    steps: list[SwimStep]


class SwimCapBottom(_SwimBox):
    color: str  # the group's palette colour name (a BadgeColor)
    edges: str  # "left"/"right"/"left right"/"" — which outer sides carry a grey (frame-matching) edge


class SwimCap(SwimCapBottom):
    label: str
    total: float | None  # the group's summed step values, shown beside the label; None when off


class SwimFoot(_SwimBox):
    total: float  # one column's summed step values, in the footer totals row


class SwimFootRow(TypedDict):
    label: str  # gutter label for the totals row; currently always "Total"
    banded: bool  # True → panel background; False (a column is split across groups) → transparent
    row_start: int
    row_end: int
    cells: list[SwimFoot]  # one per column


class SwimVSolid(TypedDict):
    col_start: int
    col_end: int
    poke: bool  # True → runs through the poke zone (trimmed) to separate two group caps
    row_start: int
    row_end: int


class SwimVDash(TypedDict):
    col_start: int
    col_end: int
    row_start: int
    row_end: int


class SwimHDiv(TypedDict):
    row: int  # grid row line the divider sits on
    col_start: int  # 1 = full width incl. the gutter (inter-lane); 2 = data columns only (header/body)


class SwimLayout(TypedDict):
    has_groups: bool
    col_template: str
    row_template: str
    subcols: list[SwimSubcol]
    headers: list[SwimHeader]
    header_tints: list[SwimTint]
    gutter: list[SwimGutter]
    cells: list[SwimCell]
    caps: list[SwimCap]
    caps_bottom: list[SwimCapBottom]
    vsolid: list[SwimVSolid]
    vdash: list[SwimVDash]
    hdiv: list[SwimHDiv]
    foot: SwimFootRow | None  # per-column totals row; None when no step carries a value
    tbl: _SwimBox
    frame_square_right: bool  # square the frame's right corners when a cap owns the right edge
    state_legend: list[SwimlaneStepState]  # states used, canonical order; [] when <2 distinct → no legend
    n_width: int  # widest step number (char count) → every badge sizes to it so labels line up


_SWIM_STATE_ORDER: tuple[SwimlaneStepState, ...] = ("done", "current", "todo", "blocked", "deferred")


class SwimTotals(TypedDict):
    lanes: dict[str, float]
    columns: dict[str, float]
    groups: dict[str, float]


def swimlane_totals(block: Swimlane) -> SwimTotals | None:
    if all(step.value is None for step in block.steps):
        return None
    steps = block.steps
    return {
        "lanes": {
            lane.key: sum(step.value or 0 for step in steps if step.lane == lane.key) for lane in block.lanes
        },
        "columns": {
            column.key: sum(step.value or 0 for step in steps if step.col == column.key)
            for column in block.columns
        },
        "groups": {
            group.name: sum(step.value or 0 for step in steps if block.step_group(step) == group.name)
            for group in block.groups
        },
    }


def _legend_states(present: set[SwimlaneStepState]) -> list[SwimlaneStepState]:
    return [state for state in _SWIM_STATE_ORDER if state in present] if len(present) >= 2 else []


def swimlane_state_legend(block: Swimlane) -> list[SwimlaneStepState]:
    return _legend_states({step.shown_state for step in block.steps})


def swimlane_marked_state_legend(block: Swimlane) -> list[SwimlaneStepState]:
    marked: set[SwimlaneStepState] = {state for step in block.steps if (state := step.state) is not None}
    some_unmarked = any(step.state is None for step in block.steps)
    if some_unmarked and marked:
        return [state for state in _SWIM_STATE_ORDER if state in marked]
    return _legend_states(marked)


def swimlane_layout(block: Swimlane) -> SwimLayout:
    """Everything the swimlane macro places on its CSS grid, as absolute 1-based grid line numbers so
    the template only loops and never computes. The grid is a lane gutter (track 1) + one track per
    atomic sub-column (a `(column, group)` segment); rows are an optional top poke zone (group caps),
    the sprint header, one row per lane, an optional footer totals row (when steps carry a `value`),
    and an optional bottom poke zone.

    The frame wraps the whole table incl. the lane gutter (track 1). The empty top-left cell where the
    gutter meets the sprint-header row is not boxed off: the header/body divider spans the data columns
    only (it skips the gutter), so that cell opens down into the row-label column rather than being a
    closed box; the gutter/data seam still runs the full height (it is the sprint header's left border).
    Line languages, all one grey: SOLID
    verticals mark real column (sprint) boundaries and normally live inside the table rows only (a
    group cap spans across them), except where two DIFFERENT group caps meet — there the solid runs
    full height (poke zones + table) to separate the caps; DASHED verticals mark a group split within
    a column and run from the top cap down to the last lane. When a totals footer is present the dash
    stops at its top edge (a per-column total is not split), so the bottom caps below it read as
    colour-separated rather than dash-separated. Horizontal dividers are one line each (never stitched
    from cell borders); the table's outer edges come from the frame overlay."""
    subcols = block.subcolumns()
    ncols = len(subcols)
    nlanes = len(block.lanes)
    has_groups = bool(block.groups)
    totals = swimlane_totals(block)
    nfoot = int(totals is not None)
    # group name → its palette colour (an ungrouped segment's None group has no tint).
    color_of = {group.name: group.color for group in block.groups}

    # rows: [poke-top] header [lane…] [footer?] [poke-bottom]. Header starts at line `top`. The footer
    # (per-column totals) only exists when a step carries a value, and it counts as a table row — the
    # frame, column solids and gutter seam all extend through it.
    top = 2 if has_groups else 1
    header_row = (top, top + 1)
    lane_rows = [(top + 1 + index, top + 2 + index) for index in range(nlanes)]
    footer_row = (top + 1 + nlanes, top + 2 + nlanes)
    table_rows = (top, top + 1 + nlanes + nfoot)
    full_rows = (1, top + 2 + nlanes + nfoot) if has_groups else table_rows
    poke_top_row = (1, 2)
    poke_bottom_row = (top + 1 + nlanes + nfoot, top + 2 + nlanes + nfoot)

    # column line for sub-column index i: track (i + 2), spanning lines (i + 2)..(i + 3).
    def col_lines(index: int) -> tuple[int, int]:
        return index + 2, index + 3

    def column_span(col: str) -> tuple[int, int]:
        """Grid lines spanning every sub-column of `col` (a column split across groups has several)."""
        first, last = block.column_spans[col]
        return col_lines(first)[0], col_lines(last)[1]

    subcol_out: list[SwimSubcol] = []
    for index, (col, group_name) in enumerate(subcols):
        start, end = col_lines(index)
        subcol_out.append(
            {
                "col": col,
                "group": group_name,
                "tone": color_of[group_name] if group_name is not None else None,
                "line_start": start,
                "line_end": end,
            }
        )

    # sprint-header tint sub-cells (one per sub-column) + one label per column spanning its sub-columns.
    header_tints: list[SwimTint] = [
        {
            "tone": sub["tone"],
            "line_start": sub["line_start"],
            "line_end": sub["line_end"],
            "row_start": header_row[0],
            "row_end": header_row[1],
        }
        for sub in subcol_out
    ]
    headers: list[SwimHeader] = []
    for col in block.columns:
        line_start, line_end = column_span(col.key)
        headers.append(
            {
                "label": col.name,
                "sub": col.sub,
                "line_start": line_start,
                "line_end": line_end,
                "row_start": header_row[0],
                "row_end": header_row[1],
            }
        )

    lane_total = totals["lanes"] if totals is not None else {}

    gutter: list[SwimGutter] = [
        {
            "lane": lane.name,
            "total": lane_total.get(lane.key),
            "row_start": lane_rows[index][0],
            "row_end": lane_rows[index][1],
        }
        for index, lane in enumerate(block.lanes)
    ]

    cells: list[SwimCell] = []
    for lane_index, lane in enumerate(block.lanes):
        row_start, row_end = lane_rows[lane_index]
        for sub in subcol_out:
            steps: list[SwimStep] = [
                {
                    "n": step.n,
                    "label": step.label,
                    "value": step.value,
                    "url": step.url,
                    "state": step.shown_state,
                    "deps": block.dependency_numbers(step),
                }
                for step in block.steps_at(lane.key, sub["col"], sub["group"])
            ]
            cells.append(
                {
                    "tone": sub["tone"],
                    "line_start": sub["line_start"],
                    "line_end": sub["line_end"],
                    "row_start": row_start,
                    "row_end": row_end,
                    "steps": steps,
                }
            )

    # caps: each group's contiguous sub-column run, top cap (labelled) + bottom cap. The leftmost /
    # rightmost cap carries a grey outer edge (`edges`) so its rounded outer corner is concentric with
    # the table frame's — a grey rounded border with the group's coloured accent on top, same radius.
    # Interior cap sides are the dashed splits.
    right_edge = ncols + 2
    caps: list[SwimCap] = []
    caps_bottom: list[SwimCapBottom] = []
    for group in block.groups:
        first, last = block.group_spans[group.name]
        line_start, line_end = col_lines(first)[0], col_lines(last)[1]
        edges = ("left " if line_start == 2 else "") + ("right" if line_end == right_edge else "")
        group_total = totals["groups"][group.name] if totals is not None else None
        caps.append(
            {
                "label": group.name,
                "color": group.color,
                "edges": edges.strip(),
                "total": group_total,
                "line_start": line_start,
                "line_end": line_end,
                "row_start": poke_top_row[0],
                "row_end": poke_top_row[1],
            }
        )
        caps_bottom.append(
            {
                "color": group.color,
                "edges": edges.strip(),
                "line_start": line_start,
                "line_end": line_end,
                "row_start": poke_bottom_row[0],
                "row_end": poke_bottom_row[1],
            }
        )

    # interior vertical lines from sub-column boundaries. Column change → solid (table rows); same
    # column, different group → dashed (full height). Plus the gutter/data seam across the whole table
    # body (header + lanes) — it is the sprint header's left border as well as the row-label separator.
    # The table's outer edges come from the frame overlay.
    vsolid: list[SwimVSolid] = [
        {"col_start": 2, "col_end": 3, "poke": False, "row_start": table_rows[0], "row_end": table_rows[1]}
    ]
    vdash: list[SwimVDash] = []
    for index in range(ncols - 1):
        boundary_line = col_lines(index)[1]
        (left_col, left_group), (right_col, right_group) = subcols[index], subcols[index + 1]
        if left_col != right_col:
            # A sprint boundary. If two DIFFERENT group caps meet here, run the line full height
            # (trimmed, like a group split) so the caps are separated; if one cap SPANS the boundary
            # (same group either side), keep it table-rows only so the cap reads as continuous. A
            # boundary against an ungrouped column has only one cap, so it stays table-rows only too —
            # a full-height line there would poke into the cap zone with nothing beside it.
            caps_differ = left_group is not None and right_group is not None and left_group != right_group
            vsolid.append(
                {
                    "col_start": boundary_line,
                    "col_end": boundary_line + 1,
                    "poke": caps_differ,
                    "row_start": full_rows[0] if caps_differ else table_rows[0],
                    "row_end": full_rows[1] if caps_differ else table_rows[1],
                }
            )
        elif left_group != right_group:
            # a group split within a column, full height so it hugs the caps. A totals footer stops it
            # at the footer's top edge — a per-column total is not itself split. The dash must cross the
            # footer to reach the bottom caps, so trimming it there trades the bottom caps' dash for
            # colour separation; keeping the totals row dash-free wins that trade.
            vdash.append(
                {
                    "col_start": boundary_line,
                    "col_end": boundary_line + 1,
                    "row_start": full_rows[0],
                    "row_end": footer_row[0] if totals is not None else full_rows[1],
                }
            )
    # horizontal dividers, each a continuous line. The header/body divider spans the DATA columns only
    # (`col_start` 2), NOT the gutter — that gutter segment was the line that closed off the empty
    # top-left corner cell, so dropping it opens the corner into the row-label column. Inter-lane
    # dividers span the full width (incl. the gutter) so the row labels stay separated. The outer
    # top/bottom edges come from the frame overlay.
    hdiv: list[SwimHDiv] = [{"row": header_row[1], "col_start": 2}]
    for index in range(1, nlanes):
        hdiv.append({"row": lane_rows[index][0], "col_start": 1})
    # a full-width divider above the totals row sets it off from the lane rows.
    if totals is not None:
        hdiv.append({"row": footer_row[0], "col_start": 1})

    # footer totals row: one cell per column, summing that column's step values across all lanes/groups.
    foot: SwimFootRow | None = None
    if totals is not None:
        foot_cells: list[SwimFoot] = []
        for col in block.columns:
            line_start, line_end = column_span(col.key)
            foot_cells.append(
                {
                    "total": totals["columns"][col.key],
                    "line_start": line_start,
                    "line_end": line_end,
                    "row_start": footer_row[0],
                    "row_end": footer_row[1],
                }
            )
        # a split column (more sub-columns than columns) drops the footer's panel band for a lighter,
        # transparent totals row over the busier split structure; an unsplit swimlane keeps the band.
        banded = ncols == len(block.columns)
        foot = {
            "label": "Total",
            "banded": banded,
            "row_start": footer_row[0],
            "row_end": footer_row[1],
            "cells": foot_cells,
        }

    return {
        "has_groups": has_groups,
        "state_legend": swimlane_state_legend(block),
        "n_width": max(len(step.n) for step in block.steps),
        "col_template": f"max-content repeat({ncols}, var(--swim-col))",
        "row_template": _swim_row_template(has_groups, nlanes, totals is not None),
        "subcols": subcol_out,
        "headers": headers,
        "header_tints": header_tints,
        "gutter": gutter,
        "cells": cells,
        "caps": caps,
        "caps_bottom": caps_bottom,
        "vsolid": vsolid,
        "vdash": vdash,
        "hdiv": hdiv,
        "foot": foot,
        # the rounded frame wraps the whole table incl. the lane gutter (line 1 to the right edge), so
        # the row-header column keeps its borders.
        "tbl": {"line_start": 1, "line_end": ncols + 2, "row_start": table_rows[0], "row_end": table_rows[1]},
        # when the rightmost column carries a cap, its right edge IS the table's right edge — so square
        # the frame's right corners, letting the cap's right border run straight down to meet the frame
        # instead of gapping against a rounded corner. The left (gutter) corners stay rounded.
        "frame_square_right": has_groups and subcols[-1][1] is not None,
    }


def _swim_row_template(has_groups: bool, nlanes: int, has_totals: bool) -> str:
    tracks = ["auto"] * nlanes  # one per lane
    if has_totals:
        tracks.append("auto")  # the footer totals row
    body = " ".join(["auto", *tracks])  # header + lanes + footer
    if has_groups:
        return f"var(--swim-poke) {body} var(--swim-pokeb)"
    return body
