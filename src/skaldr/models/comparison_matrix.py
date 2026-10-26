from typing import Literal

from pydantic import Field, StrictBool, model_validator

from skaldr.frozen_model import FrozenModel
from skaldr.models.base import BlockBase
from skaldr.models.primitives import (
    REFERENCE_KEY_PATTERN,
    BadgeColor,
    Count,
    NonBlank,
    NonBlankRichText,
    RichText,
    Tone,
)


class ComparisonCell(FrozenModel):
    value: NonBlankRichText = Field(description="Cell text (for a ✓/✗ pass a bare true/false instead).")
    tone: Tone | None = Field(default=None, description="Optional tone for the text.")


# A comparison cell is a bare bool (✓/✗), a bare string, or {value, tone} for toned text.
# StrictBool (not bool) so a stray int like 0/1 fails loudly instead of silently rendering ✓/✗.
ComparisonValue = StrictBool | RichText | ComparisonCell


class ComparisonRow(FrozenModel):
    feature: NonBlank = Field(description="Row label: the attribute being compared.")
    values: list[ComparisonValue] = Field(min_length=1, description="One cell per option, in column order.")


class Comparison(BlockBase):
    type: Literal["comparison"]
    options: list[str] = Field(
        min_length=2, description="The things being compared: the column headers (2+)."
    )
    rows: list[ComparisonRow] = Field(
        min_length=1, description="Feature rows; each supplies one value per option."
    )
    highlight: Count | None = Field(
        default=None, description="0-based index of the recommended option column to emphasise."
    )
    polarity: list[Literal["positive", "negative"]] | None = Field(
        default=None,
        description="Optional per-option polarity, one per option (default all positive). In a 'negative' "
        "column a true ✓ reads as BAD (red) and a false ✗ as GOOD (green), for present-is-bad attributes "
        "(e.g. 'leaks disk layout'). Affects only ✓/✗ bool cells; the glyph still marks present/absent.",
    )

    @model_validator(mode="after")
    def _shape(self) -> "Comparison":
        for row in self.rows:
            if len(row.values) != len(self.options):
                raise ValueError(
                    f"comparison row '{row.feature}' has {len(row.values)} values but there are "
                    f"{len(self.options)} options; they must match"
                )
        if self.highlight is not None and not (0 <= self.highlight < len(self.options)):
            raise ValueError(
                f"highlight index {self.highlight} is out of range for {len(self.options)} options"
            )
        if self.polarity is not None and len(self.polarity) != len(self.options):
            raise ValueError(
                f"comparison polarity has {len(self.polarity)} entries but there are "
                f"{len(self.options)} options; they must match"
            )
        return self

    def is_negative(self, index: int) -> bool:
        return self.polarity is not None and self.polarity[index] == "negative"


class MatrixCell(FrozenModel):
    row: NonBlank = Field(description="Which row this cell sits in: one of the block's `rows`.")
    col: NonBlank = Field(description="Which column this cell sits in: one of the block's `columns`.")
    badge: NonBlank | None = Field(
        default=None,
        description="A declared badge key: its tone fills the cell and its label is the cell text, or "
        "the state name shown beside `label` when both are set. Use this OR `tone`, not both.",
    )
    tone: BadgeColor | None = Field(
        default=None,
        description="A one-off fill colour (palette or semantic name) for a cell with no vocabulary "
        "badge, e.g. a RACI letter or a ✓. Use this OR `badge`, not both.",
    )
    label: NonBlank | None = Field(
        default=None,
        description="Short text shown in the cell. With `badge` it is shown after the badge's label; with "
        "`tone` it is the cell text; on its own it is plain text on an untinted cell.",
    )

    @model_validator(mode="after")
    def _shape(self) -> "MatrixCell":
        if self.badge is not None and self.tone is not None:
            raise ValueError("a matrix cell takes `badge` or `tone`, not both")
        if self.badge is None and self.tone is None and self.label is None:
            raise ValueError(
                "a matrix cell needs a `badge`, a `tone`, or a `label` (omit it for a blank cell)"
            )
        return self


class Matrix(BlockBase):
    type: Literal["matrix"]
    rows: list[NonBlank] = Field(min_length=1, description="Row labels, top to bottom (the row axis).")
    columns: list[NonBlank] = Field(
        min_length=1, description="Column headers, left to right (the column axis)."
    )
    cells: list[MatrixCell] = Field(
        min_length=1,
        description="Filled cells, each naming a `row` + `col` from the axes. Omit a cell entirely for a "
        "blank. At most one cell per (row, col).",
    )
    id: str | None = Field(
        default=None,
        min_length=1,
        pattern=rf"^{REFERENCE_KEY_PATTERN}$",
        description="Optional stable id (ASCII letters, digits, _, -) so a derived `cards` item can "
        "reference this matrix via `of_matrix`. Unique across the page's matrices.",
    )

    @model_validator(mode="after")
    def _shape(self) -> "Matrix":
        for axis, name in ((self.rows, "row"), (self.columns, "column")):
            stripped = [entry.strip() for entry in axis]
            if len(set(stripped)) != len(stripped):
                raise ValueError(f"matrix {name} labels must be unique")
        row_set, col_set = set(self.rows), set(self.columns)
        seen: set[tuple[str, str]] = set()
        for cell in self.cells:
            if cell.row not in row_set:
                raise ValueError(f"matrix cell row '{cell.row}' is not one of the declared rows")
            if cell.col not in col_set:
                raise ValueError(f"matrix cell col '{cell.col}' is not one of the declared columns")
            if (cell.row, cell.col) in seen:
                raise ValueError(
                    f"matrix has two cells at ('{cell.row}', '{cell.col}'); at most one per cell"
                )
            seen.add((cell.row, cell.col))
        return self
