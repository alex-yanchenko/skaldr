from typing import Any

import pytest

from skaldr.export.inline import bold, italic, plain
from skaldr.export.runs import Break, Chip, ExportRich, IndicatorMark
from skaldr.export.tree import Paragraph, TableCell, TableColumn, TableNode, TableRow, ToneName
from skaldr.richtext import Code, Plain
from tests.factories import API_BADGES, lowered, make_table
from tests.factories.lower_factory import API_LEGEND, cell_texts_of


def test_a_grouped_table_sums_each_group_and_marks_an_empty_one() -> None:
    table: dict[str, Any] = {
        "type": "table",
        "columns": [{"key": "a", "label": "Issue"}, {"key": "n", "label": "Units", "kind": "number"}],
        "totals": {"column": "n"},
        "groups": [
            {
                "name": "Ours",
                "rows": [{"a": "x", "n": 2, "subrows": [{"label": "of which `y`", "value": 1}]}],
            },
            {"name": "Theirs", "rows": []},
        ],
    }

    assert lowered([table]) == (
        TableNode(
            cell_texts_of("Issue", "Units"),
            (
                TableRow(
                    (TableCell((Plain("Ours"), Plain(" "), Plain("(2)"))), TableCell(())), emphasis="group"
                ),
                TableRow(
                    (
                        TableCell((Plain("x"), Break(), Plain("of which "), Code("y"), Plain(": 1"))),
                        TableCell((Plain("2"),)),
                    )
                ),
                TableRow(
                    (TableCell((Plain("Theirs"), Plain(" "), Plain("(0)"))), TableCell(())), emphasis="group"
                ),
                TableRow((TableCell(italic(plain("none"))), TableCell(()))),
                TableRow(cell_texts_of("Total", "2"), emphasis="total"),
            ),
            columns=(TableColumn(), TableColumn(share=0.1)),
        ),
    )


def test_a_totals_row_puts_its_label_in_the_first_cell_that_is_not_the_total() -> None:
    table = {
        "type": "table",
        "columns": [{"key": "n", "label": "Units", "kind": "number"}, {"key": "a", "label": "Issue"}],
        "totals": {"column": "n"},
        "rows": [{"n": 2, "a": "x"}, {"n": 3, "a": "y"}],
    }

    assert lowered([table]) == (
        TableNode(
            cell_texts_of("Units", "Issue"),
            (
                TableRow((TableCell((Plain("2"),)), TableCell((Plain("x"),)))),
                TableRow((TableCell((Plain("3"),)), TableCell((Plain("y"),)))),
                TableRow(cell_texts_of("5", "Total"), emphasis="total"),
            ),
            columns=(TableColumn(share=0.1), TableColumn()),
            title_column=1,
        ),
    )


def test_a_blank_title_cell_starts_with_its_badge_or_subrow_not_a_break() -> None:
    table = {
        "type": "table",
        "columns": [
            {"key": "a", "label": "Issue"},
            {"key": "tag", "label": "", "kind": "badge", "placement": "title"},
        ],
        "rows": [{"a": "", "tag": "API"}, {"a": "", "tag": "", "subrows": [{"label": "s", "value": 2}]}],
    }

    assert lowered([table], badges=API_BADGES) == (
        API_LEGEND,
        TableNode(
            cell_texts_of("Issue"),
            (
                TableRow((TableCell((Chip("api", "blue"),)),)),
                TableRow((TableCell((Plain("s"), Plain(": 2"))),)),
            ),
        ),
    )


def test_a_reconciled_table_shows_its_rollup_and_reconcile_line_which_the_footer_repeats_as_in_html() -> None:
    table = {
        "type": "table",
        "columns": [
            {"key": "a", "label": "Issue"},
            {"key": "risk", "label": "Risk", "kind": "indicator"},
            {"key": "n", "label": "Units", "kind": "number", "pct_of_total": True},
            {"key": "tag", "label": "", "kind": "badge", "placement": "title"},
        ],
        "reconcile": {"total": 10, "column": "n", "handled": {"label": "Clean", "value": 8}},
        "rollup": {"by": "tag", "label": "Owners:"},
        "rows": [{"a": "x", "risk": "warning", "n": 2, "tag": "API", "tone": "danger"}],
        "tint_by": "tag",
    }

    assert lowered([table], badges=API_BADGES) == (
        API_LEGEND,
        TableNode(
            cell_texts_of("Issue", "Risk", "Units"),
            (
                TableRow(
                    (
                        TableCell((Plain("x"), Plain(" "), Chip("api", "blue"))),
                        TableCell((IndicatorMark("warning"),), "warning"),
                        TableCell((Plain("2"), Plain(" "), Plain("(20.0% of total)"))),
                    ),
                    "danger",
                ),
            ),
            columns=(TableColumn(), TableColumn(share=0.07), TableColumn(share=0.1)),
        ),
        Paragraph((*bold("Owners"), Plain(": "), Chip("api", "blue"), Plain(" "), Plain("1"))),
        Paragraph((Plain("Reconciles: 2 + 8 clean = 10."),), "muted"),
        Paragraph((Plain("Reconciles: 2 + 8 clean = 10."),), "muted"),
    )


@pytest.mark.parametrize(
    ("tag", "chips", "tone"),
    [
        pytest.param("API", (Chip("api", "blue"),), "info", id="one-key"),
    ],
)
def test_a_tinted_table_row_takes_the_tone_of_its_badge_key(
    tag: str | list[str], chips: ExportRich, tone: ToneName | None
) -> None:
    badges = {**API_BADGES, "OPS": {"label": "ops", "tone": "red", "legend": False}}
    table = {
        "type": "table",
        "columns": [
            {"key": "a", "label": "A"},
            {"key": "tag", "label": "", "kind": "badge", "placement": "cell"},
        ],
        "tint_by": "tag",
        "rows": [{"a": "x", "tag": tag}],
    }

    assert lowered([table], badges=badges) == (
        API_LEGEND,
        TableNode(
            cell_texts_of("A", ""),
            (TableRow((TableCell((Plain("x"),)), TableCell(chips)), tint=tone),),
        ),
    )


def test_a_table_names_its_title_column_among_the_cells_it_writes() -> None:
    table = make_table(
        [
            {"key": "n", "label": "N", "kind": "number"},
            {"key": "tag", "label": "", "kind": "badge", "placement": "title"},
            {"key": "a", "label": "Item"},
        ],
        rows=[{"n": 1, "tag": "", "a": "x", "tone": "danger"}],
    )

    assert lowered([table]) == (
        TableNode(
            cell_texts_of("N", "Item"),
            (TableRow(cell_texts_of("1", "x"), "danger"),),
            columns=(TableColumn(share=0.1), TableColumn()),
            title_column=1,
        ),
    )


@pytest.mark.parametrize(
    ("columns", "table_columns"),
    [
        pytest.param(
            [{"key": "a", "label": "A", "width": 2}, {"key": "b", "label": "B", "tone": "green", "width": 4}],
            (TableColumn(share=2 / 6), TableColumn("success", 4 / 6)),
            id="tones-and-widths",
        ),
        pytest.param(
            [{"key": "a", "label": "A"}, {"key": "b", "label": "B", "tone": "warning"}],
            (TableColumn(), TableColumn("warning")),
            id="a-tone-alone",
        ),
        pytest.param([{"key": "a", "label": "A"}, {"key": "b", "label": "B"}], (), id="neither"),
    ],
)
def test_a_table_keeps_its_column_tones_and_widths_in_the_order_of_its_cells(
    columns: list[dict[str, Any]], table_columns: tuple[TableColumn, ...]
) -> None:
    table = make_table(
        [*columns, {"key": "t", "label": "", "kind": "badge"}], rows=[{"a": "x", "b": "y", "t": ""}]
    )

    assert lowered([table]) == (
        TableNode(cell_texts_of("A", "B"), (TableRow(cell_texts_of("x", "y")),), columns=table_columns),
    )


def test_a_number_column_carries_its_default_width_share_beside_an_auto_column() -> None:
    table = make_table(
        [{"key": "a", "label": "A"}, {"key": "b", "label": "B", "kind": "number"}], rows=[{"a": "x", "b": 10}]
    )

    assert lowered([table]) == (
        TableNode(
            cell_texts_of("A", "B"),
            (TableRow(cell_texts_of("x", "10")),),
            columns=(TableColumn(), TableColumn(share=0.1)),
        ),
    )


def test_a_blank_indicator_cell_is_empty_and_untoned() -> None:
    table = make_table(
        [{"key": "a", "label": "Issue"}, {"key": "risk", "label": "Risk", "kind": "indicator"}],
        rows=[{"a": "x", "risk": " "}],
    )

    assert lowered([table]) == (
        TableNode(
            cell_texts_of("Issue", "Risk"),
            (TableRow(cell_texts_of("x", "")),),
            columns=(TableColumn(), TableColumn(share=0.07)),
        ),
    )


def test_a_rollup_without_a_label_is_its_counts_alone() -> None:
    table = make_table(
        [{"key": "a", "label": "Issue"}, {"key": "tag", "label": "", "kind": "badge", "placement": "cell"}],
        rollup={"by": "tag"},
        rows=[{"a": "x", "tag": "API"}],
    )

    assert lowered([table], badges=API_BADGES) == (
        API_LEGEND,
        TableNode(
            cell_texts_of("Issue", ""),
            (TableRow((TableCell((Plain("x"),)), TableCell((Chip("api", "blue"),)))),),
        ),
        Paragraph((Chip("api", "blue"), Plain(" "), Plain("1"))),
    )


def test_a_grouped_table_with_nothing_to_sum_labels_each_group_by_name_alone() -> None:
    table = make_table(
        [{"key": "a", "label": "Issue"}, {"key": "n", "label": "Units", "kind": "number"}],
        groups=[{"name": "Ours", "rows": [{"a": "x", "n": 2}]}],
    )

    assert lowered([table]) == (
        TableNode(
            cell_texts_of("Issue", "Units"),
            (
                TableRow(cell_texts_of("Ours", ""), emphasis="group"),
                TableRow(cell_texts_of("x", "2")),
            ),
            columns=(TableColumn(), TableColumn(share=0.1)),
        ),
    )
