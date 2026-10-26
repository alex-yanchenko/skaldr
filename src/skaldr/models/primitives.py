import math
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Annotated, Any, Final, Literal
from urllib.parse import urlsplit

import emoji
from pydantic import (
    AfterValidator,
    AnyUrl,
    BeforeValidator,
    Field,
    StringConstraints,
    TypeAdapter,
    ValidationError,
)

from skaldr.patterns import SLUG_PATTERN

ALLOWED_URL_SCHEMES = ("http://", "https://", "mailto:")
_LINK_URL: TypeAdapter[AnyUrl] = TypeAdapter(AnyUrl)


def url_defect(url: str) -> str | None:
    if any(character.isspace() for character in url):
        return "it holds whitespace"
    try:
        parsed = _LINK_URL.validate_python(url)
    except ValidationError as err:
        return err.errors()[0]["msg"].removeprefix("Input should be a valid URL, ")
    if parsed.scheme == "mailto" and not parsed.path:
        return "it names no address"
    if "@" in urlsplit(url).netloc:
        return "it holds a username or password"
    return None


LINK_URL_WORDING = "an http://, https://, or mailto: link"
WEB_URL_SCHEMES = ("http://", "https://")
WEB_URL_WORDING = "an http:// or https:// link"
DATA_URI_SCHEME: Final = "data:"


def is_data_uri(src: str) -> bool:
    return src.startswith(DATA_URI_SCHEME)


def _require_scheme_and_well_formed(url: str, subject: str, schemes: tuple[str, ...], wording: str) -> None:
    if not url.startswith(schemes):
        raise ValueError(f"{subject} must be {wording}")
    defect = url_defect(url)
    if defect is not None:
        raise ValueError(f"{subject} {url!r} is not a valid URL ({defect})")


def require_web_url(url: str, subject: str) -> None:
    _require_scheme_and_well_formed(url, subject, WEB_URL_SCHEMES, WEB_URL_WORDING)


def require_url_scheme(url: str | None, subject: str) -> None:
    if url is not None:
        _require_scheme_and_well_formed(url, subject, ALLOWED_URL_SCHEMES, LINK_URL_WORDING)


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


def refuse_an_unusable_number(value: int | float, location: str) -> None:
    try:
        _reject_bool_and_non_finite(value)
    except ValueError as error:
        raise ValueError(f"{location}: {error}") from error


# Numeric field types that reject bool + non-finite before pydantic coerces them.
# Number keeps the int-vs-float distinction (a card's `600` stays an int); Count is int-only.
NUMBER_GUARD = BeforeValidator(_reject_bool_and_non_finite)
_NUMBER_BOUND_IN_SCHEMA = Field(json_schema_extra={"minimum": -LARGEST_NUMBER, "maximum": LARGEST_NUMBER})
Number = Annotated[int | float, NUMBER_GUARD, _NUMBER_BOUND_IN_SCHEMA]


def _refuse_a_negative_number(value: int | float) -> int | float:
    if value < 0:
        raise ValueError("must not be negative")
    return value


NonNegativeNumber = Annotated[
    int | float,
    NUMBER_GUARD,
    AfterValidator(_refuse_a_negative_number),
    Field(json_schema_extra={"minimum": 0, "maximum": LARGEST_NUMBER}),
]
Count = Annotated[int, NUMBER_GUARD, _NUMBER_BOUND_IN_SCHEMA]
SixthsCount = Annotated[int, Field(ge=1, le=6), NUMBER_GUARD]


NonBlank = Annotated[str, StringConstraints(min_length=1, pattern=r"\S")]
CodeLanguage = Annotated[
    str, StringConstraints(max_length=40, pattern=r"^[A-Za-z0-9#+._-]+( [A-Za-z0-9#+._-]+)*$")
]

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


def to_tone(value: Any) -> Any:
    """Normalise a palette colour name to its semantic tone twin (green → success); pass anything else
    through unchanged (semantic names, teal/sky, non-strings)."""
    return _PALETTE_TO_TONE.get(value, value) if isinstance(value, str) else value


def badge_color_of(tone: ToneLiteral) -> BadgeColorLiteral:
    return TONE_BADGE_COLOR[tone]


def _to_badge_color(value: Any) -> Any:
    """Normalise a semantic tone name to its palette colour twin (success → green); pass anything else
    through unchanged (palette names, teal/sky, non-strings)."""
    return _TONE_TO_PALETTE.get(value, value) if isinstance(value, str) else value


Tone = Annotated[ToneLiteral, BeforeValidator(to_tone)]
BadgeColor = Annotated[BadgeColorLiteral, BeforeValidator(_to_badge_color)]
_CALLOUT_TONES = ("info", "success", "warning", "danger")


def _to_callout_tone(value: Any) -> Any:
    """Normalise a palette alias to its semantic twin (blue→info), then reject a tone that isn't one of
    the four callout meanings, naming both what was given and the allowed set, so the fix is obvious in
    the error itself. A callout is a semantic 'stop and look' note, so teal/sky/accent/neutral (fine on
    cards/badges) have no callout look and are refused rather than silently mapped."""
    normalized = to_tone(value)
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
MAX_STRIP_LABELS = 24
"""How many labels one tab strip may carry: a call's cases, or a tabs block's tabs. The stylesheet pairs
a radio with its label by position, and writes that many pairs, so a label past this one would render
without ever lighting up."""


def check_distinct_strip_labels(labels: Iterable[str], refusal: str) -> None:
    repeated = sorted(label for label, count in Counter(labels).items() if count > 1)
    if repeated:
        raise ValueError(f"{refusal}: {', '.join(repeated)}")
