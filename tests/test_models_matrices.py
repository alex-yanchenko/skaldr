import pytest

from skaldr.errors import ReportError
from skaldr.models import Matrix, MatrixCell, parse_report
from tests.factories import make_report
from tests.factories.models_factory import make_matrix


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


def test_matrix_undeclared_badge_is_rejected() -> None:
    block = make_matrix([{"row": "r1", "col": "c1", "badge": "GHOST"}])
    with pytest.raises(ReportError, match=r"badge key\(s\) not declared in `badges`: \['GHOST'\]"):
        parse_report(make_report(blocks=[block]))
