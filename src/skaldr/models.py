"""Content-file contract: the pydantic model a skaldr YAML file is validated against.

The page is `version` + `meta` + author-declared `badges` + a flat, ordered `blocks` list.
`blocks` is a discriminated union on `type`, so an unknown block type, a field from the wrong
block, or an unknown top-level key each fails with a precise `blocks.3.items.2.value`-style path.

No domain vocabulary is hardcoded here: tags/statuses live in `badges`, declared per report.
The only fixed vocabularies are the design-system primitives — tones, badge colours, and the
state glyphs for status lists and timelines.
"""

import math
import sys
from collections.abc import Iterator, Sequence
from importlib import resources
from pathlib import Path
from typing import Annotated, Any, Literal, cast, get_args

# Traversable moved to importlib.resources.abc in 3.11; on 3.10 it lives in importlib.abc.
if sys.version_info >= (3, 11):
    from importlib.resources.abc import Traversable
else:
    from importlib.abc import Traversable

import yaml
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, ValidationError, model_validator
from pydantic_core import PydanticCustomError

from skaldr.errors import ReportError

_RECONCILIATION_ERROR_TYPE = "reconciliation"


def _reject_bool_and_non_finite(value: Any) -> Any:
    """Guard numeric fields at the boundary: `bool` is an int subclass pydantic would silently
    coerce (`value: true` → 1), and `.inf`/`.nan` render as literal 'inf'/'nan'. Non-numbers pass
    through untouched so a `str` in an `int | float | str` union still validates as a string."""
    if isinstance(value, bool):
        raise ValueError("must be a number, not a boolean")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("must be a finite number")
    # A Python int is unbounded; one beyond the float range overflows any float arithmetic
    # downstream (e.g. chart axis scaling). Reject it at the boundary rather than crash later.
    if isinstance(value, int) and abs(value) > sys.float_info.max:
        raise ValueError("must be a finite number")
    return value


# Numeric field types that reject bool + non-finite before pydantic coerces them.
# Number keeps the int-vs-float distinction (a card's `600` stays an int); Count is int-only.
Number = Annotated[int | float, BeforeValidator(_reject_bool_and_non_finite)]
Count = Annotated[int, BeforeValidator(_reject_bool_and_non_finite)]

# Design-system primitives (fixed — referenced by name, never authored as values).
Tone = Literal["neutral", "info", "success", "warning", "danger", "accent"]
RowTone = Literal["muted", "danger"]  # table-row emphasis: dim a rejected row, or flag a bad one
# Row-dict keys with a reserved meaning (not column values). A column may not use one as its key.
_ROW_RESERVED_KEYS = frozenset({"subrows", "tone"})
BadgeColor = Literal["slate", "blue", "green", "amber", "red", "violet", "teal", "sky"]
CalloutTone = Literal["info", "success", "warning", "danger"]
StatusState = Literal["done", "pending", "failed", "blocked"]
TimelineState = Literal["done", "current", "pending"]
ColumnKind = Literal["text", "number", "badge", "rich", "indicator"]
ChartVariant = Literal["bar", "line", "donut"]
FlowStyle = Literal["arrow", "steps"]


def _resource(name: str) -> Traversable:
    return resources.files("skaldr").joinpath(name)


def package_text(name: str) -> str:
    """Text of a bundled package resource (the stylesheet, a template)."""
    return _resource(name).read_text(encoding="utf-8")


def package_path(name: str) -> Path:
    """Filesystem path to a bundled resource. skaldr wheels install unzipped, so this resolves
    to a real path (suitable for reading or copying a bundled file, e.g. the skill dir)."""
    return Path(str(_resource(name)))


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Badge(_Frozen):
    label: str = Field(description="Chip text for this tag/status.")
    tone: BadgeColor = Field(description="Chip colour, chosen from the badge palette.")
    legend: str = Field(description="One-line meaning, shown in the derived legend.")


class Meta(_Frozen):
    title: str = Field(description="Page title (h1).")
    subtitle: list[str] = Field(default_factory=list, description="Subtitle lines under the title.")
    source: str | None = Field(default=None, description="Provenance; feeds the footer.")
    date: str | None = Field(default=None, description="Report date; feeds the footer (never auto-now).")
    toc: bool = Field(default=False, description="Render a table of contents from level-2 headings.")
    width: Literal["default", "wide", "full"] = Field(
        default="default",
        description="Page width cap: default (1600px), wide (1920px), or full (fill the window).",
    )
    hero: bool = Field(
        default=False,
        description="Opt-in hero header: a larger display title + subtitle in a tinted band, for a page "
        "that opens by selling an idea rather than a plain report header.",
    )


class Heading(_Frozen):
    type: Literal["heading"]
    text: str = Field(min_length=1, description="Heading text; also the TOC entry at level 2.")
    level: Literal[2, 3] = Field(default=2, description="Heading level: 2 (section) or 3 (sub-heading).")

    @model_validator(mode="after")
    def _non_blank(self) -> "Heading":
        if not self.text.strip():
            raise ValueError("heading text must not be blank")
        return self


class Text(_Frozen):
    type: Literal["text"]
    body: str = Field(description="Rich-text prose; blank lines split paragraphs.")
    muted: bool = Field(default=False, description="Render in the caption colour, for asides.")


class ListBlock(_Frozen):
    type: Literal["list"]
    style: Literal["bullet", "number"] = Field(default="bullet", description="Bulleted or numbered.")
    items: list[str] = Field(min_length=1, description="Rich-text points; no nesting.")


class Fact(_Frozen):
    label: str = Field(description="Fact label (e.g. 'Source').")
    value: str = Field(description="Fact value (e.g. 'prod').")


class FactStrip(_Frozen):
    type: Literal["fact_strip"]
    facts: list[Fact] = Field(min_length=1, max_length=8, description="1-8 label/value pairs, one line.")


class KVPair(_Frozen):
    label: str = Field(description="Row label (muted).")
    value: str = Field(description="Rich-text value.")


class KeyValue(_Frozen):
    type: Literal["key_value"]
    pairs: list[KVPair] = Field(min_length=1, description="Vertical label/value metadata rows.")


class Card(_Frozen):
    label: str = Field(description="Card label above the number.")
    value: Number | str = Field(description="Headline number, or a short status string.")
    of: Number | None = Field(default=None, description="Denominator; renders a derived percentage.")
    tone: Tone | None = Field(default=None, description="Optional tone for the top-border accent.")
    note: str | None = Field(default=None, description="Optional small caption line under the number.")
    badges: list[str] = Field(
        default_factory=list,
        description="Declared badge keys (from the page `badges`) to chip onto this card.",
    )

    @model_validator(mode="after")
    def _of_requires_positive_numeric_value(self) -> "Card":
        if self.of is not None:
            if isinstance(self.value, str):
                raise ValueError("'of' requires a numeric 'value'")
            if self.of <= 0:
                raise ValueError("'of' must be greater than 0")
        return self


class Cards(_Frozen):
    type: Literal["cards"]
    items: list[Card] = Field(min_length=1, description="Headline-number cards, laid out full-width.")


class BadgeRef(_Frozen):
    key: str = Field(description="A key declared in the page `badges`.")


class BadgeLiteral(_Frozen):
    label: str = Field(description="Chip text for a one-off badge (not from the page vocabulary).")
    tone: BadgeColor = Field(description="Chip colour from the badge palette.")


class BadgeRow(_Frozen):
    type: Literal["badge_row"]
    label: str | None = Field(default=None, description="Optional leading label (e.g. 'Affects:').")
    items: list[BadgeRef | BadgeLiteral] = Field(
        min_length=1, description="Chips: page-vocabulary refs or one-off label+tone pairs."
    )


class Callout(_Frozen):
    type: Literal["callout"]
    tone: CalloutTone = Field(description="Accent + tint tone: info, success, warning, or danger.")
    title: str | None = Field(default=None, description="Optional bold title line in the tone colour.")
    body: str = Field(description="Rich-text body.")


class StatusItem(_Frozen):
    state: StatusState = Field(description="Step state, driving the glyph: done, pending, failed, blocked.")
    text: str = Field(description="Rich-text label for the step.")


class StatusList(_Frozen):
    type: Literal["status_list"]
    items: list[StatusItem] = Field(min_length=1, description="Steps/checks with a coloured state glyph.")


class MeterItem(_Frozen):
    label: str = Field(description="Bar label.")
    value: Number = Field(description="Filled amount (0 ≤ value ≤ max).")
    max: Number = Field(description="Bar maximum (> 0); the denominator for the derived percentage.")
    tone: Tone | None = Field(default=None, description="Optional tone for the bar fill.")

    @model_validator(mode="after")
    def _bounds(self) -> "MeterItem":
        if self.max <= 0:
            raise ValueError("'max' must be greater than 0")
        if not (0 <= self.value <= self.max):
            raise ValueError("'value' must be between 0 and 'max'")
        return self


class Meter(_Frozen):
    type: Literal["meter"]
    items: list[MeterItem] = Field(min_length=1, description="Labelled horizontal bars.")


class Code(_Frozen):
    type: Literal["code"]
    content: str = Field(description="Code/log/config text; rendered verbatim, no highlighting.")
    label: str | None = Field(default=None, description="Optional label header above the block.")
    mode: Literal["plain", "diff"] = Field(
        default="plain", description="plain, or diff (+/- lines tinted success/danger)."
    )


class Quote(_Frozen):
    type: Literal["quote"]
    body: str = Field(description="Rich-text quotation.")
    cite: str | None = Field(default=None, description="Optional attribution line.")


class Image(_Frozen):
    type: Literal["image"]
    src: str = Field(
        description="A data: URI (self-contained — no external fetches). Base64-encode the payload "
        "(e.g. data:image/svg+xml;base64,...); a raw, unencoded SVG isn't a valid URI and won't render."
    )
    alt: str = Field(description="Alt text for the image.")
    caption: str | None = Field(default=None, description="Optional caption shown below the image.")
    max_width: Count | None = Field(default=None, description="Optional max width in pixels.")

    @model_validator(mode="after")
    def _data_uri_only(self) -> "Image":
        if not self.src.startswith("data:"):
            raise ValueError("'src' must be a data: URI")
        return self


class TimelineItem(_Frozen):
    time: str | None = Field(default=None, description="Optional timestamp/label for the entry.")
    title: str = Field(description="Entry title.")
    body: str | None = Field(default=None, description="Optional rich-text detail.")
    state: TimelineState | None = Field(
        default=None, description="Optional dot state: done, current, pending."
    )
    badges: list[str] = Field(
        default_factory=list,
        description="Declared badge keys (from the page `badges`) to chip onto this entry.",
    )


class Timeline(_Frozen):
    type: Literal["timeline"]
    items: list[TimelineItem] = Field(min_length=1, description="Ordered entries with state-coloured dots.")


class FlowStep(_Frozen):
    label: str = Field(min_length=1, description="Short stage name — the node label.")
    tone: Tone | None = Field(
        default=None, description="Optional tone accent for this node's border + number."
    )
    note: str | None = Field(
        default=None,
        description="Optional one-line detail (rich text). Shown as the caption in `steps` style, and as a "
        "small sub-line in `arrow` style. If most nodes need a note, prefer style: steps.",
    )
    badges: list[str] = Field(
        default_factory=list,
        description="Declared badge keys (from the page `badges`) to chip onto this node.",
    )

    @model_validator(mode="after")
    def _non_blank(self) -> "FlowStep":
        if not self.label.strip():
            raise ValueError("flow step label must not be blank")
        return self


class Flow(_Frozen):
    type: Literal["flow"]
    steps: list[FlowStep] = Field(
        min_length=2, description="Ordered stages (2+); a flow needs two or more nodes."
    )
    style: FlowStyle = Field(
        default="arrow",
        description="arrow (default): short-labelled nodes joined by → connectors — reach for it when the "
        "DIRECTION between stages is the message (a pipeline or a data flow). steps: equal cards that each "
        "carry a caption line — reach for it when every stage needs a sentence of explanation.",
    )
    loop: bool = Field(
        default=False,
        description="Draw a '↺ back to <first>' return marker after the last node — for a cycle, "
        "not a one-way pipeline.",
    )
    numbered: bool = Field(
        default=True, description="Number the nodes 1..n (derived); set false to hide numbers."
    )


class ChartSeries(_Frozen):
    label: str = Field(min_length=1, description="Series name — shown in the legend.")
    values: list[Number] = Field(
        min_length=1, description="One value per category, in the same order as `categories`."
    )
    tone: Tone | None = Field(default=None, description="Optional tone for this series' bars/line.")


class ChartSlice(_Frozen):
    label: str = Field(min_length=1, description="Slice name — shown in the legend.")
    value: Number = Field(description="Slice magnitude (> 0); its share of the whole is derived.")
    tone: Tone | None = Field(default=None, description="Optional tone for this slice.")


class Chart(_Frozen):
    type: Literal["chart"]
    variant: ChartVariant = Field(
        description="bar: compare a value across categories (grouped, or set stacked). "
        "line: a trend across an ordered axis (smoothed). "
        "donut: parts of a whole. Reach for a chart when a number's SHAPE (trend/spread/share) is the "
        "message; use `cards` for standalone figures and `meter` for a single ratio."
    )
    title: str | None = Field(default=None, description="Optional caption shown above the chart.")
    categories: list[str] = Field(
        default_factory=list,
        description="x-axis labels, left to right (bar/line only); each series has one value per category.",
    )
    series: list[ChartSeries] = Field(
        default_factory=list[ChartSeries],
        description="One or more data series (bar/line only). Multiple series group side by side, or stack.",
    )
    slices: list[ChartSlice] = Field(
        default_factory=list[ChartSlice],
        description="Donut segments (donut only); shares are derived from the total.",
    )
    stacked: bool = Field(
        default=False,
        description="Stack the bar series into one bar per category instead of grouping (bar only).",
    )

    @model_validator(mode="after")
    def _shape(self) -> "Chart":
        if self.stacked and self.variant != "bar":
            raise ValueError("'stacked' applies only to variant: bar")
        if self.variant in ("bar", "line"):
            if self.slices:
                raise ValueError("'slices' is only for variant: donut")
            if not self.categories:
                raise ValueError(f"variant '{self.variant}' needs 'categories'")
            if not self.series:
                raise ValueError(f"variant '{self.variant}' needs at least one entry in 'series'")
            for entry in self.series:
                if len(entry.values) != len(self.categories):
                    raise ValueError(
                        f"series '{entry.label}' has {len(entry.values)} values but there are "
                        f"{len(self.categories)} categories — they must match"
                    )
                # Bars/lines measure up from a zero baseline (no negative axis) — a negative value
                # would draw an invalid or below-axis mark. Mirror the donut/meter positivity guard.
                if any(value < 0 for value in entry.values):
                    raise ValueError(
                        f"series '{entry.label}' has a negative value; bar/line values must be >= 0"
                    )
        else:  # donut
            if self.categories or self.series:
                raise ValueError("'categories'/'series' are for variant: bar/line, not donut")
            if not self.slices:
                raise ValueError("variant 'donut' needs at least one entry in 'slices'")
            for segment in self.slices:
                if segment.value <= 0:
                    raise ValueError(f"donut slice '{segment.label}' value must be greater than 0")
        return self


class Column(_Frozen):
    key: str = Field(description="Row-dict key this column reads.")
    label: str = Field(description="Column header text.")
    kind: ColumnKind = Field(
        description="text/rich (first one becomes the title column), number, badge (chip under title), "
        "or indicator (a colour-only dot in its own column; the cell value is a tone name)."
    )
    pct_of_total: bool = Field(
        default=False, description="Show a derived '% of total' caption (needs a reconcile total)."
    )
    width: Count | None = Field(
        default=None,
        ge=1,
        le=6,
        description="Proportional width weight (1-6); set it on every non-badge column, or none.",
    )


class Handled(_Frozen):
    label: str = Field(description="Label for the non-issue bucket (e.g. 'Imported cleanly').")
    value: Count = Field(description="Count in the bucket; added to the column sum for reconciliation.")


class Reconcile(_Frozen):
    total: Count = Field(gt=0, description="Denominator; the column sum + handled must equal this.")
    column: str = Field(description="Key of the number column that must sum to `total`.")
    handled: Handled | None = Field(default=None, description="A bucket outside the rows.")


class Totals(_Frozen):
    column: str = Field(description="Key of the number column to sum into a footer row.")


def col_sum(rows: Sequence[dict[str, Any]], key: str) -> float:
    """Sum a number column's raw values (ints stay ints; floats are not truncated)."""
    return sum(row[key] for row in rows)


def _validate_rows(rows: Sequence[dict[str, Any]], columns: Sequence[Column], loc: str) -> None:
    keys = {column.key for column in columns}
    for index, row in enumerate(rows):
        present = set(row) - _ROW_RESERVED_KEYS
        missing = keys - present
        extra = present - keys
        if missing:
            raise ValueError(f"{loc}.{index}: missing column value(s): {sorted(missing)}")
        if extra:
            raise ValueError(f"{loc}.{index}: unknown key(s): {sorted(extra)}")
        row_tone = row.get("tone")
        if row_tone is not None and row_tone not in get_args(RowTone):
            raise ValueError(f"{loc}.{index}.tone: row tone must be 'muted' or 'danger'")
        for column in columns:
            value = row[column.key]
            if column.kind == "number":
                if isinstance(value, bool) or not isinstance(value, int | float):
                    raise ValueError(f"{loc}.{index}.{column.key}: number column needs a numeric value")
                if not math.isfinite(value):
                    raise ValueError(f"{loc}.{index}.{column.key}: number column must be finite")
            else:
                if not isinstance(value, str):
                    raise ValueError(f"{loc}.{index}.{column.key}: {column.kind} column needs a string value")
                # An indicator value is validated to an exact Tone here (or blank), so the rendered
                # `<span class="dot {value}">` class is always a known tone.
                if column.kind == "indicator" and value.strip() and value not in get_args(Tone):
                    raise ValueError(
                        f"{loc}.{index}.{column.key}: indicator value must be a tone name "
                        "(neutral·info·success·warning·danger·accent) or blank"
                    )
        raw_subrows = row.get("subrows")
        if raw_subrows is not None:
            if not isinstance(raw_subrows, list):
                raise ValueError(f"{loc}.{index}.subrows: must be a list")
            for sub_index, raw_subrow in enumerate(cast("list[Any]", raw_subrows)):
                sub_loc = f"{loc}.{index}.subrows.{sub_index}"
                if not isinstance(raw_subrow, dict) or set(cast("dict[str, Any]", raw_subrow)) != {
                    "label",
                    "value",
                }:
                    raise ValueError(f"{sub_loc}: must be {{label, value}}")
                subrow = cast("dict[str, Any]", raw_subrow)
                if not isinstance(subrow["label"], str):
                    raise ValueError(f"{sub_loc}.label: must be a string")
                sub_value = subrow["value"]
                if isinstance(sub_value, bool) or not isinstance(sub_value, int | float | str):
                    raise ValueError(f"{sub_loc}.value: must be a number or string")
                if isinstance(sub_value, float) and not math.isfinite(sub_value):
                    raise ValueError(f"{sub_loc}.value: number must be finite")


class Group(_Frozen):
    name: str = Field(description="Group band label; shows the derived subtotal.")
    rows: list[dict[str, Any]] = Field(
        default_factory=list[dict[str, Any]], description="Empty renders a '— none —' row."
    )


class Table(_Frozen):
    type: Literal["table"]
    columns: list[Column] = Field(min_length=1, description="Column specs; at least one text/rich column.")
    groups: list[Group] | None = Field(
        default=None, description="Grouped rows with derived subtotals; provide this OR `rows`, not both."
    )
    rows: list[dict[str, Any]] | None = Field(
        default=None, description="Ungrouped rows; provide this OR `groups`, not both."
    )
    reconcile: Reconcile | None = Field(default=None, description="Opt-in trust check on a number column.")
    totals: Totals | None = Field(default=None, description="Sum a number column into a footer row.")

    @model_validator(mode="after")
    def _validate_table(self) -> "Table":
        if (self.groups is None) == (self.rows is None):
            raise ValueError("provide exactly one of 'groups' or 'rows'")
        if not any(column.kind in ("text", "rich") for column in self.columns):
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
        badge_widths = [c.key for c in self.columns if c.kind == "badge" and c.width is not None]
        if badge_widths:
            raise ValueError(f"badge column(s) {badge_widths} can't take a width (rendered under the title)")
        non_badge = [column for column in self.columns if column.kind != "badge"]
        widthed = [column for column in non_badge if column.width is not None]
        if widthed and len(widthed) != len(non_badge):
            raise ValueError("set width on every non-badge column, or none")
        if self.groups is not None:
            for group_index, group in enumerate(self.groups):
                _validate_rows(group.rows, self.columns, f"groups.{group_index}.rows")
        if self.rows is not None:
            _validate_rows(self.rows, self.columns, "rows")
        self._reconcile()
        return self

    def all_rows(self) -> list[dict[str, Any]]:
        if self.groups is not None:
            return [row for group in self.groups for row in group.rows]
        return self.rows or []

    def _reconcile(self) -> None:
        if self.reconcile is None:
            return
        column = self.reconcile.column
        total = col_sum(self.all_rows(), column)
        handled = self.reconcile.handled.value if self.reconcile.handled else 0
        grand = total + handled
        # Exact when the column is integer-valued (the norm) — the "off by even one" guarantee must
        # hold at any magnitude. A fixed abs_tol absorbs IEEE-754 noise only when floats are present;
        # a rel_tol would widen the slack with the total and silently pass real discrepancies at scale.
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


_Leaf = (
    Heading
    | Text
    | ListBlock
    | FactStrip
    | KeyValue
    | Cards
    | BadgeRow
    | Callout
    | StatusList
    | Meter
    | Table
    | Code
    | Quote
    | Image
    | Timeline
    | Flow
    | Chart
)
InnerBlock = Annotated[_Leaf, Field(discriminator="type")]


class Section(_Frozen):
    type: Literal["section"]
    title: str = Field(description="Summary label shown on the collapsible.")
    collapsed: bool = Field(default=True, description="Whether the section starts collapsed.")
    blocks: list[InnerBlock] = Field(min_length=1, description="Blocks; no nested section.")


# Grid: a bounded side-by-side layout over a 6-column base.
# Nesting is capped at depth 2 by the type graph: a top-level GridCell may hold nested InnerGrids,
# whose cells hold only leaf blocks — so a depth-3 grid is unrepresentable. `span` is required
# (not auto-distributed) and cell spans in a grid sum to at most 6 (trailing space allowed).
# A grid nests only within a grid; `section` stays a leaf-only container and the two do not mix.


class InnerGridCell(_Frozen):
    span: Count = Field(ge=1, le=6, description="Columns this cell spans, of 6.")
    blocks: list[InnerBlock] = Field(min_length=1, description="Leaf blocks stacked in the cell.")
    tone: Tone | None = Field(
        default=None,
        description="Optional tone: turns the cell into an emphasis panel (accent top-border + tint). "
        "Use `neutral` for a muted aside, `accent`/`success` for a primary panel.",
    )


class InnerGrid(_Frozen):
    type: Literal["grid"]
    cells: list[InnerGridCell] = Field(min_length=1, description="Cells across the 6-column row.")

    @model_validator(mode="after")
    def _spans_fit(self) -> "InnerGrid":
        _check_span_sum(self.cells)
        return self


CellBlock = Annotated[_Leaf | InnerGrid, Field(discriminator="type")]


class GridCell(_Frozen):
    span: Count = Field(ge=1, le=6, description="Columns this cell spans, of 6.")
    blocks: list[CellBlock] = Field(
        min_length=1, description="Blocks stacked in the cell; may include nested grids (depth 2 max)."
    )
    tone: Tone | None = Field(
        default=None,
        description="Optional tone: turns the cell into an emphasis panel (accent top-border + tint). "
        "Use `neutral` for a muted aside, `accent`/`success` for a primary panel.",
    )


class Grid(_Frozen):
    type: Literal["grid"]
    cells: list[GridCell] = Field(min_length=1, description="Cells across a 6-column row.")

    @model_validator(mode="after")
    def _spans_fit(self) -> "Grid":
        _check_span_sum(self.cells)
        return self


def _check_span_sum(cells: Sequence[GridCell | InnerGridCell]) -> None:
    total = sum(cell.span for cell in cells)
    if total > 6:
        raise ValueError(f"cell spans sum to {total}; must total at most 6")


Block = Annotated[_Leaf | Section | Grid, Field(discriminator="type")]
# Every node the tree-walkers (badge/heading/table recursion) may descend into.
AnyBlock = _Leaf | Section | Grid | InnerGrid


def iter_referenced_badge_keys(blocks: Sequence[AnyBlock]) -> Iterator[str]:
    """Every badge key referenced anywhere in the block tree (recursing into sections and grids).

    Single source of truth for both validation (undeclared keys) and the derived legend.
    """
    for block in blocks:
        if isinstance(block, Section):
            yield from iter_referenced_badge_keys(block.blocks)
        elif isinstance(block, (Grid, InnerGrid)):
            for cell in block.cells:
                yield from iter_referenced_badge_keys(cell.blocks)
        elif isinstance(block, BadgeRow):
            yield from (item.key for item in block.items if isinstance(item, BadgeRef))
        elif isinstance(block, Cards):
            for card in block.items:
                yield from card.badges
        elif isinstance(block, Timeline):
            for item in block.items:
                yield from item.badges
        elif isinstance(block, Flow):
            for step in block.steps:
                yield from step.badges
        elif isinstance(block, Table):
            badge_columns = [column.key for column in block.columns if column.kind == "badge"]
            for row in block.all_rows():
                for key in badge_columns:
                    value = row.get(key)
                    # A blank badge cell is an opt-out (no chip on that row), not a reference.
                    if isinstance(value, str) and value.strip():
                        yield value


class Report(_Frozen):
    version: Literal[1] = Field(description="Content-file schema version.")
    meta: Meta
    badges: dict[str, Badge] = Field(
        default_factory=dict, description="Author-declared tag/status vocabulary."
    )
    blocks: list[Block] = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_badge_references(self) -> "Report":
        bad = sorted({key for key in iter_referenced_badge_keys(self.blocks) if key not in self.badges})
        if bad:
            raise ValueError(f"badge key(s) not declared in `badges`: {bad} (add them to the badges map)")
        return self


def _format_validation_error(error: ValidationError) -> str:
    issues = error.errors()
    for issue in issues:
        if issue["type"] == _RECONCILIATION_ERROR_TYPE:
            return issue["msg"]
    lines: list[str] = []
    for issue in issues:
        location = ".".join(str(part) for part in issue["loc"])
        lines.append(f"{location}: {issue['msg']}" if location else issue["msg"])
    return "invalid content data: " + "; ".join(lines)


def read_text_file(path: Path) -> str:
    if not path.exists():
        raise ReportError(f"file not found: {path}")
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as err:
        raise ReportError(f"could not read {path}: {err}") from err


def parse_report(data: Any) -> Report:
    try:
        return Report.model_validate(data)
    except ValidationError as err:
        raise ReportError(_format_validation_error(err)) from err


def load_report(path: Path) -> Report:
    try:
        data = yaml.safe_load(read_text_file(path))
    except yaml.YAMLError as err:
        raise ReportError(f"invalid YAML in {path}: {err}") from err
    return parse_report(data)
