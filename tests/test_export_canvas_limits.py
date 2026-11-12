import pytest

from skaldr.export.capabilities import (
    CANVAS_HEADING_LEVEL_LIMIT,
    CANVAS_LAYOUT_COLUMN_LIMIT,
    CANVAS_TABLE_CELL_LIMIT,
    canvas_heading_is_too_deep,
    canvas_heading_level,
    canvas_layout_has_too_many_columns,
    canvas_table_cell_count,
    canvas_table_has_too_many_cells,
    writes_definitions_as_blocks,
)
from skaldr.export.tree import TableNode, TableRow
from skaldr.export_targets import EXPORT_TARGETS, ExportTarget
from tests.factories.export_factory import cell_texts_of


def test_a_table_counts_its_header_row_and_its_widest_row() -> None:
    ragged = TableNode(
        cell_texts_of("a", "b"),
        (TableRow(cell_texts_of("1", "2", "3")), TableRow(cell_texts_of("4"))),
    )

    assert canvas_table_cell_count(ragged) == 9


@pytest.mark.parametrize(
    ("cells", "too_many"),
    [
        pytest.param(CANVAS_TABLE_CELL_LIMIT - 1, False, id="under"),
        pytest.param(CANVAS_TABLE_CELL_LIMIT, False, id="at-the-limit"),
        pytest.param(CANVAS_TABLE_CELL_LIMIT + 1, True, id="over"),
    ],
)
def test_a_canvas_table_may_hold_the_limit_and_no_more(cells: int, too_many: bool) -> None:
    assert canvas_table_has_too_many_cells(cells) is too_many


@pytest.mark.parametrize(
    ("level", "shift", "canvas_level"),
    [pytest.param(1, 0, 1, id="no-shift"), pytest.param(3, 1, 2, id="shifted-up")],
)
def test_a_heading_level_on_a_canvas_is_the_level_less_the_shift(
    level: int, shift: int, canvas_level: int
) -> None:
    assert canvas_heading_level(level, shift) == canvas_level


@pytest.mark.parametrize(
    ("canvas_level", "too_deep"),
    [
        pytest.param(CANVAS_HEADING_LEVEL_LIMIT, False, id="at-the-limit"),
        pytest.param(CANVAS_HEADING_LEVEL_LIMIT + 1, True, id="below-the-limit"),
    ],
)
def test_a_canvas_holds_headings_down_to_its_limit(canvas_level: int, too_deep: bool) -> None:
    assert canvas_heading_is_too_deep(canvas_level) is too_deep


@pytest.mark.parametrize(
    ("columns", "too_many"),
    [
        pytest.param(CANVAS_LAYOUT_COLUMN_LIMIT, False, id="at-the-limit"),
        pytest.param(CANVAS_LAYOUT_COLUMN_LIMIT + 1, True, id="over"),
    ],
)
def test_a_canvas_layout_holds_its_limit_of_columns_and_no_more(columns: int, too_many: bool) -> None:
    assert canvas_layout_has_too_many_columns(columns) is too_many


def test_only_the_canvas_writes_a_definition_list_as_blocks() -> None:
    chosen: dict[ExportTarget, bool] = {
        target: writes_definitions_as_blocks(target) for target in EXPORT_TARGETS
    }

    assert chosen == {"markdown": False, "notion": False, "adf": False, "slack": True}
