from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Final, Literal

from skaldr.export_targets import EXPORT_TARGETS, ExportTarget
from skaldr.richtext import ScriptPosition

PlacementFeature = Literal[
    "table inside a callout",
    "callout inside a callout",
    "quote inside a callout",
    "toggle inside a callout",
    "table inside a toggle inside a toggle",
    "toggle inside a toggle inside a toggle",
]
ListItemFeature = Literal["block inside a list item", "block inside a walkthrough step"]
ListStartFeature = Literal["numbered list starting past 1"]
CellCountFeature = Literal["table over 300 cells"]
GridInAStepFeature = Literal["grid inside a walkthrough step"]
ScriptFormFeature = Literal["subscript or superscript with no Unicode form"]
TextMarkFeature = Literal[
    "colour span",
    "highlight span",
    "colour and highlight span",
    "underline",
    "highlight span inside a toned walkthrough step title",
]
SameDocumentLinkFeature = Literal["link to a heading of the same document"]
OtherDocumentLinkFeature = Literal["link to another skaldr document"]
InlineCodeFeature = Literal[
    "inline code holding a backtick",
    "inline code holding a closing tag in a table cell",
    "inline code holding a closing tag in a coloured or highlighted span",
]
TextNumberingFeature = Literal["list numbered with letters or roman numerals"]
FencedInAListItemFeature = Literal[
    "table, callout, heading, quote, toggle or divider inside a list item or walkthrough step"
]
ListInAQuoteFeature = Literal["list inside a quote"]
Feature = Literal[
    PlacementFeature,
    ListItemFeature,
    ListStartFeature,
    CellCountFeature,
    GridInAStepFeature,
    ScriptFormFeature,
    TextMarkFeature,
    SameDocumentLinkFeature,
    OtherDocumentLinkFeature,
    InlineCodeFeature,
    TextNumberingFeature,
    FencedInAListItemFeature,
    ListInAQuoteFeature,
]
Holder = Literal["callout", "toggle inside a toggle"]
Container = Literal["document", "toggle", Holder]
Held = Literal["table", "callout", "quote", "toggle"]
FIRST_LIST_NUMBER: Final = 1
BACKTICK: Final = "`"
CLOSING_TAG_OPENER: Final = "</"
CANVAS_TABLE_CELL_LIMIT: Final = 300
UNICODE_SCRIPT_FORMS: Final[Mapping[ScriptPosition, Mapping[int, int]]] = {
    "superscript": str.maketrans(
        "0123456789+-\N{MINUS SIGN}=()ABDEGHIJKLMNOPRTUVWabcdefghijklmnoprstuvwxyz",
        "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁻⁼⁽⁾ᴬᴮᴰᴱᴳᴴᴵᴶᴷᴸᴹᴺᴼᴾᴿᵀᵁⱽᵂᵃᵇᶜᵈᵉᶠᵍʰⁱʲᵏˡᵐⁿᵒᵖʳˢᵗᵘᵛʷˣʸᶻ",
    ),
    "subscript": str.maketrans(
        "0123456789+-\N{MINUS SIGN}=()aehijklmnoprstuvx",
        "₀₁₂₃₄₅₆₇₈₉₊₋₋₌₍₎ₐₑₕᵢⱼₖₗₘₙₒₚᵣₛₜᵤᵥₓ",
    ),
}


@dataclass(frozen=True)
class Placement:
    feature: PlacementFeature
    held: str
    holder: str
    holder_name: str


@dataclass(frozen=True)
class HeldByAListItem:
    feature: ListItemFeature
    held: str


@dataclass(frozen=True)
class ListStart:
    start: int
    feature: ListStartFeature = field(default="numbered list starting past 1", init=False)


@dataclass(frozen=True)
class CellCount:
    cells: int
    limit: int = CANVAS_TABLE_CELL_LIMIT
    feature: CellCountFeature = field(default="table over 300 cells", init=False)


@dataclass(frozen=True)
class GridInAStep:
    feature: GridInAStepFeature = field(default="grid inside a walkthrough step", init=False)


@dataclass(frozen=True)
class ScriptForm:
    position: ScriptPosition
    text: str
    character: str
    feature: ScriptFormFeature = field(default="subscript or superscript with no Unicode form", init=False)


@dataclass(frozen=True)
class MarkedText:
    feature: TextMarkFeature
    text: str


@dataclass(frozen=True)
class SameDocumentLink:
    text: str
    link: str
    feature: SameDocumentLinkFeature = field(default="link to a heading of the same document", init=False)


@dataclass(frozen=True)
class OtherDocumentLink:
    text: str
    doc_id: str
    feature: OtherDocumentLinkFeature = field(default="link to another skaldr document", init=False)


@dataclass(frozen=True)
class InlineCode:
    feature: InlineCodeFeature
    code: str


@dataclass(frozen=True)
class TextNumbering:
    numbering: Literal["letters", "roman numerals"]
    feature: TextNumberingFeature = field(default="list numbered with letters or roman numerals", init=False)


@dataclass(frozen=True)
class FencedInAListItem:
    held: str
    item: Literal["list item", "walkthrough step"]
    out_of: Literal["list", "step"]
    after: Literal["list", "walkthrough"]
    feature: FencedInAListItemFeature = field(
        default="table, callout, heading, quote, toggle or divider inside a list item or walkthrough step",
        init=False,
    )

    @classmethod
    def in_a_list_item(cls, held: str) -> "FencedInAListItem":
        return cls(held, "list item", "list", "list")

    @classmethod
    def in_a_walkthrough_step(cls, held: str) -> "FencedInAListItem":
        return cls(held, "walkthrough step", "step", "walkthrough")


@dataclass(frozen=True)
class ListInAQuote:
    feature: ListInAQuoteFeature = field(default="list inside a quote", init=False)


Details = (
    Placement
    | HeldByAListItem
    | ListStart
    | CellCount
    | GridInAStep
    | ScriptForm
    | MarkedText
    | SameDocumentLink
    | OtherDocumentLink
    | InlineCode
    | TextNumbering
    | FencedInAListItem
    | ListInAQuote
)


@dataclass(frozen=True)
class Rejection:
    why: str
    instead: str
    names_the_heading: bool = False


Capability = Literal["keep"] | Rejection

_ADF_CANNOT_PLACE: Final = Rejection(
    "ADF cannot place a {held} inside {holder}",
    "move the {held} out of the {holder_name}",
    names_the_heading=True,
)
_CANVAS_LIST_ITEM_WHY: Final = (
    "a Slack canvas list item holds only text and one nested list, so it cannot show {held}"
)
_WITHOUT_THE_MARK: Final = "write the text without the {mark} or export the document elsewhere"
_WITHOUT_THE_COLOUR: Final = _WITHOUT_THE_MARK.format(mark="colour")
_GITHUB_CANNOT_COLOUR: Final = Rejection(
    "GitHub Markdown cannot colour text, so it cannot show the colour of '{text}'", _WITHOUT_THE_COLOUR
)
_CANVAS_CANNOT_COLOUR: Final = Rejection(
    "a Slack canvas cannot colour text, so it cannot show the colour of '{text}'", _WITHOUT_THE_COLOUR
)
_WITHOUT_THE_HIGHLIGHT: Final = _WITHOUT_THE_MARK.format(mark="highlight")
_JIRA_CANNOT_HIGHLIGHT: Final = Rejection(
    "a Jira description does not show a text highlight, so it cannot show the highlight on '{text}'",
    _WITHOUT_THE_HIGHLIGHT,
)
_FROM_ONE_WHY: Final = (
    "{target} numbers every list from 1, so it cannot show a numbered list that starts at {{start}}"
)
_FROM_ONE_INSTEAD: Final = "number the list from 1, or export it elsewhere"
_OWN_HEADING_WHY: Final = (
    "{target} cannot link to its own headings, so it cannot show the link '{{text}}' to '{{link}}'"
)
_OWN_HEADING_INSTEAD: Final = "write the heading's name without the link, or export the document elsewhere"
_OTHER_DOCUMENT_WHY: Final = (
    "{target} cannot link '{{text}}' to the document '{{doc_id}}', "
    "since skaldr has no address for that document there"
)
_OTHER_DOCUMENT_INSTEAD: Final = "link to the document's https address, or export it elsewhere"
_DIGITS_ONLY_WHY: Final = (
    "{target} numbers a list only with digits, so it cannot show a list numbered with {{numbering}}"
)
_DIGITS_ONLY_INSTEAD: Final = "number the list with digits, or export it elsewhere"


def _kept_except(cells: Mapping[ExportTarget, Capability]) -> dict[ExportTarget, Capability]:
    kept: dict[ExportTarget, Capability] = dict.fromkeys(EXPORT_TARGETS, "keep")
    return {**kept, **cells}


CAPABILITIES: Final[Mapping[Feature, Mapping[ExportTarget, Capability]]] = {
    "table inside a callout": _kept_except({"adf": _ADF_CANNOT_PLACE}),
    "callout inside a callout": _kept_except({"adf": _ADF_CANNOT_PLACE}),
    "quote inside a callout": _kept_except({"adf": _ADF_CANNOT_PLACE}),
    "toggle inside a callout": _kept_except({"adf": _ADF_CANNOT_PLACE}),
    "table inside a toggle inside a toggle": _kept_except({"adf": _ADF_CANNOT_PLACE}),
    "toggle inside a toggle inside a toggle": _kept_except({"adf": _ADF_CANNOT_PLACE}),
    "block inside a list item": _kept_except(
        {"slack": Rejection(_CANVAS_LIST_ITEM_WHY, "move it out of the list, after the list")}
    ),
    "block inside a walkthrough step": _kept_except(
        {"slack": Rejection(_CANVAS_LIST_ITEM_WHY, "move it out of the step, after the walkthrough")}
    ),
    "numbered list starting past 1": _kept_except(
        {
            "notion": Rejection(_FROM_ONE_WHY.format(target="Notion"), _FROM_ONE_INSTEAD),
            "slack": Rejection(_FROM_ONE_WHY.format(target="a Slack canvas"), _FROM_ONE_INSTEAD),
        }
    ),
    "table over 300 cells": _kept_except(
        {
            "slack": Rejection(
                "a table has {cells:,} cells, over the {limit} a Slack canvas table can hold",
                "split it into two tables or export it elsewhere",
                names_the_heading=True,
            )
        }
    ),
    "grid inside a walkthrough step": _kept_except(
        {
            "slack": Rejection(
                "a Slack canvas cannot show a grid inside a walkthrough step, "
                "since a canvas list item holds only text",
                "move the grid out of the step, after the walkthrough",
            )
        }
    ),
    "subscript or superscript with no Unicode form": _kept_except(
        {
            "slack": Rejection(
                "a Slack canvas cannot show the {position} '{text}', "
                "since '{character}' has no Unicode {position} form",
                _WITHOUT_THE_MARK.format(mark="{position}"),
            )
        }
    ),
    "colour span": _kept_except({"markdown": _GITHUB_CANNOT_COLOUR, "slack": _CANVAS_CANNOT_COLOUR}),
    "highlight span": _kept_except(
        {
            "adf": _JIRA_CANNOT_HIGHLIGHT,
            "slack": Rejection(
                "a Slack canvas cannot highlight text, so it cannot show the highlight on '{text}'",
                _WITHOUT_THE_HIGHLIGHT,
            ),
        }
    ),
    "colour and highlight span": _kept_except(
        {
            "markdown": _GITHUB_CANNOT_COLOUR,
            "notion": Rejection(
                "a Notion text run takes a colour or a highlight, not both, "
                "so it cannot show both on '{text}'",
                "keep either the colour or the highlight on the text",
            ),
            "adf": _JIRA_CANNOT_HIGHLIGHT,
            "slack": _CANVAS_CANNOT_COLOUR,
        }
    ),
    "underline": _kept_except(
        {
            "slack": Rejection(
                "a Slack canvas cannot underline text, so it cannot show the underline on '{text}'",
                _WITHOUT_THE_MARK.format(mark="underline"),
            )
        }
    ),
    "highlight span inside a toned walkthrough step title": _kept_except(
        {
            "notion": Rejection(
                "Notion cannot show a highlight inside the coloured title of a toned walkthrough step, "
                "so it cannot show the highlight on '{text}'",
                _WITHOUT_THE_HIGHLIGHT,
            )
        }
    ),
    "link to a heading of the same document": _kept_except(
        {
            "notion": Rejection(_OWN_HEADING_WHY.format(target="a Notion page"), _OWN_HEADING_INSTEAD),
            "adf": Rejection(_OWN_HEADING_WHY.format(target="a Jira description"), _OWN_HEADING_INSTEAD),
            "slack": Rejection(_OWN_HEADING_WHY.format(target="a Slack canvas"), _OWN_HEADING_INSTEAD),
        }
    ),
    "link to another skaldr document": _kept_except(
        {
            "notion": Rejection(_OTHER_DOCUMENT_WHY.format(target="Notion"), _OTHER_DOCUMENT_INSTEAD),
            "slack": Rejection(_OTHER_DOCUMENT_WHY.format(target="a Slack canvas"), _OTHER_DOCUMENT_INSTEAD),
        }
    ),
    "inline code holding a backtick": _kept_except(
        {
            "notion": Rejection(
                "Notion cannot show inline code holding a backtick, as in '{code}'",
                "write the code in a code block, or without the backtick",
            )
        }
    ),
    "inline code holding a closing tag in a table cell": _kept_except(
        {
            "notion": Rejection(
                "Notion loses a table cell whose inline code holds '</', as in '{code}'",
                "write the code outside the table, or without '</'",
            )
        }
    ),
    "inline code holding a closing tag in a coloured or highlighted span": _kept_except(
        {
            "notion": Rejection(
                "Notion closes a coloured or highlighted span early at inline code holding '</', "
                "as in '{code}'",
                "write the code outside the coloured text, or without '</'",
            )
        }
    ),
    "list numbered with letters or roman numerals": _kept_except(
        {
            "adf": Rejection(_DIGITS_ONLY_WHY.format(target="ADF"), _DIGITS_ONLY_INSTEAD),
            "slack": Rejection(_DIGITS_ONLY_WHY.format(target="a Slack canvas"), _DIGITS_ONLY_INSTEAD),
        }
    ),
    "table, callout, heading, quote, toggle or divider inside a list item or walkthrough step": _kept_except(
        {
            "adf": Rejection(
                "ADF cannot place a {held} inside a {item}",
                "move the {held} out of the {out_of}, after the {after}",
                names_the_heading=True,
            )
        }
    ),
    "list inside a quote": _kept_except(
        {
            "slack": Rejection(
                "a Slack canvas quote holds only text, so it cannot show a list inside a quote",
                "move the list out of the quote, after it",
            )
        }
    ),
}

PLACEMENTS: Final[Mapping[tuple[Holder, Held], PlacementFeature]] = {
    ("callout", "table"): "table inside a callout",
    ("callout", "callout"): "callout inside a callout",
    ("callout", "quote"): "quote inside a callout",
    ("callout", "toggle"): "toggle inside a callout",
    ("toggle inside a toggle", "table"): "table inside a toggle inside a toggle",
    ("toggle inside a toggle", "toggle"): "toggle inside a toggle inside a toggle",
}


def character_without_a_unicode_form(position: ScriptPosition, text: str) -> str | None:
    forms = UNICODE_SCRIPT_FORMS[position]
    return next((character for character in text if ord(character) not in forms), None)
