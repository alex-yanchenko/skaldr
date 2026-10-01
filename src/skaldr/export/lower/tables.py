from collections.abc import Mapping, Sequence
from typing import Any, cast

from skaldr import compute
from skaldr.export.inline import bold, italic, labelled, paragraphs, plain
from skaldr.export.lower.context import Lowering, cells, tone_named
from skaldr.export.tree import Node, Paragraph, Table, TableCell, TableRow
from skaldr.models import Comparison, ComparisonCell, Matrix, Swimlane, SwimlaneStep, SwimlaneStepState
from skaldr.models import Table as TableBlock
from skaldr.richtext import Break, Link, Plain, Rich

SWIMLANE_MARK: dict[SwimlaneStepState, str] = {
    "done": "✅",
    "current": "🔵",
    "todo": "⚪",
    "blocked": "⛔",
    "deferred": "⏸️",
}
INDICATOR_MARK = {"success": "🟢", "warning": "🟡", "danger": "🔴", "info": "🔵", "neutral": "⚪"}

Row = Mapping[str, object]


def _after_break(runs: Rich) -> Rich:
    return (Break(), *runs) if runs else ()


def _blank_cells(count: int) -> tuple[TableCell, ...]:
    return tuple(TableCell(()) for _ in range(count))


def _cell_text(value: object, lowering: Lowering) -> Rich:
    if value is None or value == "":
        return ()
    runs: Rich = ()
    for part in paragraphs(str(value)):
        runs += _after_break(lowering.rich(part)) if runs else lowering.rich(part)
    return runs


def _badge_keys(raw: object) -> list[str]:
    values = cast("list[object]", raw) if isinstance(raw, list) else [raw]
    return [str(key).strip() for key in values if key is not None and str(key).strip()]


def _subrows(row: Row) -> list[Row]:
    return cast("list[Row]", row.get("subrows") or [])


def _title_cell(block: TableBlock, row: Row, value: object, lowering: Lowering) -> TableCell:
    text = _cell_text(value, lowering)
    for badge_column in block.title_badges:
        keys = _badge_keys(row.get(badge_column.key))
        if keys:
            text += plain(" ") + lowering.chips(keys)
    for sub in _subrows(row):
        text += _after_break(lowering.rich(str(sub["label"])) + plain(f": {compute.fmt(sub['value'])}"))
    return TableCell(text)


def _number_cell(block: TableBlock, column_pct_of_total: bool, value: object) -> TableCell:
    text = plain(compute.fmt(value)) if value is not None else ()
    if column_pct_of_total and block.reconcile and isinstance(value, (int, float)):
        text += plain(f" ({compute.pct(value, block.reconcile.total)} of total)")
    return TableCell(text)


def _table_row(block: TableBlock, row: Row, title_key: str, lowering: Lowering) -> TableRow:
    row_cells: list[TableCell] = []
    for column in block.cell_columns:
        value = row.get(column.key)
        if column.key == title_key:
            row_cells.append(_title_cell(block, row, value, lowering))
        elif column.kind == "number":
            row_cells.append(_number_cell(block, column.pct_of_total, value))
        elif column.kind == "indicator":
            tone = str(value or "").strip()
            row_cells.append(TableCell(plain(INDICATOR_MARK.get(tone, "")), tone_named(tone)))
        elif column.kind == "badge":
            row_cells.append(TableCell(lowering.chips(_badge_keys(value))))
        else:
            row_cells.append(TableCell(_cell_text(value, lowering)))
    raw_tone = row.get("tone")
    tone = tone_named(raw_tone) if isinstance(raw_tone, str) else None
    if tone is None and block.tint_by:
        keys = _badge_keys(row.get(block.tint_by))
        if keys:
            tone = tone_named(lowering.report.badges[keys[0]].tone)
    return TableRow(tuple(row_cells), tone)


def _table_body(block: TableBlock, title_key: str, lowering: Lowering) -> list[TableRow]:
    if block.groups is None:
        return [_table_row(block, row, title_key, lowering) for row in block.all_rows()]
    sum_key = block.reconcile.column if block.reconcile else block.totals.column if block.totals else None
    width = len(block.cell_columns)
    rows: list[TableRow] = []
    for group in block.groups:
        group_rows = cast("list[dict[str, Any]]", group.rows)
        label = bold(group.name)
        if sum_key:
            label += plain(f" ({compute.fmt(compute.col_sum(group_rows, sum_key))})")
        rows.append(TableRow((TableCell(label), *_blank_cells(width - 1)), emphasis="group"))
        if group_rows:
            rows += [_table_row(block, row, title_key, lowering) for row in group_rows]
        else:
            rows.append(TableRow((TableCell(italic(plain("none"))), *_blank_cells(width - 1))))
    return rows


def _totals_row(block: TableBlock, total_key: str) -> TableRow:
    total = compute.fmt(compute.col_sum(block.all_rows(), total_key))
    return TableRow(
        tuple(
            TableCell(bold(total))
            if column.key == total_key
            else TableCell(bold("Total") if index == 0 else ())
            for index, column in enumerate(block.cell_columns)
        ),
        emphasis="total",
    )


def _rollup(block: TableBlock, lowering: Lowering) -> list[Node]:
    buckets = compute.table_rollup(block)
    if not buckets:
        return []
    lead = labelled(block.rollup.label) if block.rollup and block.rollup.label else ()
    counts = [(lowering.chip(bucket["key"]), *plain(f" {bucket['count']}")) for bucket in buckets]
    runs: Rich = ()
    for count in counts:
        runs += (*plain(" · "), *count) if runs else count
    return [Paragraph(lead + runs)]


def lower_table(block: TableBlock, lowering: Lowering) -> list[Node]:
    text_keys = [column.key for column in block.columns if column.kind == "text"]
    rich_keys = [column.key for column in block.columns if column.kind == "rich"]
    title_key = text_keys[0] if text_keys else rich_keys[0] if rich_keys else block.cell_columns[0].key
    rows = _table_body(block, title_key, lowering)
    if block.totals:
        rows.append(_totals_row(block, block.totals.column))
    nodes: list[Node] = [Table(cells(*(column.label for column in block.cell_columns)), tuple(rows))]
    nodes += _rollup(block, lowering)
    if block.reconcile:
        nodes.append(Paragraph(plain(compute.reconcile_line(block)), "muted"))
    return nodes


def _comparison_cell(cell: bool | str | ComparisonCell, negative: bool, lowering: Lowering) -> TableCell:
    if isinstance(cell, bool):
        good = cell != negative
        return TableCell(plain("✓" if cell else "✗"), "success" if good else "danger")
    if isinstance(cell, str):
        return TableCell(lowering.rich(cell))
    return TableCell(lowering.rich(cell.value), tone_named(cell.tone))


def lower_comparison(block: Comparison, lowering: Lowering) -> list[Node]:
    header = (
        TableCell(()),
        *(
            TableCell(bold(f"★ {option}") if index == block.highlight else plain(option))
            for index, option in enumerate(block.options)
        ),
    )
    polarity = block.polarity or []
    rows: list[TableRow] = []
    for row in block.rows:
        row_cells = [TableCell(bold(row.feature))]
        for index, cell in enumerate(row.values):
            negative = index < len(polarity) and polarity[index] == "negative"
            row_cells.append(_comparison_cell(cell, negative, lowering))
        rows.append(TableRow(tuple(row_cells)))
    return [Table(header, tuple(rows), header_column=True)]


def lower_matrix(block: Matrix, lowering: Lowering) -> list[Node]:
    header = (TableCell(()), *cells(*block.columns))
    rows: list[TableRow] = []
    for row_name, grid_row in zip(block.rows, compute.matrix_grid(block), strict=True):
        row_cells = [TableCell(bold(row_name))]
        for cell in grid_row:
            if cell is None:
                row_cells.append(TableCell(()))
            elif cell.badge:
                badge = lowering.report.badges[cell.badge]
                row_cells.append(TableCell(plain(cell.label or badge.label), tone_named(badge.tone)))
            else:
                row_cells.append(TableCell(plain(cell.label or ""), tone_named(cell.tone)))
        rows.append(TableRow(tuple(row_cells)))
    return [Table(header, tuple(rows), header_column=True)]


def _swim_step(step: SwimlaneStep, number_by_id: Mapping[str, str]) -> Rich:
    number: Rich = (Link((Plain(step.n),), step.url),) if step.url else bold(step.n)
    text = plain(f"{SWIMLANE_MARK[step.state]} ") + number + plain(f" {step.label}")
    if step.value is not None:
        text += plain(f" ({compute.fmt(step.value)})")
    if step.depends_on:
        needs = ", ".join(dict.fromkeys(number_by_id[dep] for dep in step.depends_on))
        text += italic(plain(f" needs {needs}"))
    return text


def _with_total(text: Rich, totals: Mapping[str, float] | None, key: str) -> Rich:
    return text + plain(f" ({compute.fmt(totals[key])})") if totals is not None else text


def _swimlane_header(block: Swimlane, totals: compute.SwimTotals | None) -> tuple[TableCell, ...]:
    groups_by_column: dict[str, list[str]] = {}
    for group in block.groups:
        for column in group.columns:
            groups_by_column.setdefault(column, []).append(group.name)
    group_totals = totals["groups"] if totals is not None else None
    header = [TableCell(plain("Lane"))]
    for column in block.columns:
        text: Rich = bold(column.name)
        if column.sub:
            text += _after_break(italic(plain(column.sub)))
        names = [
            _with_total(plain(name), group_totals, name) for name in groups_by_column.get(column.key, [])
        ]
        for index, name in enumerate(names):
            text += _after_break(name) if index == 0 else plain(", ") + name
        header.append(TableCell(text))
    return tuple(header)


def _lane_cells(block: Swimlane, lane_key: str, number_by_id: Mapping[str, str]) -> list[TableCell]:
    lane_cells: list[TableCell] = []
    for column in block.columns:
        runs: Rich = ()
        for step in block.steps:
            if step.lane == lane_key and step.col == column.key:
                runs += (
                    _after_break(_swim_step(step, number_by_id)) if runs else _swim_step(step, number_by_id)
                )
        lane_cells.append(TableCell(runs))
    return lane_cells


def _state_legend(states: Sequence[SwimlaneStepState]) -> list[Node]:
    if not states:
        return []
    return [Paragraph(plain(" · ".join(f"{SWIMLANE_MARK[state]} {state}" for state in states)), "muted")]


def lower_swimlane(block: Swimlane) -> list[Node]:
    number_by_id = {step.id: step.n for step in block.steps if step.id is not None}
    totals = compute.swimlane_totals(block)
    lane_totals = totals["lanes"] if totals is not None else None
    rows = [
        TableRow(
            (
                TableCell(_with_total(bold(lane.name), lane_totals, lane.key)),
                *_lane_cells(block, lane.key, number_by_id),
            )
        )
        for lane in block.lanes
    ]
    if totals is not None:
        footer = (
            TableCell(bold("Total")),
            *(TableCell(plain(compute.fmt(totals["columns"][column.key]))) for column in block.columns),
        )
        rows.append(TableRow(footer, emphasis="total"))
    table = Table(_swimlane_header(block, totals), tuple(rows), header_column=True)
    return [table, *_state_legend(compute.swimlane_state_legend(block))]
