import math
from collections.abc import Iterator, Mapping, Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass, field
from functools import cached_property
from typing import Any, Literal, TypeGuard, cast, get_args

from pydantic import Field, model_validator
from pydantic_core import PydanticCustomError
from typing_extensions import assert_never

from skaldr.frozen_model import FrozenModel
from skaldr.models.base import BlockBase
from skaldr.models.primitives import (
    DEFAULT_COLUMN_WIDTH_SHARES,
    REFERENCE_KEY_PATTERN,
    RICH_COLUMN_KINDS,
    RICH_PROSE,
    RICH_TEXT,
    ColumnKind,
    ColumnPlacement,
    Count,
    FieldPath,
    MappedRow,
    RichTextMarker,
    SixthsCount,
    Tone,
    ToneLiteral,
    refuse_an_unusable_number,
    to_tone,
)

_RECONCILIATION_ERROR_TYPE = "reconciliation"
RowTone = Literal["muted", "danger"]
# Row-dict keys with a reserved meaning (not column values). A column may not use one as its key.
_ROW_RESERVED_KEYS = frozenset({"subrows", "tone"})


def _mapped_rows(rows: object) -> list[MappedRow]:
    return cast("list[MappedRow]", rows)


class Column(FrozenModel):
    key: str = Field(description="Row-dict key this column reads.")
    label: str = Field(description="Column header text.")
    kind: ColumnKind = Field(
        default="text",
        description="text (default) / rich (first one becomes the title column), number, badge (a "
        "coloured chip; see `placement`), or indicator (a colour-only dot in its own column; the cell "
        "value is a tone name). Omit for a plain text column: `{key, label}` alone is a text column.",
    )
    placement: ColumnPlacement = Field(
        default="title",
        description="For a `badge` column: `cell` gives the badge its own labelled column, the cell value "
        "a badge key or a list of keys (several chips, wrapping); `title` chips the badge under the "
        "row's title and shows no `label`. Omitted, a badge column with a non-blank `label` is `cell` "
        "and one with a blank `label` is `title`. `cell` on a non-badge column is rejected; the "
        "default is a no-op elsewhere.",
    )
    pct_of_total: bool = Field(
        default=False, description="Show a derived '% of total' caption (needs a reconcile total)."
    )
    width: SixthsCount | None = Field(
        default=None,
        description="Proportional width weight (1-6); set it on every in-cell column, or none. A "
        "`title`-placement badge column takes no width (it rides under the title).",
    )
    tone: Tone | None = Field(
        default=None,
        description="Optional tone that faintly tints the whole column. A row `tone` or a `tint_by` "
        "row tint paints over it. A `title`-placement badge column takes no tone (it rides under the "
        "title).",
    )

    @model_validator(mode="before")
    @classmethod
    def _a_labelled_badge_column_gets_its_own_cell(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        fields = cast("dict[str, Any]", data)
        if fields.get("kind") != "badge" or "placement" in fields:
            return fields
        label = fields.get("label")
        return {**fields, "placement": "cell" if isinstance(label, str) and label.strip() else "title"}


class Handled(FrozenModel):
    label: str = Field(description="Label for the non-issue bucket (e.g. 'Imported cleanly').")
    value: Count = Field(description="Count in the bucket; added to the column sum for reconciliation.")


class Reconcile(FrozenModel):
    total: Count = Field(gt=0, description="Denominator; the column sum + handled must equal this.")
    column: str = Field(description="Key of the number column that must sum to `total`.")
    handled: Handled | None = Field(default=None, description="A bucket outside the rows.")


class Totals(FrozenModel):
    column: str = Field(description="Key of the number column to sum into a footer row.")


class Rollup(FrozenModel):
    by: str = Field(description="Key of the badge column whose per-row values are counted.")
    label: str | None = Field(default=None, description="Optional label shown before the counted chips.")


@dataclass(frozen=True)
class Subrow:
    label: str
    value: int | float | str


@dataclass(frozen=True)
class Row:
    texts: Mapping[str, str] = field(default_factory=dict[str, str])
    numbers: Mapping[str, int | float] = field(default_factory=dict[str, "int | float"])
    badges: Mapping[str, tuple[str, ...]] = field(default_factory=dict[str, "tuple[str, ...]"])
    indicators: Mapping[str, ToneLiteral | None] = field(default_factory=dict[str, "ToneLiteral | None"])
    tone: RowTone | None = None
    subrows: tuple[Subrow, ...] = ()

    def first_badge(self, key: str) -> str | None:
        return next(iter(self.badges[key]), None)


@dataclass(frozen=True)
class RowGroup:
    name: str
    rows: tuple[Row, ...]


def col_sum(rows: Sequence[Row], key: str) -> float:
    return sum(row.numbers[key] for row in rows)


def _as_badge_list(value: Any) -> list[Any]:
    """A badge cell holds one key or a list of keys; normalise to a list either way."""
    return cast("list[Any]", value) if isinstance(value, list) else [value]


def _is_row_tone(value: object) -> TypeGuard[RowTone]:
    return value in get_args(RowTone)


def _is_tone(value: object) -> TypeGuard[ToneLiteral]:
    return value in get_args(ToneLiteral)


def _row_tone(value: object, loc: str) -> RowTone | None:
    if value is None:
        return None
    if not _is_row_tone(value):
        raise ValueError(f"{loc}.tone: row tone must be 'muted' or 'danger'")
    return value


def _string_cell(value: object, kind: ColumnKind, loc: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{loc}: {kind} column needs a string value")
    return value


def _number_cell(value: object, loc: str) -> int | float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{loc}: number column needs a numeric value")
    refuse_an_unusable_number(value, loc)
    return value


def _badge_cell(value: object, placement: ColumnPlacement, loc: str) -> tuple[str, ...]:
    if placement == "title":
        keys: list[Any] = [_string_cell(value, "badge", loc)]
    else:
        keys = _as_badge_list(value)
        if not keys or not all(isinstance(key, str) for key in keys):
            raise ValueError(f"{loc}: cell badge needs a key or a non-empty list of keys")
    return tuple(trimmed for key in cast("list[str]", keys) if (trimmed := key.strip()))


def _indicator_cell(value: object, loc: str) -> ToneLiteral | None:
    if not _string_cell(value, "indicator", loc).strip():
        return None
    if not _is_tone(value):
        raise ValueError(
            f"{loc}: indicator value must be a tone name "
            "(neutral·info·success·warning·danger·accent·teal·sky) or blank"
        )
    return value


def _subrow(raw_subrow: object, loc: str) -> Subrow:
    if not isinstance(raw_subrow, dict) or set(cast("dict[str, Any]", raw_subrow)) != {"label", "value"}:
        raise ValueError(f"{loc}: must be {{label, value}}")
    subrow = cast("dict[str, Any]", raw_subrow)
    label, value = subrow["label"], subrow["value"]
    if not isinstance(label, str):
        raise ValueError(f"{loc}.label: must be a string")
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        raise ValueError(f"{loc}.value: must be a number or string")
    if not isinstance(value, str):
        refuse_an_unusable_number(value, f"{loc}.value")
    return Subrow(label, value)


def _subrows(raw_subrows: object, loc: str) -> tuple[Subrow, ...]:
    if raw_subrows is None:
        return ()
    if not isinstance(raw_subrows, list):
        raise ValueError(f"{loc}.subrows: must be a list")
    return tuple(
        _subrow(raw_subrow, f"{loc}.subrows.{index}")
        for index, raw_subrow in enumerate(cast("list[Any]", raw_subrows))
    )


def _parsed_row(row: MappedRow, columns: Sequence[Column], loc: str) -> Row:
    keys = {column.key for column in columns}
    present = set(row) - _ROW_RESERVED_KEYS
    missing = keys - present
    extra = present - keys
    if missing:
        raise ValueError(f"{loc}: missing column value(s): {sorted(missing)}")
    if extra:
        raise ValueError(f"{loc}: unknown key(s): {sorted(extra)}")
    tone = _row_tone(row.get("tone"), loc)
    texts: dict[str, str] = {}
    numbers: dict[str, int | float] = {}
    badges: dict[str, tuple[str, ...]] = {}
    indicators: dict[str, ToneLiteral | None] = {}
    for column in columns:
        value, cell_loc = row[column.key], f"{loc}.{column.key}"
        match column.kind:
            case "number":
                numbers[column.key] = _number_cell(value, cell_loc)
            case "badge":
                badges[column.key] = _badge_cell(value, column.placement, cell_loc)
            case "indicator":
                indicators[column.key] = _indicator_cell(value, cell_loc)
            case "text" | "rich":
                texts[column.key] = _string_cell(value, column.kind, cell_loc)
            case _:
                assert_never(column.kind)
    return Row(texts, numbers, badges, indicators, tone, _subrows(row.get("subrows"), loc))


def _parsed_rows(rows: Sequence[MappedRow], columns: Sequence[Column], loc: str) -> tuple[Row, ...]:
    return tuple(_parsed_row(row, columns, f"{loc}.{index}") for index, row in enumerate(rows))


def _tone_aliases_resolved(row: MappedRow, indicator_keys: AbstractSet[str]) -> MappedRow:
    return {
        key: to_tone(value) if key == "tone" or key in indicator_keys else value for key, value in row.items()
    }


# A table row is authored as a mapping (column key → value) OR a positional list of values in column
# order. `Table._expand_positional_rows` normalises list rows to mappings before validation. The field
# type is the union (not just dict) so the JSON schema advertises both input shapes; downstream reads
# cast back to a dict, which the normalisation (asserted on Group, guaranteed on Table) makes safe.
TableRow = dict[str, Any] | list[Any]


class Group(FrozenModel):
    name: str = Field(description="Group band label; shows the derived subtotal.")
    rows: list[TableRow] = Field(
        default_factory=list[TableRow],
        description="Rows in this group, each a mapping or a positional list in the declared column "
        "order. Empty renders a 'none' row.",
    )

    @model_validator(mode="after")
    def _rows_are_mappings(self) -> "Group":
        if not all(isinstance(row, dict) for row in self.rows):
            raise ValueError("group rows must be mappings (positional list rows are expanded by the table)")
        return self


class Table(BlockBase):
    type: Literal["table"]
    columns: list[Column] = Field(min_length=1, description="Column specs; at least one text/rich column.")
    groups: list[Group] | None = Field(
        default=None, description="Grouped rows with derived subtotals; provide this OR `rows`, not both."
    )
    rows: list[TableRow] | None = Field(
        default=None,
        description="Ungrouped rows; provide this OR `groups`, not both. Each row is a mapping (column "
        "key → value) or a positional list in the declared column order.",
    )
    reconcile: Reconcile | None = Field(default=None, description="Opt-in trust check on a number column.")
    totals: Totals | None = Field(default=None, description="Sum a number column into a footer row.")
    rollup: Rollup | None = Field(
        default=None,
        description="Opt-in summary strip below the table: counts the rows by a badge column and shows "
        "one '<chip> <count>' per value, derived from the rows so it can never drift from them.",
    )
    tint_by: str | None = Field(
        default=None,
        description="Opt-in row heatmap: faintly tint each row by the tone of the badge in this column "
        "(named by its key), so a long table's state reads as bands of colour. A row left blank in that "
        "column stays untinted; an explicit row `tone` (muted/danger) wins over the tint. Must name a "
        "`badge` column (the same one may still render its chip).",
    )
    id: str | None = Field(
        default=None,
        min_length=1,
        pattern=rf"^{REFERENCE_KEY_PATTERN}$",
        description="Optional stable id (ASCII letters, digits, _, -) so a derived `cards` item can "
        "count this table via `of_tables` (the table must declare a `rollup`). Unique across the page's "
        "tables.",
    )

    @model_validator(mode="before")
    @classmethod
    def _expand_positional_rows(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        fields = cast("dict[str, Any]", data)
        raw_columns = fields.get("columns")
        if not isinstance(raw_columns, list):
            return fields
        keys: list[str] = []
        indicator_keys: set[str] = set()
        for col in cast("list[Any]", raw_columns):
            key = cast("dict[str, Any]", col).get("key") if isinstance(col, dict) else None
            if not isinstance(key, str):
                return fields
            keys.append(key)
            if cast("dict[str, Any]", col).get("kind") == "indicator":
                indicator_keys.add(key)

        def _expand_row_list(rows: Any, loc: str) -> Any:
            if not isinstance(rows, list):
                return rows
            expanded: list[Any] = []
            for index, row in enumerate(cast("list[Any]", rows)):
                if isinstance(row, list):
                    values = cast("list[Any]", row)
                    if len(values) != len(keys):
                        raise ValueError(
                            f"{loc}.{index}: a positional row needs exactly {len(keys)} values, one per "
                            f"column; got {len(values)}"
                        )
                    expanded.append(
                        _tone_aliases_resolved(dict(zip(keys, values, strict=True)), indicator_keys)
                    )
                elif isinstance(row, dict):
                    expanded.append(_tone_aliases_resolved(cast("MappedRow", row), indicator_keys))
                else:
                    expanded.append(row)
            return expanded

        updated = {**fields}
        if "rows" in updated:
            updated["rows"] = _expand_row_list(updated["rows"], "rows")
        groups = updated.get("groups")
        if isinstance(groups, list):
            new_groups: list[Any] = []
            for index, group in enumerate(cast("list[Any]", groups)):
                if isinstance(group, dict) and "rows" in group:
                    group_fields = cast("dict[str, Any]", group)
                    rows = _expand_row_list(group_fields["rows"], f"groups.{index}.rows")
                    new_groups.append({**group_fields, "rows": rows})
                else:
                    new_groups.append(group)
            updated["groups"] = new_groups
        return updated

    @model_validator(mode="after")
    def _validate_table(self) -> "Table":
        if (self.groups is None) == (self.rows is None):
            raise ValueError("provide exactly one of 'groups' or 'rows'")
        if not any(column.kind in RICH_COLUMN_KINDS for column in self.columns):
            raise ValueError("a table needs at least one text or rich column (it hosts the title + chips)")
        column_keys = [column.key for column in self.columns]
        if len(column_keys) != len(set(column_keys)):
            raise ValueError("column keys must be unique")
        reserved_clash = sorted(_ROW_RESERVED_KEYS.intersection(column_keys))
        if reserved_clash:
            raise ValueError(f"column key(s) {reserved_clash} are reserved row keys; rename the column(s)")
        number_keys = {column.key for column in self.columns if column.kind == "number"}
        for spec, name in ((self.reconcile, "reconcile"), (self.totals, "totals")):
            if spec is not None and spec.column not in number_keys:
                raise ValueError(f"{name}.column '{spec.column}' must be a number column")
        if self.reconcile is None and any(column.pct_of_total for column in self.columns):
            raise ValueError("pct_of_total requires a reconcile total")
        pct_misuse = [
            column.key for column in self.columns if column.pct_of_total and column.kind != "number"
        ]
        if pct_misuse:
            raise ValueError(f"column(s) {pct_misuse}: pct_of_total is only for number columns")
        placement_misuse = [c.key for c in self.columns if c.placement == "cell" and c.kind != "badge"]
        if placement_misuse:
            raise ValueError(f"column(s) {placement_misuse}: placement 'cell' is only for badge columns")
        title_badge_widths = [c.key for c in self.title_badges if c.width is not None]
        if title_badge_widths:
            raise ValueError(
                f"badge column(s) {title_badge_widths} can't take a width (they ride under the title)"
            )
        title_badge_tones = [c.key for c in self.title_badges if c.tone is not None]
        if title_badge_tones:
            raise ValueError(
                f"badge column(s) {title_badge_tones} can't take a tone (they ride under the title)"
            )
        # in-cell columns get their own <td>: everything except title-placement badge chips.
        widthed = [c for c in self.cell_columns if c.width is not None]
        if widthed and len(widthed) != len(self.cell_columns):
            raise ValueError("set width on every in-cell column, or none")
        rows = self.body_rows
        if self.rollup is not None:
            badge_keys = {column.key for column in self.columns if column.kind == "badge"}
            if self.rollup.by not in badge_keys:
                raise ValueError(f"rollup.by '{self.rollup.by}' must be a badge column")
            self._refuse_list_cells(
                f"rollup.by '{self.rollup.by}' counts each row under one badge", self.rollup.by
            )
            if not any(row.badges[self.rollup.by] for row in rows):
                raise ValueError(
                    f"rollup.by '{self.rollup.by}' has no values to count: every row is blank there"
                )
        if self.tint_by is not None:
            badge_keys = {column.key for column in self.columns if column.kind == "badge"}
            if self.tint_by not in badge_keys:
                raise ValueError(f"tint_by '{self.tint_by}' must be a badge column")
            self._refuse_list_cells(f"tint_by '{self.tint_by}' tints each row by one badge", self.tint_by)
        self._reconcile()
        return self

    def _refuse_list_cells(self, reason: str, key: str) -> None:
        for loc, row in self.located_rows():
            if isinstance(row[key], list):
                raise ValueError(f"{reason}, so its cells can't hold a list of keys ({loc} holds {row[key]})")

    @property
    def cell_columns(self) -> list[Column]:
        """Columns that get their own <td>, in declared order — everything except title-placement
        badge columns (whose chip rides under the row title). The render's single source of order."""
        return [c for c in self.columns if not (c.kind == "badge" and c.placement == "title")]

    @cached_property
    def column_width_shares(self) -> tuple[float | None, ...]:
        columns = self.cell_columns
        weight_total = sum(column.width or 0 for column in columns)
        if weight_total:
            return tuple((column.width or 0) / weight_total for column in columns)
        defaults = [DEFAULT_COLUMN_WIDTH_SHARES.get(column.kind) for column in columns]
        sized = [share for share in defaults if share is not None]
        if not sized:
            return tuple(defaults)
        room_asked = sum(sized) + defaults.count(None) * max(sized)
        scale = min(1.0, 1 / room_asked)
        return tuple(None if share is None else share * scale for share in defaults)

    @property
    def title_badges(self) -> list[Column]:
        """Badge columns whose chip renders under the row title (placement 'title')."""
        return [c for c in self.columns if c.kind == "badge" and c.placement == "title"]

    def located_rows(self) -> list[tuple[str, MappedRow]]:
        if self.groups is not None:
            return [
                (f"groups.{group_index}.rows.{row_index}", row)
                for group_index, group in enumerate(self.groups)
                for row_index, row in enumerate(_mapped_rows(group.rows))
            ]
        return [(f"rows.{index}", row) for index, row in enumerate(_mapped_rows(self.rows or []))]

    @cached_property
    def row_groups(self) -> tuple[RowGroup, ...] | None:
        if self.groups is None:
            return None
        return tuple(
            RowGroup(group.name, _parsed_rows(_mapped_rows(group.rows), self.columns, f"groups.{index}.rows"))
            for index, group in enumerate(self.groups)
        )

    @cached_property
    def body_rows(self) -> tuple[Row, ...]:
        if self.row_groups is not None:
            return tuple(row for group in self.row_groups for row in group.rows)
        return _parsed_rows(_mapped_rows(self.rows or []), self.columns, "rows")

    def row_tint_key(self, row: Row) -> str | None:
        return None if self.tint_by is None else row.first_badge(self.tint_by)

    @property
    def title_key(self) -> str:
        return next(
            column.key for kind in RICH_COLUMN_KINDS for column in self.columns if column.kind == kind
        )

    def rich_cells(self) -> Iterator[tuple[FieldPath, str, RichTextMarker]]:
        keys = [column.key for column in self.columns if column.kind in RICH_COLUMN_KINDS]
        row_sets = (
            [(("rows",), self.body_rows)]
            if self.row_groups is None
            else [(("groups", str(index), "rows"), group.rows) for index, group in enumerate(self.row_groups)]
        )
        for rows_path, rows in row_sets:
            for index, row in enumerate(rows):
                row_path = (*rows_path, str(index))
                for key in keys:
                    yield (*row_path, key), row.texts[key], RICH_PROSE
                for sub_index, subrow in enumerate(row.subrows):
                    yield (*row_path, "subrows", str(sub_index), "label"), subrow.label, RICH_TEXT

    @property
    def sum_key(self) -> str | None:
        if self.reconcile:
            return self.reconcile.column
        return self.totals.column if self.totals else None

    @property
    def totals_label_key(self) -> str | None:
        if self.totals is None:
            return None
        return next(column.key for column in self.cell_columns if column.key != self.totals.column)

    def _reconcile(self) -> None:
        if self.reconcile is None:
            return
        column = self.reconcile.column
        total = col_sum(self.body_rows, column)
        handled = self.reconcile.handled.value if self.reconcile.handled else 0
        grand = total + handled
        matches = (
            grand == self.reconcile.total
            if isinstance(total, int)
            else math.isclose(grand, self.reconcile.total, rel_tol=0.0, abs_tol=1e-6)
        )
        if not matches:
            raise PydanticCustomError(
                _RECONCILIATION_ERROR_TYPE,
                "RECONCILIATION FAILED: handled ({handled}) + {column} ({total}) = {grand}, "
                "but declared total is {declared} (off by {delta}). "
                "A category is wrong, double-counted, or missing.",
                {
                    "handled": f"{handled:,}",
                    "column": column,
                    "total": f"{total:,}",
                    "grand": f"{grand:,}",
                    "declared": f"{self.reconcile.total:,}",
                    "delta": f"{grand - self.reconcile.total:+,}",
                },
            )
