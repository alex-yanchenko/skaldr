import re
from typing import Any

import pytest

from skaldr.errors import ReportError
from skaldr.models import Row, RowGroup, Subrow, Table, parse_report
from tests.factories import make_report, make_table, parsed_block

EVERY_KIND_COLUMNS: list[dict[str, Any]] = [
    {"key": "a", "label": "A"},
    {"key": "note", "label": "Note", "kind": "rich"},
    {"key": "n", "label": "N", "kind": "number"},
    {"key": "ok", "label": "OK", "kind": "indicator"},
    {"key": "acc", "label": "Access", "kind": "badge", "placement": "cell"},
    {"key": "tag", "label": "", "kind": "badge"},
]
ACCESS_BADGES: dict[str, Any] = {
    "W": {"label": "Write", "tone": "green", "legend": "rw"},
    "R": {"label": "Read", "tone": "blue", "legend": "ro"},
}
TEXT_COLUMN: list[dict[str, Any]] = [{"key": "a", "label": "A"}]


def _every_kind_row(**overrides: Any) -> dict[str, Any]:
    return {"a": "x", "note": "**y**", "n": 2, "ok": "", "acc": "W", "tag": "", **overrides}


def _table(rows: list[Any], **overrides: Any) -> Table:
    return parsed_block(Table, make_table(EVERY_KIND_COLUMNS, rows=rows, **overrides), badges=ACCESS_BADGES)


def test_a_validated_row_holds_each_cell_typed_by_its_column_kind_with_aliases_resolved() -> None:
    row = _every_kind_row(
        n=2.5,
        ok="green",
        acc=["W", " ", "R "],
        tag=" W ",
        tone="red",
        subrows=[{"label": "bin", "value": 4}, {"label": "rest", "value": "n/a"}],
    )

    assert _table([row]).body_rows == (
        Row(
            texts={"a": "x", "note": "**y**"},
            numbers={"n": 2.5},
            badges={"acc": ("W", "R"), "tag": ("W",)},
            indicators={"ok": "success"},
            tone="danger",
            subrows=(Subrow("bin", 4), Subrow("rest", "n/a")),
        ),
    )


def test_a_blank_indicator_reads_as_no_tone_and_a_blank_badge_as_no_keys() -> None:
    assert _table([_every_kind_row(ok="  ", acc=[" "], tag="")]).body_rows == (
        Row(
            texts={"a": "x", "note": "**y**"},
            numbers={"n": 2},
            badges={"acc": (), "tag": ()},
            indicators={"ok": None},
        ),
    )


def test_a_positional_row_is_typed_by_the_column_in_its_position() -> None:
    rows = [["x", "y", 3, "warning", ["R"], "W"]]

    assert _table(rows).body_rows == (
        Row(
            texts={"a": "x", "note": "y"},
            numbers={"n": 3},
            badges={"acc": ("R",), "tag": ("W",)},
            indicators={"ok": "warning"},
        ),
    )


def test_a_grouped_table_keeps_its_typed_rows_per_group_and_reads_them_all_in_order() -> None:
    table = parsed_block(
        Table,
        make_table(
            TEXT_COLUMN,
            groups=[{"name": "G1", "rows": [{"a": "x"}, ["y"]]}, {"name": "G2", "rows": []}],
        ),
    )

    assert (table.row_groups, table.body_rows) == (
        (RowGroup("G1", (Row(texts={"a": "x"}), Row(texts={"a": "y"}))), RowGroup("G2", ())),
        (Row(texts={"a": "x"}), Row(texts={"a": "y"})),
    )


def test_an_ungrouped_table_has_no_row_groups() -> None:
    assert parsed_block(Table, make_table(TEXT_COLUMN, rows=[{"a": "x"}])).row_groups is None


def test_a_number_cell_keeps_an_integer_an_integer() -> None:
    (row,) = _table([_every_kind_row(n=7)]).body_rows

    assert (row.numbers["n"], type(row.numbers["n"])) == (7, int)


def test_the_emitted_model_shows_each_row_as_authored_with_its_tone_aliases_resolved() -> None:
    row = _every_kind_row(ok="green", acc=["W", " R"], tone="red")

    assert _table([row]).model_dump(mode="json")["rows"] == [
        {"a": "x", "note": "**y**", "n": 2, "ok": "success", "acc": ["W", " R"], "tag": "", "tone": "danger"}
    ]


@pytest.mark.parametrize(
    ("row", "message"),
    [
        pytest.param(
            _every_kind_row(extra="z"), "rows.0: unknown key(s): ['extra']", id="a-key-no-column-reads"
        ),
        pytest.param(
            _every_kind_row(ok=3),
            "rows.0.ok: indicator column needs a string value",
            id="a-numeric-indicator",
        ),
        pytest.param(
            _every_kind_row(subrows=[{"label": "bin"}]),
            "rows.0.subrows.0: must be {label, value}",
            id="a-subrow-without-a-value",
        ),
    ],
)
def test_a_row_that_does_not_fit_its_columns_is_refused_at_its_path(
    row: dict[str, Any], message: str
) -> None:
    report = make_report(badges=ACCESS_BADGES, blocks=[make_table(EVERY_KIND_COLUMNS, rows=[row])])

    with pytest.raises(ReportError, match=re.escape(message)):
        parse_report(report)
