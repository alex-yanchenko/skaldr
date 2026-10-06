"""Content-file contract: the pydantic model a skaldr YAML file is validated against.

The page is `version` + `meta` + author-declared `badges` + a flat, ordered `blocks` list.
`blocks` is a discriminated union on `type`, so an unknown block type, a field from the wrong
block, or an unknown top-level key each fails with a precise `blocks.3.items.2.value`-style path.

No domain vocabulary is hardcoded here: tags/statuses live in `badges`, declared per report.
The only fixed vocabularies are the design-system primitives: tones, badge colours, and the
state glyphs for status lists and timelines.
"""

import math
import re
import sys
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from functools import cached_property
from importlib import resources
from pathlib import Path
from typing import Annotated, Any, Final, Literal, NamedTuple, cast, get_args

# Traversable moved to importlib.resources.abc in 3.11; on 3.10 it lives in importlib.abc.
if sys.version_info >= (3, 11):
    from importlib.resources.abc import Traversable
else:
    from importlib.abc import Traversable

import emoji
import yaml
from pydantic import (
    AfterValidator,
    AnyUrl,
    BeforeValidator,
    Discriminator,
    Field,
    StrictBool,
    StringConstraints,
    Tag,
    TypeAdapter,
    ValidationError,
    ValidationInfo,
    field_validator,
    model_validator,
)
from pydantic.json_schema import SkipJsonSchema
from pydantic_core import PydanticCustomError
from typing_extensions import assert_never

from skaldr.errors import ReportError
from skaldr.frozen_model import FrozenModel
from skaldr.mathml import refuse_invalid_math
from skaldr.patterns import SLUG_PATTERN
from skaldr.publish import Publish, section_choice_errors

_RECONCILIATION_ERROR_TYPE = "reconciliation"
# URL schemes safe to emit into an href — the one gate for every author-supplied link (markdown
# links in render.py and reference `url`s here), so a `javascript:`/`data:text/html:` link can't ship.
ALLOWED_URL_SCHEMES = ("http://", "https://", "mailto:")
_LINK_URL: TypeAdapter[AnyUrl] = TypeAdapter(AnyUrl)


def _url_defect(url: str) -> str | None:
    if any(character.isspace() for character in url):
        return "it holds whitespace"
    try:
        parsed = _LINK_URL.validate_python(url)
    except ValidationError as err:
        return err.errors()[0]["msg"].removeprefix("Input should be a valid URL, ")
    if parsed.scheme == "mailto" and not parsed.path:
        return "it names no address"
    return None


def _require_url_scheme(url: str | None, subject: str) -> None:
    """Raise if an author-supplied `url` isn't an allowed scheme. Shared by every model with a link
    field so the gate (and message) can't drift; `subject` names the field in the error."""
    if url is None:
        return
    if not url.startswith(ALLOWED_URL_SCHEMES):
        raise ValueError(f"{subject} must be an http://, https://, or mailto: link")
    defect = _url_defect(url)
    if defect is not None:
        raise ValueError(f"{subject} {url!r} is not a valid URL ({defect})")


# A reference key must be a safe HTML id/fragment and match the inline `[^key]` marker regex in
# render.py; both derive from this one class so key-validation and marker-matching can't drift.
REFERENCE_KEY_PATTERN = r"[A-Za-z0-9_-]+"

ANCHOR_ID_PATTERN = SLUG_PATTERN


LARGEST_NUMBER: Final = 1e300


def _reject_bool_and_non_finite(value: Any) -> Any:
    """Guard numeric fields at the boundary: `bool` is an int subclass pydantic would silently
    coerce (`value: true` → 1), and `.inf`/`.nan` render as literal 'inf'/'nan'. Non-numbers pass
    through untouched so a `str` in an `int | float | str` union still validates as a string."""
    if isinstance(value, bool):
        raise ValueError("must be a number, not a boolean")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("must be a finite number")
    if isinstance(value, int | float) and abs(value) > LARGEST_NUMBER:
        raise ValueError(f"must be between -{LARGEST_NUMBER:g} and {LARGEST_NUMBER:g}")
    return value


def _refuse_an_unusable_number(value: int | float, location: str) -> None:
    try:
        _reject_bool_and_non_finite(value)
    except ValueError as error:
        raise ValueError(f"{location}: {error}") from error


# Numeric field types that reject bool + non-finite before pydantic coerces them.
# Number keeps the int-vs-float distinction (a card's `600` stays an int); Count is int-only.
_NUMBER_GUARD = BeforeValidator(_reject_bool_and_non_finite)
_NUMBER_BOUND_IN_SCHEMA = Field(json_schema_extra={"minimum": -LARGEST_NUMBER, "maximum": LARGEST_NUMBER})
Number = Annotated[int | float, _NUMBER_GUARD, _NUMBER_BOUND_IN_SCHEMA]
Count = Annotated[int, _NUMBER_GUARD, _NUMBER_BOUND_IN_SCHEMA]
SixthsCount = Annotated[int, Field(ge=1, le=6), _NUMBER_GUARD]


NonBlank = Annotated[str, StringConstraints(min_length=1, pattern=r"\S")]

# One palette, two vocabularies. Semantic tones (info/success/…) and badge colours (blue/green/…) name
# the SAME eight colours — the six overlapping pairs share their tokens exactly, plus teal/sky which have
# a palette name only. An author may write either name wherever a tone or a badge colour is taken; these
# maps normalise each input to its field's canonical spelling before the Literal validates, so a `tone:
# green` (or a badge `tone: success`) just works instead of failing. teal/sky pass through unchanged.
ToneLiteral = Literal["neutral", "info", "success", "warning", "danger", "accent", "teal", "sky"]
BadgeColorLiteral = Literal["slate", "blue", "green", "amber", "red", "violet", "teal", "sky"]
TONE_BADGE_COLOR: Final[Mapping[ToneLiteral, BadgeColorLiteral]] = {
    "neutral": "slate",
    "info": "blue",
    "success": "green",
    "warning": "amber",
    "danger": "red",
    "accent": "violet",
    "teal": "teal",
    "sky": "sky",
}
BADGE_COLOR_TONE: Final[Mapping[BadgeColorLiteral, ToneLiteral]] = {
    color: tone for tone, color in TONE_BADGE_COLOR.items()
}
_PALETTE_TO_TONE: Final[Mapping[str, str]] = dict(BADGE_COLOR_TONE.items())
_TONE_TO_PALETTE: Final[Mapping[str, str]] = dict(TONE_BADGE_COLOR.items())


def _to_tone(value: Any) -> Any:
    """Normalise a palette colour name to its semantic tone twin (green → success); pass anything else
    through unchanged (semantic names, teal/sky, non-strings)."""
    return _PALETTE_TO_TONE.get(value, value) if isinstance(value, str) else value


def badge_color_of(tone: ToneLiteral) -> BadgeColorLiteral:
    return TONE_BADGE_COLOR[tone]


def _to_badge_color(value: Any) -> Any:
    """Normalise a semantic tone name to its palette colour twin (success → green); pass anything else
    through unchanged (palette names, teal/sky, non-strings)."""
    return _TONE_TO_PALETTE.get(value, value) if isinstance(value, str) else value


def _tone_names(tone_type: Any) -> tuple[str, ...]:
    """The canonical string values of a tone Literal wrapped in Annotated[Literal[...], validator]:
    for the manually-validated tones (table row + indicator cell) that aren't plain typed fields."""
    return get_args(get_args(tone_type)[0])


# Design-system primitives (fixed — referenced by name, never authored as values). Tone is the eight
# colours by their semantic name (+ teal/sky, palette-only); BadgeColor is the same eight by palette name.
Tone = Annotated[ToneLiteral, BeforeValidator(_to_tone)]
RowTone = Annotated[
    Literal["muted", "danger"], BeforeValidator(_to_tone)
]  # row emphasis: dim a rejected row, or flag a bad one (red aliases to danger)
# Row-dict keys with a reserved meaning (not column values). A column may not use one as its key.
_ROW_RESERVED_KEYS = frozenset({"subrows", "tone"})
BadgeColor = Annotated[BadgeColorLiteral, BeforeValidator(_to_badge_color)]
_CALLOUT_TONES = ("info", "success", "warning", "danger")


def _to_callout_tone(value: Any) -> Any:
    """Normalise a palette alias to its semantic twin (blue→info), then reject a tone that isn't one of
    the four callout meanings, naming both what was given and the allowed set, so the fix is obvious in
    the error itself. A callout is a semantic 'stop and look' note, so teal/sky/accent/neutral (fine on
    cards/badges) have no callout look and are refused rather than silently mapped."""
    normalized = _to_tone(value)
    if isinstance(normalized, str) and normalized not in _CALLOUT_TONES:
        raise ValueError(
            f"callout tone must be one of info, success, warning, danger (got '{value}'): a callout is "
            "semantic; for another palette colour reach for a card, badge_row, or note"
        )
    return normalized


CalloutTone = Annotated[Literal["info", "success", "warning", "danger"], BeforeValidator(_to_callout_tone)]


ACCEPTED_EMOJI_STATUSES: Final = frozenset(
    {emoji.STATUS["fully_qualified"], emoji.STATUS["minimally_qualified"]}
)


def _one_emoji(value: str) -> str:
    entry = emoji.EMOJI_DATA.get(value)
    if entry is not None and entry["status"] == emoji.STATUS["unqualified"]:
        return emoji.emojize(entry["en"])
    if entry is None or entry["status"] not in ACCEPTED_EMOJI_STATUSES:
        raise ValueError(f"icon must be a single emoji (got '{value}')")
    return value


Icon = Annotated[str, AfterValidator(_one_emoji)]


@dataclass(frozen=True)
class RichTextMarker:
    split_into_paragraphs: bool


RICH_TEXT: Final = RichTextMarker(split_into_paragraphs=False)
RICH_PROSE: Final = RichTextMarker(split_into_paragraphs=True)
RichText = Annotated[str, RICH_TEXT]
RichProse = Annotated[str, RICH_PROSE]
NonBlankRichText = Annotated[NonBlank, RICH_TEXT]
NonBlankRichProse = Annotated[NonBlank, RICH_PROSE]
RICH_COLUMN_KINDS: Final = ("text", "rich")
FieldPath = tuple[str, ...]
MappedRow = dict[str, Any]


def _mapped_rows(rows: object) -> list[MappedRow]:
    return cast("list[MappedRow]", rows)


StatusState = Literal["done", "current", "pending", "failed", "blocked"]
DeltaDirection = Literal["up", "down", "flat"]
TimelineState = Literal["done", "current", "pending"]
ColumnKind = Literal["text", "number", "badge", "rich", "indicator"]
NotionWidth = Literal["normal", "full"]
DEFAULT_COLUMN_WIDTH_SHARES: Final[Mapping[ColumnKind, float]] = {"number": 0.1, "indicator": 0.07}
ColumnPlacement = Literal["title", "cell"]  # where a badge column's chip renders
ChartVariant = Literal["bar", "line", "donut"]
FlowStyle = Literal["arrow", "steps"]
FanDirection = Literal["in", "out"]
SwimlaneStepState = Literal[
    "done", "current", "todo", "blocked", "deferred"
]  # progress axis, like status_list/timeline (roadmap-tuned vocabulary: todo, deferred)


def _resource(name: str) -> Traversable:
    return resources.files("skaldr").joinpath(name)


def package_text(name: str) -> str:
    """Text of a bundled package resource (the stylesheet, a template)."""
    return _resource(name).read_text(encoding="utf-8")


def package_path(name: str) -> Path:
    """Filesystem path to a bundled resource. skaldr wheels install unzipped, so this resolves
    to a real path (suitable for reading or copying a bundled file, e.g. the skill dir)."""
    return Path(str(_resource(name)))


class _Block(FrozenModel):
    """Base for every top-level/section block. Carries the one width primitive: `span`, how many of
    the 6 content columns the block occupies. It is width only; blocks still stack vertically (one per
    row). To place several blocks in a single row, use a `grid` (whose cells carry their own span)."""

    span: SixthsCount | None = Field(
        default=None,
        description="Block width in content columns (1 to 6); omit for full width. Same column-count "
        "vocabulary as a grid cell's span, relative to the block's container (the page, or the "
        "enclosing grid cell when nested). Width only: blocks still stack vertically; use a `grid` to "
        "put several in one row.",
    )


class Badge(FrozenModel):
    label: str = Field(description="Chip text for this tag/status.")
    tone: BadgeColor = Field(
        description="Chip colour: a palette name (slate/blue/…) or its semantic tone twin (neutral/info/…)."
    )
    legend: str | Literal[False] = Field(
        description="One-line meaning, shown in the derived legend. Set `false` to keep this badge out "
        "of the legend entirely, for a one-off inline chip that needs no explanation.",
    )


class Meta(FrozenModel):
    title: str = Field(description="Page title (h1).")
    subtitle: list[str] = Field(default_factory=list, description="Subtitle lines under the title.")
    source: str | None = Field(default=None, description="Provenance; feeds the footer.")
    notion_width: NotionWidth = Field(
        default="normal",
        description="The Notion page width the Notion export sizes tables for: `normal` (default) leaves a "
        "table without author widths to Notion; `full` gives every table column widths that add up to "
        "1,200 px, for a page switched to Full width.",
    )
    date: str | None = Field(default=None, description="Report date; feeds the footer (never auto-now).")
    updated: str | None = Field(
        default=None,
        description="When the report was last revised; feeds the footer as 'updated <value>'. A "
        "free-form label like the date (author it; never auto-now).",
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
    text: NonBlank = Field(description="Heading text; also the TOC entry at level 2.")
    level: Literal[2, 3, 4] = Field(
        default=2,
        description="Heading level: 2 (major heading), 3 (sub-heading) or 4 (a minor heading under a 3).",
    )
    id: str | None = Field(
        default=None,
        pattern=rf"^{ANCHOR_ID_PATTERN}$",
        description="Optional stable anchor id (lowercase, hyphen-separated). Overrides the text-derived "
        "slug so `[…](#id)` links survive a heading rename. Must be unique across the page.",
    )
    sub: NonBlankRichText | None = Field(
        default=None,
        description="Optional caption line under the heading, styled subordinate: a real subtitle "
        "slot instead of a muted `text` paragraph faking one. Rich text. Does not feed the TOC (that "
        "stays the plain `text`).",
    )


class Text(_Block):
    type: Literal["text"]
    body: RichProse = Field(description="Rich-text prose; blank lines split paragraphs.")
    muted: bool = Field(default=False, description="Render in the caption colour, for asides.")


_MAX_LIST_DEPTH = 4


class ListItem(FrozenModel):
    text: NonBlankRichText = Field(description="The point's rich-text content.")
    checked: bool = Field(
        default=False,
        description="Only meaningful in a `style: check` list: renders the box ticked. Set it in the "
        "YAML to record durable progress (an agent editing its plan marks items done here); a reader "
        "clicking a box in the browser is ephemeral and does not persist.",
    )
    decided: bool = Field(
        default=False,
        description="Only meaningful in a `style: decision` list: marks the point a decision already "
        "taken. Left false, the point is an open question.",
    )
    items: "list[ListPoint]" = Field(
        default=[],
        description="Optional nested sub-points, rendered as an indented list in the parent's style.",
    )


def _list_point_kind(point: Any) -> Literal["str", "ListItem"]:
    return "str" if isinstance(point, str) else "ListItem"


ListPoint = Annotated[
    Annotated[NonBlankRichText, Tag("str")] | Annotated[ListItem, Tag("ListItem")],
    Discriminator(_list_point_kind),
]
ListItem.model_rebuild()


def _check_list_depth(items: list["str | ListItem"], depth: int) -> None:
    """Reject list nesting deeper than `_MAX_LIST_DEPTH`: past that a bullet tree is unreadable and
    almost always a data-shape mistake. Depth 1 is the top-level list; each nested `items` is +1."""
    if depth > _MAX_LIST_DEPTH:
        raise ValueError(f"list nesting exceeds the maximum depth of {_MAX_LIST_DEPTH}")
    for item in items:
        if isinstance(item, ListItem):
            _check_list_depth(item.items, depth + 1)


def _any_item_flagged(items: list["str | ListItem"], flagged: Callable[["ListItem"], bool]) -> bool:
    return any(
        isinstance(item, ListItem) and (flagged(item) or _any_item_flagged(item.items, flagged))
        for item in items
    )


ListStyle = Literal["bullet", "number", "check", "decision"]
ListNumbering = Literal["decimal", "letters", "roman"]
LARGEST_LIST_START: Final = 999_999_999


class ListBlock(_Block):
    type: Literal["list"]
    style: ListStyle = Field(
        default="bullet",
        description="Bulleted, numbered, or `check`, which shows tickable checkboxes for a live checklist "
        "(the ticks are ephemeral: a browser reload resets them). `decision` marks each point as a "
        "decision taken (`decided: true`) or an open question.",
    )
    start: Annotated[int, Field(ge=1, le=LARGEST_LIST_START), _NUMBER_GUARD] | None = Field(
        default=None,
        description="Only in a `style: number` list: the number the first point carries (default 1). "
        "Nested lists count from 1.",
    )
    numbering: ListNumbering | None = Field(
        default=None,
        description="Only in a `style: number` list: `decimal` (the default), `letters` (a, b, c) or "
        "`roman` (i, ii, iii). Nested lists keep it.",
    )
    items: list[ListPoint] = Field(
        min_length=1,
        description="Rich-text points. A point is a plain string, or `{text, items: [...]}` to nest "
        f"sub-points (nested lists inherit the parent's style; up to {_MAX_LIST_DEPTH} levels deep).",
    )

    @model_validator(mode="after")
    def _bounded_depth(self) -> "ListBlock":
        _check_list_depth(self.items, 1)
        return self

    @model_validator(mode="after")
    def _options_only_in_their_style(self) -> "ListBlock":
        if self.style != "number" and self.start is not None:
            raise ValueError("`start` is only valid in a `style: number` list")
        if self.style != "number" and self.numbering is not None:
            raise ValueError("`numbering` is only valid in a `style: number` list")
        if self.style != "check" and _any_item_flagged(self.items, lambda item: item.checked):
            raise ValueError("`checked` is only valid in a `style: check` list")
        if self.style != "decision" and _any_item_flagged(self.items, lambda item: item.decided):
            raise ValueError("`decided` is only valid in a `style: decision` list")
        return self


class Fact(FrozenModel):
    label: str = Field(description="Fact label (e.g. 'Source').")
    value: str = Field(description="Fact value (e.g. 'prod').")


class FactStrip(_Block):
    type: Literal["fact_strip"]
    facts: list[Fact] = Field(min_length=1, max_length=8, description="1-8 label/value pairs, one line.")


class KVPair(FrozenModel):
    label: str = Field(description="Row label (muted).")
    value: RichText = Field(description="Rich-text value.")


class KeyValue(_Block):
    type: Literal["key_value"]
    pairs: list[KVPair] = Field(min_length=1, description="Vertical label/value metadata rows.")


class DefItem(FrozenModel):
    term: NonBlank = Field(description="The label/term, rendered prominent (e.g. 'Action').")
    body: RichProse = Field(min_length=1, description="Rich-text definition; blank lines split paragraphs.")


class DefList(_Block):
    type: Literal["def_list"]
    items: list[DefItem] = Field(
        min_length=1,
        description="Term/definition pairs: a real labelled list for procedural sub-labels like "
        "Action / Expected / Say. Unlike `key_value` (compact muted metadata), the term reads as a "
        "prominent label and the body is full rich prose.",
    )


class CardDelta(FrozenModel):
    label: NonBlank = Field(description="Delta text shown beside the value, e.g. '+12%' or '0.3s'.")
    direction: DeltaDirection | None = Field(
        default=None, description="Optional glyph before the label: ▲ up, ▼ down, → flat."
    )
    tone: Tone | None = Field(
        default=None,
        description="Delta colour, which YOU set: up isn't always good (down is good for cost/errors), so "
        "skaldr never infers it. Omit for a neutral chip.",
    )


class Card(FrozenModel):
    label: str | None = Field(
        default=None,
        description="Card label above the number. Required for a normal card; for a derived card "
        "(`of_matrix`/`of_tables`) it defaults to the badge's label; set it only to override.",
    )
    value: Number | str | None = Field(
        default=None,
        description="Headline number, or a short status string. Required for a normal card; a derived "
        "card (`of_matrix`/`of_tables`) computes it instead, so leave it unset there.",
    )
    of: Number | None = Field(
        default=None,
        description="Denominator; renders a derived percentage. Not for a derived card (it computes its "
        "own denominator).",
    )
    tone: Tone | None = Field(
        default=None,
        description="Optional tone for the top-border accent. On a derived card, defaults to the badge's "
        "tone (driving chip + border together); set it to override.",
    )
    delta: CardDelta | None = Field(
        default=None, description="Optional trend chip beside the value (a period-over-period change)."
    )
    note: str | None = Field(default=None, description="Optional small caption line under the number.")
    badges: list[str] = Field(
        default_factory=list,
        description="Declared badge keys (from the page `badges`) to chip onto this card.",
    )
    badge: str | None = Field(
        default=None,
        description="For a derived card: the declared badge key to count. Supplies the card's chip, its "
        "label (unless `label` overrides), and its top-border tone. Requires `of_matrix` or `of_tables`.",
    )
    of_matrix: str | None = Field(
        default=None,
        description="Derive this card's value by counting the cells in the matrix with this `id` whose "
        "state is `badge`; the percentage denominator is that matrix's total cell count. When set, "
        "`value` and `of` are computed, so don't author them. Requires `badge`; not with `of_tables`.",
    )
    of_tables: list[str] | None = Field(
        default=None,
        description="Derive this card's value by counting `badge` across the tables with these `id`s, a "
        "page-level summary over several per-section tables that can't drift. Each named table must "
        "declare a `rollup` (its `rollup.by` is the column counted); the percentage denominator is the "
        "total rows across those tables. When set, `value`/`of` are computed. Requires `badge`; not with "
        "`of_matrix`.",
    )

    @property
    def derived(self) -> bool:
        return self.of_matrix is not None or self.of_tables is not None

    @model_validator(mode="after")
    def _shape(self) -> "Card":
        if self.of_matrix is not None and self.of_tables is not None:
            raise ValueError("a derived card counts a matrix (`of_matrix`) OR tables (`of_tables`), not both")
        if self.derived:
            # Derived card: the count and percentage come from the source, so authoring them is a
            # contradiction. The badge names which state to count and supplies the card's chip/label/tone.
            if self.badge is None:
                raise ValueError("a derived card (`of_matrix`/`of_tables`) needs a `badge` to count")
            if self.value is not None:
                raise ValueError("a derived card computes its value; don't set `value`")
            if self.of is not None:
                raise ValueError("a derived card computes its percentage; don't set `of`")
            if self.badges:
                raise ValueError("a derived card shows its own badge chip; don't also set `badges`")
            if self.delta is not None:
                raise ValueError("a derived card has no `delta`; its value is a live count")
        else:
            if self.badge is not None:
                raise ValueError(
                    "`badge` on a card requires `of_matrix` or `of_tables` (use `badges` for plain chips)"
                )
            if self.value is None:
                raise ValueError("a card needs a `value` (or `of_matrix`/`of_tables` to derive one)")
            if self.label is None:
                raise ValueError("a card needs a `label`")
        if self.of_tables is not None:
            if not self.of_tables:
                raise ValueError("`of_tables` must name at least one table")
            if len(set(self.of_tables)) != len(self.of_tables):
                # a table listed twice would double-count in both the numerator and the denominator
                raise ValueError("`of_tables` lists a table id more than once; each table is counted once")
        if self.of is not None:
            if isinstance(self.value, str):
                raise ValueError("'of' requires a numeric 'value'")
            if self.of <= 0:
                raise ValueError("'of' must be greater than 0")
        return self


class Cards(_Block):
    type: Literal["cards"]
    items: list[Card] = Field(min_length=1, description="Headline-number cards, laid out full-width.")


class BadgeRef(FrozenModel):
    key: str = Field(description="A key declared in the page `badges`.")


class BadgeLiteral(FrozenModel):
    label: str = Field(description="Chip text for a one-off badge (not from the page vocabulary).")
    tone: BadgeColor = Field(
        description="Chip colour: a palette name (slate/blue/…) or its semantic tone twin."
    )


class BadgeGroup(FrozenModel):
    label: NonBlank = Field(description="Group label, shown in the row's gutter.")
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
        description="Grouped chips: each group renders as a labelled gutter row. Use this OR `items`, "
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
        description="Accent + tint: info/success/warning/danger only (blue/green/amber/red alias in). A "
        "callout is semantic, so teal/sky/accent/neutral aren't callout tones; use a card/badge_row/note."
    )
    title: str | None = Field(default=None, description="Optional bold title line in the tone colour.")
    body: RichProse = Field(description="Rich-text body.")
    icon: Icon | None = Field(
        default=None,
        description="Optional single emoji shown at the head of the callout, in place of the tone's "
        "default icon in the Markdown exports.",
    )


class StatusItem(FrozenModel):
    state: StatusState = Field(
        description="Step state, driving the glyph: done, current (in progress), pending, failed, blocked."
    )
    text: RichText = Field(description="Rich-text label for the step.")


class StatusList(_Block):
    type: Literal["status_list"]
    items: list[StatusItem] = Field(min_length=1, description="Steps/checks with a coloured state glyph.")


class MeterItem(FrozenModel):
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


class RangeSegment(FrozenModel):
    label: NonBlank = Field(description="Label shown inside the segment.")
    span: Number = Field(
        description="Relative width (> 0). Spans are normalised across the segments, so only the "
        "ratios matter: [3, 1] and [30, 10] render identically."
    )
    tone: Tone | None = Field(
        default=None, description="Soft-tint fill + text colour for the segment (defaults to neutral)."
    )
    sub: NonBlankRichText | None = Field(
        default=None, description="Optional rich-text sub-line under the label."
    )

    @model_validator(mode="after")
    def _shape(self) -> "RangeSegment":
        if self.span <= 0:
            raise ValueError("segment 'span' must be greater than 0")
        return self


class RangeAxis(FrozenModel):
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


class Math(_Block):
    type: Literal["math"]
    expression: str = Field(
        min_length=1,
        description="A LaTeX expression shown as display math, converted to MathML when the page builds.",
    )

    @field_validator("expression")
    @classmethod
    def _converts_to_mathml(cls, expression: str) -> str:
        try:
            refuse_invalid_math(expression, "block")
        except ReportError as error:
            raise ValueError(str(error)) from error
        return expression


class Quote(_Block):
    type: Literal["quote"]
    body: RichProse = Field(description="Rich-text quotation.")
    cite: str | None = Field(default=None, description="Optional attribution line.")


class Note(_Block):
    type: Literal["note"]
    body: NonBlankRichProse = Field(description="Rich-text aside; blank lines split paragraphs.")
    title: str | None = Field(default=None, description="Optional label for the note.")
    icon: Icon | None = Field(
        default=None,
        description="Optional single emoji shown at the head of the note, in place of the default note "
        "icon in the Markdown exports.",
    )


class Divider(_Block):
    type: Literal["divider"]


class Image(_Block):
    type: Literal["image"]
    src: str = Field(
        description="A data: URI (self-contained, no external fetches). Base64-encode the payload "
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


class TimelineItem(FrozenModel):
    time: str | None = Field(default=None, description="Optional timestamp/label for the entry.")
    title: str = Field(description="Entry title.")
    body: RichText | None = Field(default=None, description="Optional rich-text detail.")
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


class FlowStep(FrozenModel):
    label: NonBlank = Field(description="Short stage name: the node label.")
    tone: Tone | None = Field(
        default=None, description="Optional tone accent for this node's border + number."
    )
    note: RichText | None = Field(
        default=None,
        description="Optional one-line detail (rich text). Shown as the caption in `steps` style, and as a "
        "small sub-line in `arrow` style. If most nodes need a note, prefer style: steps.",
    )
    points: list[RichText] = Field(
        default_factory=list,
        description="Optional detail bullets (rich text) under the node, for when one line isn't enough. "
        "Render below the note. Best paired with style: steps, since a few bullets crowd a compact "
        "arrow chip.",
    )
    badges: list[str] = Field(
        default_factory=list,
        description="Declared badge keys (from the page `badges`) to chip onto this node.",
    )


class Flow(_Block):
    type: Literal["flow"]
    steps: list[FlowStep] = Field(
        min_length=2, description="Ordered stages (2+); a flow needs two or more nodes."
    )
    style: FlowStyle = Field(
        default="arrow",
        description="arrow (default): short-labelled nodes joined by → connectors; reach for it when the "
        "DIRECTION between stages is the message (a pipeline or a data flow). steps: equal cards that each "
        "carry a caption line; reach for it when every stage needs a sentence of explanation.",
    )
    loop: bool = Field(
        default=False,
        description="Draw a '↺ back to <first>' return marker after the last node, for a cycle, "
        "not a one-way pipeline.",
    )
    numbered: bool = Field(
        default=True, description="Number the nodes 1..n (derived); set false to hide numbers."
    )


class Fan(_Block):
    type: Literal["fan"]
    hub: FlowStep = Field(
        description="The single node: the 'one' side (a fan-in's target, a fan-out's source)."
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


class ChartSeries(FrozenModel):
    label: NonBlank = Field(description="Series name, shown in the legend.")
    values: list[Number] = Field(
        min_length=1, description="One value per category, in the same order as `categories`."
    )
    tone: Tone | None = Field(default=None, description="Optional tone for this series' bars/line.")


class ChartSlice(FrozenModel):
    label: NonBlank = Field(description="Slice name, shown in the legend.")
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
                        f"{len(self.categories)} categories; they must match"
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
        description="For a `badge` column: `title` (default) chips the badge under the row's title and "
        "ignores the column `label`; `cell` gives the badge its own labelled column, the cell value a "
        "badge key or a list of keys (several chips, wrapping). `cell` on a non-badge column is "
        "rejected; the default is a no-op elsewhere.",
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


def col_sum(rows: Sequence[dict[str, Any]], key: str) -> float:
    """Sum a number column's raw values (ints stay ints; floats are not truncated)."""
    return sum(row[key] for row in rows)


def _as_badge_list(value: Any) -> list[Any]:
    """A badge cell holds one key or a list of keys; normalise to a list either way."""
    return cast("list[Any]", value) if isinstance(value, list) else [value]


def _trimmed_badge_keys(value: Any) -> list[str]:
    return ["" if key is None else str(key).strip() for key in _as_badge_list(value)]


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
                _refuse_an_unusable_number(value, f"{loc}.{index}.{column.key}")
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
                if not isinstance(sub_value, str):
                    _refuse_an_unusable_number(sub_value, f"{sub_loc}.value")


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
            self._refuse_list_cells(
                f"rollup.by '{self.rollup.by}' counts each row under one badge", self.rollup.by
            )
            if not any(row[self.rollup.by].strip() for _, row in self.located_rows()):
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

    def located_rows(self) -> list[tuple[str, dict[str, Any]]]:
        if self.groups is not None:
            return [
                (f"groups.{group_index}.rows.{row_index}", cast("dict[str, Any]", row))
                for group_index, group in enumerate(self.groups)
                for row_index, row in enumerate(group.rows)
            ]
        return [(f"rows.{index}", row) for index, row in enumerate(self.all_rows())]

    def badge_keys(self, row: Mapping[str, Any], key: str) -> list[str]:
        return [badge for badge in _trimmed_badge_keys(row.get(key)) if badge]

    def row_tint_key(self, row: Mapping[str, Any]) -> str:
        if self.tint_by is None:
            return ""
        return next(iter(_trimmed_badge_keys(row.get(self.tint_by))), "")

    @property
    def title_key(self) -> str:
        return next(
            column.key for kind in RICH_COLUMN_KINDS for column in self.columns if column.kind == kind
        )

    def rich_cells(self) -> Iterator[tuple[FieldPath, str, RichTextMarker]]:
        keys = [column.key for column in self.columns if column.kind in RICH_COLUMN_KINDS]
        row_sets = (
            [(("rows",), self.all_rows())]
            if self.groups is None
            else [
                (("groups", str(index), "rows"), _mapped_rows(group.rows))
                for index, group in enumerate(self.groups)
            ]
        )
        for rows_path, rows in row_sets:
            for index, row in enumerate(rows):
                row_path = (*rows_path, str(index))
                for key in keys:
                    yield (*row_path, key), row[key], RICH_PROSE
                for sub_index, subrow in enumerate(_mapped_rows(row.get("subrows") or [])):
                    yield (*row_path, "subrows", str(sub_index), "label"), subrow["label"], RICH_TEXT

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


class ReferenceItem(FrozenModel):
    key: str = Field(
        min_length=1,
        pattern=rf"^{REFERENCE_KEY_PATTERN}$",
        description="Short id (ASCII letters, digits, _, -); cite it inline with [^key].",
    )
    text: NonBlankRichText = Field(description="Rich-text source description (e.g. a doc name + page).")
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


class ComparisonCell(FrozenModel):
    value: NonBlankRichText = Field(description="Cell text (for a ✓/✗ pass a bare true/false instead).")
    tone: Tone | None = Field(default=None, description="Optional tone for the text.")


# A comparison cell is a bare bool (✓/✗), a bare string, or {value, tone} for toned text.
# StrictBool (not bool) so a stray int like 0/1 fails loudly instead of silently rendering ✓/✗.
ComparisonValue = StrictBool | RichText | ComparisonCell


class ComparisonRow(FrozenModel):
    feature: NonBlank = Field(description="Row label: the attribute being compared.")
    values: list[ComparisonValue] = Field(min_length=1, description="One cell per option, in column order.")


class Comparison(_Block):
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
        description="A declared badge key: its tone fills the cell and its label is the cell text. Use "
        "this OR `tone`, not both.",
    )
    tone: BadgeColor | None = Field(
        default=None,
        description="A one-off fill colour (palette or semantic name) for a cell with no vocabulary "
        "badge, e.g. a RACI letter or a ✓. Use this OR `badge`, not both.",
    )
    label: NonBlank | None = Field(
        default=None,
        description="Short text shown in the cell. With `badge` it overrides the badge's label; with "
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


class Matrix(_Block):
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


class SwimlaneStep(FrozenModel):
    lane: NonBlank = Field(description="Which lane this step sits in: one of the block's `lanes`.")
    col: NonBlank = Field(
        description="Which column (sprint) this step sits in: one of the block's `columns`. Two steps "
        "sharing a lane/col stack in that cell.",
    )
    n: NonBlank = Field(
        description="The number shown in the step's cell, a free string ('1', '3a', 'R1'); skaldr never "
        "derives or renumbers it, so it reads exactly as written.",
    )
    label: NonBlank = Field(description="Step label, shown beside the number.")
    group: str | None = Field(
        default=None,
        description="Which group (milestone) this step belongs to: one of the block's `groups` that covers "
        "its `col`. Required only when the column is split across more than one group; inferred otherwise.",
    )
    value: Number | None = Field(
        default=None,
        description="Optional numeric weight for this step (points, hours, cost, count: whatever the "
        "matrix measures). When any step in the block has a value, skaldr auto-sums them into per-column "
        "(footer row), per-lane (beside the lane label), and per-group (on the cap) totals, so the "
        "numbers never drift by hand. A step with no value counts as 0.",
    )
    url: str | None = Field(
        default=None,
        description="Optional link (http/https/mailto) for the step, e.g. its Jira/GitHub ticket. The "
        "step's number becomes a link out to it.",
    )
    state: SwimlaneStepState = Field(
        default="todo",
        description="Progress state: the same progress axis as `status_list`/`timeline`, in roadmap "
        "terms (`todo` for not-started, plus `deferred`). `done` (green), "
        "`current` (in progress, the raised blue badge), `todo` (default: planned, not started; a cool "
        "filled slate badge), `blocked` (waiting / on-hold: amber + dashed), `deferred` (pushed out / "
        "post-MVP: a warm hollow badge that recedes). The value counts toward the totals in every state.",
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
    def _url_scheme(self) -> "SwimlaneStep":
        _require_url_scheme(self.url, "swimlane step url")
        return self


class SwimlaneLane(FrozenModel):
    name: NonBlank = Field(description="Lane label shown in the row gutter.")
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


class SwimlaneColumn(FrozenModel):
    name: NonBlank = Field(description="Column header label.")
    id: str | None = Field(
        default=None,
        min_length=1,
        pattern=rf"^{REFERENCE_KEY_PATTERN}$",
        description="Optional stable id (ASCII letters, digits, _, -) that a step references via `col` "
        "and a group via `columns`; defaults to `name`. Set it to rename the header without touching "
        "every step/group.",
    )
    sub: NonBlank | None = Field(
        default=None,
        description="Optional secondary caption under the header (e.g. a delivery target or date range).",
    )

    @property
    def key(self) -> str:
        """The reference key steps/groups use — the explicit id, or the name when no id is given."""
        return self.id if self.id is not None else self.name


class SwimlaneGroup(FrozenModel):
    name: NonBlank = Field(description="Group (milestone / delivery) name, shown on its cap.")
    color: BadgeColor = Field(
        description="Cap colour: a palette name (slate/blue/…) or its semantic tone twin (neutral/info/…). "
        "Author-chosen, never auto-assigned: a group's colour carries meaning."
    )
    columns: list[str] = Field(
        min_length=1,
        description="The columns this group spans, by their key (id, or name if no id): a CONTIGUOUS run "
        "of the block's `columns` (a group cannot skip a column). Order need not match; it is derived "
        "from the block `columns`.",
    )


def _first_and_last_index(keys: Iterable[str | None]) -> dict[str, tuple[int, int]]:
    spans: dict[str, tuple[int, int]] = {}
    for index, key in enumerate(keys):
        if key is not None:
            spans[key] = (spans[key][0], index) if key in spans else (index, index)
    return spans


MAX_SWIMLANE_LANES: Final = 8


def _wrap_bare_names(value: Any) -> Any:
    if not isinstance(value, list):
        return value
    return [{"name": item} if isinstance(item, str) else item for item in cast("list[object]", value)]


class Swimlane(_Block):
    type: Literal["swimlane"]
    lanes: list[SwimlaneLane] = Field(
        min_length=1,
        max_length=MAX_SWIMLANE_LANES,
        description="Lanes, in row order (top to bottom). A bare string is shorthand for `{name: …}`; "
        f"use `{{id, name}}` to give a stable reference key. Capped at {MAX_SWIMLANE_LANES}: more rows "
        "than that stop reading as a matrix; split into two swimlanes instead.",
    )
    columns: list[SwimlaneColumn] = Field(
        min_length=1,
        description="Columns, left to right: the sprint / phase axis. A bare string is shorthand for "
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

    @field_validator(
        "lanes",
        mode="before",
        json_schema_input_type=Annotated[
            list[NonBlank | SwimlaneLane], Field(min_length=1, max_length=MAX_SWIMLANE_LANES)
        ],
    )
    @classmethod
    def _wrap_bare_lane_names(cls, value: Any) -> Any:
        return _wrap_bare_names(value)

    @field_validator(
        "columns",
        mode="before",
        json_schema_input_type=Annotated[list[NonBlank | SwimlaneColumn], Field(min_length=1)],
    )
    @classmethod
    def _wrap_bare_column_names(cls, value: Any) -> Any:
        return _wrap_bare_names(value)

    def _groups_covering(self, col: str) -> list[SwimlaneGroup]:
        return [group for group in self.groups if col in group.columns]

    @cached_property
    def _number_by_id(self) -> dict[str, str]:
        return {step.id: step.n for step in self.steps if step.id is not None}

    def dependency_numbers(self, step: SwimlaneStep) -> list[str]:
        return list(dict.fromkeys(self._number_by_id[dependency] for dependency in step.depends_on))

    @cached_property
    def _placed_steps(self) -> dict[tuple[str, str, str | None], tuple[SwimlaneStep, ...]]:
        placed: defaultdict[tuple[str, str, str | None], list[SwimlaneStep]] = defaultdict(list)
        for step in self.steps:
            placed[(step.lane, step.col, self.step_group(step))].append(step)
        return {placement: tuple(steps) for placement, steps in placed.items()}

    def steps_at(self, lane: str, col: str, group: str | None) -> tuple[SwimlaneStep, ...]:
        return self._placed_steps.get((lane, col, group), ())

    @cached_property
    def group_spans(self) -> Mapping[str, tuple[int, int]]:
        return _first_and_last_index(group for _, group in self.subcolumns())

    @cached_property
    def column_spans(self) -> Mapping[str, tuple[int, int]]:
        return _first_and_last_index(column for column, _ in self.subcolumns())

    def step_group(self, step: SwimlaneStep) -> str | None:
        """The group a step resolves to: its explicit `group`, else the sole group covering its column,
        else None (an ungrouped column)."""
        if step.group is not None:
            return step.group
        covering = self._groups_covering(step.col)
        return covering[0].name if len(covering) == 1 else None

    def subcolumns(self) -> tuple[tuple[str, str | None], ...]:
        return self._segments

    @cached_property
    def _segments(self) -> tuple[tuple[str, str | None], ...]:
        """The ordered atomic (column, group-name) segments the grid is built from. A column with no
        group → one `(col, None)` segment; a column split across N groups → N segments in canonical
        order (by column span, then declaration order). Raises if a group's segments cannot be laid out
        contiguously (it interleaves with another group instead of nesting)."""
        if not self.groups:
            return tuple((col.key, None) for col in self.columns)
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
                    f"swimlane group '{group.name}' cannot be laid out contiguously: it shares a column "
                    "with another group while spanning past it; groups must nest, not interleave"
                )
        return tuple(segments)

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
                    f"swimlane step in column '{step.col}' must name a group: that column is split across "
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


HttpMethod = Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]
VARIABLE_TOKEN = re.compile(rf"\{{\{{\s*({REFERENCE_KEY_PATTERN})\s*\}}\}}")
CaseTone = Literal["neutral", "info", "success", "warning", "danger"]


def _command_without_block_scalar_trailing_newline(text: str) -> str:
    trimmed = text.rstrip("\n")
    if not trimmed.strip():
        raise ValueError("command must not be blank (omit it instead)")
    return trimmed


CommandText = Annotated[str, AfterValidator(_command_without_block_scalar_trailing_newline)]


class ComposedCall(NamedTuple):
    method: HttpMethod
    url: str


class RequestVariable(FrozenModel):
    name: str = Field(
        pattern=rf"^{REFERENCE_KEY_PATTERN}$",
        description="The token a reader fills, written `{{name}}` in the url, a header value or the "
        "body. ASCII letters, digits, _ and -.",
    )
    label: NonBlank | None = Field(
        default=None, description="Field label above the input. Defaults to `name`."
    )
    example: NonBlank | None = Field(
        default=None,
        description="A sample value, prefilled into the input so the request can be run as it stands. "
        "On a `secret` it is placeholder text only and is never prefilled, since a prefilled secret "
        "would be a secret stored in the YAML.",
    )
    secret: bool = Field(
        default=False,
        description="Never prefill this field from `example`, and mark it in the form as a value that "
        "is not saved. What the reader types stays in their browser tab: it reaches neither the page's "
        "embedded source nor a `--pdf` render, which loads the file fresh with the form empty. Printing "
        "from a tab they have filled in does capture it, in the form and in the command. The input is "
        "not masked, because the same value is shown in full in the command right below it.",
    )


class RequestResponse(FrozenModel):
    status: Annotated[int, Field(ge=100, le=599), _NUMBER_GUARD] | None = Field(
        default=None,
        description="The status you recorded. Omit for a response with no status line, such as a bare "
        "token from `curl -s`. The case's tone follows this number, so you never pick one.",
    )
    reason: str | None = Field(
        default=None,
        description="The reason phrase. Omit and skaldr supplies the standard text for the status, "
        "which is what an HTTP/2 response needs since it carries no reason phrase.",
    )
    headers: dict[str, str | list[str]] = Field(
        default_factory=dict,
        description="Response headers worth keeping, in the order you want them read. Give a list for "
        "a header that legitimately repeats, such as `Set-Cookie`.",
    )
    body: str = Field(
        description="The body, verbatim. A one-line JSON object or array, as `curl -s` or `jq -c` "
        "prints it, is pretty-printed for display; a body you laid out across lines is shown as written."
    )

    @model_validator(mode="after")
    def _shape(self) -> "RequestResponse":
        for name in self.headers:
            if not name.strip():
                raise ValueError("response header name must not be blank")
        return self


def check_header_map(
    headers: Mapping[str, str] | None, what: Literal["request header", "request case header"]
) -> None:
    """Every rule a set of headers on one call obeys, wherever it is written.

    A name is case-insensitive on the wire, so two spellings of one name are that header written
    twice: the command a reader pastes would carry both, and which one the server honours is not
    ours to decide."""
    spellings: dict[str, str] = {}
    for name, value in (headers or {}).items():
        if not name.strip():
            raise ValueError(f"{what} name must not be blank")
        if not value.strip():
            raise ValueError(f"{what} `{name}` must not have a blank value")
        seen = spellings.get(name.lower())
        if seen is not None:
            raise ValueError(f"{what}s `{seen}` and `{name}` differ only in case, so they name one header")
        spellings[name.lower()] = name


class RequestCase(FrozenModel):
    label: NonBlank = Field(description="Tab label, and the case's heading when printed.")
    value: NonBlank | None = Field(
        default=None,
        description="What this case supplies for the block's `case_variable`. Defaults to `label`, "
        "which is what you want when the cases are resource names.",
    )
    headers: dict[str, str] | None = Field(
        default=None,
        description="Replace the request's headers for this case alone. Omit to inherit them; give an "
        "empty map to send none, which is how you record what happens with the auth header removed.",
    )
    headers_add: dict[str, str] | None = Field(
        default=None,
        description="Add to the request's headers for this case, replacing a name it already sets and "
        "leaving the rest. Use it when cases share a credential and differ in one header, so the shared "
        "one is written once. Cannot be combined with `headers`, which replaces them outright.",
    )
    command: CommandText | None = Field(
        default=None,
        description="Replace the request's `command` for this case alone, for a control that differs "
        "from the finding by more than one value. Only on a request that runs a `command`.",
    )
    tone: CaseTone | None = Field(
        default=None,
        description="Colour this case's tab and verdict when its response carries no `status`, such as "
        "the output of a `curl -s | jq` command: `warning` for a finding, `success` for a control that "
        "passes. A recorded status decides the tone by itself, so the two are never set together.",
    )
    response: RequestResponse = Field(description="What came back when you ran it.")
    verdict: NonBlankRichText | None = Field(
        default=None,
        description="Rich-text reading of this response: what you expected, what you got, what it "
        "means. The one part of the block a reader cannot work out for themselves.",
    )

    @model_validator(mode="after")
    def _shape(self) -> "RequestCase":
        if self.headers is not None and self.headers_add is not None:
            raise ValueError(
                "a request case sets headers and headers_add together: headers replaces and "
                "headers_add layers, so state the headers you want once, under headers"
            )
        for source in (self.headers, self.headers_add):
            check_header_map(source, "request case header")
        if self.tone is not None and self.response.status is not None:
            raise ValueError(
                f"case '{self.label}' sets a tone and records status {self.response.status}: the status "
                "already decides the tone, so drop `tone`"
            )
        return self


MAX_STRIP_LABELS = 24
"""How many labels one tab strip may carry: a call's cases, or a tabs block's tabs. The stylesheet pairs
a radio with its label by position, and writes that many pairs, so a label past this one would render
without ever lighting up."""


def _check_distinct_strip_labels(labels: Iterable[str], refusal: str) -> None:
    repeated = sorted(label for label, count in Counter(labels).items() if count > 1)
    if repeated:
        raise ValueError(f"{refusal}: {', '.join(repeated)}")


class _RequestCore(FrozenModel):
    """One recorded call, composed from its HTTP fields or given as an exact command, and the outcomes
    it produced. Shared by a standalone `request` and by a step of a `request_flow`, which differ only
    in where their variables come from."""

    label: NonBlank = Field(description="What the call is for, shown in the header.")
    method: HttpMethod | None = Field(
        default=None, description="The HTTP method. Required unless the call runs a `command`."
    )
    url: str | None = Field(
        default=None,
        min_length=1,
        description="The full URL. May carry `{{variable}}` tokens. Required unless the call runs a "
        "`command`.",
    )
    command: CommandText | None = Field(
        default=None,
        description="A shell command the reader copies and runs exactly as written, in place of the "
        "curl skaldr would build from `method`, `url`, `headers` and `body`. Use it when the call needs "
        "what those fields cannot say: a secret manager supplying the credential, a proxy, a `| jq` "
        "that shapes the output. May carry `{{variable}}` tokens, written in as the reader types them "
        "with no shell quoting added. Cannot be combined with `method`, `url`, `headers` or `body`.",
    )
    command_note: NonBlankRichText | None = Field(
        default=None,
        description="Rich-text line under the command explaining why it is shaped the way it is, such "
        "as what a `jq` filter makes visible. The verdict stays about what came back.",
    )
    headers: dict[str, str] = Field(
        default_factory=dict,
        description="Request headers as a map, in the order they should read. A value may carry "
        "`{{variable}}` tokens.",
    )
    body: NonBlank | None = Field(
        default=None,
        description="Request body, sent as `--data`. May carry `{{variable}}` tokens, so a credential "
        "can sit inside a JSON login payload without ever being written here.",
    )
    case_variable: str | None = Field(
        default=None,
        pattern=rf"^{REFERENCE_KEY_PATTERN}$",
        description="The `{{name}}` each case supplies, for cases that differ by one value such as a "
        "resource name. Omit when the cases differ by headers instead, or when there is only one.",
    )
    cases: list[RequestCase] = Field(
        min_length=1,
        description="One entry per recorded outcome. Tabs on screen, stacked under their own headings "
        "when printed, because a tab must never hide evidence on paper.",
    )

    def referenced_variables(self) -> set[str]:
        """Every `{{name}}` this call interpolates, across the url, the command, the header values, the
        body and each case's own command.

        A case's headers count whichever way it sets them: `headers` replaces the request's and
        `headers_add` layers over them, and both are interpolated the same way at render time."""
        case_headers = (
            value
            for case in self.cases
            for source in (case.headers, case.headers_add)
            for value in (source or {}).values()
        )
        case_commands = (case.command or "" for case in self.cases)
        scan = " ".join(
            (
                self.url or "",
                self.command or "",
                *self.headers.values(),
                self.body or "",
                *case_headers,
                *case_commands,
            )
        )
        return {match.group(1) for match in VARIABLE_TOKEN.finditer(scan)}

    def composed_call(self) -> ComposedCall:
        if self.method is None or self.url is None:
            raise ReportError(f"request '{self.label}' runs a command, so skaldr composes no call for it")
        return ComposedCall(self.method, self.url)

    def case_axis(self) -> set[str]:
        """The case variable as a set, empty when the call declares none."""
        return {self.case_variable} if self.case_variable else set()

    @model_validator(mode="after")
    def _core_shape(self) -> "_RequestCore":
        _check_distinct_strip_labels((case.label for case in self.cases), "request repeats a case label")
        if len(self.cases) > MAX_STRIP_LABELS:
            raise ValueError(
                f"a request records at most {MAX_STRIP_LABELS} cases, and this one has "
                f"{len(self.cases)}; split it into blocks a reader can take in"
            )
        if self.case_variable is None:
            for case in self.cases:
                if case.value is not None:
                    raise ValueError(
                        f"case '{case.label}' sets a value but the request declares no case_variable, "
                        "so there is nothing for it to fill"
                    )
        check_header_map(self.headers, "request header")
        if self.command is None:
            self._check_composed_call()
        else:
            self._check_command_call()
        return self

    def _check_composed_call(self) -> None:
        if self.method is None or self.url is None:
            raise ValueError(
                f"request '{self.label}' needs `method` and `url` to build a curl, or a `command` to run "
                "as written"
            )
        for case in self.cases:
            if case.command is not None:
                raise ValueError(
                    f"case '{case.label}' sets a command but the request builds a curl from `method` and "
                    "`url`: set `command` on the request to run its cases as written"
                )
        if self.command_note is not None:
            raise ValueError(
                f"request '{self.label}' sets a command_note but runs no command: put the note in a verdict"
            )

    def _check_command_call(self) -> None:
        composed_fields = {
            "method": self.method,
            "url": self.url,
            "headers": self.headers or None,
            "body": self.body,
        }
        for name, value in composed_fields.items():
            if value is not None:
                raise ValueError(
                    f"request '{self.label}' sets `command` and `{name}`: a command runs exactly as "
                    f"written, so skaldr builds no curl and `{name}` would never reach it"
                )
        for case in self.cases:
            for name, value in (("headers", case.headers), ("headers_add", case.headers_add)):
                if value is not None:
                    raise ValueError(
                        f"case '{case.label}' sets `{name}` on a request that runs a command, which sends "
                        "no headers of its own: write them into the command"
                    )


class _VariableOwner(FrozenModel):
    """The block a reader's fields belong to."""

    variables: list[RequestVariable] = Field(
        default_factory=list[RequestVariable],
        description="The values a reader supplies. A `{{name}}` declared here is a runtime blank the "
        "reader fills, so `--check --strict` leaves it alone; an undeclared one is still an unfilled "
        "placeholder and still fails strict, which is what catches a mistyped name.",
    )
    id: str | None = Field(
        default=None,
        pattern=rf"^{ANCHOR_ID_PATTERN}$",
        description="Optional stable id, unique across the page's request blocks. It keys what a "
        "reader's non-secret fields are remembered under while their tab is open, so set one when two "
        "blocks share a label, and keep it fixed if you want those values to survive a rename.",
    )


class Request(_RequestCore, _VariableOwner, _Block):
    type: Literal["request"]

    def resolvable_variables(self) -> set[str]:
        """Every name the block can fill by itself: the reader's fields plus the case axis."""
        return {variable.name for variable in self.variables} | self.case_axis()

    @model_validator(mode="after")
    def _shape(self) -> "Request":
        declared = [variable.name for variable in self.variables]
        repeated = {name for name in declared if declared.count(name) > 1}
        if repeated:
            raise ValueError(f"request declares a variable twice: {', '.join(sorted(repeated))}")
        if self.case_variable is not None and self.case_variable in declared:
            raise ValueError(
                f"`{self.case_variable}` is both the case_variable and a declared variable: each case "
                "supplies it, so it must not also be a field the reader fills"
            )
        unused = self.resolvable_variables() - self.referenced_variables()
        if unused:
            raise ValueError(
                f"request declares {', '.join(sorted(unused))} but never uses "
                f"{'them' if len(unused) > 1 else 'it'}; every variable needs a `{{{{name}}}}` to fill"
            )
        return self


class RequestCapture(FrozenModel):
    name: str = Field(
        pattern=rf"^{REFERENCE_KEY_PATTERN}$",
        description="The name this step produces. A later step writes it as `{{name}}` and the reader "
        "never types it.",
    )
    source: Literal["body"] | None = Field(
        default=None,
        description="Take the whole response body, trimmed. For an endpoint that answers with a bare "
        "token and no JSON wrapper. Use this or `json_path`, not both.",
    )
    json_path: str | None = Field(
        default=None,
        pattern=r"^\$\.[A-Za-z0-9_-]+(\.[A-Za-z0-9_-]+)*$",
        description="A dotted path into a JSON response body, written `$.access_token` or "
        "`$.data.token`. Object keys only, since that is what the page resolves; an array index is "
        "not part of the path language. Use this or `source`, not both.",
    )
    secret: bool = Field(
        default=False,
        description="Show the captured value as a count rather than in the field that reports it. The "
        "value still appears in the command of any step that interpolates it.",
    )

    @model_validator(mode="after")
    def _shape(self) -> "RequestCapture":
        if (self.source is None) == (self.json_path is None):
            raise ValueError(
                f"capture `{self.name}` takes `source: body` or a `json_path`, exactly one of the two"
            )
        return self


class RequestStep(_RequestCore):
    captures: list[RequestCapture] = Field(
        default_factory=list[RequestCapture],
        description="Values this step's response produces for later steps to interpolate.",
    )

    @model_validator(mode="after")
    def _shape(self) -> "RequestStep":
        names = [capture.name for capture in self.captures]
        repeated = {name for name in names if names.count(name) > 1}
        if repeated:
            raise ValueError(f"step captures the same name twice: {', '.join(sorted(repeated))}")
        if self.captures and len(self.cases) > 1:
            raise ValueError(
                f"step '{self.label}' captures a value and records {len(self.cases)} cases; a capture "
                "reads one definite response, so a step that produces a value keeps a single case"
            )
        return self


class RequestFlow(_VariableOwner, _Block):
    type: Literal["request_flow"]
    label: NonBlank = Field(description="What the flow is for, shown in the block header.")
    steps: list[RequestStep] = Field(
        min_length=2,
        description="The calls in the order they run. A flow of one step is a `request`, so use that.",
    )

    def produced_by(self, index: int) -> set[str]:
        """Names captured by the steps before `index`, which is what that step may interpolate."""
        return {capture.name for step in self.steps[:index] for capture in step.captures}

    def resolvable_variables(self) -> set[str]:
        """Every name the block fills by itself: the reader's fields, each step's case axis, and every
        captured name."""
        names = {variable.name for variable in self.variables}
        for step in self.steps:
            names |= step.case_axis() | {capture.name for capture in step.captures}
        return names

    def unresolved_variables(self) -> set[str]:
        """Names a step interpolates that nothing can fill by the time that step runs. A capture from a
        later step does not count: the value does not exist yet when the reader reaches this one."""
        declared = {variable.name for variable in self.variables}
        missing: set[str] = set()
        for index, step in enumerate(self.steps):
            available = declared | step.case_axis() | self.produced_by(index)
            missing |= step.referenced_variables() - available
        return missing

    @model_validator(mode="after")
    def _shape(self) -> "RequestFlow":
        declared = [variable.name for variable in self.variables]
        repeated = {name for name in declared if declared.count(name) > 1}
        if repeated:
            raise ValueError(f"flow declares a variable twice: {', '.join(sorted(repeated))}")
        captured = [capture.name for step in self.steps for capture in step.captures]
        clashing = {name for name in captured if name in declared}
        if clashing:
            raise ValueError(
                f"{', '.join(sorted(clashing))} is both captured and declared: a step produces it, so "
                "it must not also be a field the reader fills"
            )
        duplicated = {name for name in captured if captured.count(name) > 1}
        if duplicated:
            raise ValueError(f"two steps capture the same name: {', '.join(sorted(duplicated))}")
        for index, step in enumerate(self.steps):
            late = step.referenced_variables() & (set(captured) - self.produced_by(index))
            if late:
                raise ValueError(
                    f"step {index + 1} uses {', '.join(sorted(late))} before the step that captures "
                    f"{'them' if len(late) > 1 else 'it'} has run"
                )
        unused = self.resolvable_variables() - {
            name for step in self.steps for name in step.referenced_variables()
        }
        if unused:
            raise ValueError(
                f"flow declares or captures {', '.join(sorted(unused))} but no step uses "
                f"{'them' if len(unused) > 1 else 'it'}"
            )
        return self


class _ToggleBase(_Block):
    type: Literal["toggle"]
    title: NonBlank = Field(description="Summary label shown on the collapsible.")
    collapsed: bool = Field(
        default=True,
        description="Whether the toggle starts collapsed, as a section does. Set false to open it.",
    )


class InnerToggle(_ToggleBase):
    blocks: list["InnerBlock"] = Field(
        min_length=1,
        description="Blocks inside a toggle in a grid cell, a walkthrough step's detail or a tab: any block "
        "except a section, panel, grid, walkthrough, request or request_flow. It may hold another toggle "
        "or a tabs block.",
    )


class Toggle(_ToggleBase):
    blocks: list["SectionBlock"] = Field(
        min_length=1,
        description="Blocks inside a toggle at the top level, in a section, in a panel or in another such "
        "toggle: any block a section holds, including a request or request_flow.",
    )


class Tab(FrozenModel):
    label: NonBlank = Field(description="The tab's label in the strip, and its heading on paper.")
    tone: Tone | None = Field(
        default=None,
        description="Optional tone: a coloured dot before the label, the way a request case shows its "
        "outcome. Omit it for a plain label.",
    )
    blocks: list["InnerBlock"] = Field(
        min_length=1,
        description="Blocks shown while the tab is chosen: any block a toggle in a grid cell holds, "
        "including a toggle or another tabs block, and never a request or request_flow.",
    )


class Tabs(_Block):
    type: Literal["tabs"]
    tabs: list[Tab] = Field(
        min_length=2,
        max_length=MAX_STRIP_LABELS,
        description=f"The tabs, in strip order; the first starts chosen. Two to {MAX_STRIP_LABELS}, with "
        "distinct labels. Every tab prints, each under its label.",
    )

    @model_validator(mode="after")
    def _shape(self) -> "Tabs":
        _check_distinct_strip_labels((tab.label for tab in self.tabs), "tabs repeat a label")
        return self


_Simple = (
    Heading
    | Text
    | ListBlock
    | FactStrip
    | KeyValue
    | DefList
    | Cards
    | BadgeRow
    | Callout
    | StatusList
    | Meter
    | Range
    | Table
    | Code
    | Math
    | Quote
    | Note
    | Divider
    | Image
    | Timeline
    | Flow
    | Fan
    | Chart
    | Comparison
    | Matrix
    | Swimlane
    | References
)
_Leaf = _Simple | InnerToggle | Tabs
InnerBlock = Annotated[_Leaf, Field(discriminator="type")]
InnerToggle.model_rebuild()
Tab.model_rebuild()
FullWidthBlock = Annotated[_Simple | Toggle | Tabs | Request | RequestFlow, Field(discriminator="type")]
RequestLike = Request | RequestStep


class Section(_Block):
    type: Literal["section"]
    title: NonBlank = Field(description="Summary label shown on the collapsible.")
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
        "free-form label like the report date (author it; never auto-now).",
    )
    blocks: list["SectionBlock"] = Field(
        min_length=1,
        description="Blocks in the section: any block except another section, grid, or walkthrough.",
    )


class Panel(_Block):
    type: Literal["panel"]
    title: NonBlank = Field(description="Panel title, shown in the header band.")
    blocks: list[FullWidthBlock] = Field(
        min_length=1,
        description="Blocks inside the panel: any block except another panel, section, grid, or "
        "walkthrough. Unlike a `section`, a panel is always open: "
        "a titled framed card, one per 'slide' in a deck-style doc.",
    )


SectionBlock = Annotated[_Simple | Toggle | Tabs | Request | RequestFlow | Panel, Field(discriminator="type")]
Toggle.model_rebuild()
Section.model_rebuild()
Panel.model_rebuild()


# Grid: a bounded side-by-side layout over a 6-column base.
# Nesting is capped at depth 2 by the type graph: a top-level GridCell may hold nested InnerGrids,
# whose cells hold only leaf blocks — so a depth-3 grid is unrepresentable. `span` is required
# (not auto-distributed) and cell spans in a grid sum to at most 6 (trailing space allowed).
# A grid nests only within a grid; `section` stays a leaf-only container and the two do not mix.


class InnerGridCell(FrozenModel):
    span: SixthsCount = Field(description="Columns this cell spans, of 6.")
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


class GridCell(FrozenModel):
    span: SixthsCount = Field(description="Columns this cell spans, of 6.")
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


class WalkthroughStep(FrozenModel):
    label: NonBlank = Field(
        description="Step title: a few words to a short sentence; it wraps across lines, so it can be long.",
    )
    sub: NonBlankRichText | None = Field(
        default=None, description="Optional one-line sub-label under the title (rich text)."
    )
    tone: Tone | None = Field(
        default=None,
        description="Optional tone for the step's left rail. Every step always HAS the rail (it is the "
        "list's structure); tone only changes its colour, so use it to mark a key step, not every "
        "step. The numeral stays a uniform muted grey regardless, so tones can't leave steps mismatched.",
    )
    detail: list[CellBlock] = Field(
        min_length=1,
        description="The step's detail (paragraphs, lists, code, callouts, tables, or a `grid` for a "
        "two-column step like Action | Script), rendered in the column beside the numbered title.",
    )


class Walkthrough(_Block):
    type: Literal["walkthrough"]
    steps: list[WalkthroughStep] = Field(
        min_length=1,
        description="Ordered steps; each is a big numbered title beside its detail column.",
    )
    step_span: Annotated[int, Field(ge=1, le=5), _NUMBER_GUARD] = Field(
        default=2,
        description="Width of the title column, of 6; the detail column takes the rest (default 2).",
    )


_TopLevel = _Simple | Toggle | Tabs | Request | RequestFlow | Section | Grid | Walkthrough | Panel
Block = Annotated[_TopLevel, Field(discriminator="type")]

BUILT_BY_AN_INDEX: Final = "built_by_an_index"


def _is_built_by_an_index(info: ValidationInfo) -> bool:
    context: object = info.context
    return (
        isinstance(context, Mapping) and cast("Mapping[str, object]", context).get(BUILT_BY_AN_INDEX) is True
    )


class Part(FrozenModel):
    type: Literal["part"]
    title: NonBlank
    collapsed: bool = False
    blocks: list[Block] = Field(min_length=1)

    @model_validator(mode="after")
    def _only_an_index_builds_a_part(self, info: ValidationInfo) -> "Part":
        if not _is_built_by_an_index(info):
            raise ValueError(
                "a `part` block is built by an `index`, not written by hand; list the file under "
                "`index.parts`, or use a `section` or a `heading`"
            )
        return self


PageBlock = Annotated[_TopLevel | SkipJsonSchema[Part], Field(discriminator="type")]
# Every node the tree-walkers (badge/heading/table recursion) may descend into.
AuthoredBlock = _Leaf | Toggle | Request | RequestFlow | Section | Panel | Grid | InnerGrid | Walkthrough
AnyBlock = AuthoredBlock | Part


def located_child_blocks(block: AnyBlock) -> Sequence[tuple[str, AnyBlock]]:
    match block:
        case Part() | Section() | Panel() | Toggle() | InnerToggle():
            return [(f"blocks.{index}", inner) for index, inner in enumerate(block.blocks)]
        case Grid() | InnerGrid():
            return [
                (f"cells.{cell_index}.blocks.{index}", inner)
                for cell_index, cell in enumerate(block.cells)
                for index, inner in enumerate(cell.blocks)
            ]
        case Walkthrough():
            return [
                (f"steps.{step_index}.detail.{index}", inner)
                for step_index, step in enumerate(block.steps)
                for index, inner in enumerate(step.detail)
            ]
        case Tabs():
            return [
                (f"tabs.{tab_index}.blocks.{index}", inner)
                for tab_index, tab in enumerate(block.tabs)
                for index, inner in enumerate(tab.blocks)
            ]
        case (
            Heading()
            | Text()
            | ListBlock()
            | FactStrip()
            | KeyValue()
            | DefList()
            | Cards()
            | BadgeRow()
            | Callout()
            | StatusList()
            | Meter()
            | Range()
            | Table()
            | Code()
            | Math()
            | Quote()
            | Note()
            | Divider()
            | Image()
            | Timeline()
            | Flow()
            | Fan()
            | Chart()
            | Comparison()
            | Matrix()
            | Swimlane()
            | References()
            | Request()
            | RequestFlow()
        ):
            return ()
        case _:
            assert_never(block)


def child_blocks(block: AnyBlock) -> Sequence[AnyBlock]:
    return [inner for _, inner in located_child_blocks(block)]


def walk_blocks(blocks: Sequence[AnyBlock]) -> Iterator[AnyBlock]:
    for block in blocks:
        yield block
        yield from walk_blocks(child_blocks(block))


def _walk_placed(placed: Iterable[tuple[str, AnyBlock]]) -> Iterator[tuple[str, AnyBlock]]:
    for place, block in placed:
        path = f"{place}.{block.type}"
        yield path, block
        yield from _walk_placed((f"{path}.{child}", inner) for child, inner in located_child_blocks(block))


def walk_located_blocks(blocks: Sequence[AnyBlock]) -> Iterator[tuple[str, AnyBlock]]:
    yield from _walk_placed((f"blocks.{index}", block) for index, block in enumerate(blocks))


def iter_requests(blocks: Sequence[AnyBlock]) -> Iterator[Request | RequestFlow]:
    """Every `request` and `request_flow` on the page, including ones nested in a section or a panel."""
    for block in walk_blocks(blocks):
        if isinstance(block, Request | RequestFlow):
            yield block


def unresolvable_request_variables(blocks: Sequence[AnyBlock]) -> set[str]:
    """Names a `request` or `request_flow` interpolates but cannot fill: neither a reader's field, nor
    a case axis, nor a value an earlier step captured. A declared name is a runtime blank the reader
    supplies, so it is not an unfilled placeholder; an undeclared one is a typo the strict gate should
    still catch."""
    names: set[str] = set()
    for block in iter_requests(blocks):
        if isinstance(block, RequestFlow):
            names |= block.unresolved_variables()
        else:
            names |= block.referenced_variables() - block.resolvable_variables()
    return names


def iter_referenced_badge_keys(blocks: Sequence[AnyBlock]) -> Iterator[str]:
    """Every badge key referenced anywhere in the block tree (recursing into sections and grids).

    Single source of truth for both validation (undeclared keys) and the derived legend.
    """
    return (key for _, key in iter_located_badge_keys(blocks))


def iter_located_badge_keys(blocks: Sequence[AnyBlock]) -> Iterator[tuple[str, str]]:
    for path, block in walk_located_blocks(blocks):
        yield from _badge_keys_in(path, block)


def _badge_keys_from(path: str, keys: Sequence[str]) -> Iterator[tuple[str, str]]:
    for index, key in enumerate(keys):
        yield f"{path}.{index}", key


def _badge_keys_in(path: str, block: AnyBlock) -> Iterator[tuple[str, str]]:
    if isinstance(block, BadgeRow):
        for index, item in enumerate(block.items):
            if isinstance(item, BadgeRef):
                yield f"{path}.items.{index}.key", item.key
        for group_index, group in enumerate(block.groups):
            for index, item in enumerate(group.items):
                if isinstance(item, BadgeRef):
                    yield f"{path}.groups.{group_index}.items.{index}.key", item.key
    elif isinstance(block, Cards):
        for index, card in enumerate(block.items):
            yield from _badge_keys_from(f"{path}.items.{index}.badges", card.badges)
            if card.badge is not None:
                yield f"{path}.items.{index}.badge", card.badge
    elif isinstance(block, Timeline):
        for index, item in enumerate(block.items):
            yield from _badge_keys_from(f"{path}.items.{index}.badges", item.badges)
    elif isinstance(block, Flow):
        for index, step in enumerate(block.steps):
            yield from _badge_keys_from(f"{path}.steps.{index}.badges", step.badges)
    elif isinstance(block, Fan):
        yield from _badge_keys_from(f"{path}.hub.badges", block.hub.badges)
        for index, spoke in enumerate(block.spokes):
            yield from _badge_keys_from(f"{path}.spokes.{index}.badges", spoke.badges)
    elif isinstance(block, Matrix):
        for index, cell in enumerate(block.cells):
            if cell.badge is not None:
                yield f"{path}.cells.{index}.badge", cell.badge
    elif isinstance(block, Table):
        badge_columns = [column.key for column in block.columns if column.kind == "badge"]
        for row_path, row in block.located_rows():
            for key in badge_columns:
                yield from _badge_keys_in_cell(f"{path}.{row_path}.{key}", row.get(key))


def _badge_keys_in_cell(path: str, value: Any) -> Iterator[tuple[str, str]]:
    placed = (
        [(f"{path}.{index}", key) for index, key in enumerate(cast("list[Any]", value))]
        if isinstance(value, list)
        else [(path, value)]
    )
    for place, candidate in placed:
        if isinstance(candidate, str) and candidate.strip():
            yield place, candidate.strip()


def iter_reference_items(blocks: Sequence[AnyBlock]) -> Iterator[ReferenceItem]:
    """Every reference item in the block tree (recursing into sections and grids), in document
    order. One source for both the derived numbering and the global key-uniqueness check."""
    for block in walk_blocks(blocks):
        if isinstance(block, References):
            yield from block.items


def iter_matrices(blocks: Sequence[AnyBlock]) -> Iterator[Matrix]:
    """Every matrix in the block tree (recursing into containers), in document order — for the derived
    cell tallies and the matrix-id uniqueness / `of_matrix` reference checks."""
    for block in walk_blocks(blocks):
        if isinstance(block, Matrix):
            yield block


def iter_tables(blocks: Sequence[AnyBlock]) -> Iterator[Table]:
    """Every table in the block tree (recursing into containers), in document order — for the derived
    row tallies and the table-id uniqueness / `of_tables` reference checks."""
    for block in walk_blocks(blocks):
        if isinstance(block, Table):
            yield block


def _relative_part_path(path: str) -> str:
    if Path(path).is_absolute():
        raise ValueError(f"a part path is relative to the index file, not absolute: {path}")
    return path


PartPath = Annotated[NonBlank, AfterValidator(_relative_part_path)]


class Index(FrozenModel):
    layout: Literal["one_page"] = Field(
        default="one_page",
        description="How the parts combine: `one_page` builds one page holding every part in order, each "
        "under its own title.",
    )
    parts: list[PartPath] = Field(
        min_length=1,
        description="The skaldr documents this index combines, in order, each a path relative to the index "
        "file. A part's `meta.title` becomes its part title; its blocks follow unchanged; its badges merge "
        "into the page. A part cannot be an index itself.",
    )
    collapsed: bool = Field(
        default=False,
        description="Whether every part starts collapsed (a collapsible in HTML, a toggle heading in the "
        "exports). Default false: every part is open.",
    )

    @field_validator("parts")
    @classmethod
    def _each_part_listed_once(cls, parts: list[str]) -> list[str]:
        repeated = sorted({part for part, count in Counter(parts).items() if count > 1})
        if repeated:
            raise ValueError(f"a part is listed more than once: {', '.join(repeated)}; list each part once")
        return parts


class Report(FrozenModel):
    version: Literal[1] = Field(description="Content-file schema version.")
    meta: Meta
    badges: dict[str, Badge] = Field(
        default_factory=dict, description="Author-declared tag/status vocabulary."
    )
    index: Index | None = Field(
        default=None,
        description="Makes this document an index: one page built from other skaldr documents. `blocks` "
        "becomes optional and, when present, opens the page before the first part.",
    )
    blocks: list[PageBlock] = Field(default_factory=list[PageBlock], min_length=1)
    publish: Publish | None = Field(
        default=None,
        description="Where the document publishes (Notion pages, Jira issues). Omitted from the source "
        "embedded in a rendered page. Not yet accepted on an index document.",
    )

    @model_validator(mode="after")
    def _refuse_an_index_that_was_not_loaded(self) -> "Report":
        if self.index is not None:
            raise ValueError(
                "`index` is read when its file is loaded, which brings in every part; load the index file "
                "rather than its parsed data"
            )
        return self

    @model_validator(mode="after")
    def _refuse_a_page_without_blocks(self) -> "Report":
        if not self.blocks:
            raise ValueError("`blocks` needs at least one block; only an index document may leave it out")
        return self

    @model_validator(mode="after")
    def _validate_publish_sections(self) -> "Report":
        if self.publish is None:
            return self
        section_ids = [block.id for block in self.blocks if isinstance(block, Section) and block.id]
        errors = section_choice_errors(self.publish, section_ids)
        if errors:
            raise ValueError("; ".join(errors))
        return self

    @model_validator(mode="after")
    def _validate_badge_references(self) -> "Report":
        undeclared = [
            (path, key) for path, key in iter_located_badge_keys(self.blocks) if key not in self.badges
        ]
        if undeclared:
            keys = sorted({key for _, key in undeclared})
            where = ", ".join(f"{path} ({key!r})" for path, key in undeclared)
            raise ValueError(
                f"badge key(s) not declared in `badges`: {keys}, at {where}; add them to the badges map"
            )
        return self

    @cached_property
    def located_blocks(self) -> list[tuple[str, AnyBlock]]:
        return list(walk_located_blocks(self.blocks))

    def _located_cards(self) -> Iterator[tuple[str, Card]]:
        for path, block in self.located_blocks:
            if isinstance(block, Cards):
                for index, card in enumerate(block.items):
                    yield f"{path}.items.{index}", card

    @model_validator(mode="after")
    def _validate_matrix_references(self) -> "Report":
        placed = [
            (f"{path}.id", block.id)
            for path, block in self.located_blocks
            if isinstance(block, Matrix) and block.id is not None
        ]
        _refuse_repeats(placed, "matrix id(s)", "matrix ids must be unique")
        matrix_ids = {matrix_id for _, matrix_id in placed}
        for path, card in self._located_cards():
            if card.of_matrix is not None and card.of_matrix not in matrix_ids:
                raise ValueError(
                    f"card of_matrix names '{card.of_matrix}', which is not the id of any matrix, at "
                    f"{path}.of_matrix"
                )
        return self

    @model_validator(mode="after")
    def _validate_table_references(self) -> "Report":
        tables = [
            (f"{path}.id", block.id, block)
            for path, block in self.located_blocks
            if isinstance(block, Table) and block.id is not None
        ]
        _refuse_repeats(
            [(path, table_id) for path, table_id, _ in tables], "table id(s)", "table ids must be unique"
        )
        rollups = {table_id: table.rollup is not None for _, table_id, table in tables}
        for path, card in self._located_cards():
            for index, table_id in enumerate(card.of_tables or []):
                where = f"{path}.of_tables.{index}"
                if table_id not in rollups:
                    raise ValueError(
                        f"card of_tables names '{table_id}', which is not the id of any table, at {where}"
                    )
                if not rollups[table_id]:
                    raise ValueError(
                        f"card of_tables names '{table_id}', which is a table with no `rollup`, at {where}; "
                        "of_tables counts a badge with each table's rollup column, so the table must "
                        "declare one"
                    )
        return self

    @model_validator(mode="after")
    def _validate_request_storage_keys_unique(self) -> "Report":
        _refuse_repeats(
            [
                (path, block.id or block.label)
                for path, block in self.located_blocks
                if isinstance(block, Request | RequestFlow)
            ],
            "request block label(s)",
            "request labels must be unique, because a label keys what a reader's fields are remembered "
            "under while their tab is open: give one of them an `id`",
        )
        return self

    @model_validator(mode="after")
    def _validate_reference_keys_unique(self) -> "Report":
        _refuse_repeats(
            [
                (f"{path}.items.{index}.key", item.key)
                for path, block in self.located_blocks
                if isinstance(block, References)
                for index, item in enumerate(block.items)
            ],
            "reference key(s)",
            "reference keys must be unique",
        )
        return self

    @model_validator(mode="after")
    def _validate_anchor_ids_unique(self) -> "Report":
        _refuse_repeats(
            [
                (f"{path}.id", block.id)
                for path, block in self.located_blocks
                if isinstance(block, Heading | Section) and block.id is not None
            ],
            "heading/section id(s)",
            "heading and section ids must be unique",
        )
        return self


def _refuse_repeats(placed: Sequence[tuple[str, str]], what: str, reason: str) -> None:
    counts = Counter(value for _, value in placed)
    repeated = sorted(value for value, count in counts.items() if count > 1)
    if repeated:
        where = ", ".join(path for path, value in placed if counts[value] > 1)
        raise ValueError(f"{what} used more than once: {repeated}, at {where}; {reason}")


def _format_validation_error(error: ValidationError, within: tuple[str, ...] = ()) -> str:
    lines: list[str] = []
    for issue in error.errors():
        location = ".".join(str(part) for part in (*within, *issue["loc"]))
        lines.append(f"{location}: {issue['msg']}" if location else issue["msg"])
    return "invalid content data: " + "; ".join(lines)


def read_text_file(path: Path) -> str:
    if not path.exists():
        raise ReportError(f"file not found: {path}")
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as err:
        raise ReportError(f"could not read {path}: {err}") from err


def _first_unencodable(text: str) -> str | None:
    try:
        text.encode("utf-8")
    except UnicodeEncodeError as err:
        return f"U+{ord(text[err.start]):04X}"
    return None


def _refuse_unencodable_text(data: object, location: tuple[str, ...]) -> None:
    where = ".".join(location)
    prefix = f"invalid content data: {where}: " if where else "invalid content data: "
    if isinstance(data, str):
        code_point = _first_unencodable(data)
        if code_point is not None:
            raise ReportError(f"{prefix}{code_point} is a lone surrogate, which a page cannot hold")
        return
    if isinstance(data, Mapping):
        for key, value in cast("Mapping[object, object]", data).items():
            key_code_point = _first_unencodable(key) if isinstance(key, str) else None
            if key_code_point is not None:
                raise ReportError(
                    f"{prefix}the key {key!r} holds {key_code_point}, a lone surrogate, "
                    "which a page cannot hold"
                )
            _refuse_unencodable_text(value, (*location, str(key)))
        return
    if isinstance(data, list | tuple):
        for index, item in enumerate(cast("Sequence[object]", data)):
            _refuse_unencodable_text(item, (*location, str(index)))


def parse_report(data: Any, *, built_by_an_index: bool = False) -> Report:
    _refuse_unencodable_text(data, ())
    try:
        return Report.model_validate(data, context={BUILT_BY_AN_INDEX: built_by_an_index})
    except ValidationError as err:
        raise ReportError(_format_validation_error(err)) from err


# Non-cyclic depth cap: cycles are already caught by `ancestors`, but a pathological non-cyclic chain
# would recurse until Python's own recursion limit and surface as a raw RecursionError. Every other
# load failure is a ReportError, so cap the depth to keep that contract. Real docs never nest this far.
_MAX_INCLUDE_DEPTH = 50


def _load_yaml_with_includes(path: Path, ancestors: tuple[Path, ...], loaded: list[Path]) -> Any:
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
        raise ReportError(f"!include nested more than {_MAX_INCLUDE_DEPTH} deep at {path}, likely a mistake")
    text = read_text_file(path)
    loaded.append(resolved)

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
        return _load_yaml_with_includes(path.parent / target, (*ancestors, resolved), loaded)

    _IncludeLoader.add_constructor("!include", _construct_include)
    try:
        return yaml.load(text, Loader=_IncludeLoader)
    except yaml.YAMLError as err:
        raise ReportError(f"invalid YAML in {path}: {err}") from err


def _index_of(data: object) -> object:
    return cast("Mapping[str, object]", data).get("index") if isinstance(data, Mapping) else None


class _LoadedPart(NamedTuple):
    path: Path
    data: Mapping[str, Any]
    report: Report


def _parsed_index(data: object) -> Index:
    try:
        return Index.model_validate(data)
    except ValidationError as err:
        raise ReportError(_format_validation_error(err, ("index",))) from err


def _loaded_part(path: Path) -> _LoadedPart:
    data = _load_yaml_with_includes(path, (), [])
    if _index_of(data) is not None:
        raise ReportError(f"part {path} is itself an index; an index lists document files, not other indexes")
    try:
        report = parse_report(data)
    except ReportError as err:
        raise ReportError(f"in part {path}: {err}") from err
    return _LoadedPart(path, cast("Mapping[str, Any]", data), report)


_BADGES: Final = TypeAdapter(dict[str, Badge])


def _parsed_badges(data: object) -> dict[str, Badge]:
    try:
        return _BADGES.validate_python(data)
    except ValidationError as err:
        raise ReportError(_format_validation_error(err, ("badges",))) from err


def _merged_badges(declared: Sequence[tuple[Path, Mapping[str, Badge]]]) -> dict[str, Any]:
    merged: dict[str, Badge] = {}
    declared_in: dict[str, Path] = {}
    for path, badges in declared:
        for key, badge in badges.items():
            if key in merged and merged[key] != badge:
                raise ReportError(
                    f"badge {key!r} is declared differently in {declared_in[key]} and {path}; "
                    "an index merges every part's badges, "
                    "so give it one label, tone and legend or rename one key"
                )
            merged.setdefault(key, badge)
            declared_in.setdefault(key, path)
    return {key: badge.model_dump(mode="json") for key, badge in merged.items()}


def _part_block(part: _LoadedPart, index: Index) -> dict[str, Any]:
    return {
        "type": "part",
        "title": part.report.meta.title,
        "collapsed": index.collapsed,
        "blocks": part.data["blocks"],
    }


_INTRO_BLOCKS: Final = TypeAdapter(list[PageBlock])


def _intro_blocks(data: Mapping[str, Any]) -> list[object]:
    intro: object = data.get("blocks", [])
    try:
        _INTRO_BLOCKS.validate_python(intro, context={BUILT_BY_AN_INDEX: False})
    except ValidationError as err:
        raise ReportError(_format_validation_error(err, ("blocks",))) from err
    return cast("list[object]", intro)


class _Document(NamedTuple):
    data: object
    parts: tuple[tuple[int, Path], ...] = ()


def _combined_index(path: Path, data: Mapping[str, Any], index: Index) -> _Document:
    if data.get("publish") is not None:
        raise ReportError("an index document cannot carry `publish` yet; publish each part file on its own")
    intro = _intro_blocks(data)
    parts = [_loaded_part(path.parent / part_path) for part_path in index.parts]
    own_badges = _parsed_badges(data.get("badges", {}))
    badges = _merged_badges([(path, own_badges), *((part.path, part.report.badges) for part in parts)])
    page = {key: value for key, value in data.items() if key != "index"}
    combined = {**page, "badges": badges, "blocks": [*intro, *(_part_block(part, index) for part in parts)]}
    return _Document(combined, tuple(enumerate((part.path for part in parts), start=len(intro))))


def _load_document(path: Path) -> _Document:
    data = _load_yaml_with_includes(path, (), [])
    index = _index_of(data)
    if index is None:
        return _Document(data)
    return _combined_index(path, cast("Mapping[str, Any]", data), _parsed_index(index))


_PART_PLACE = re.compile(r"\bblocks\.(\d+)\.part\b")


def _parts_named_in(message: str, parts: Sequence[tuple[int, Path]]) -> str | None:
    named = {int(position) for position in _PART_PLACE.findall(message)}
    places = [f"blocks.{position} is {path}" for position, path in parts if position in named]
    if not places:
        return None
    listed = places[0] if len(places) == 1 else f"{', '.join(places[:-1])} and {places[-1]}"
    return f"in this index, {listed}"


def load_report(path: Path) -> Report:
    document = _load_document(path)
    try:
        return parse_report(document.data, built_by_an_index=bool(document.parts))
    except ReportError as err:
        where = _parts_named_in(str(err), document.parts)
        if where is None:
            raise
        raise ReportError(f"{err}; {where}") from err


def content_files(path: Path) -> tuple[Path, ...]:
    loaded: list[Path] = []
    index = _index_of(_load_yaml_with_includes(path, (), loaded))
    if index is not None:
        for part_path in _parsed_index(index).parts:
            _load_yaml_with_includes(path.parent / part_path, (), loaded)
    return tuple(loaded)
