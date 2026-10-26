import pytest

from skaldr.errors import ReportError
from skaldr.models import Matrix, MatrixCell, parse_report
from tests.factories import make_report
from tests.factories.models_factory import make_matrix


def test_meter_value_out_of_bounds_is_rejected() -> None:
    block = {"type": "meter", "items": [{"label": "x", "value": 120, "max": 100}]}

    with pytest.raises(ReportError, match=r"blocks\.0\.meter\.items\.0.*between 0 and"):
        parse_report(make_report(blocks=[block]))


def test_a_comparison_cell_with_blank_text_is_rejected() -> None:
    block = {
        "type": "comparison",
        "options": ["A", "B"],
        "rows": [{"feature": "f", "values": [{"value": " "}, False]}],
    }

    with pytest.raises(ReportError) as raised:
        parse_report(make_report(blocks=[block]))

    assert str(raised.value) == (
        "invalid content data: blocks.0.comparison.rows.0.values.0.bool: Input should be a valid boolean; "
        "blocks.0.comparison.rows.0.values.0.str: Input should be a valid string; "
        "blocks.0.comparison.rows.0.values.0.ComparisonCell.value: String should match pattern '\\S'"
    )


def test_meter_max_must_be_positive() -> None:
    with pytest.raises(ReportError, match=r"greater than 0"):
        parse_report(make_report(blocks=[{"type": "meter", "items": [{"label": "x", "value": 0, "max": 0}]}]))


def test_range_segment_span_must_be_positive() -> None:
    with pytest.raises(ReportError, match=r"segment 'span' must be greater than 0"):
        parse_report(make_report(blocks=[{"type": "range", "segments": [{"label": "x", "span": 0}]}]))


def test_range_segment_span_rejects_boolean() -> None:
    with pytest.raises(ReportError, match=r"must be a number, not a boolean"):
        parse_report(make_report(blocks=[{"type": "range", "segments": [{"label": "x", "span": True}]}]))


def test_range_segment_span_rejects_non_finite() -> None:
    block = {"type": "range", "segments": [{"label": "x", "span": float("inf")}]}
    with pytest.raises(ReportError, match=r"must be a finite number"):
        parse_report(make_report(blocks=[block]))


def test_range_segment_label_must_not_be_blank() -> None:
    with pytest.raises(
        ReportError, match=r"blocks\.0\.range\.segments\.0\.label: String should match pattern '\\S'$"
    ):
        parse_report(make_report(blocks=[{"type": "range", "segments": [{"label": "   ", "span": 1}]}]))


def test_range_needs_at_least_one_segment() -> None:
    with pytest.raises(ReportError, match=r"blocks\.0\.range\.segments.*at least 1"):
        parse_report(make_report(blocks=[{"type": "range", "segments": []}]))


def test_range_axis_needs_at_least_one_of_min_or_max() -> None:
    block: dict[str, object] = {"type": "range", "axis": {}, "segments": [{"label": "x", "span": 1}]}
    with pytest.raises(ReportError, match=r"range axis needs at least one of 'min' or 'max'"):
        parse_report(make_report(blocks=[block]))


def test_range_axis_rejects_blank_only_labels() -> None:
    block: dict[str, object] = {
        "type": "range",
        "axis": {"min": "  ", "max": ""},
        "segments": [{"label": "x", "span": 1}],
    }
    with pytest.raises(ReportError, match=r"range axis needs at least one of 'min' or 'max'"):
        parse_report(make_report(blocks=[block]))


def test_meter_rejects_non_finite_value() -> None:
    block = {"type": "meter", "items": [{"label": "x", "value": float("inf"), "max": 100}]}

    with pytest.raises(ReportError, match=r"value\b.*must be a finite number"):
        parse_report(make_report(blocks=[block]))


def test_meter_rejects_non_finite_max() -> None:
    block = {"type": "meter", "items": [{"label": "x", "value": 1, "max": float("inf")}]}

    with pytest.raises(ReportError, match=r"max\b.*must be a finite number"):
        parse_report(make_report(blocks=[block]))


def test_meter_rejects_boolean_value() -> None:
    block = {"type": "meter", "items": [{"label": "x", "value": True, "max": 100}]}

    with pytest.raises(ReportError, match=r"value\b.*must be a number, not a boolean"):
        parse_report(make_report(blocks=[block]))


def test_meter_negative_value_is_rejected() -> None:
    block = {"type": "meter", "items": [{"label": "x", "value": -5, "max": 100}]}

    with pytest.raises(ReportError, match=r"between 0 and"):
        parse_report(make_report(blocks=[block]))


def test_chart_series_values_must_match_category_count() -> None:
    block = {
        "type": "chart",
        "variant": "bar",
        "categories": ["a", "b", "c"],
        "series": [{"label": "X", "values": [1, 2]}],
    }
    with pytest.raises(ReportError, match=r"2 values but there are 3 categories"):
        parse_report(make_report(blocks=[block]))


def test_chart_bar_requires_categories() -> None:
    with pytest.raises(ReportError, match=r"needs 'categories'"):
        parse_report(make_report(blocks=[{"type": "chart", "variant": "bar"}]))


def test_chart_bar_requires_series() -> None:
    # categories present but no series — reaches the series guard (past the categories check)
    with pytest.raises(ReportError, match=r"needs at least one entry in 'series'"):
        parse_report(make_report(blocks=[{"type": "chart", "variant": "bar", "categories": ["a"]}]))


def test_chart_bar_rejects_negative_values() -> None:
    block = {
        "type": "chart",
        "variant": "bar",
        "categories": ["a"],
        "series": [{"label": "X", "values": [-1]}],
    }
    with pytest.raises(ReportError, match=r"negative value; bar/line values must be >= 0"):
        parse_report(make_report(blocks=[block]))


def test_chart_bar_rejects_donut_slices() -> None:
    block = {
        "type": "chart",
        "variant": "bar",
        "categories": ["a"],
        "series": [{"label": "X", "values": [1]}],
        "slices": [{"label": "s", "value": 1}],
    }
    with pytest.raises(ReportError, match=r"'slices' is only for variant: donut"):
        parse_report(make_report(blocks=[block]))


def test_chart_donut_rejects_bar_line_fields() -> None:
    block = {
        "type": "chart",
        "variant": "donut",
        "series": [{"label": "X", "values": [1]}],
        "slices": [{"label": "s", "value": 1}],
    }
    with pytest.raises(ReportError, match=r"'categories'/'series' are for variant: bar/line"):
        parse_report(make_report(blocks=[block]))


def test_chart_donut_requires_slices() -> None:
    with pytest.raises(ReportError, match=r"variant 'donut' needs"):
        parse_report(make_report(blocks=[{"type": "chart", "variant": "donut"}]))


def test_chart_donut_slice_value_must_be_positive() -> None:
    block = {"type": "chart", "variant": "donut", "slices": [{"label": "s", "value": 0}]}
    with pytest.raises(ReportError, match=r"donut slice 's' value must be greater than 0"):
        parse_report(make_report(blocks=[block]))


def test_comparison_requires_at_least_two_options() -> None:
    block = {"type": "comparison", "options": ["only"], "rows": [{"feature": "X", "values": ["a"]}]}
    with pytest.raises(ReportError, match=r"blocks\.0\.comparison\.options.*at least 2"):
        parse_report(make_report(blocks=[block]))


def test_comparison_highlight_out_of_range_is_rejected() -> None:
    block = {
        "type": "comparison",
        "options": ["A", "B"],
        "highlight": 5,
        "rows": [{"feature": "X", "values": [True, False]}],
    }
    with pytest.raises(ReportError, match=r"highlight index 5 is out of range"):
        parse_report(make_report(blocks=[block]))


def test_comparison_polarity_length_must_match_option_count() -> None:
    block = {
        "type": "comparison",
        "options": ["A", "B"],
        "polarity": ["positive"],
        "rows": [{"feature": "X", "values": [True, False]}],
    }
    with pytest.raises(ReportError, match=r"polarity has 1 entries but there are 2 options"):
        parse_report(make_report(blocks=[block]))


def test_matrix_cell_unknown_col_is_rejected() -> None:
    block = make_matrix([{"row": "r1", "col": "nope", "label": "x"}])
    with pytest.raises(ReportError, match=r"matrix cell col 'nope' is not one of the declared columns"):
        parse_report(make_report(blocks=[block]))


def test_matrix_two_cells_at_the_same_position_are_rejected() -> None:
    block = make_matrix([{"row": "r1", "col": "c1", "label": "a"}, {"row": "r1", "col": "c1", "label": "b"}])
    with pytest.raises(ReportError, match=r"two cells at \('r1', 'c1'\); at most one per cell"):
        parse_report(make_report(blocks=[block]))


def test_matrix_cell_with_badge_and_tone_together_is_rejected() -> None:
    block = make_matrix([{"row": "r1", "col": "c1", "badge": "HAVE", "tone": "green"}])
    with pytest.raises(ReportError, match=r"a matrix cell takes `badge` or `tone`, not both"):
        parse_report(
            make_report(blocks=[block], badges={"HAVE": {"label": "H", "tone": "green", "legend": "x"}})
        )


def test_matrix_cell_with_no_fill_is_rejected() -> None:
    block = make_matrix([{"row": "r1", "col": "c1"}])
    with pytest.raises(ReportError, match=r"needs a `badge`, a `tone`, or a `label`"):
        parse_report(make_report(blocks=[block]))


def test_matrix_cell_blank_badge_is_rejected() -> None:
    block = make_matrix([{"row": "r1", "col": "c1", "badge": "  "}])
    with pytest.raises(
        ReportError,
        match=r"blocks\.0\.matrix\.cells\.0\.badge: String should match pattern '\\S'$",
    ):
        parse_report(make_report(blocks=[block]))


def test_matrix_cell_blank_label_is_rejected() -> None:
    block = make_matrix([{"row": "r1", "col": "c1", "label": "  "}])
    with pytest.raises(
        ReportError,
        match=r"blocks\.0\.matrix\.cells\.0\.label: String should match pattern '\\S'$",
    ):
        parse_report(make_report(blocks=[block]))


def test_matrix_blank_axis_label_is_rejected() -> None:
    block = make_matrix([{"row": "r2", "col": "c1", "label": "x"}], rows=["  ", "r2"])
    with pytest.raises(ReportError, match=r"blocks\.0\.matrix\.rows\.0: String should match pattern '\\S'$"):
        parse_report(make_report(blocks=[block]))


def test_matrix_parses_to_whole_model() -> None:
    block = {
        "type": "matrix",
        "rows": ["r1", "r2"],
        "columns": ["c1", "c2"],
        "cells": [
            {"row": "r1", "col": "c1", "badge": "HAVE"},
            {"row": "r2", "col": "c2", "tone": "green", "label": "R"},  # semantic tone normalises to palette
        ],
    }

    report = parse_report(
        make_report(blocks=[block], badges={"HAVE": {"label": "Have", "tone": "green", "legend": "x"}})
    )

    assert report.blocks[0] == Matrix(
        type="matrix",
        rows=["r1", "r2"],
        columns=["c1", "c2"],
        cells=[
            MatrixCell(row="r1", col="c1", badge="HAVE"),
            MatrixCell(row="r2", col="c2", tone="green", label="R"),
        ],
    )


def test_chart_stacked_only_applies_to_bar() -> None:
    block = {
        "type": "chart",
        "variant": "line",
        "categories": ["a", "b"],
        "series": [{"label": "X", "values": [1, 2]}],
        "stacked": True,
    }
    with pytest.raises(ReportError, match=r"'stacked' applies only to variant: bar"):
        parse_report(make_report(blocks=[block]))
