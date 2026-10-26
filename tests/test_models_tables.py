from typing import Any

import pytest
from pydantic import ValidationError

from skaldr.errors import ReportError
from skaldr.models import Column, Group, Row, Table, parse_report
from tests.factories import make_label_table, make_reconciled_table, make_report, make_table
from tests.factories.models_factory import make_matrix


def test_reconciliation_failure_names_the_delta() -> None:
    table = make_reconciled_table(
        reconcile={"total": 100, "column": "count", "handled": {"label": "Clean", "value": 80}},
    )

    with pytest.raises(ReportError) as excinfo:
        parse_report(make_report(blocks=[table]))

    assert str(excinfo.value) == (
        "invalid content data: blocks.0.table: RECONCILIATION FAILED: handled (80) + count (10) = 90, but "
        "declared total is 100 (off by -10). A category is wrong, double-counted, or missing."
    )


def test_a_reconciliation_failure_names_its_table_and_keeps_the_other_errors_in_the_document() -> None:
    balanced = make_reconciled_table()
    off_by_ten = make_reconciled_table(
        reconcile={"total": 100, "column": "count", "handled": {"label": "Clean", "value": 80}},
    )

    with pytest.raises(ReportError) as excinfo:
        parse_report(make_report(blocks=[balanced, off_by_ten, {"type": "heading", "text": "  "}]))

    assert str(excinfo.value) == (
        "invalid content data: blocks.1.table: RECONCILIATION FAILED: handled (80) + count (10) = 90, but "
        "declared total is 100 (off by -10). A category is wrong, double-counted, or missing.; "
        "blocks.2.heading.text: String should match pattern '\\S'"
    )


def test_rollup_by_a_non_badge_column_is_rejected() -> None:
    table = make_table(
        columns=[
            {"key": "item", "label": "I", "kind": "text"},
            {"key": "n", "label": "N", "kind": "number"},
        ],
        rows=[{"item": "a", "n": 1}],
        rollup={"by": "n"},
    )

    with pytest.raises(ReportError, match=r"rollup.by 'n' must be a badge column"):
        parse_report(make_report(blocks=[table]))


def test_rollup_by_an_unknown_column_is_rejected() -> None:
    table = make_table(
        columns=[{"key": "item", "label": "I", "kind": "text"}],
        rows=[{"item": "a"}],
        rollup={"by": "nope"},
    )

    with pytest.raises(ReportError, match=r"rollup.by 'nope' must be a badge column"):
        parse_report(make_report(blocks=[table]))


def test_rollup_by_a_badge_column_no_row_populates_is_rejected() -> None:
    table = make_table(
        columns=[
            {"key": "item", "label": "I", "kind": "text"},
            {"key": "tag", "label": "", "kind": "badge"},
        ],
        rows=[{"item": "a", "tag": ""}, {"item": "b", "tag": ""}],
        rollup={"by": "tag"},
    )

    with pytest.raises(ReportError, match=r"rollup.by 'tag' has no values to count"):
        parse_report(make_report(blocks=[table]))


LIST_CELL_ROWS = [
    pytest.param(
        {"rows": [{"item": "a", "tag": "API"}, {"item": "b", "tag": ["API", "WEB"]}]},
        "rows.1 holds ['API', 'WEB']",
        id="flat-table",
    ),
    pytest.param(
        {
            "groups": [
                {"name": "One", "rows": [{"item": "a", "tag": "API"}]},
                {"name": "Two", "rows": [{"item": "b", "tag": ["API", "WEB"]}]},
            ]
        },
        "groups.1.rows.0 holds ['API', 'WEB']",
        id="grouped-table",
    ),
    pytest.param(
        {"rows": [{"item": "a", "tag": ["API"]}]},
        "rows.0 holds ['API']",
        id="one-key-list",
    ),
    pytest.param(
        {"rows": [{"item": "a", "tag": ["", "WEB"]}]},
        "rows.0 holds ['', 'WEB']",
        id="blank-first-key",
    ),
]


LIST_CELL_BADGES = {
    "API": {"label": "API", "tone": "blue", "legend": "api work"},
    "WEB": {"label": "WEB", "tone": "green", "legend": "web work"},
}


IN_CELL_TAG_COLUMNS = [
    {"key": "item", "label": "I", "kind": "text"},
    {"key": "tag", "label": "", "kind": "badge", "placement": "cell"},
]


@pytest.mark.parametrize(("rows", "located"), LIST_CELL_ROWS)
def test_rollup_by_an_in_cell_badge_column_holding_a_list_is_rejected(
    rows: dict[str, Any], located: str
) -> None:
    table = make_table(columns=IN_CELL_TAG_COLUMNS, rollup={"by": "tag"}, **rows)

    with pytest.raises(ReportError) as excinfo:
        parse_report(make_report(badges=LIST_CELL_BADGES, blocks=[table]))

    assert str(excinfo.value) == (
        "invalid content data: blocks.0.table: Value error, rollup.by 'tag' counts each row under one "
        f"badge, so its cells can't hold a list of keys ({located})"
    )


@pytest.mark.parametrize(("rows", "located"), LIST_CELL_ROWS)
def test_tint_by_an_in_cell_badge_column_holding_a_list_is_rejected(
    rows: dict[str, Any], located: str
) -> None:
    table = make_table(columns=IN_CELL_TAG_COLUMNS, tint_by="tag", **rows)

    with pytest.raises(ReportError) as excinfo:
        parse_report(make_report(badges=LIST_CELL_BADGES, blocks=[table]))

    assert str(excinfo.value) == (
        "invalid content data: blocks.0.table: Value error, tint_by 'tag' tints each row by one "
        f"badge, so its cells can't hold a list of keys ({located})"
    )


def test_tint_by_an_in_cell_badge_column_of_single_keys_is_allowed() -> None:
    table = make_table(
        columns=IN_CELL_TAG_COLUMNS,
        tint_by="tag",
        rows=[{"item": "a", "tag": "API"}, {"item": "b", "tag": ""}],
    )

    parse_report(make_report(badges=LIST_CELL_BADGES, blocks=[table]))


def test_tint_by_a_non_badge_column_is_rejected() -> None:
    table = make_table(
        columns=[{"key": "item", "label": "I", "kind": "text"}],
        rows=[{"item": "a"}],
        tint_by="item",
    )

    with pytest.raises(ReportError, match=r"tint_by 'item' must be a badge column"):
        parse_report(make_report(blocks=[table]))


def test_tint_by_an_all_blank_badge_column_is_allowed() -> None:
    """Unlike `rollup`, `tint_by` tolerates an all-blank column — a blank cell is a valid untinted
    row, not an error (the whole column being blank just renders every row untinted)."""
    table = make_table(
        columns=[
            {"key": "item", "label": "I", "kind": "text"},
            {"key": "tag", "label": "", "kind": "badge"},
        ],
        rows=[{"item": "a", "tag": ""}],
        tint_by="tag",
    )

    parse_report(make_report(blocks=[table]))  # no raise


_POSITIONAL_COLUMNS = [
    {"key": "issue", "label": "Issue", "kind": "text"},
    {"key": "tag", "label": "", "kind": "badge"},
    {"key": "n", "label": "N", "kind": "number"},
]


def test_positional_row_expands_to_the_same_as_a_mapping_row() -> None:
    positional = Table.model_validate(make_table(columns=_POSITIONAL_COLUMNS, rows=[["Dupe", "FLOOR", 600]]))
    mapping = Table.model_validate(
        make_table(columns=_POSITIONAL_COLUMNS, rows=[{"issue": "Dupe", "tag": "FLOOR", "n": 600}])
    )

    assert positional.model_dump() == mapping.model_dump()


def test_positional_row_alongside_a_malformed_column_reports_the_column_error() -> None:
    # malformed columns make row-expansion early-return; the positional list row must then surface the
    # column error cleanly, not crash validation.
    table = make_table(
        columns=[{"key": "a", "label": "A", "kind": "text"}, {"key": 5, "label": "N", "kind": "number"}],
        rows=[["x", 1]],
    )

    with pytest.raises(ReportError, match=r"Input should be a valid string"):
        parse_report(make_report(blocks=[table]))


def test_positional_and_mapping_rows_mix_in_one_table() -> None:
    cols = [{"key": "a", "label": "A", "kind": "text"}, {"key": "n", "label": "N", "kind": "number"}]
    table = Table.model_validate(make_table(columns=cols, rows=[["x", 1], {"a": "y", "n": 2}]))

    assert table.body_rows == (
        Row(texts={"a": "x"}, numbers={"n": 1}),
        Row(texts={"a": "y"}, numbers={"n": 2}),
    )


def test_positional_rows_expand_inside_groups() -> None:
    cols = [{"key": "a", "label": "A", "kind": "text"}, {"key": "n", "label": "N", "kind": "number"}]
    table = Table.model_validate(
        make_table(columns=cols, groups=[{"name": "G", "rows": [["x", 1], ["y", 2]]}])
    )

    assert table.body_rows == (
        Row(texts={"a": "x"}, numbers={"n": 1}),
        Row(texts={"a": "y"}, numbers={"n": 2}),
    )


def test_positional_row_preserves_a_list_cell_value() -> None:
    cols = [
        {"key": "name", "label": "N", "kind": "text"},
        {"key": "access", "label": "Access", "kind": "badge", "placement": "cell"},
    ]
    table = Table.model_validate(make_table(columns=cols, rows=[["Supplier ledger", ["WRITE", "READ"]]]))

    assert table.body_rows == (Row(texts={"name": "Supplier ledger"}, badges={"access": ("WRITE", "READ")}),)


@pytest.mark.parametrize("row", [["x"], ["x", 1, "extra"]], ids=["too-few", "too-many"])
def test_positional_row_with_the_wrong_length_is_rejected(row: list[Any]) -> None:
    cols = [{"key": "a", "label": "A", "kind": "text"}, {"key": "n", "label": "N", "kind": "number"}]
    table = make_table(columns=cols, rows=[row])

    with pytest.raises(ReportError, match=rf"positional row needs exactly 2 values.*got {len(row)}"):
        parse_report(make_report(blocks=[table]))


def test_positional_row_still_validates_cell_types() -> None:
    cols = [{"key": "a", "label": "A", "kind": "text"}, {"key": "n", "label": "N", "kind": "number"}]
    table = make_table(columns=cols, rows=[["x", "not-a-number"]])

    with pytest.raises(ReportError, match=r"rows\.0\.n: number column needs a numeric value"):
        parse_report(make_report(blocks=[table]))


def test_group_built_with_an_unexpanded_positional_row_is_rejected() -> None:
    # the loud guard: a Group constructed outside the table's row-expansion (which turns list rows
    # into mappings) must reject a raw list row, not let it crash the render.
    with pytest.raises(ValidationError, match=r"group rows must be mappings"):
        Group.model_validate({"name": "G", "rows": [["x", "y"]]})


def test_row_tone_is_a_reserved_key_not_an_unknown_column() -> None:
    table = make_table(
        columns=[{"key": "a", "label": "A", "kind": "text"}], rows=[{"a": "x", "tone": "muted"}]
    )

    block = parse_report(make_report(blocks=[table])).blocks[0]

    assert isinstance(block, Table)
    assert block.rows == [{"a": "x", "tone": "muted"}]  # tone kept, not tripping the unknown-key guard


def test_row_tone_rejects_an_unknown_value() -> None:
    table = make_table(
        columns=[{"key": "a", "label": "A", "kind": "text"}], rows=[{"a": "x", "tone": "bogus"}]
    )

    with pytest.raises(ReportError, match=r"tone: row tone must be 'muted' or 'danger'"):
        parse_report(make_report(blocks=[table]))


def test_row_tone_alias_that_is_not_a_row_tone_is_still_rejected() -> None:
    """`blue` aliases to `info`, a real tone — but not a ROW tone (only muted/danger). It must still
    reject after normalisation, not slip through."""
    table = make_table(
        columns=[{"key": "a", "label": "A", "kind": "text"}], rows=[{"a": "x", "tone": "blue"}]
    )

    with pytest.raises(ReportError, match=r"tone: row tone must be 'muted' or 'danger'"):
        parse_report(make_report(blocks=[table]))


def test_table_column_key_may_not_collide_with_a_reserved_row_key() -> None:
    table = make_table(columns=[{"key": "tone", "label": "Tone", "kind": "text"}], rows=[{"tone": "warm"}])

    with pytest.raises(ReportError, match=r"reserved row keys"):
        parse_report(make_report(blocks=[table]))


def _indicator_table(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return make_table(
        columns=[
            {"key": "a", "label": "A", "kind": "text"},
            {"key": "r", "label": "Risk", "kind": "indicator"},
        ],
        rows=rows,
    )


def test_indicator_column_rejects_a_non_tone_value() -> None:
    with pytest.raises(ReportError, match=r"indicator value must be a tone"):
        parse_report(make_report(blocks=[_indicator_table([{"a": "x", "r": "purple"}])]))


def test_indicator_column_accepts_a_tone_or_blank() -> None:
    block = parse_report(
        make_report(blocks=[_indicator_table([{"a": "x", "r": "danger"}, {"a": "y", "r": ""}])])
    ).blocks[0]

    assert isinstance(block, Table)
    assert block.rows == [{"a": "x", "r": "danger"}, {"a": "y", "r": ""}]


def test_column_kind_defaults_to_text() -> None:
    # a plain column is just {key, label} — no `kind` boilerplate; it resolves to a text column
    table = {
        "type": "table",
        "columns": [{"key": "flag", "label": "Flag"}, {"key": "n", "label": "N", "kind": "number"}],
        "rows": [{"flag": "on", "n": 1}],
    }

    block = parse_report(make_report(blocks=[table])).blocks[0]

    assert isinstance(block, Table)
    assert block.columns[0].kind == "text"


def test_table_row_missing_a_column_is_rejected() -> None:
    table = make_reconciled_table(groups=[{"name": "g", "rows": [{"issue": "only"}]}])

    with pytest.raises(ReportError, match=r"missing column value"):
        parse_report(make_report(blocks=[table]))


def test_table_row_with_unknown_key_is_rejected() -> None:
    table = make_reconciled_table(
        groups=[{"name": "g", "rows": [{"issue": "x", "count": 10, "extra": 1}]}],
        reconcile={"total": 10, "column": "count"},
    )

    with pytest.raises(ReportError, match=r"unknown key"):
        parse_report(make_report(blocks=[table]))


def test_reconcile_total_must_be_positive() -> None:
    table = make_reconciled_table(
        reconcile={"total": 0, "column": "count", "handled": {"label": "c", "value": 0}},
        groups=[{"name": "g", "rows": [{"issue": "x", "count": 0}]}],
    )

    with pytest.raises(ReportError, match=r"greater than 0"):
        parse_report(make_report(blocks=[table]))


def test_number_column_rejects_non_numeric_value() -> None:
    table = make_reconciled_table(groups=[{"name": "g", "rows": [{"issue": "x", "count": "ten"}]}])

    with pytest.raises(ReportError, match=r"count: number column needs a numeric value"):
        parse_report(make_report(blocks=[table]))


def test_badge_column_rejects_non_string_value() -> None:
    table = make_reconciled_table(
        columns=[
            {"key": "issue", "label": "I", "kind": "text"},
            {"key": "tag", "label": "", "kind": "badge"},
            {"key": "count", "label": "C", "kind": "number"},
        ],
        groups=[{"name": "g", "rows": [{"issue": "x", "tag": 123, "count": 10}]}],
    )

    with pytest.raises(ReportError, match=r"tag: badge column needs a string value"):
        parse_report(make_report(blocks=[table]))


def test_all_badge_table_is_rejected() -> None:
    table = {
        "type": "table",
        "columns": [{"key": "tag", "label": "", "kind": "badge"}],
        "groups": [{"name": "g", "rows": [{"tag": "X"}]}],
    }

    with pytest.raises(ReportError, match=r"at least one text or rich column"):
        parse_report(
            make_report(badges={"X": {"label": "x", "tone": "amber", "legend": "l"}}, blocks=[table])
        )


def test_duplicate_column_keys_rejected() -> None:
    table = make_reconciled_table(
        columns=[
            {"key": "issue", "label": "I", "kind": "text"},
            {"key": "count", "label": "A", "kind": "number"},
            {"key": "count", "label": "B", "kind": "number"},
        ],
        reconcile={"total": 10, "column": "count"},
        groups=[{"name": "g", "rows": [{"issue": "x", "count": 10}]}],
    )

    with pytest.raises(ReportError, match=r"column keys must be unique"):
        parse_report(make_report(blocks=[table]))


def test_reconcile_column_must_be_a_number_column() -> None:
    table = make_reconciled_table(
        reconcile={"total": 10, "column": "issue", "handled": {"label": "c", "value": 0}},
    )

    with pytest.raises(ReportError, match=r"reconcile.column 'issue' must be a number column"):
        parse_report(make_report(blocks=[table]))


def test_ungrouped_rows_mode_parses() -> None:
    table = {
        "type": "table",
        "columns": [{"key": "issue", "label": "I", "kind": "text"}],
        "rows": [{"issue": "x"}],
    }

    report = parse_report(make_report(blocks=[table]))

    assert report.blocks[0].type == "table"


def test_both_groups_and_rows_rejected() -> None:
    table = {
        "type": "table",
        "columns": [{"key": "issue", "label": "I", "kind": "text"}],
        "groups": [{"name": "g", "rows": [{"issue": "x"}]}],
        "rows": [{"issue": "x"}],
    }

    with pytest.raises(ReportError, match=r"exactly one of 'groups' or 'rows'"):
        parse_report(make_report(blocks=[table]))


def test_neither_groups_nor_rows_rejected() -> None:
    table = {"type": "table", "columns": [{"key": "issue", "label": "I", "kind": "text"}]}

    with pytest.raises(ReportError, match=r"exactly one of 'groups' or 'rows'"):
        parse_report(make_report(blocks=[table]))


def test_subrows_must_be_a_list() -> None:
    table = make_reconciled_table(
        reconcile={"total": 10, "column": "count"},
        groups=[{"name": "g", "rows": [{"issue": "x", "count": 10, "subrows": "nope"}]}],
    )

    with pytest.raises(ReportError, match=r"subrows: must be a list"):
        parse_report(make_report(blocks=[table]))


def test_subrow_shape_is_enforced() -> None:
    table = make_reconciled_table(
        reconcile={"total": 10, "column": "count"},
        groups=[{"name": "g", "rows": [{"issue": "x", "count": 10, "subrows": [{"label": "a"}]}]}],
    )

    with pytest.raises(ReportError, match=r"must be \{label, value\}"):
        parse_report(make_report(blocks=[table]))


def test_reconcile_without_handled_bucket_passes() -> None:
    table = make_reconciled_table(
        reconcile={"total": 10, "column": "count"},
        groups=[{"name": "g", "rows": [{"issue": "x", "count": 10}]}],
    )

    report = parse_report(make_report(blocks=[table]))

    assert report.blocks[0].type == "table"


def test_number_column_rejects_non_finite_value() -> None:
    table = make_reconciled_table(groups=[{"name": "g", "rows": [{"issue": "x", "count": float("inf")}]}])

    with pytest.raises(ReportError, match=r"groups\.0\.rows\.0\.count: must be a finite number$"):
        parse_report(make_report(blocks=[table]))


def test_number_column_rejects_boolean_value() -> None:
    table = make_reconciled_table(groups=[{"name": "g", "rows": [{"issue": "x", "count": True}]}])

    with pytest.raises(ReportError, match=r"count: number column needs a numeric value"):
        parse_report(make_report(blocks=[table]))


def test_float_reconcile_tolerates_ieee754_noise() -> None:
    # 33.1 + 33.2 + 33.7 == 100.00000000000001 — exact `==` would wrongly fail this.
    table = make_reconciled_table(
        reconcile={"total": 100, "column": "count"},
        groups=[
            {
                "name": "g",
                "rows": [
                    {"issue": "a", "count": 33.1},
                    {"issue": "b", "count": 33.2},
                    {"issue": "c", "count": 33.7},
                ],
            }
        ],
    )

    report = parse_report(make_report(blocks=[table]))

    assert report.blocks[0].type == "table"


def test_float_reconcile_still_fails_a_real_discrepancy() -> None:
    table = make_reconciled_table(
        reconcile={"total": 100, "column": "count"},
        groups=[{"name": "g", "rows": [{"issue": "a", "count": 33.1}, {"issue": "b", "count": 33.2}]}],
    )

    with pytest.raises(ReportError, match=r"RECONCILIATION FAILED"):
        parse_report(make_report(blocks=[table]))


def test_subrow_value_rejects_non_finite() -> None:
    row = {"issue": "x", "count": 10, "subrows": [{"label": "a", "value": float("nan")}]}
    table = make_reconciled_table(
        reconcile={"total": 10, "column": "count"}, groups=[{"name": "g", "rows": [row]}]
    )

    with pytest.raises(ReportError, match=r"subrows\.0\.value: must be a finite number$"):
        parse_report(make_report(blocks=[table]))


def test_table_requires_a_text_or_rich_column() -> None:
    table = {
        "type": "table",
        "columns": [
            {"key": "count", "label": "C", "kind": "number"},
            {"key": "tag", "label": "", "kind": "badge"},
        ],
        "rows": [{"count": 10, "tag": "X"}],
    }

    with pytest.raises(ReportError, match=r"at least one text or rich column"):
        parse_report(
            make_report(badges={"X": {"label": "x", "tone": "amber", "legend": "l"}}, blocks=[table])
        )


def test_pct_of_total_without_reconcile_is_rejected() -> None:
    table = {
        "type": "table",
        "columns": [
            {"key": "issue", "label": "I", "kind": "text"},
            {"key": "count", "label": "C", "kind": "number", "pct_of_total": True},
        ],
        "rows": [{"issue": "x", "count": 10}],
    }

    with pytest.raises(ReportError, match=r"pct_of_total requires a reconcile total"):
        parse_report(make_report(blocks=[table]))


@pytest.mark.parametrize("kind", ["text", "rich", "badge", "indicator"])
def test_pct_of_total_on_a_column_that_is_not_a_number_column_is_rejected(kind: str) -> None:
    table = make_reconciled_table(
        columns=[
            {"key": "issue", "label": "Issue", "kind": "text"},
            {"key": "count", "label": "Count", "kind": "number"},
            {"key": "extra", "label": "Extra", "kind": kind, "pct_of_total": True},
        ],
        groups=[{"name": "Our side", "rows": [{"issue": "Dupes", "count": 10, "extra": ""}]}],
    )

    with pytest.raises(ReportError) as raised:
        parse_report(make_report(blocks=[table]))

    assert str(raised.value) == (
        "invalid content data: blocks.0.table: Value error, column(s) ['extra']: pct_of_total is only "
        "for number columns"
    )


def test_pct_of_total_on_a_reconciled_number_column_is_accepted() -> None:
    table = make_reconciled_table(
        columns=[
            {"key": "issue", "label": "Issue"},
            {"key": "count", "label": "Count", "kind": "number", "pct_of_total": True},
        ]
    )

    assert parse_report(make_report(blocks=[table])).blocks[0].model_dump(exclude_defaults=True) == table


def test_totals_column_must_be_a_number_column() -> None:
    table = {
        "type": "table",
        "columns": [{"key": "issue", "label": "I", "kind": "text"}],
        "rows": [{"issue": "x"}],
        "totals": {"column": "issue"},
    }

    with pytest.raises(ReportError, match=r"totals.column 'issue' must be a number column"):
        parse_report(make_report(blocks=[table]))


def test_empty_badge_cell_is_allowed() -> None:
    table = make_reconciled_table(
        columns=[
            {"key": "issue", "label": "I", "kind": "text"},
            {"key": "tag", "label": "", "kind": "badge"},
            {"key": "count", "label": "C", "kind": "number"},
        ],
        groups=[{"name": "g", "rows": [{"issue": "x", "tag": "", "count": 10}]}],
    )

    report = parse_report(make_report(blocks=[table]))

    assert report.blocks[0].type == "table"


def test_subrow_label_must_be_a_string() -> None:
    table = make_reconciled_table(
        reconcile={"total": 10, "column": "count"},
        groups=[{"name": "g", "rows": [{"issue": "x", "count": 10, "subrows": [{"label": 1, "value": 2}]}]}],
    )

    with pytest.raises(ReportError, match=r"subrows\.0\.label: must be a string"):
        parse_report(make_report(blocks=[table]))


def test_subrow_value_must_be_number_or_string() -> None:
    row = {"issue": "x", "count": 10, "subrows": [{"label": "a", "value": [1]}]}
    table = make_reconciled_table(
        reconcile={"total": 10, "column": "count"}, groups=[{"name": "g", "rows": [row]}]
    )

    with pytest.raises(ReportError, match=r"subrows\.0\.value: must be a number or string"):
        parse_report(make_report(blocks=[table]))


def test_subrow_value_rejects_boolean() -> None:
    row = {"issue": "x", "count": 10, "subrows": [{"label": "a", "value": True}]}
    table = make_reconciled_table(
        reconcile={"total": 10, "column": "count"}, groups=[{"name": "g", "rows": [row]}]
    )

    with pytest.raises(ReportError, match=r"subrows\.0\.value: must be a number or string"):
        parse_report(make_report(blocks=[table]))


def test_table_column_widths_are_read_onto_every_column() -> None:
    table = make_table(
        [
            {"key": "a", "label": "A", "kind": "text", "width": 2},
            {"key": "b", "label": "B", "kind": "number", "width": 4},
        ],
        rows=[{"a": "x", "b": 10}],
    )

    block = parse_report(make_report(blocks=[table])).blocks[0]

    assert isinstance(block, Table)
    assert [column.width for column in block.columns] == [2, 4]


@pytest.mark.parametrize(
    ("columns", "shares"),
    [
        pytest.param(
            [
                {"key": "a", "label": "A", "width": 2},
                {"key": "b", "label": "B", "kind": "number", "width": 4},
            ],
            (2 / 6, 4 / 6),
            id="weights-over-the-kind-defaults",
        ),
        pytest.param(
            [
                {"key": "a", "label": "A"},
                {"key": "b", "label": "B", "kind": "number"},
                {"key": "c", "label": "C", "kind": "indicator"},
            ],
            (None, 0.1, 0.07),
            id="kind-defaults-beside-an-auto-column",
        ),
        pytest.param(
            [{"key": "a", "label": "A"}, {"key": "t", "label": "", "kind": "badge"}], (None,), id="all-auto"
        ),
    ],
)
def test_a_table_gives_each_cell_column_its_width_share(
    columns: list[dict[str, Any]], shares: tuple[float | None, ...]
) -> None:
    values = {"a": "x", "b": 10, "c": "", "t": ""}
    table = make_table(columns, rows=[{column["key"]: values[column["key"]] for column in columns}])

    block = parse_report(make_report(blocks=[table])).blocks[0]

    assert isinstance(block, Table)
    assert block.column_width_shares == shares


@pytest.mark.parametrize(
    ("kinds", "shares"),
    [
        pytest.param(["number"] * 9, (None, *[0.1] * 9), id="nine-numbers-leave-the-label-one-default-width"),
        pytest.param(["number"] * 10, (None, *[1 / 11] * 10), id="ten-numbers-scale-to-elevenths"),
        pytest.param(["number"] * 12, (None, *[1 / 13] * 12), id="twelve-numbers-scale-to-thirteenths"),
        pytest.param(["indicator"] * 13, (None, *[0.07] * 13), id="thirteen-indicators-still-fit"),
        pytest.param(
            ["indicator"] * 14, (None, *[1 / 15] * 14), id="fourteen-indicators-scale-to-fifteenths"
        ),
        pytest.param(
            ["number"] * 8 + ["indicator"] * 2,
            (None, *[0.1 / 1.04] * 8, *[0.07 / 1.04] * 2),
            id="mixed-kinds-keep-the-label-as-wide-as-a-number-column",
        ),
    ],
)
def test_kind_defaults_scale_down_so_an_auto_column_keeps_one_default_width(
    kinds: list[str], shares: tuple[float | None, ...]
) -> None:
    block = parse_report(make_report(blocks=[make_label_table(kinds)])).blocks[0]

    assert isinstance(block, Table)
    assert block.column_width_shares == pytest.approx(shares)


def test_a_table_column_takes_a_tone_and_a_palette_alias_names_the_same_tone() -> None:
    table = make_table(
        [
            {"key": "a", "label": "A", "tone": "info"},
            {"key": "b", "label": "B", "kind": "number", "tone": "green"},
            {"key": "c", "label": "C", "kind": "badge", "placement": "cell", "tone": "teal"},
        ],
        rows=[{"a": "x", "b": 10, "c": "K"}],
    )

    badges = {"K": {"label": "k", "tone": "blue", "legend": False}}

    block = parse_report(make_report(blocks=[table], badges=badges)).blocks[0]

    assert isinstance(block, Table)
    assert block.columns == [
        Column(key="a", label="A", tone="info"),
        Column(key="b", label="B", kind="number", tone="success"),
        Column(key="c", label="C", kind="badge", placement="cell", tone="teal"),
    ]


@pytest.mark.parametrize(
    ("column", "placement"),
    [
        pytest.param(
            {"key": "t", "label": "Level", "kind": "badge"}, "cell", id="a-labelled-badge-column-is-a-column"
        ),
        pytest.param(
            {"key": "t", "label": "", "kind": "badge"}, "title", id="an-unlabelled-one-rides-the-title"
        ),
        pytest.param({"key": "t", "label": "  ", "kind": "badge"}, "title", id="a-blank-label-is-no-label"),
        pytest.param(
            {"key": "t", "label": "Level", "kind": "badge", "placement": "title"},
            "title",
            id="explicit-title-wins",
        ),
        pytest.param(
            {"key": "t", "label": "", "kind": "badge", "placement": "cell"}, "cell", id="explicit-cell-wins"
        ),
        pytest.param({"key": "t", "label": "Note"}, "title", id="a-text-column-keeps-the-no-op-default"),
    ],
)
def test_a_badge_column_without_a_placement_follows_its_label(column: dict[str, Any], placement: str) -> None:
    table = make_table([{"key": "a", "label": "A"}, column], rows=[{"a": "x", "t": ""}])

    block = parse_report(make_report(blocks=[table])).blocks[0]

    assert isinstance(block, Table)
    assert block.columns[1].placement == placement


def test_a_title_placement_badge_column_cannot_take_a_tone() -> None:
    table = make_table(
        [{"key": "a", "label": "A"}, {"key": "t", "label": "", "kind": "badge", "tone": "info"}],
        rows=[{"a": "x", "t": ""}],
    )

    with pytest.raises(ReportError) as raised:
        parse_report(make_report(blocks=[table]))

    assert str(raised.value) == (
        "invalid content data: blocks.0.table: Value error, "
        "badge column(s) ['t'] can't take a tone (they ride under the title)"
    )


def test_table_mixed_widths_are_rejected() -> None:
    table = make_table(
        [
            {"key": "a", "label": "A", "kind": "text", "width": 2},
            {"key": "b", "label": "B", "kind": "number"},
        ],
        rows=[{"a": "x", "b": 10}],
    )

    with pytest.raises(ReportError, match=r"set width on every in-cell column, or none"):
        parse_report(make_report(blocks=[table]))


def test_badge_column_cannot_take_a_width() -> None:
    table = make_table(
        [
            {"key": "a", "label": "A", "kind": "text"},
            {"key": "t", "label": "", "kind": "badge", "width": 2},
        ],
        rows=[{"a": "x", "t": "OK"}],
    )

    with pytest.raises(ReportError, match=r"badge column\(s\).*can't take a width"):
        parse_report(
            make_report(badges={"OK": {"label": "Ok", "tone": "green", "legend": "l"}}, blocks=[table])
        )


def test_placement_cell_is_only_for_badge_columns() -> None:
    table = make_table(
        [{"key": "a", "label": "A", "kind": "text", "placement": "cell"}],
        rows=[{"a": "x"}],
    )
    with pytest.raises(ReportError, match=r"placement 'cell' is only for badge columns"):
        parse_report(make_report(blocks=[table]))


def test_cell_badge_column_takes_a_width_and_accepts_a_key_or_list() -> None:
    """A placement:cell badge is an in-cell column: it may take a width, and its cell value is a single
    key or a list of keys."""
    table = make_table(
        [
            {"key": "a", "label": "A", "kind": "text", "width": 2},
            {"key": "acc", "label": "Access", "kind": "badge", "placement": "cell", "width": 1},
        ],
        rows=[{"a": "one", "acc": "W"}, {"a": "two", "acc": ["W", "R"]}],
    )
    report = parse_report(
        make_report(
            badges={
                "W": {"label": "Write", "tone": "green", "legend": "rw"},
                "R": {"label": "Read", "tone": "blue", "legend": "ro"},
            },
            blocks=[table],
        )
    )
    parsed = report.blocks[0]
    assert isinstance(parsed, Table)
    assert [row.badges["acc"] for row in parsed.body_rows] == [("W",), ("W", "R")]


@pytest.mark.parametrize("bad_value", [[], ["W", 123]])
def test_cell_badge_value_must_be_a_key_or_nonempty_string_list(bad_value: object) -> None:
    table = make_table(
        [
            {"key": "a", "label": "A", "kind": "text"},
            {"key": "acc", "label": "Access", "kind": "badge", "placement": "cell"},
        ],
        rows=[{"a": "x", "acc": bad_value}],
    )
    with pytest.raises(ReportError, match=r"cell badge needs a key or a non-empty list of keys"):
        parse_report(
            make_report(badges={"W": {"label": "Write", "tone": "green", "legend": "rw"}}, blocks=[table])
        )


def test_mixed_widths_rejected_when_a_cell_badge_column_is_in_the_set() -> None:
    """A cell-placement badge joins the in-cell width set, so widthing it but not a sibling still fails."""
    table = make_table(
        [
            {"key": "a", "label": "A", "kind": "text"},  # no width
            {"key": "acc", "label": "Access", "kind": "badge", "placement": "cell", "width": 1},
        ],
        rows=[{"a": "x", "acc": "W"}],
    )
    with pytest.raises(ReportError, match=r"set width on every in-cell column, or none"):
        parse_report(
            make_report(badges={"W": {"label": "Write", "tone": "green", "legend": "rw"}}, blocks=[table])
        )


@pytest.mark.parametrize(
    ("width", "message"),
    [
        pytest.param(7, r"width\b.*less than or equal to 6", id="above-range"),
        pytest.param(0, r"width\b.*greater than or equal to 1", id="below-range"),
        pytest.param(True, r"width\b.*must be a number, not a boolean", id="boolean"),
    ],
)
def test_column_width_bad_values_are_rejected(width: object, message: str) -> None:
    table = make_table([{"key": "a", "label": "A", "kind": "text", "width": width}], rows=[{"a": "x"}])

    with pytest.raises(ReportError, match=message):
        parse_report(make_report(blocks=[table]))


def test_comparison_row_values_must_match_option_count() -> None:
    block = {
        "type": "comparison",
        "options": ["A", "B", "C"],
        "rows": [{"feature": "X", "values": [True, False]}],
    }
    with pytest.raises(ReportError, match=r"has 2 values but there are 3 options"):
        parse_report(make_report(blocks=[block]))


def test_matrix_cell_unknown_row_is_rejected() -> None:
    block = make_matrix([{"row": "nope", "col": "c1", "label": "x"}])
    with pytest.raises(ReportError, match=r"matrix cell row 'nope' is not one of the declared rows"):
        parse_report(make_report(blocks=[block]))


def test_matrix_duplicate_row_labels_are_rejected() -> None:
    block = make_matrix([{"row": "dup", "col": "c1", "label": "x"}], rows=["dup", "dup"])
    with pytest.raises(ReportError, match=r"matrix row labels must be unique"):
        parse_report(make_report(blocks=[block]))


def test_matrix_cell_whitespace_row_is_rejected() -> None:
    block = make_matrix([{"row": "  ", "col": "c1", "label": "x"}])
    with pytest.raises(
        ReportError, match=r"blocks\.0\.matrix\.cells\.0\.row: String should match pattern '\\S'$"
    ):
        parse_report(make_report(blocks=[block]))


def test_matrix_duplicate_column_labels_are_rejected() -> None:
    block = make_matrix([{"row": "r1", "col": "dup", "label": "x"}], columns=["dup", "dup"])
    with pytest.raises(ReportError, match=r"matrix column labels must be unique"):
        parse_report(make_report(blocks=[block]))
