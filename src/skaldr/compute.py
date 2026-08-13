"""Derived, never-authored values: TOC, the used-badge legend, the provenance footer, the
number/percent formatting helpers, and the swimlane grid layout — everything the templates need
computed from the data so it can't drift from it.

`col_sum` is re-exported from `models` (it lives there because `Table._reconcile` validates against
it, and models must not import compute) so templates can reach it through this one module.
"""

import re
from collections import Counter
from collections.abc import Callable, Iterator, Sequence
from typing import Any, TypedDict

from skaldr.errors import ReportError
from skaldr.models import (
    AnyBlock,
    Badge,
    Grid,
    Heading,
    InnerGrid,
    Matrix,
    MatrixCell,
    Panel,
    Report,
    Section,
    Swimlane,
    SwimlaneStep,
    SwimlaneStepState,
    Table,
    Walkthrough,
    col_sum,
    iter_matrices,
    iter_reference_items,
    iter_referenced_badge_keys,
    iter_tables,
)

__all__ = [
    "anchor_slugs",
    "col_sum",
    "first_table_index",
    "fmt",
    "matrix_grid",
    "matrix_tallies",
    "pct",
    "provenance_footer",
    "reconcile_line",
    "reference_numbers",
    "swimlane_layout",
    "table_rollup",
    "table_tallies",
    "toc_entries",
    "used_badges",
]

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


def _slugify(text: str) -> str:
    return _SLUG_STRIP.sub("-", text.lower()).strip("-") or "section"


def _iter_anchored(blocks: Sequence[AnyBlock]) -> Iterator[Heading | Section]:
    """Headings (any level, nested) and sections, in document order — the blocks that carry an anchor
    id and can appear in the TOC. A section yields itself, then its inner headings."""
    for block in blocks:
        if isinstance(block, Heading):
            yield block
        elif isinstance(block, Section):
            yield block
            yield from _iter_anchored(block.blocks)
        elif isinstance(block, Panel):
            yield from _iter_anchored(block.blocks)
        elif isinstance(block, (Grid, InnerGrid)):
            for cell in block.cells:
                yield from _iter_anchored(cell.blocks)
        elif isinstance(block, Walkthrough):
            for step in block.steps:
                yield from _iter_anchored(step.detail)


def reference_numbers(report: Report) -> dict[str, int]:
    """`reference key -> 1-based number`, in document order across every `references` block, so an
    inline `[^key]` marker and its entry in the list carry the same number from one source. Keys are
    globally unique (a Report validator enforces it), so each contributes exactly one number."""
    numbers: dict[str, int] = {}
    for item in iter_reference_items(report.blocks):
        numbers[item.key] = len(numbers) + 1
    return numbers


def anchor_slugs(report: Report) -> dict[int, str]:
    """`id(block) -> slug` for every heading and section, in document order. One source for the
    heading/section `id` attribute, the TOC, and same-page `#link` targets so they can't drift. An
    author-set `id` is used verbatim (and reserved so a text-derived slug yields to it with a `-N`
    suffix); a text-derived slug de-dups the same way. Duplicate author ids fail the build."""
    anchored = list(_iter_anchored(report.blocks))
    explicit = [block.id for block in anchored if block.id is not None]
    duplicate = next((anchor for anchor in explicit if explicit.count(anchor) > 1), None)
    if duplicate is not None:
        raise ReportError(f"duplicate anchor id '{duplicate}' — a heading/section id must be unique")

    slugs: dict[int, str] = {}
    taken: set[str] = set(explicit)
    for block in anchored:
        if block.id is not None:
            slugs[id(block)] = block.id
            continue
        base = _slugify(block.text if isinstance(block, Heading) else block.title)
        slug, suffix = base, 1
        while slug in taken:
            suffix += 1
            slug = f"{base}-{suffix}"
        taken.add(slug)
        slugs[id(block)] = slug
    return slugs


def toc_entries(report: Report, slugs: dict[int, str]) -> list[tuple[str, str]]:
    """(slug, text) for top-level level-2 headings and sections, in document order — the TOC targets.
    A section is a top-level region on a par with an h2, so it earns a TOC entry and its own anchor."""
    if not report.meta.toc:
        return []
    entries: list[tuple[str, str]] = []
    for block in report.blocks:
        if isinstance(block, Heading) and block.level == 2:
            entries.append((slugs[id(block)], block.text))
        elif isinstance(block, Section):
            entries.append((slugs[id(block)], block.title))
    return entries


def first_table_index(report: Report) -> int | None:
    """Index of the first top-level table block (the legend renders just before it)."""
    for index, block in enumerate(report.blocks):
        if isinstance(block, Table):
            return index
    return None


def used_badges(report: Report) -> list[tuple[str, Badge]]:
    """Declared badges that are actually referenced AND carry a legend, in declaration order (drives the
    legend). A badge with `legend: false` opts out — its chips still render, but it never lists."""
    referenced = set(iter_referenced_badge_keys(report.blocks))
    return [
        (key, badge)
        for key, badge in report.badges.items()
        if key in referenced and badge.legend is not False
    ]


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
    has_totals = any(step.value is not None for step in block.steps)
    nfoot = int(has_totals)  # 1 when a totals footer row is present
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
        indices = [index for index, (segment_col, _) in enumerate(subcols) if segment_col == col]
        return col_lines(indices[0])[0], col_lines(indices[-1])[1]

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

    # value rollups (only surfaced when has_totals). A step with no value counts as 0; a group total
    # sums the steps resolved into that group, so it composes with the cap overlay.
    def value_of(step: SwimlaneStep) -> float:
        return step.value if step.value is not None else 0

    def sum_where(predicate: Callable[[SwimlaneStep], bool]) -> float:
        return sum(value_of(step) for step in block.steps if predicate(step))

    lane_total = (
        {lane.key: sum_where(lambda step, key=lane.key: step.lane == key) for lane in block.lanes}
        if has_totals
        else {}
    )

    gutter: list[SwimGutter] = [
        {
            "lane": lane.name,
            "total": lane_total.get(lane.key),
            "row_start": lane_rows[index][0],
            "row_end": lane_rows[index][1],
        }
        for index, lane in enumerate(block.lanes)
    ]

    # a step's `depends_on` holds other steps' ids; show the reader the numbers (n) they recognise.
    id_to_n = {step.id: step.n for step in block.steps if step.id is not None}

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
                    "state": step.state,
                    # dedupe on the displayed number (order-preserving) so repeats never show "needs 1, 1"
                    "deps": list(dict.fromkeys(id_to_n[dep] for dep in step.depends_on)),
                }
                for step in block.steps
                if step.lane == lane.key and step.col == sub["col"] and block.step_group(step) == sub["group"]
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
        indices = [index for index, (_, name) in enumerate(subcols) if name == group.name]
        line_start, line_end = col_lines(indices[0])[0], col_lines(indices[-1])[1]
        edges = ("left " if line_start == 2 else "") + ("right" if line_end == right_edge else "")
        group_total = (
            sum_where(lambda step, name=group.name: block.step_group(step) == name) if has_totals else None
        )
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
                    "row_end": footer_row[0] if has_totals else full_rows[1],
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
    if has_totals:
        hdiv.append({"row": footer_row[0], "col_start": 1})

    # footer totals row: one cell per column, summing that column's step values across all lanes/groups.
    foot: SwimFootRow | None = None
    if has_totals:
        foot_cells: list[SwimFoot] = []
        for col in block.columns:
            line_start, line_end = column_span(col.key)
            foot_cells.append(
                {
                    "total": sum_where(lambda step, key=col.key: step.col == key),
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

    present_states = {step.state for step in block.steps}
    state_legend: list[SwimlaneStepState] = (
        [s for s in _SWIM_STATE_ORDER if s in present_states] if len(present_states) >= 2 else []
    )

    return {
        "has_groups": has_groups,
        "state_legend": state_legend,
        "n_width": max(len(step.n) for step in block.steps),
        "col_template": f"max-content repeat({ncols}, var(--swim-col))",
        "row_template": _swim_row_template(has_groups, nlanes, has_totals),
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


def provenance_footer(report: Report) -> str | None:
    """Composed footer: meta source/date/updated + each reconciled table's 'Reconciles: …' line."""
    parts = [part for part in (report.meta.source, report.meta.date) if part]
    if report.meta.updated:
        parts.append(f"updated {report.meta.updated}")
    parts.extend(reconcile_line(table) for table in iter_tables(report.blocks) if table.reconcile is not None)
    return " · ".join(parts) if parts else None


def fmt(value: Any) -> str:
    """Thousands separators for ints/whole floats; strings pass through untouched."""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float):
        # Round first so summed float noise (100.00000000000001) reads as a clean count.
        rounded = round(value, 4)
        return f"{rounded:,.0f}" if rounded.is_integer() else f"{rounded:,}"
    return str(value)


def pct(value: float, of: float) -> str:
    ratio = value / of * 100
    if 0 < ratio < 0.1:
        return "<0.1%"
    return f"{ratio:.1f}%"


class RollupBucket(TypedDict):
    key: str  # a badge key, resolved to its chip label/tone at render time
    count: int


def _rollup_counts(rows: Sequence[dict[str, Any]], by: str) -> Counter[str]:
    """Count rows by a badge column's value, in first-appearance order (a blank cell counts toward no
    badge). The one tally rule shared by a table's own `rollup` strip and its `of_tables` contribution,
    so the two views of the same table can never drift apart."""
    counts: Counter[str] = Counter()
    for row in rows:
        key = row[by].strip()
        if key:
            counts[key] += 1
    return counts


def table_rollup(table: Table) -> list[RollupBucket] | None:
    """Count the table's rows by its rollup badge column, in first-appearance order — a summary
    derived from the rows, so it cannot drift from them. None when no rollup is declared. A row left
    blank in that column contributes to no bucket; the table validator guarantees at least one is set."""
    if table.rollup is None:
        return None
    counts = _rollup_counts(table.all_rows(), table.rollup.by)
    return [{"key": key, "count": count} for key, count in counts.items()]


class DerivedTally(TypedDict):
    counts: dict[str, int]  # badge key -> how many of the source's units are in that state
    total: int  # the percentage denominator (a matrix's cells, or a table's rows)


def matrix_tallies(report: Report) -> dict[str, DerivedTally]:
    """`matrix id -> {counts: {badge: n}, total: rows*columns}` for every id'd matrix — the derived
    source a `cards` item reads via `of_matrix`. The denominator is the full grid (blank cells count as
    uncovered), so a derived card's percentage is the share of the whole matrix in that state. A matrix
    with no id contributes nothing (only referenceable matrices are tallied)."""
    tallies: dict[str, DerivedTally] = {}
    for matrix in iter_matrices(report.blocks):
        if matrix.id is None:
            continue
        counts: Counter[str] = Counter(cell.badge for cell in matrix.cells if cell.badge is not None)
        tallies[matrix.id] = {"counts": dict(counts), "total": len(matrix.rows) * len(matrix.columns)}
    return tallies


def table_tallies(report: Report) -> dict[str, DerivedTally]:
    """`table id -> {counts: {badge: n}, total: row count}` for every id'd table that declares a `rollup`
    — the derived source a `cards` item reads via `of_tables`. Rows are counted by the table's own
    `rollup.by` column (a blank cell counts toward no badge); the denominator is every row, so an
    `of_tables` card's percentage is the badge's share across the referenced tables. A table with no id
    or no rollup contributes nothing (the validator requires both on any referenced table)."""
    tallies: dict[str, DerivedTally] = {}
    for table in iter_tables(report.blocks):
        if table.id is None or table.rollup is None:
            continue
        rows = table.all_rows()
        tallies[table.id] = {"counts": dict(_rollup_counts(rows, table.rollup.by)), "total": len(rows)}
    return tallies


def matrix_grid(block: Matrix) -> list[list[MatrixCell | None]]:
    """The matrix as a row-major grid: `grid[r][c]` is the cell for row `rows[r]`, column `columns[c]`,
    or None for a blank (unfilled) cell. The block validator guarantees at most one cell per (row, col),
    so the lookup is unambiguous; the template only loops and never searches."""
    lookup = {(cell.row, cell.col): cell for cell in block.cells}
    return [[lookup.get((row, col)) for col in block.columns] for row in block.rows]


def reconcile_line(table: Table) -> str:
    if table.reconcile is None:
        return ""
    total = col_sum(table.all_rows(), table.reconcile.column)
    handled = table.reconcile.handled
    if handled is not None:
        return (
            f"Reconciles: {fmt(total)} + {fmt(handled.value)} {handled.label.lower()} "
            f"= {fmt(table.reconcile.total)}."
        )
    return f"Reconciles: {fmt(total)} = {fmt(table.reconcile.total)}."
