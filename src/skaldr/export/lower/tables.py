from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Final, cast

from typing_extensions import assert_never

from skaldr import compute, models
from skaldr.export.inline import bold, italic, plain
from skaldr.export.lower.context import Lowering, plain_cells, spaced, tone_named, tone_of, with_bold_label
from skaldr.export.runs import Break, CheckMark, ExportRich, ExportRun, IndicatorMark, SwimlaneMark
from skaldr.export.tree import Node, Paragraph, TableCell, TableColumn, TableNode, TableRow, ToneName
from skaldr.richtext import Link, Plain

Row = Mapping[str, Any]
EMPTY_GROUP_LABEL: Final = "none"


def _joined_by_breaks(lines: Iterable[ExportRich]) -> ExportRich:
    runs: list[ExportRun] = []
    for line in lines:
        if line and runs:
            runs.append(Break())
        runs.extend(line)
    return tuple(runs)


def _blank_cells(count: int) -> tuple[TableCell, ...]:
    return tuple(TableCell(()) for _ in range(count))


def _cell_text(value: object, lowering: Lowering) -> ExportRich:
    if value is None or value == "":
        return ()
    return _joined_by_breaks(lowering.prose_lines(str(value)))


def _subrows(row: Row) -> list[Row]:
    return cast("list[Row]", row.get("subrows") or [])


def _title_cell(block: models.Table, row: Row, value: object, lowering: Lowering) -> TableCell:
    chips = [
        lowering.chips(keys)
        for badge_column in block.title_badges
        if (keys := block.badge_keys(row, badge_column.key))
    ]
    title = spaced([part for part in (_cell_text(value, lowering), *chips) if part])
    subrows = [
        lowering.rich(str(sub["label"])) + plain(f": {compute.fmt(sub['value'])}") for sub in _subrows(row)
    ]
    return TableCell(_joined_by_breaks([title, *subrows]))


def _number_cell(block: models.Table, column: models.Column, value: object) -> TableCell:
    parts = [plain(compute.fmt(value)) if value is not None else ()]
    if column.pct_of_total and block.reconcile and isinstance(value, int | float):
        parts.append(plain(f"({compute.pct(value, block.reconcile.total)} of total)"))
    return TableCell(spaced([part for part in parts if part]))


def _indicator_cell(value: object) -> TableCell:
    tone = tone_of(str(value or "").strip())
    return TableCell((IndicatorMark(tone),), tone) if tone else TableCell(())


def _row_tone(block: models.Table, row: Row, lowering: Lowering) -> ToneName | None:
    explicit_tone = row.get("tone")
    if explicit_tone:
        return tone_named(explicit_tone)
    tint_key = block.row_tint_key(row)
    return models.BADGE_COLOR_TONE[lowering.report.badges[tint_key].tone] if tint_key else None


def _body_cell(block: models.Table, column: models.Column, row: Row, lowering: Lowering) -> TableCell:
    value = row.get(column.key)
    if column.key == block.title_key:
        return _title_cell(block, row, value, lowering)
    match column.kind:
        case "number":
            return _number_cell(block, column, value)
        case "indicator":
            return _indicator_cell(value)
        case "badge":
            return TableCell(lowering.chips(block.badge_keys(row, column.key)))
        case "text" | "rich":
            return TableCell(_cell_text(value, lowering))
        case _:
            assert_never(column.kind)


def _table_row(block: models.Table, row: Row, lowering: Lowering) -> TableRow:
    row_cells = tuple(_body_cell(block, column, row, lowering) for column in block.cell_columns)
    return TableRow(row_cells, _row_tone(block, row, lowering))


def _table_body(block: models.Table, lowering: Lowering) -> list[TableRow]:
    if block.groups is None:
        return [_table_row(block, row, lowering) for row in block.all_rows()]
    width = len(block.cell_columns)
    rows: list[TableRow] = []
    for group in block.groups:
        group_rows = cast("list[dict[str, Any]]", group.rows)
        label = plain(group.name)
        if block.sum_key:
            label = spaced([label, plain(f"({compute.fmt(compute.col_sum(group_rows, block.sum_key))})")])
        rows.append(TableRow((TableCell(label), *_blank_cells(width - 1)), emphasis="group"))
        if group_rows:
            rows += [_table_row(block, row, lowering) for row in group_rows]
        else:
            rows.append(TableRow((TableCell(italic(plain(EMPTY_GROUP_LABEL))), *_blank_cells(width - 1))))
    return rows


def _totals_row(block: models.Table, total_key: str) -> TableRow:
    total = compute.fmt(compute.col_sum(block.all_rows(), total_key))
    label_key = block.totals_label_key
    return TableRow(
        tuple(
            TableCell(
                plain(total) if column.key == total_key else plain("Total") if column.key == label_key else ()
            )
            for column in block.cell_columns
        ),
        emphasis="total",
    )


def _rollup(block: models.Table, lowering: Lowering) -> list[Node]:
    buckets = compute.table_rollup(block)
    if not buckets:
        return []
    counts = [spaced([(lowering.chip(bucket["key"]),), plain(str(bucket["count"]))]) for bucket in buckets]
    label = block.rollup.label if block.rollup else None
    return [Paragraph(with_bold_label(label, spaced(counts, " · ")))]


def _table_columns(block: models.Table) -> tuple[TableColumn, ...]:
    columns = tuple(
        TableColumn(column.tone, share)
        for column, share in zip(block.cell_columns, block.column_width_shares, strict=True)
    )
    return () if all(column == TableColumn() for column in columns) else columns


def lower_table(block: models.Table, lowering: Lowering) -> list[Node]:
    rows = _table_body(block, lowering)
    if block.totals:
        rows.append(_totals_row(block, block.totals.column))
    header = plain_cells(*(column.label for column in block.cell_columns))
    nodes: list[Node] = [TableNode(header, tuple(rows), columns=_table_columns(block))]
    nodes += _rollup(block, lowering)
    if block.reconcile:
        nodes.append(Paragraph(plain(compute.reconcile_line(block)), "muted"))
    return nodes


def _comparison_cell(
    cell: bool | str | models.ComparisonCell, is_negative: bool, lowering: Lowering
) -> TableCell:
    if isinstance(cell, bool):
        good = cell != is_negative
        return TableCell((CheckMark(cell),), "success" if good else "danger")
    if isinstance(cell, str):
        return TableCell(lowering.rich(cell))
    return TableCell(lowering.rich(cell.value), cell.tone)


def lower_comparison(block: models.Comparison, lowering: Lowering) -> list[Node]:
    header = (
        TableCell(()),
        *(
            TableCell(plain(f"★ {option}" if index == block.highlight else option))
            for index, option in enumerate(block.options)
        ),
    )
    rows = [
        TableRow(
            (
                TableCell(plain(row.feature)),
                *(
                    _comparison_cell(cell, block.is_negative(index), lowering)
                    for index, cell in enumerate(row.values)
                ),
            )
        )
        for row in block.rows
    ]
    return [TableNode(header, tuple(rows), header_column=True)]


def _matrix_cell(cell: models.MatrixCell | None, lowering: Lowering) -> TableCell:
    if cell is None:
        return TableCell(())
    display = compute.matrix_cell_display(cell, lowering.report.badges)
    tone = models.BADGE_COLOR_TONE[display.tone] if display.tone else None
    return TableCell(plain(display.text), tone)


def lower_matrix(block: models.Matrix, lowering: Lowering) -> list[Node]:
    header = (TableCell(()), *plain_cells(*block.columns))
    rows = [
        TableRow((TableCell(plain(row_name)), *(_matrix_cell(cell, lowering) for cell in grid_row)))
        for row_name, grid_row in zip(block.rows, compute.matrix_grid(block), strict=True)
    ]
    return [TableNode(header, tuple(rows), header_column=True)]


def _swim_step(block: models.Swimlane, step: models.SwimlaneStep, show_group: bool) -> ExportRich:
    number: ExportRich = (Link(plain(step.n), step.url),) if step.url else bold(step.n)
    mark: ExportRich = (SwimlaneMark(step.state),) if step.state is not None else ()
    parts: list[ExportRich] = [mark, number, plain(step.label)]
    if step.value is not None:
        parts.append(plain(f"({compute.fmt(step.value)})"))
    text = spaced([part for part in parts if part])
    group = block.step_group(step)
    if show_group and group:
        text += plain(f", {group}")
    needs = block.dependency_numbers(step)
    if needs:
        text += (Plain(" "), *italic(plain(f"needs {', '.join(needs)}")))
    return text


def _with_total(text: ExportRich, totals: Mapping[str, float] | None, key: str) -> ExportRich:
    return spaced([text, plain(f"({compute.fmt(totals[key])})")]) if totals is not None else text


def _groups_starting_at(block: models.Swimlane) -> dict[str, list[str]]:
    subcolumns = block.subcolumns()
    starting: dict[str, list[str]] = {column.key: [] for column in block.columns}
    for group, (first, _) in block.group_spans.items():
        starting[subcolumns[first][0]].append(group)
    return starting


def _swimlane_header(block: models.Swimlane, totals: compute.SwimTotals | None) -> tuple[TableCell, ...]:
    group_totals = totals["groups"] if totals is not None else None
    starting = _groups_starting_at(block)
    header = [TableCell(plain("Lane"))]
    for column in block.columns:
        names = [_with_total(plain(name), group_totals, name) for name in starting[column.key]]
        sub = italic(plain(column.sub)) if column.sub else ()
        header.append(TableCell(_joined_by_breaks([plain(column.name), sub, spaced(names, ", ")])))
    return tuple(header)


def _split_columns(block: models.Swimlane) -> set[str]:
    return {column for column, (first, last) in block.column_spans.items() if last > first}


def _lane_cells(block: models.Swimlane, lane_key: str, split: set[str]) -> list[TableCell]:
    cells: list[TableCell] = []
    for column in block.columns:
        first, last = block.column_spans[column.key]
        steps = [
            step
            for sub_column, group in block.subcolumns()[first : last + 1]
            for step in block.steps_at(lane_key, sub_column, group)
        ]
        cells.append(
            TableCell(_joined_by_breaks(_swim_step(block, step, column.key in split) for step in steps))
        )
    return cells


def _state_legend(states: Sequence[models.SwimlaneStepState]) -> list[Node]:
    if not states:
        return []
    entries = [spaced([(SwimlaneMark(state),), plain(state)]) for state in states]
    return [Paragraph(spaced(entries, " · "), "muted")]


def lower_swimlane(block: models.Swimlane) -> list[Node]:
    totals = compute.swimlane_totals(block)
    lane_totals = totals["lanes"] if totals is not None else None
    split = _split_columns(block)
    rows = [
        TableRow(
            (
                TableCell(_with_total(plain(lane.name), lane_totals, lane.key)),
                *_lane_cells(block, lane.key, split),
            )
        )
        for lane in block.lanes
    ]
    if totals is not None:
        footer = (
            TableCell(plain("Total")),
            *(TableCell(plain(compute.fmt(totals["columns"][column.key]))) for column in block.columns),
        )
        rows.append(TableRow(footer, emphasis="total"))
    table = TableNode(_swimlane_header(block, totals), tuple(rows), header_column=True)
    return [table, *_state_legend(compute.swimlane_marked_state_legend(block))]
