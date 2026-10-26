from collections.abc import Callable, Mapping
from typing import Annotated, Any, Final, Literal, cast

from pydantic import Discriminator, Field, Tag, field_validator, model_validator

from skaldr.errors import ReportError
from skaldr.frozen_model import FrozenModel
from skaldr.mathml import refuse_invalid_math
from skaldr.models.base import BlockBase
from skaldr.models.primitives import (
    ANCHOR_ID_PATTERN,
    NUMBER_GUARD,
    REFERENCE_KEY_PATTERN,
    WEB_URL_SCHEMES,
    BadgeColor,
    CalloutTone,
    ChartVariant,
    CodeLanguage,
    Count,
    DeltaDirection,
    FanDirection,
    FlowStyle,
    Icon,
    NonBlank,
    NonBlankRichProse,
    NonBlankRichText,
    Number,
    RichProse,
    RichText,
    StatusState,
    TimelineState,
    Tone,
    is_data_uri,
    require_url_scheme,
    require_web_url,
)


class Heading(BlockBase):
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


class Text(BlockBase):
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


ListKind = Literal["bullet", "number", "check"]
ListStyle = Literal[ListKind, "decision"]
ListNumbering = Literal["decimal", "letters", "roman"]
LARGEST_LIST_START: Final = 999_999_999


class ListBlock(BlockBase):
    type: Literal["list"]
    style: ListStyle = Field(
        default="bullet",
        description="Bulleted, numbered, or `check`, which shows tickable checkboxes for a live checklist "
        "(the ticks are ephemeral: a browser reload resets them). `decision` marks each point as a "
        "decision taken (`decided: true`) or an open question.",
    )
    start: Annotated[int, Field(ge=1, le=LARGEST_LIST_START), NUMBER_GUARD] | None = Field(
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


class FactStrip(BlockBase):
    type: Literal["fact_strip"]
    facts: list[Fact] = Field(min_length=1, max_length=8, description="1-8 label/value pairs, one line.")


class KVPair(FrozenModel):
    label: str = Field(description="Row label (muted).")
    value: RichText = Field(description="Rich-text value.")


class KeyValue(BlockBase):
    type: Literal["key_value"]
    pairs: list[KVPair] = Field(min_length=1, description="Vertical label/value metadata rows.")


class DefItem(FrozenModel):
    term: NonBlank = Field(description="The label/term, rendered prominent (e.g. 'Action').")
    body: RichProse = Field(min_length=1, description="Rich-text definition; blank lines split paragraphs.")


class DefList(BlockBase):
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

    @property
    def counted_badge(self) -> str:
        if not self.derived or self.badge is None:
            raise ValueError("a card that is not derived counts no badge")
        return self.badge

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


class Cards(BlockBase):
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


class BadgeRow(BlockBase):
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
        if bool(self.items) == bool(self.groups):
            raise ValueError("a badge row needs exactly one of 'items' or 'groups'")
        if self.groups and self.label is not None:
            raise ValueError("badge row 'label' applies to a flat 'items' row, not 'groups'")
        return self


class Callout(BlockBase):
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


class StatusList(BlockBase):
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


class Meter(BlockBase):
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


class Range(BlockBase):
    type: Literal["range"]
    segments: list[RangeSegment] = Field(
        min_length=1, description="Segments laid left-to-right, each sized in proportion to its span."
    )
    axis: RangeAxis | None = Field(
        default=None, description="Optional end-cap labels marking the bar's extent."
    )


class Code(BlockBase):
    type: Literal["code"]
    content: str = Field(
        description="Code/log/config text; shown verbatim, highlighted in the HTML if the language is known."
    )
    label: str | None = Field(default=None, description="Optional label header above the block.")
    mode: Literal["plain", "diff"] = Field(
        default="plain", description="plain, or diff (+/- lines tinted success/danger)."
    )
    lang: CodeLanguage | None = Field(
        default=None,
        description="Optional language of the code, such as `shell`, `python` or `plain text`: the Markdown "
        "exports put it on the code fence and the HTML highlights with it. Unset, the language comes from a "
        "file name in `label` (`deploy.sh` is bash); with neither, the HTML shows plain code, the GitHub "
        "fence has no language and the Notion fence says `plain text`. `mode: diff` exports as `diff`.",
    )


class Math(BlockBase):
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


class Quote(BlockBase):
    type: Literal["quote"]
    body: RichProse = Field(description="Rich-text quotation.")
    cite: str | None = Field(default=None, description="Optional attribution line.")


class Note(BlockBase):
    type: Literal["note"]
    body: NonBlankRichProse = Field(description="Rich-text aside; blank lines split paragraphs.")
    title: str | None = Field(default=None, description="Optional label for the note.")
    icon: Icon | None = Field(
        default=None,
        description="Optional single emoji shown at the head of the note, in place of the default note "
        "icon in the Markdown exports.",
    )


class Divider(BlockBase):
    type: Literal["divider"]


class Image(BlockBase):
    type: Literal["image"]
    src: str = Field(
        description="A data: URI (self-contained, shown in the page) or an http(s) URL (shown as a link "
        "card on the page, as an image in a Markdown export). Base64-encode a data: payload "
        "(e.g. data:image/svg+xml;base64,...); a raw, unencoded SVG isn't a valid URI and won't render. "
        "A URL may not carry a username or password."
    )
    alt: str = Field(description="Alt text for the image. Required, and it must hold visible text.")
    caption: str | None = Field(default=None, description="Optional caption shown below the image.")
    max_width: Count | None = Field(default=None, description="Optional max width in pixels.")

    @model_validator(mode="before")
    @classmethod
    def _alt_must_hold_visible_text(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        fields = cast("dict[str, Any]", data)
        alt = fields.get("alt", "")
        if isinstance(alt, str) and not alt.strip():
            raise ValueError("'alt' must hold visible text")
        return fields

    @model_validator(mode="after")
    def _data_uri_or_web_url(self) -> "Image":
        if is_data_uri(self.src):
            return self
        if not self.src.startswith(WEB_URL_SCHEMES):
            raise ValueError("'src' must be a data: URI or an http:// or https:// URL")
        require_web_url(self.src, "'src'")
        return self


MediaKind = Literal["video", "audio", "file", "pdf"]
MEDIA_KIND_LABELS: Final[Mapping[MediaKind, str]] = {
    "video": "Video",
    "audio": "Audio",
    "file": "File",
    "pdf": "PDF",
}


class Media(BlockBase):
    type: Literal["media"]
    kind: MediaKind = Field(description="What the URL points at: video, audio, file or pdf.")
    src: str = Field(
        description="An http(s) URL, shown as a link card on the page and as a link in a Markdown "
        "export. It may not carry a username or password."
    )
    caption: str | None = Field(default=None, description="Optional caption naming the media.")

    @model_validator(mode="after")
    def _web_url_only(self) -> "Media":
        require_web_url(self.src, "'src'")
        return self


LinkDisplay = Literal["inline", "card", "embed"]


class Link(BlockBase):
    type: Literal["link"]
    url: str = Field(description="An http:// or https:// address.")
    display: LinkDisplay = Field(
        default="card",
        description="`inline` is a plain link in a line of text; `card` is a bordered card with the title, "
        "the domain and the caption; `embed` asks for the page to be shown in place. The HTML page loads "
        "nothing from outside, so an embed renders as the card with a note, and both Markdown exports "
        "write an embed as the card.",
    )
    title: NonBlank | None = Field(
        default=None, description="Link text or card title; the URL without its scheme when omitted."
    )
    caption: NonBlank | None = Field(
        default=None, description="A line under a card or embed; not allowed on an inline link."
    )

    @model_validator(mode="after")
    def _web_url_and_no_inline_caption(self) -> "Link":
        require_web_url(self.url, "'url'")
        if self.display == "inline" and self.caption is not None:
            raise ValueError("a link shown inline takes no caption; use display: card or display: embed")
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


class Timeline(BlockBase):
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


class Flow(BlockBase):
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


class Fan(BlockBase):
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


class Chart(BlockBase):
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
        require_url_scheme(self.url, "'url'")
        return self


class References(BlockBase):
    type: Literal["references"]
    items: list[ReferenceItem] = Field(
        min_length=1, description="Numbered sources; cite each inline with [^key]."
    )
