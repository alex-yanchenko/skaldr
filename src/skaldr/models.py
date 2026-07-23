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
from collections import Counter
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
from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StrictBool,
    ValidationError,
    field_validator,
    model_validator,
)
from pydantic_core import PydanticCustomError

from skaldr.errors import ReportError

_RECONCILIATION_ERROR_TYPE = "reconciliation"
# URL schemes safe to emit into an href — the one gate for every author-supplied link (markdown
# links in render.py and reference `url`s here), so a `javascript:`/`data:text/html:` link can't ship.
ALLOWED_URL_SCHEMES = ("http://", "https://", "mailto:")


def _require_url_scheme(url: str | None, subject: str) -> None:
    """Raise if an author-supplied `url` isn't an allowed scheme. Shared by every model with a link
    field so the gate (and message) can't drift; `subject` names the field in the error."""
    if url is not None and not url.startswith(ALLOWED_URL_SCHEMES):
        raise ValueError(f"{subject} must be an http://, https://, or mailto: link")


# A reference key must be a safe HTML id/fragment and match the inline `[^key]` marker regex in
# render.py; both derive from this one class so key-validation and marker-matching can't drift.
REFERENCE_KEY_PATTERN = r"[A-Za-z0-9_-]+"

# An author-assigned heading/section anchor id: lowercase, hyphen-separated, same shape the auto-slug
# produces (`_slugify` in compute.py) so a hand-written id and a generated one are indistinguishable
# as a `#link` target, and no id can introduce a character the auto-slugger never would.
ANCHOR_ID_PATTERN = r"[a-z0-9]+(?:-[a-z0-9]+)*"


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

# One palette, two vocabularies. Semantic tones (info/success/…) and badge colours (blue/green/…) name
# the SAME eight colours — the six overlapping pairs share their tokens exactly, plus teal/sky which have
# a palette name only. An author may write either name wherever a tone or a badge colour is taken; these
# maps normalise each input to its field's canonical spelling before the Literal validates, so a `tone:
# green` (or a badge `tone: success`) just works instead of failing. teal/sky pass through unchanged.
_PALETTE_TO_TONE = {
    "slate": "neutral",
    "blue": "info",
    "green": "success",
    "amber": "warning",
    "red": "danger",
    "violet": "accent",
}
_TONE_TO_PALETTE = {tone: palette for palette, tone in _PALETTE_TO_TONE.items()}


def _to_tone(value: Any) -> Any:
    """Normalise a palette colour name to its semantic tone twin (green → success); pass anything else
    through unchanged (semantic names, teal/sky, non-strings)."""
    return _PALETTE_TO_TONE.get(value, value) if isinstance(value, str) else value


def _to_badge_color(value: Any) -> Any:
    """Normalise a semantic tone name to its palette colour twin (success → green); pass anything else
    through unchanged (palette names, teal/sky, non-strings)."""
    return _TONE_TO_PALETTE.get(value, value) if isinstance(value, str) else value


def _tone_names(tone_type: Any) -> tuple[str, ...]:
    """The canonical string values of a tone Literal wrapped in Annotated[Literal[...], validator] —
    for the manually-validated tones (table row + indicator cell) that aren't plain typed fields."""
    return get_args(get_args(tone_type)[0])


# Design-system primitives (fixed — referenced by name, never authored as values). Tone is the eight
# colours by their semantic name (+ teal/sky, palette-only); BadgeColor is the same eight by palette name.
Tone = Annotated[
    Literal["neutral", "info", "success", "warning", "danger", "accent", "teal", "sky"],
    BeforeValidator(_to_tone),
]
RowTone = Annotated[
    Literal["muted", "danger"], BeforeValidator(_to_tone)
]  # row emphasis: dim a rejected row, or flag a bad one (red aliases to danger)
# Row-dict keys with a reserved meaning (not column values). A column may not use one as its key.
_ROW_RESERVED_KEYS = frozenset({"subrows", "tone"})
BadgeColor = Annotated[
    Literal["slate", "blue", "green", "amber", "red", "violet", "teal", "sky"],
    BeforeValidator(_to_badge_color),
]
CalloutTone = Annotated[Literal["info", "success", "warning", "danger"], BeforeValidator(_to_tone)]
StatusState = Literal["done", "current", "pending", "failed", "blocked"]
TimelineState = Literal["done", "current", "pending"]
ColumnKind = Literal["text", "number", "badge", "rich", "indicator"]
ColumnPlacement = Literal["title", "cell"]  # where a badge column's chip renders
ChartVariant = Literal["bar", "line", "donut"]
FlowStyle = Literal["arrow", "steps"]
FanDirection = Literal["in", "out"]
SwimlaneStepState = Literal["normal", "low", "blocked"]  # ticket emphasis: normal / low-pri / blocked


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


class _Block(_Frozen):
    """Base for every top-level/section block. Carries the one width primitive: `span`, how many of
    the 6 content columns the block occupies. It is width only; blocks still stack vertically (one per
    row). To place several blocks in a single row, use a `grid` (whose cells carry their own span)."""

    span: Count | None = Field(
        default=None,
        ge=1,
        le=6,
        description="Block width in content columns (1 to 6); omit for full width. Same column-count "
        "vocabulary as a grid cell's span, relative to the block's container (the page, or the "
        "enclosing grid cell when nested). Width only: blocks still stack vertically; use a `grid` to "
        "put several in one row.",
    )


class Badge(_Frozen):
    label: str = Field(description="Chip text for this tag/status.")
    tone: BadgeColor = Field(
        description="Chip colour — a palette name (slate/blue/…) or its semantic tone twin (neutral/info/…)."
    )
    legend: str = Field(description="One-line meaning, shown in the derived legend.")


class Meta(_Frozen):
    title: str = Field(description="Page title (h1).")
    subtitle: list[str] = Field(default_factory=list, description="Subtitle lines under the title.")
    source: str | None = Field(default=None, description="Provenance; feeds the footer.")
    date: str | None = Field(default=None, description="Report date; feeds the footer (never auto-now).")
    updated: str | None = Field(
        default=None,
        description="When the report was last revised; feeds the footer as 'updated <value>'. A "
        "free-form label like the date (author it — never auto-now).",
    )
    toc: bool = Field(
        default=False, description="Render a table of contents from top-level level-2 headings and sections."
    )
    hero: bool = Field(
        default=False,
        description="Opt-in hero header: a larger display title + subtitle in a tinted band, for a page "
        "that opens by selling an idea rather than a plain report header.",
    )


class Heading(_Block):
    type: Literal["heading"]
    text: str = Field(min_length=1, description="Heading text; also the TOC entry at level 2.")
    level: Literal[2, 3] = Field(
        default=2, description="Heading level: 2 (major heading) or 3 (sub-heading)."
    )
    id: str | None = Field(
        default=None,
        pattern=rf"^{ANCHOR_ID_PATTERN}$",
        description="Optional stable anchor id (lowercase, hyphen-separated). Overrides the text-derived "
        "slug so `[…](#id)` links survive a heading rename. Must be unique across the page.",
    )

    @model_validator(mode="after")
    def _non_blank(self) -> "Heading":
        if not self.text.strip():
            raise ValueError("heading text must not be blank")
        return self


class Text(_Block):
    type: Literal["text"]
    body: str = Field(description="Rich-text prose; blank lines split paragraphs.")
    muted: bool = Field(default=False, description="Render in the caption colour, for asides.")


_MAX_LIST_DEPTH = 4


class ListItem(_Frozen):
    text: str = Field(min_length=1, description="The point's rich-text content.")
    items: list["str | ListItem"] = Field(
        default=[],
        description="Optional nested sub-points, rendered as an indented list in the parent's style.",
    )


def _check_list_depth(items: list["str | ListItem"], depth: int) -> None:
    """Reject list nesting deeper than `_MAX_LIST_DEPTH` — past that a bullet tree is unreadable and
    almost always a data-shape mistake. Depth 1 is the top-level list; each nested `items` is +1."""
    if depth > _MAX_LIST_DEPTH:
        raise ValueError(f"list nesting exceeds the maximum depth of {_MAX_LIST_DEPTH}")
    for item in items:
        if isinstance(item, ListItem):
            _check_list_depth(item.items, depth + 1)


class ListBlock(_Block):
    type: Literal["list"]
    style: Literal["bullet", "number"] = Field(default="bullet", description="Bulleted or numbered.")
    items: list[str | ListItem] = Field(
        min_length=1,
        description="Rich-text points. A point is a plain string, or `{text, items: [...]}` to nest "
        f"sub-points (nested lists inherit the parent's style; up to {_MAX_LIST_DEPTH} levels deep).",
    )

    @model_validator(mode="after")
    def _bounded_depth(self) -> "ListBlock":
        _check_list_depth(self.items, 1)
        return self


class Fact(_Frozen):
    label: str = Field(description="Fact label (e.g. 'Source').")
    value: str = Field(description="Fact value (e.g. 'prod').")


class FactStrip(_Block):
    type: Literal["fact_strip"]
    facts: list[Fact] = Field(min_length=1, max_length=8, description="1-8 label/value pairs, one line.")


class KVPair(_Frozen):
    label: str = Field(description="Row label (muted).")
    value: str = Field(description="Rich-text value.")


class KeyValue(_Block):
    type: Literal["key_value"]
    pairs: list[KVPair] = Field(min_length=1, description="Vertical label/value metadata rows.")


class CardDelta(_Frozen):
    label: str = Field(min_length=1, description="Delta text shown beside the value, e.g. '+12%' or '0.3s'.")
    direction: Literal["up", "down", "flat"] | None = Field(
        default=None, description="Optional glyph before the label: ▲ up, ▼ down, → flat."
    )
    tone: Tone | None = Field(
        default=None,
        description="Delta colour — YOU set it: up isn't always good (down is good for cost/errors), so "
        "skaldr never infers it. Omit for a neutral chip.",
    )


class Card(_Frozen):
    label: str = Field(description="Card label above the number.")
    value: Number | str = Field(description="Headline number, or a short status string.")
    of: Number | None = Field(default=None, description="Denominator; renders a derived percentage.")
    tone: Tone | None = Field(default=None, description="Optional tone for the top-border accent.")
    delta: CardDelta | None = Field(
        default=None, description="Optional trend chip beside the value (a period-over-period change)."
    )
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


class Cards(_Block):
    type: Literal["cards"]
    items: list[Card] = Field(min_length=1, description="Headline-number cards, laid out full-width.")


class BadgeRef(_Frozen):
    key: str = Field(description="A key declared in the page `badges`.")


class BadgeLiteral(_Frozen):
    label: str = Field(description="Chip text for a one-off badge (not from the page vocabulary).")
    tone: BadgeColor = Field(
        description="Chip colour — a palette name (slate/blue/…) or its semantic tone twin."
    )


class BadgeGroup(_Frozen):
    label: str = Field(min_length=1, description="Group label, shown in the row's gutter.")
    items: list[BadgeRef | BadgeLiteral] = Field(
        min_length=1, description="Chips in this group: page-vocabulary refs or one-off label+tone pairs."
    )


class BadgeRow(_Block):
    type: Literal["badge_row"]
    label: str | None = Field(
        default=None, description="Optional leading label (e.g. 'Affects:') for a flat `items` row."
    )
    items: list[BadgeRef | BadgeLiteral] = Field(
        default_factory=list[BadgeRef | BadgeLiteral],
        description="A flat row of chips: page-vocabulary refs or one-off label+tone pairs. Use this OR "
        "`groups`, not both.",
    )
    groups: list[BadgeGroup] = Field(
        default_factory=list[BadgeGroup],
        description="Grouped chips — each group renders as a labelled gutter row. Use this OR `items`, "
        "not both.",
    )

    @model_validator(mode="after")
    def _one_source(self) -> "BadgeRow":
        # items/groups default to [] (never None), so truthiness — not `is None` — distinguishes them.
        if bool(self.items) == bool(self.groups):
            raise ValueError("a badge row needs exactly one of 'items' or 'groups'")
        if self.groups and self.label is not None:
            raise ValueError("badge row 'label' applies to a flat 'items' row, not 'groups'")
        return self


class Callout(_Block):
    type: Literal["callout"]
    tone: CalloutTone = Field(
        description="Accent + tint: info/success/warning/danger (blue/green/amber/red alias in)."
    )
    title: str | None = Field(default=None, description="Optional bold title line in the tone colour.")
    body: str = Field(description="Rich-text body.")


class StatusItem(_Frozen):
    state: StatusState = Field(
        description="Step state, driving the glyph: done, current (in progress), pending, failed, blocked."
    )
    text: str = Field(description="Rich-text label for the step.")


class StatusList(_Block):
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


class Meter(_Block):
    type: Literal["meter"]
    items: list[MeterItem] = Field(min_length=1, description="Labelled horizontal bars.")


class RangeSegment(_Frozen):
    label: str = Field(min_length=1, description="Label shown inside the segment.")
    span: Number = Field(
        description="Relative width (> 0). Spans are normalised across the segments, so only the "
        "ratios matter — [3, 1] and [30, 10] render identically."
    )
    tone: Tone | None = Field(
        default=None, description="Soft-tint fill + text colour for the segment (defaults to neutral)."
    )
    sub: str | None = Field(default=None, description="Optional rich-text sub-line under the label.")

    @model_validator(mode="after")
    def _shape(self) -> "RangeSegment":
        if not self.label.strip():
            raise ValueError("range segment label must not be blank")
        if self.span <= 0:
            raise ValueError("segment 'span' must be greater than 0")
        return self


class RangeAxis(_Frozen):
    min: str | None = Field(default=None, description="Label at the left end of the bar (e.g. a start year).")
    max: str | None = Field(default=None, description="Label at the right end of the bar (e.g. an end year).")

    @model_validator(mode="after")
    def _at_least_one(self) -> "RangeAxis":
        if not (self.min or "").strip() and not (self.max or "").strip():
            raise ValueError("range axis needs at least one of 'min' or 'max'")
        return self


class Range(_Block):
    type: Literal["range"]
    segments: list[RangeSegment] = Field(
        min_length=1, description="Segments laid left-to-right, each sized in proportion to its span."
    )
    axis: RangeAxis | None = Field(
        default=None, description="Optional end-cap labels marking the bar's extent."
    )


class Code(_Block):
    type: Literal["code"]
    content: str = Field(description="Code/log/config text; rendered verbatim, no highlighting.")
    label: str | None = Field(default=None, description="Optional label header above the block.")
    mode: Literal["plain", "diff"] = Field(
        default="plain", description="plain, or diff (+/- lines tinted success/danger)."
    )


class Quote(_Block):
    type: Literal["quote"]
    body: str = Field(description="Rich-text quotation.")
    cite: str | None = Field(default=None, description="Optional attribution line.")


class Image(_Block):
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


class Timeline(_Block):
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
    points: list[str] = Field(
        default_factory=list,
        description="Optional detail bullets (rich text) under the node, for when one line isn't enough. "
        "Render below the note. Best paired with style: steps — a few bullets crowd a compact arrow chip.",
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


class Flow(_Block):
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


class Fan(_Block):
    type: Literal["fan"]
    hub: FlowStep = Field(
        description="The single node — the 'one' side (a fan-in's target, a fan-out's source)."
    )
    spokes: list[FlowStep] = Field(
        min_length=2,
        description="The 'many' side (2+): the nodes that converge into (in) or diverge from (out) the hub.",
    )
    direction: FanDirection = Field(
        default="in",
        description="in (default): the spokes converge INTO the hub (N→1, e.g. 3 source systems → 1 "
        "record). out: the hub diverges to the spokes (1→N, e.g. 1 request → 3 services). Reach for a "
        "fan when the shape is one-to-many, not a linear pipeline (use flow for that).",
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


class Chart(_Block):
    type: Literal["chart"]
    variant: ChartVariant = Field(
        description="bar: compare a value across categories (grouped, or set stacked). "
        "line: a trend across an ordered axis (smoothed). "
        "donut: parts of a whole. Provide `categories`+`series` for bar/line, or `slices` for donut. "
        "Reach for a chart when a number's SHAPE (trend/spread/share) is the "
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
        description="text/rich (first one becomes the title column), number, badge (a coloured chip — "
        "see `placement`), or indicator (a colour-only dot in its own column; the cell value is a tone "
        "name)."
    )
    placement: ColumnPlacement = Field(
        default="title",
        description="For a `badge` column: `title` (default) chips the badge under the row's title and "
        "ignores the column `label`; `cell` gives the badge its own labelled column, the cell value a "
        "badge key or a list of keys (several chips, wrapping). `cell` on a non-badge column is "
        "rejected; the default is a no-op elsewhere.",
    )
    pct_of_total: bool = Field(
        default=False, description="Show a derived '% of total' caption (needs a reconcile total)."
    )
    width: Count | None = Field(
        default=None,
        ge=1,
        le=6,
        description="Proportional width weight (1-6); set it on every in-cell column, or none. A "
        "`title`-placement badge column takes no width (it rides under the title).",
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


class Rollup(_Frozen):
    by: str = Field(description="Key of the badge column whose per-row values are counted.")
    label: str | None = Field(default=None, description="Optional label shown before the counted chips.")


def col_sum(rows: Sequence[dict[str, Any]], key: str) -> float:
    """Sum a number column's raw values (ints stay ints; floats are not truncated)."""
    return sum(row[key] for row in rows)


def _as_badge_list(value: Any) -> list[Any]:
    """A badge cell holds one key or a list of keys; normalise to a list either way."""
    return cast("list[Any]", value) if isinstance(value, list) else [value]


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
        if row_tone is not None:
            row["tone"] = _to_tone(row_tone)  # normalise an alias (e.g. red → danger) for rendering
            if row["tone"] not in _tone_names(RowTone):
                raise ValueError(f"{loc}.{index}.tone: row tone must be 'muted' or 'danger'")
        for column in columns:
            value = row[column.key]
            if column.kind == "number":
                if isinstance(value, bool) or not isinstance(value, int | float):
                    raise ValueError(f"{loc}.{index}.{column.key}: number column needs a numeric value")
                if not math.isfinite(value):
                    raise ValueError(f"{loc}.{index}.{column.key}: number column must be finite")
            elif column.kind == "badge" and column.placement == "cell":
                # an in-cell badge holds one key or a list of keys (several wrapping chips)
                badge_vals = _as_badge_list(value)
                if not badge_vals or not all(isinstance(key, str) for key in badge_vals):
                    raise ValueError(
                        f"{loc}.{index}.{column.key}: cell badge needs a key or a non-empty list of keys"
                    )
            else:
                if not isinstance(value, str):
                    raise ValueError(f"{loc}.{index}.{column.key}: {column.kind} column needs a string value")
                # An indicator value is normalised to a canonical Tone here (or blank), so the rendered
                # `<span class="dot {value}">` class is always a known tone (a palette alias like `green`
                # becomes `success`).
                if column.kind == "indicator" and value.strip():
                    value = _to_tone(value)
                    row[column.key] = value
                    if value not in _tone_names(Tone):
                        raise ValueError(
                            f"{loc}.{index}.{column.key}: indicator value must be a tone name "
                            "(neutral·info·success·warning·danger·accent·teal·sky) or blank"
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


# A table row is authored as a mapping (column key → value) OR a positional list of values in column
# order. `Table._expand_positional_rows` normalises list rows to mappings before validation. The field
# type is the union (not just dict) so the JSON schema advertises both input shapes; downstream reads
# cast back to a dict, which the normalisation (asserted on Group, guaranteed on Table) makes safe.
TableRow = dict[str, Any] | list[Any]


class Group(_Frozen):
    name: str = Field(description="Group band label; shows the derived subtotal.")
    rows: list[TableRow] = Field(
        default_factory=list[TableRow],
        description="Rows in this group — each a mapping or a positional list in the declared column "
        "order. Empty renders a '— none —' row.",
    )

    @model_validator(mode="after")
    def _rows_are_mappings(self) -> "Group":
        # `Table._expand_positional_rows` turns positional list rows into mappings before a Group is
        # built. Assert it so a Group constructed some other way fails loud here, not with an opaque
        # AttributeError deep in the render — the `list[dict]` casts on the rows rely on this holding.
        if not all(isinstance(row, dict) for row in self.rows):
            raise ValueError("group rows must be mappings (positional list rows are expanded by the table)")
        return self


class Table(_Block):
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

    @model_validator(mode="before")
    @classmethod
    def _expand_positional_rows(cls, data: Any) -> Any:
        """Normalise a positional (list) row to a mapping before field validation: zip its values with
        the column keys in declared order. A list whose length doesn't match the columns is an error
        (a silent zip would drop or blank cells). Mapping rows pass through untouched."""
        if not isinstance(data, dict):
            return data
        fields = cast("dict[str, Any]", data)
        raw_columns = fields.get("columns")
        if not isinstance(raw_columns, list):
            return fields  # malformed columns — let field validation report it
        keys: list[str] = []
        for col in cast("list[Any]", raw_columns):
            key = cast("dict[str, Any]", col).get("key") if isinstance(col, dict) else None
            if not isinstance(key, str):
                return fields  # a column missing a string key — let Column validation report it precisely
            keys.append(key)

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
                    expanded.append(dict(zip(keys, values, strict=True)))
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
        placement_misuse = [c.key for c in self.columns if c.placement == "cell" and c.kind != "badge"]
        if placement_misuse:
            raise ValueError(f"column(s) {placement_misuse}: placement 'cell' is only for badge columns")
        title_badge_widths = [
            c.key
            for c in self.columns
            if c.kind == "badge" and c.placement == "title" and c.width is not None
        ]
        if title_badge_widths:
            raise ValueError(
                f"badge column(s) {title_badge_widths} can't take a width (they ride under the title)"
            )
        # in-cell columns get their own <td>: everything except title-placement badge chips.
        widthed = [c for c in self.cell_columns if c.width is not None]
        if widthed and len(widthed) != len(self.cell_columns):
            raise ValueError("set width on every in-cell column, or none")
        # casts: rows are mappings post-expansion (guaranteed by `_expand_positional_rows`).
        if self.groups is not None:
            for group_index, group in enumerate(self.groups):
                _validate_rows(
                    cast("Sequence[dict[str, Any]]", group.rows), self.columns, f"groups.{group_index}.rows"
                )
        if self.rows is not None:
            _validate_rows(cast("Sequence[dict[str, Any]]", self.rows), self.columns, "rows")
        if self.rollup is not None:
            # Rows are validated above, so every row carries `by` as a string. Both checks run here so
            # the "has values" test sees well-formed rows (a malformed row reports its own error first).
            badge_keys = {column.key for column in self.columns if column.kind == "badge"}
            if self.rollup.by not in badge_keys:
                raise ValueError(f"rollup.by '{self.rollup.by}' must be a badge column")
            if not any(row[self.rollup.by].strip() for row in self.all_rows()):
                raise ValueError(
                    f"rollup.by '{self.rollup.by}' has no values to count — every row is blank there"
                )
        self._reconcile()
        return self

    @property
    def cell_columns(self) -> list[Column]:
        """Columns that get their own <td>, in declared order — everything except title-placement
        badge columns (whose chip rides under the row title). The render's single source of order."""
        return [c for c in self.columns if not (c.kind == "badge" and c.placement == "title")]

    @property
    def title_badges(self) -> list[Column]:
        """Badge columns whose chip renders under the row title (placement 'title')."""
        return [c for c in self.columns if c.kind == "badge" and c.placement == "title"]

    def all_rows(self) -> list[dict[str, Any]]:
        # casts: rows are mappings post-expansion (see `_expand_positional_rows`).
        if self.groups is not None:
            return cast("list[dict[str, Any]]", [row for group in self.groups for row in group.rows])
        return cast("list[dict[str, Any]]", self.rows or [])

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


class ReferenceItem(_Frozen):
    key: str = Field(
        min_length=1,
        pattern=rf"^{REFERENCE_KEY_PATTERN}$",
        description="Short id (ASCII letters, digits, _, -); cite it inline with [^key].",
    )
    text: str = Field(min_length=1, description="Rich-text source description (e.g. a doc name + page).")
    url: str | None = Field(default=None, description="Optional link for the source (http/https/mailto).")

    @model_validator(mode="after")
    def _url_scheme(self) -> "ReferenceItem":
        _require_url_scheme(self.url, "'url'")
        return self


class References(_Block):
    type: Literal["references"]
    items: list[ReferenceItem] = Field(
        min_length=1, description="Numbered sources; cite each inline with [^key]."
    )


class ComparisonCell(_Frozen):
    value: str = Field(min_length=1, description="Cell text (for a ✓/✗ pass a bare true/false instead).")
    tone: Tone | None = Field(default=None, description="Optional tone for the text.")


# A comparison cell is a bare bool (✓/✗), a bare string, or {value, tone} for toned text.
# StrictBool (not bool) so a stray int like 0/1 fails loudly instead of silently rendering ✓/✗.
ComparisonValue = StrictBool | str | ComparisonCell


class ComparisonRow(_Frozen):
    feature: str = Field(min_length=1, description="Row label — the attribute being compared.")
    values: list[ComparisonValue] = Field(min_length=1, description="One cell per option, in column order.")


class Comparison(_Block):
    type: Literal["comparison"]
    options: list[str] = Field(
        min_length=2, description="The things being compared — the column headers (2+)."
    )
    rows: list[ComparisonRow] = Field(
        min_length=1, description="Feature rows; each supplies one value per option."
    )
    highlight: int | None = Field(
        default=None, description="0-based index of the recommended option column to emphasise."
    )
    polarity: list[Literal["positive", "negative"]] | None = Field(
        default=None,
        description="Optional per-option polarity, one per option (default all positive). In a 'negative' "
        "column a true ✓ reads as BAD (red) and a false ✗ as GOOD (green) — for present-is-bad attributes "
        "(e.g. 'leaks disk layout'). Affects only ✓/✗ bool cells; the glyph still marks present/absent.",
    )

    @model_validator(mode="after")
    def _shape(self) -> "Comparison":
        for row in self.rows:
            if len(row.values) != len(self.options):
                raise ValueError(
                    f"comparison row '{row.feature}' has {len(row.values)} values but there are "
                    f"{len(self.options)} options — they must match"
                )
        if self.highlight is not None and not (0 <= self.highlight < len(self.options)):
            raise ValueError(
                f"highlight index {self.highlight} is out of range for {len(self.options)} options"
            )
        if self.polarity is not None and len(self.polarity) != len(self.options):
            raise ValueError(
                f"comparison polarity has {len(self.polarity)} entries but there are "
                f"{len(self.options)} options — they must match"
            )
        return self


class SwimlaneStep(_Frozen):
    lane: str = Field(min_length=1, description="Which lane this step sits in — one of the block's `lanes`.")
    col: str = Field(
        min_length=1,
        description="Which column (sprint) this step sits in — one of the block's `columns`. Two steps "
        "sharing a lane/col stack in that cell.",
    )
    n: str = Field(
        min_length=1,
        description="The number shown in the step's cell — a free string ('1', '3a', 'R1'); skaldr never "
        "derives or renumbers it, so it reads exactly as written.",
    )
    label: str = Field(min_length=1, description="Step label, shown beside the number.")
    group: str | None = Field(
        default=None,
        description="Which group (milestone) this step belongs to — one of the block's `groups` that covers "
        "its `col`. Required only when the column is split across more than one group; inferred otherwise.",
    )
    value: Number | None = Field(
        default=None,
        description="Optional numeric weight for this step (points, hours, cost, count — whatever the "
        "matrix measures). When any step in the block has a value, skaldr auto-sums them into per-column "
        "(footer row), per-lane (beside the lane label), and per-group (on the cap) totals — so the "
        "numbers never drift by hand. A step with no value counts as 0.",
    )
    url: str | None = Field(
        default=None,
        description="Optional link (http/https/mailto) for the step — e.g. its Jira/GitHub ticket. The "
        "step's number becomes a link out to it.",
    )
    state: SwimlaneStepState = Field(
        default="normal",
        description="Ticket emphasis. `normal` (default) is full-weight active work. `low` fades the "
        "ticket (solid, still clearly live) for low-priority / tail work. `blocked` marks it waiting / "
        "on-hold — dashed outline + a greyed number badge, distinct from `low`. The value counts toward "
        "the totals in every state.",
    )
    id: str | None = Field(
        default=None,
        min_length=1,
        pattern=rf"^{REFERENCE_KEY_PATTERN}$",
        description="Optional stable id (ASCII letters, digits, _, -) so other steps can point at this "
        "one via `depends_on`. Unique across the block's steps.",
    )
    depends_on: list[str] = Field(
        default_factory=list,
        description="Ids of steps this one depends on. The dependent renders a compact 'needs N' marker "
        "listing each referenced step's number. Each id must be a step's `id`; a step can't depend on "
        "itself.",
    )

    @model_validator(mode="after")
    def _non_blank(self) -> "SwimlaneStep":
        if not self.lane.strip():
            raise ValueError("swimlane step lane must not be blank")
        if not self.col.strip():
            raise ValueError("swimlane step col must not be blank")
        if not self.n.strip():
            raise ValueError("swimlane step n must not be blank")
        if not self.label.strip():
            raise ValueError("swimlane step label must not be blank")
        _require_url_scheme(self.url, "swimlane step url")
        return self


class SwimlaneLane(_Frozen):
    name: str = Field(min_length=1, description="Lane label shown in the row gutter.")
    id: str | None = Field(
        default=None,
        min_length=1,
        pattern=rf"^{REFERENCE_KEY_PATTERN}$",
        description="Optional stable id (ASCII letters, digits, _, -) that a step references via `lane`; "
        "defaults to `name`. Set it to rename the displayed label without touching every step.",
    )

    @property
    def key(self) -> str:
        """The reference key steps use — the explicit id, or the name when no id is given."""
        return self.id if self.id is not None else self.name


class SwimlaneColumn(_Frozen):
    name: str = Field(min_length=1, description="Column header label.")
    id: str | None = Field(
        default=None,
        min_length=1,
        pattern=rf"^{REFERENCE_KEY_PATTERN}$",
        description="Optional stable id (ASCII letters, digits, _, -) that a step references via `col` "
        "and a group via `columns`; defaults to `name`. Set it to rename the header without touching "
        "every step/group.",
    )
    sub: str | None = Field(
        default=None,
        description="Optional secondary caption under the header (e.g. a delivery target or date range).",
    )

    @property
    def key(self) -> str:
        """The reference key steps/groups use — the explicit id, or the name when no id is given."""
        return self.id if self.id is not None else self.name


class SwimlaneGroup(_Frozen):
    name: str = Field(min_length=1, description="Group (milestone / delivery) name, shown on its cap.")
    color: BadgeColor = Field(
        description="Cap colour — a palette name (slate/blue/…) or its semantic tone twin (neutral/info/…). "
        "Author-chosen, never auto-assigned: a group's colour carries meaning."
    )
    columns: list[str] = Field(
        min_length=1,
        description="The columns this group spans, by their key (id, or name if no id) — a CONTIGUOUS run "
        "of the block's `columns` (a group cannot skip a column). Order need not match; it is derived "
        "from the block `columns`.",
    )


class Swimlane(_Block):
    type: Literal["swimlane"]
    lanes: list[SwimlaneLane] = Field(
        min_length=1,
        max_length=8,
        description="Lanes, in row order (top to bottom). A bare string is shorthand for `{name: …}`; "
        "use `{id, name}` to give a stable reference key. Capped at 8 — more rows than that stop "
        "reading as a matrix; split into two swimlanes instead.",
    )
    columns: list[SwimlaneColumn] = Field(
        min_length=1,
        description="Columns, left to right — the sprint / phase axis. A bare string is shorthand for "
        "`{name: …}`; use `{id, name, sub}` for a stable key and/or a secondary header caption.",
    )
    groups: list[SwimlaneGroup] = Field(
        default_factory=list[SwimlaneGroup],
        description="Optional milestone overlay: coloured caps beyond the table, each spanning a contiguous "
        "run of columns. Omit entirely for a plain swimlane.",
    )
    steps: list[SwimlaneStep] = Field(
        min_length=1, description="Steps placed on the lane/column grid; the sequence reads as a staircase."
    )

    @field_validator("lanes", "columns", mode="before")
    @classmethod
    def _wrap_bare_names(cls, value: Any) -> Any:
        """A bare string lane/column is shorthand for `{name: <string>}` (key defaults to the name)."""
        if not isinstance(value, list):
            return value
        return [{"name": item} if isinstance(item, str) else item for item in cast("list[object]", value)]

    def _groups_covering(self, col: str) -> list[SwimlaneGroup]:
        return [group for group in self.groups if col in group.columns]

    def step_group(self, step: SwimlaneStep) -> str | None:
        """The group a step resolves to: its explicit `group`, else the sole group covering its column,
        else None (an ungrouped column)."""
        if step.group is not None:
            return step.group
        covering = self._groups_covering(step.col)
        return covering[0].name if len(covering) == 1 else None

    def subcolumns(self) -> list[tuple[str, str | None]]:
        """The ordered atomic (column, group-name) segments the grid is built from. A column with no
        group → one `(col, None)` segment; a column split across N groups → N segments in canonical
        order (by column span, then declaration order). Raises if a group's segments cannot be laid out
        contiguously (it interleaves with another group instead of nesting)."""
        if not self.groups:
            return [(col.key, None) for col in self.columns]
        col_index = {col.key: index for index, col in enumerate(self.columns)}
        group_index = {group.name: index for index, group in enumerate(self.groups)}

        def span(group: "SwimlaneGroup") -> tuple[int, int]:
            indices = [col_index[col] for col in group.columns]
            return min(indices), max(indices)

        segments: list[tuple[str, str | None]] = []
        for col in self.columns:
            covering = sorted(
                self._groups_covering(col.key),
                key=lambda group: (*span(group), group_index[group.name]),
            )
            if covering:
                segments.extend((col.key, group.name) for group in covering)
            else:
                segments.append((col.key, None))
        for group in self.groups:
            positions = [index for index, (_, name) in enumerate(segments) if name == group.name]
            if positions and positions != list(range(positions[0], positions[-1] + 1)):
                raise ValueError(
                    f"swimlane group '{group.name}' cannot be laid out contiguously — it shares a column "
                    "with another group while spanning past it; groups must nest, not interleave"
                )
        return segments

    @model_validator(mode="after")
    def _shape(self) -> "Swimlane":
        lane_keys = [lane.key for lane in self.lanes]
        col_keys = [col.key for col in self.columns]
        if len(set(lane_keys)) != len(lane_keys):
            raise ValueError("swimlane lanes must be unique")
        if len(set(col_keys)) != len(col_keys):
            raise ValueError("swimlane columns must be unique")
        lane_set = set(lane_keys)
        col_set = set(col_keys)
        col_index = {col: index for index, col in enumerate(col_keys)}

        group_names = [group.name for group in self.groups]
        if len(set(group_names)) != len(group_names):
            raise ValueError("swimlane group names must be unique")
        for group in self.groups:
            undeclared = [col for col in group.columns if col not in col_set]
            if undeclared:
                raise ValueError(
                    f"swimlane group '{group.name}' references undeclared column(s): {', '.join(undeclared)}"
                )
            indices = sorted(col_index[col] for col in group.columns)
            if indices != list(range(indices[0], indices[-1] + 1)):
                raise ValueError(f"swimlane group '{group.name}' columns must be contiguous in column order")

        group_name_set = set(group_names)
        for step in self.steps:
            if step.lane not in lane_set:
                raise ValueError(f"swimlane step lane '{step.lane}' is not one of the declared lanes")
            if step.col not in col_set:
                raise ValueError(f"swimlane step col '{step.col}' is not one of the declared columns")
            covering = {group.name for group in self._groups_covering(step.col)}
            if step.group is not None:
                if step.group not in group_name_set:
                    raise ValueError(f"swimlane step group '{step.group}' is not a declared group")
                if step.group not in covering:
                    raise ValueError(f"swimlane step group '{step.group}' does not cover column '{step.col}'")
            elif len(covering) > 1:
                raise ValueError(
                    f"swimlane step in column '{step.col}' must name a group — that column is split across "
                    f"{len(covering)} groups"
                )

        used_lanes = {step.lane for step in self.steps}
        for lane in self.lanes:
            if lane.key not in used_lanes:
                raise ValueError(f"swimlane lane '{lane.key}' has no steps")
        used_cols = {step.col for step in self.steps}
        for col in self.columns:
            if col.key not in used_cols:
                raise ValueError(f"swimlane column '{col.key}' has no steps")
        used_groups = {resolved for step in self.steps if (resolved := self.step_group(step)) is not None}
        for group in self.groups:
            if group.name not in used_groups:
                raise ValueError(f"swimlane group '{group.name}' has no steps")

        step_ids = [step.id for step in self.steps if step.id is not None]
        if len(set(step_ids)) != len(step_ids):
            raise ValueError("swimlane step ids must be unique")
        id_set = set(step_ids)
        for step in self.steps:
            for dep in step.depends_on:
                if dep not in id_set:
                    raise ValueError(f"swimlane step depends_on references unknown step id '{dep}'")
                if dep == step.id:
                    raise ValueError(f"swimlane step '{dep}' cannot depend on itself")

        self.subcolumns()  # trigger the contiguity / ordering check
        return self


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
    | Range
    | Table
    | Code
    | Quote
    | Image
    | Timeline
    | Flow
    | Fan
    | Chart
    | Comparison
    | Swimlane
    | References
)
InnerBlock = Annotated[_Leaf, Field(discriminator="type")]


class Section(_Block):
    type: Literal["section"]
    title: str = Field(description="Summary label shown on the collapsible.")
    id: str | None = Field(
        default=None,
        pattern=rf"^{ANCHOR_ID_PATTERN}$",
        description="Optional stable anchor id (lowercase, hyphen-separated). Overrides the title-derived "
        "slug so `[…](#id)` links survive a title rename. Must be unique across the page.",
    )
    collapsed: bool = Field(
        default=True,
        description="Whether the section starts collapsed. Default true suits an appendix / detail; set "
        "false for a read-through living doc so the section opens expanded.",
    )
    updated: str | None = Field(
        default=None,
        description="When this section was last revised; shown as a muted stamp in its header. A "
        "free-form label like the report date (author it — never auto-now).",
    )
    blocks: list[InnerBlock] = Field(
        min_length=1,
        description="Blocks in the section — any block except another section, grid, or walkthrough.",
    )


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


class InnerGrid(_Block):
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


class Grid(_Block):
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


class WalkthroughStep(_Frozen):
    label: str = Field(
        min_length=1,
        description="Step title — a few words to a short sentence; it wraps across lines, so it can be long.",
    )
    sub: str | None = Field(
        default=None, description="Optional one-line sub-label under the title (rich text)."
    )
    tone: Tone | None = Field(
        default=None,
        description="Optional tone; draws a subtle accent down the step's inline-start edge (the "
        "numeral itself is always a uniform faint ghost, so tone can't leave steps looking mismatched).",
    )
    detail: list[InnerBlock] = Field(
        min_length=1,
        description="The step's detail, a nested block list (paragraphs, lists, code, callouts, tables — "
        "like a grid cell), rendered in the column beside the numbered title.",
    )

    @model_validator(mode="after")
    def _non_blank(self) -> "WalkthroughStep":
        if not self.label.strip():
            raise ValueError("walkthrough step label must not be blank")
        return self


class Walkthrough(_Block):
    type: Literal["walkthrough"]
    steps: list[WalkthroughStep] = Field(
        min_length=1,
        description="Ordered steps; each is a big numbered title beside its detail column.",
    )
    step_span: Count = Field(
        default=2,
        ge=1,
        le=5,
        description="Width of the title column, of 6; the detail column takes the rest (default 2).",
    )


Block = Annotated[_Leaf | Section | Grid | Walkthrough, Field(discriminator="type")]
# Every node the tree-walkers (badge/heading/table recursion) may descend into.
AnyBlock = _Leaf | Section | Grid | InnerGrid | Walkthrough


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
        elif isinstance(block, Walkthrough):
            for step in block.steps:
                yield from iter_referenced_badge_keys(step.detail)
        elif isinstance(block, BadgeRow):
            for item in (*block.items, *(i for group in block.groups for i in group.items)):
                if isinstance(item, BadgeRef):
                    yield item.key
        elif isinstance(block, Cards):
            for card in block.items:
                yield from card.badges
        elif isinstance(block, Timeline):
            for item in block.items:
                yield from item.badges
        elif isinstance(block, Flow):
            for step in block.steps:
                yield from step.badges
        elif isinstance(block, Fan):
            yield from block.hub.badges
            for spoke in block.spokes:
                yield from spoke.badges
        elif isinstance(block, Table):
            badge_columns = [column.key for column in block.columns if column.kind == "badge"]
            for row in block.all_rows():
                for key in badge_columns:
                    value = row.get(key)
                    # A cell badge may hold a list of keys; a title badge holds one. A blank string is
                    # an opt-out (no chip on that row), not a reference.
                    for candidate in _as_badge_list(value):
                        if isinstance(candidate, str) and candidate.strip():
                            yield candidate


def iter_reference_items(blocks: Sequence[AnyBlock]) -> Iterator[ReferenceItem]:
    """Every reference item in the block tree (recursing into sections and grids), in document
    order. One source for both the derived numbering and the global key-uniqueness check."""
    for block in blocks:
        if isinstance(block, References):
            yield from block.items
        elif isinstance(block, Section):
            yield from iter_reference_items(block.blocks)
        elif isinstance(block, (Grid, InnerGrid)):
            for cell in block.cells:
                yield from iter_reference_items(cell.blocks)
        elif isinstance(block, Walkthrough):
            for step in block.steps:
                yield from iter_reference_items(step.detail)


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

    @model_validator(mode="after")
    def _validate_reference_keys_unique(self) -> "Report":
        # A key must be globally unique: it becomes an HTML id, and the shared numbering assumes one
        # source per key. This subsumes any within-block check, so `References` carries none.
        counts = Counter(item.key for item in iter_reference_items(self.blocks))
        duplicates = sorted(key for key, count in counts.items() if count > 1)
        if duplicates:
            raise ValueError(f"reference key(s) declared more than once: {duplicates}")
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


# Non-cyclic depth cap: cycles are already caught by `ancestors`, but a pathological non-cyclic chain
# would recurse until Python's own recursion limit and surface as a raw RecursionError. Every other
# load failure is a ReportError, so cap the depth to keep that contract. Real docs never nest this far.
_MAX_INCLUDE_DEPTH = 50


def _load_yaml_with_includes(path: Path, ancestors: tuple[Path, ...]) -> Any:
    """Parse a YAML file, resolving `!include <relative-path>` tags by splicing in the parsed content
    of the referenced file. Paths resolve relative to the *including* file's directory (not the cwd),
    so a fragment set can move as a unit. `ancestors` is the chain of files currently being loaded —
    a resolved path reappearing in it is a cycle and raises rather than recursing forever."""
    try:
        resolved = path.resolve()
    except (OSError, RuntimeError) as err:  # RuntimeError: a symlink loop while resolving
        raise ReportError(f"could not resolve {path}: {err}") from err
    if resolved in ancestors:
        chain = " -> ".join(str(ancestor) for ancestor in (*ancestors, resolved))
        raise ReportError(f"circular !include: {chain}")
    if len(ancestors) >= _MAX_INCLUDE_DEPTH:
        raise ReportError(f"!include nested more than {_MAX_INCLUDE_DEPTH} deep at {path} — likely a mistake")
    text = read_text_file(path)

    class _IncludeLoader(yaml.SafeLoader):
        """SafeLoader subclass — `!include` scoped to this file's dir; keeps `yaml.load` safe."""

    def _construct_include(loader: yaml.SafeLoader, node: yaml.Node) -> Any:
        if not isinstance(node, yaml.ScalarNode):
            raise ReportError(f"!include in {path} takes a single file path, not a list or mapping")
        target = str(loader.construct_scalar(node)).strip()
        if not target:
            raise ReportError(f"!include in {path} needs a file path")
        if Path(target).is_absolute():
            raise ReportError(f"!include in {path} must be a relative path, not absolute: {target}")
        return _load_yaml_with_includes(path.parent / target, (*ancestors, resolved))

    _IncludeLoader.add_constructor("!include", _construct_include)
    try:
        return yaml.load(text, Loader=_IncludeLoader)
    except yaml.YAMLError as err:
        raise ReportError(f"invalid YAML in {path}: {err}") from err


def load_report(path: Path) -> Report:
    data = _load_yaml_with_includes(path, ())
    return parse_report(data)
