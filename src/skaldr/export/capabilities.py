from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Final, Literal

from skaldr.errors import ExportInvariantError
from skaldr.export.tree import PanesKind, ToneName
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
    "inline code holding a closing tag in a coloured, highlighted or underlined span",
]
TextNumberingFeature = Literal["list numbered with letters or roman numerals"]
FencedInAListItemFeature = Literal[
    "table, callout, heading, quote, toggle or divider inside a list item or walkthrough step"
]
ListInAQuoteFeature = Literal["list inside a quote"]
CalloutPlacementFeature = Literal["divider inside a callout", "link card inside a callout"]
AnyPlacementFeature = Literal[PlacementFeature, CalloutPlacementFeature]
GridCellFeature = Literal[
    "table inside a grid cell", "callout inside a grid cell", "divider inside a grid cell"
]
GridCellsFeature = Literal["grid with more than three cells"]
TonedCellFeature = Literal["toned grid cell"]
GridInAGridCellFeature = Literal["grid inside a grid cell"]
DeepHeadingFeature = Literal["heading deeper than a canvas holds"]
DividerInAStepFeature = Literal["divider inside a walkthrough step"]
PanesFeature = Literal["set of tabs", "request with several cases"]
OccurrenceFeature = Literal[
    "range",
    "flow diagram",
    "fan diagram",
    "link, citation, math or strikethrough in a flow or fan step's note",
    "chart",
    "chart with several series",
    "math block",
    "inline math",
    "image from a data: URI",
]
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
    CalloutPlacementFeature,
    GridCellFeature,
    GridCellsFeature,
    TonedCellFeature,
    GridInAGridCellFeature,
    DeepHeadingFeature,
    DividerInAStepFeature,
    PanesFeature,
    OccurrenceFeature,
]
RICH_STEP_NOTE: Final[OccurrenceFeature] = (
    "link, citation, math or strikethrough in a flow or fan step's note"
)
Holder = Literal["callout", "toggle inside a toggle"]
Container = Literal["document", "toggle", Holder]
Held = Literal["table", "callout", "quote", "link card", "toggle", "divider"]
FIRST_LIST_NUMBER: Final = 1
BACKTICK: Final = "`"
CLOSING_TAG_OPENER: Final = "</"
CANVAS_TABLE_CELL_LIMIT: Final = 300
CANVAS_LAYOUT_COLUMN_LIMIT: Final = 3
CANVAS_HEADING_LEVEL_LIMIT: Final = 3
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
    feature: AnyPlacementFeature
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
    held: str
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


@dataclass(frozen=True)
class HeldByAGridCell:
    feature: GridCellFeature
    held: str


@dataclass(frozen=True)
class GridCells:
    cells: int
    limit: int = CANVAS_LAYOUT_COLUMN_LIMIT
    feature: GridCellsFeature = field(default="grid with more than three cells", init=False)


@dataclass(frozen=True)
class TonedCell:
    tone: ToneName
    feature: TonedCellFeature = field(default="toned grid cell", init=False)


@dataclass(frozen=True)
class GridInAGridCell:
    feature: GridInAGridCellFeature = field(default="grid inside a grid cell", init=False)


@dataclass(frozen=True)
class DeepHeading:
    text: str
    level: int
    limit: int = CANVAS_HEADING_LEVEL_LIMIT
    feature: DeepHeadingFeature = field(default="heading deeper than a canvas holds", init=False)


@dataclass(frozen=True)
class DividerInAStep:
    feature: DividerInAStepFeature = field(default="divider inside a walkthrough step", init=False)


@dataclass(frozen=True)
class Panes:
    feature: PanesFeature


@dataclass(frozen=True)
class Occurrence:
    feature: OccurrenceFeature


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
    | HeldByAGridCell
    | GridCells
    | TonedCell
    | GridInAGridCell
    | DeepHeading
    | DividerInAStep
    | Panes
    | Occurrence
)


@dataclass(frozen=True)
class Rejection:
    why: str
    instead: str
    names_the_heading: bool = False
    in_the_guide: str = field(kw_only=True)


@dataclass(frozen=True)
class Swap:
    writes: str


Capability = Literal["keep"] | Rejection | Swap

_ADF_CANNOT_PLACE: Final = Rejection(
    "ADF cannot place a {held} inside {holder}",
    "move the {held} out of the {holder_name}",
    names_the_heading=True,
    in_the_guide="this export cannot place it there, since ADF limits what each container may hold; "
    "move it out of the container",
)
_CANVAS_LIST_ITEM_WHY: Final = (
    "a Slack canvas list item holds only text and one nested list, so it cannot show {held}"
)
_CANVAS_LIST_ITEM_GUIDE: Final = "a canvas list item holds only text and one nested list; "
_WITHOUT_THE_MARK: Final = "write the text without the {mark} or export the document elsewhere"
_WITHOUT_THE_COLOUR: Final = _WITHOUT_THE_MARK.format(mark="colour")
_GITHUB_CANNOT_COLOUR: Final = Rejection(
    "GitHub Markdown cannot colour text, so it cannot show the colour of '{text}'",
    _WITHOUT_THE_COLOUR,
    in_the_guide=f"GitHub cannot colour text; {_WITHOUT_THE_COLOUR}",
)
_CANVAS_CANNOT_COLOUR: Final = Rejection(
    "a Slack canvas cannot colour text, so it cannot show the colour of '{text}'",
    _WITHOUT_THE_COLOUR,
    in_the_guide=f"a canvas cannot colour text; {_WITHOUT_THE_COLOUR}",
)
_WITHOUT_THE_HIGHLIGHT: Final = _WITHOUT_THE_MARK.format(mark="highlight")
_FROM_ONE_WHY: Final = (
    "{target} numbers every list from 1, so it cannot show a numbered list that starts at {{start}}"
)
_FROM_ONE_INSTEAD: Final = "number the list from 1, or export it elsewhere"
_FROM_ONE_GUIDE: Final = f"this export numbers every list from 1; {_FROM_ONE_INSTEAD}"
_OWN_HEADING_WHY: Final = (
    "{target} cannot link to its own headings, so it cannot show the link '{{text}}' to '{{link}}'"
)
_OWN_HEADING_INSTEAD: Final = "write the heading's name without the link, or export the document elsewhere"
_OWN_HEADING_GUIDE: Final = f"this export cannot link to its own headings; {_OWN_HEADING_INSTEAD}"
_OTHER_DOCUMENT_WHY: Final = (
    "{target} cannot link '{{text}}' to the document '{{doc_id}}', "
    "since skaldr has no address for that document there"
)
_OTHER_DOCUMENT_INSTEAD: Final = "link to the document's https address, or export it elsewhere"
_OTHER_DOCUMENT_GUIDE: Final = (
    f"skaldr has no address for that document in this export; {_OTHER_DOCUMENT_INSTEAD}"
)
_DIGITS_ONLY_WHY: Final = (
    "{target} numbers a list only with digits, so it cannot show a list numbered with {{numbering}}"
)
_DIGITS_ONLY_INSTEAD: Final = "number the list with digits, or export it elsewhere"
_DIGITS_ONLY_GUIDE: Final = f"this export numbers a list only with digits; {_DIGITS_ONLY_INSTEAD}"


def _kept_except(cells: Mapping[ExportTarget, Capability]) -> dict[ExportTarget, Capability]:
    kept: dict[ExportTarget, Capability] = dict.fromkeys(EXPORT_TARGETS, "keep")
    return {**kept, **cells}


_CANVAS_CALLOUT_CANNOT_HOLD: Final = Rejection(
    "a Slack canvas callout holds only text, headings, lists, quotes, code blocks and images, "
    "so it cannot show the {held} inside {holder}",
    "move the {held} out of the {holder_name}",
    names_the_heading=True,
    in_the_guide="a canvas callout holds only text, headings, lists, quotes, code blocks and images; "
    "move it out of the callout",
)
_CANVAS_COLUMN_CANNOT_HOLD: Final = Rejection(
    "a Slack canvas column holds no table, callout or divider, "
    "so it cannot show the {held} inside a grid cell",
    "move the {held} out of the grid",
    names_the_heading=True,
    in_the_guide="a canvas column holds no table, callout or divider; move it out of the grid",
)
TARGET_SUBJECTS: Final[Mapping[ExportTarget, str]] = {
    "markdown": "GitHub",
    "notion": "Notion",
    "adf": "ADF",
    "slack": "a Slack canvas",
}


_TARGETS_WITHOUT_DIAGRAMS_OR_MATH: Final[tuple[ExportTarget, ...]] = ("adf", "slack")
_TARGETS_WITH_MERMAID_DIAGRAMS: Final[tuple[ExportTarget, ...]] = ("markdown", "notion")
_HOST_THE_IMAGE: Final = "host the image and give its https address"
_CHART_AS_ITS_TABLE: Final = Swap(
    "the chart's data table: a donut's slices, a row each with its value and share, then a total row; "
    "a bar or line chart's series, a row each with its value in each category, "
    "then for stacked bars with several series a total row holding each category's stack"
)


def _refused_by(
    targets: Iterable[ExportTarget], cannot: str, instead: str, in_the_guide: str | None = None
) -> Mapping[ExportTarget, Capability]:
    guide_sentence = f"this export cannot {cannot}; {instead}" if in_the_guide is None else in_the_guide
    return {
        target: Rejection(f"{TARGET_SUBJECTS[target]} cannot {cannot}", instead, in_the_guide=guide_sentence)
        for target in targets
    }


CAPABILITIES: Final[Mapping[Feature, Mapping[ExportTarget, Capability]]] = {
    "table inside a callout": _kept_except({"adf": _ADF_CANNOT_PLACE, "slack": _CANVAS_CALLOUT_CANNOT_HOLD}),
    "callout inside a callout": _kept_except(
        {"adf": _ADF_CANNOT_PLACE, "slack": _CANVAS_CALLOUT_CANNOT_HOLD}
    ),
    "quote inside a callout": _kept_except({"adf": _ADF_CANNOT_PLACE}),
    "link card inside a callout": _kept_except({}),
    "toggle inside a callout": _kept_except({"adf": _ADF_CANNOT_PLACE, "slack": _CANVAS_CALLOUT_CANNOT_HOLD}),
    "table inside a toggle inside a toggle": _kept_except({"adf": _ADF_CANNOT_PLACE}),
    "toggle inside a toggle inside a toggle": _kept_except({"adf": _ADF_CANNOT_PLACE}),
    "block inside a list item": _kept_except(
        {
            "slack": Rejection(
                _CANVAS_LIST_ITEM_WHY,
                "move it out of the list, after the list",
                in_the_guide=f"{_CANVAS_LIST_ITEM_GUIDE}move it out of the list, after the list",
            )
        }
    ),
    "block inside a walkthrough step": _kept_except(
        {
            "slack": Rejection(
                _CANVAS_LIST_ITEM_WHY,
                "move it out of the step, after the walkthrough",
                in_the_guide=f"{_CANVAS_LIST_ITEM_GUIDE}move it out of the step, after the walkthrough",
            )
        }
    ),
    "numbered list starting past 1": _kept_except(
        {
            "notion": Rejection(
                _FROM_ONE_WHY.format(target="Notion"), _FROM_ONE_INSTEAD, in_the_guide=_FROM_ONE_GUIDE
            ),
            "slack": Rejection(
                _FROM_ONE_WHY.format(target="a Slack canvas"), _FROM_ONE_INSTEAD, in_the_guide=_FROM_ONE_GUIDE
            ),
        }
    ),
    "table over 300 cells": _kept_except(
        {
            "slack": Rejection(
                "the {held} takes {cells:,} cells as a Slack canvas table, "
                "over the {limit} such a table can hold",
                "split the {held} in two or export it elsewhere",
                names_the_heading=True,
                in_the_guide=f"a canvas table holds at most {CANVAS_TABLE_CELL_LIMIT} cells, "
                "the header row included; "
                "split the table in two, or export the document elsewhere",
            )
        }
    ),
    "grid inside a walkthrough step": _kept_except(
        {
            "slack": Rejection(
                "a Slack canvas cannot show a grid inside a walkthrough step, "
                "since a canvas list item holds only text",
                "move the grid out of the step, after the walkthrough",
                in_the_guide=f"{_CANVAS_LIST_ITEM_GUIDE}move the grid out of the step, after the walkthrough",
            )
        }
    ),
    "subscript or superscript with no Unicode form": _kept_except(
        {
            "slack": Rejection(
                "a Slack canvas cannot show the {position} '{text}', "
                "since '{character}' has no Unicode {position} form",
                _WITHOUT_THE_MARK.format(mark="{position}"),
                in_the_guide="a canvas shows only the subscripts and superscripts that have a Unicode form, "
                "which the `H~2~O` row of the table above lists; "
                "write the text without the subscript or superscript, or export the document elsewhere",
            )
        }
    ),
    "colour span": _kept_except({"markdown": _GITHUB_CANNOT_COLOUR, "slack": _CANVAS_CANNOT_COLOUR}),
    "highlight span": _kept_except(
        {
            "slack": Rejection(
                "a Slack canvas cannot highlight text, so it cannot show the highlight on '{text}'",
                _WITHOUT_THE_HIGHLIGHT,
                in_the_guide=f"a canvas cannot highlight text; {_WITHOUT_THE_HIGHLIGHT}",
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
                in_the_guide="a Notion text run takes a colour or a highlight, not both; "
                "keep either the colour or the highlight on the text",
            ),
            "slack": _CANVAS_CANNOT_COLOUR,
        }
    ),
    "underline": _kept_except(
        {
            "slack": Rejection(
                "a Slack canvas cannot underline text, so it cannot show the underline on '{text}'",
                _WITHOUT_THE_MARK.format(mark="underline"),
                in_the_guide=f"a canvas cannot underline text; {_WITHOUT_THE_MARK.format(mark='underline')}",
            )
        }
    ),
    "highlight span inside a toned walkthrough step title": _kept_except(
        {
            "notion": Rejection(
                "Notion cannot show a highlight inside the coloured title of a toned walkthrough step, "
                "so it cannot show the highlight on '{text}'",
                _WITHOUT_THE_HIGHLIGHT,
                in_the_guide="Notion cannot show a highlight inside the coloured title of a toned "
                f"walkthrough step; {_WITHOUT_THE_HIGHLIGHT}",
            )
        }
    ),
    "link to a heading of the same document": _kept_except(
        {
            "notion": Rejection(
                _OWN_HEADING_WHY.format(target="a Notion page"),
                _OWN_HEADING_INSTEAD,
                in_the_guide=_OWN_HEADING_GUIDE,
            ),
            "adf": Rejection(
                _OWN_HEADING_WHY.format(target="a Jira description"),
                _OWN_HEADING_INSTEAD,
                in_the_guide=_OWN_HEADING_GUIDE,
            ),
            "slack": Rejection(
                _OWN_HEADING_WHY.format(target="a Slack canvas"),
                _OWN_HEADING_INSTEAD,
                in_the_guide=_OWN_HEADING_GUIDE,
            ),
        }
    ),
    "link to another skaldr document": _kept_except(
        {
            "notion": Rejection(
                _OTHER_DOCUMENT_WHY.format(target="Notion"),
                _OTHER_DOCUMENT_INSTEAD,
                in_the_guide=_OTHER_DOCUMENT_GUIDE,
            ),
            "adf": Rejection(
                _OTHER_DOCUMENT_WHY.format(target="a Jira description"),
                _OTHER_DOCUMENT_INSTEAD,
                in_the_guide=_OTHER_DOCUMENT_GUIDE,
            ),
            "slack": Rejection(
                _OTHER_DOCUMENT_WHY.format(target="a Slack canvas"),
                _OTHER_DOCUMENT_INSTEAD,
                in_the_guide=_OTHER_DOCUMENT_GUIDE,
            ),
        }
    ),
    "inline code holding a backtick": _kept_except(
        {
            "notion": Rejection(
                "Notion cannot show inline code holding a backtick, as in '{code}'",
                "write the code in a code block, or without the backtick",
                in_the_guide="Notion cannot show inline code holding a backtick; "
                "write the code in a code block, or without the backtick",
            )
        }
    ),
    "inline code holding a closing tag in a table cell": _kept_except(
        {
            "notion": Rejection(
                "Notion loses a table cell whose inline code holds '</', as in '{code}'",
                "write the code outside the table, or without '</'",
                in_the_guide="Notion loses a table cell whose inline code holds `</`; "
                "write the code outside the table, or without `</`",
            )
        }
    ),
    "inline code holding a closing tag in a coloured, highlighted or underlined span": _kept_except(
        {
            "notion": Rejection(
                "Notion closes a coloured, highlighted or underlined span early at inline code holding '</', "
                "as in '{code}'",
                "write the code outside the coloured, highlighted or underlined text, or without '</'",
                in_the_guide="Notion closes a coloured, highlighted or underlined span early at inline code "
                "holding `</`; write the code outside the coloured, highlighted or underlined text, "
                "or without `</`",
            )
        }
    ),
    "list numbered with letters or roman numerals": _kept_except(
        {
            "adf": Rejection(
                _DIGITS_ONLY_WHY.format(target="ADF"), _DIGITS_ONLY_INSTEAD, in_the_guide=_DIGITS_ONLY_GUIDE
            ),
            "slack": Rejection(
                _DIGITS_ONLY_WHY.format(target="a Slack canvas"),
                _DIGITS_ONLY_INSTEAD,
                in_the_guide=_DIGITS_ONLY_GUIDE,
            ),
        }
    ),
    "table, callout, heading, quote, toggle or divider inside a list item or walkthrough step": _kept_except(
        {
            "adf": Rejection(
                "ADF cannot place a {held} inside a {item}",
                "move the {held} out of the {out_of}, after the {after}",
                names_the_heading=True,
                in_the_guide="ADF limits what a list item or walkthrough step may hold, so this export "
                "cannot place it there; move it out of the list or step, after the list or walkthrough",
            )
        }
    ),
    "list inside a quote": _kept_except(
        {
            "slack": Rejection(
                "a Slack canvas quote holds only text, so it cannot show a list inside a quote",
                "move the list out of the quote, after it",
                in_the_guide="a canvas quote holds only text; move the list out of the quote, after it",
            )
        }
    ),
    "divider inside a callout": _kept_except({"slack": _CANVAS_CALLOUT_CANNOT_HOLD}),
    "grid with more than three cells": _kept_except(
        {
            "slack": Rejection(
                "a Slack canvas column layout holds at most {limit} columns, so it cannot show a grid of "
                "{cells} cells",
                "split the grid into grids of at most {limit} cells",
                names_the_heading=True,
                in_the_guide=f"a canvas column layout holds at most {CANVAS_LAYOUT_COLUMN_LIMIT} columns; "
                f"split the grid into grids of at most {CANVAS_LAYOUT_COLUMN_LIMIT} cells",
            )
        }
    ),
    "table inside a grid cell": _kept_except({"slack": _CANVAS_COLUMN_CANNOT_HOLD}),
    "callout inside a grid cell": _kept_except({"slack": _CANVAS_COLUMN_CANNOT_HOLD}),
    "divider inside a grid cell": _kept_except({"slack": _CANVAS_COLUMN_CANNOT_HOLD}),
    "toned grid cell": _kept_except(
        {
            "slack": Rejection(
                "a Slack canvas column has no tone, so it cannot show a grid cell with the tone '{tone}'",
                "drop the tone from the grid cell",
                names_the_heading=True,
                in_the_guide="a canvas column has no tone; drop the tone from the grid cell",
            )
        }
    ),
    "grid inside a grid cell": _kept_except(
        {
            "slack": Rejection(
                "a Slack canvas cannot show a grid's columns inside a grid cell",
                "write the inner grid's cells as cells of the outer grid",
                names_the_heading=True,
                in_the_guide="a canvas cannot show a grid's columns inside a grid cell; "
                "write the inner grid's cells as cells of the outer grid",
            )
        }
    ),
    "heading deeper than a canvas holds": _kept_except(
        {
            "slack": Rejection(
                "a Slack canvas holds headings down to level {limit}, "
                "so it cannot show the heading '{text}' at level {level}",
                "write the heading as bold text, or export the document elsewhere",
                in_the_guide=f"a canvas holds headings down to level {CANVAS_HEADING_LEVEL_LIMIT}; "
                "write the heading as bold text, or export the document elsewhere",
            )
        }
    ),
    "divider inside a walkthrough step": _kept_except(
        {
            "adf": Rejection(
                "ADF cannot place a divider inside a walkthrough step, "
                "since Jira writes a step as a list item",
                "move the divider out of the step, after the walkthrough",
                names_the_heading=True,
                in_the_guide="Jira writes a walkthrough step as a list item, which holds no divider; "
                "move the divider out of the step, after the walkthrough",
            )
        }
    ),
    "set of tabs": _kept_except(
        {"adf": Swap("one expand per tab, its title led by the icon of the tab's tone")}
    ),
    "request with several cases": _kept_except(
        {"adf": Swap("one expand per case, its title led by the icon of the case's status")}
    ),
    "range": _refused_by(
        EXPORT_TARGETS,
        "draw a range bar",
        "use a meter or a table",
        in_the_guide="this export cannot draw a range bar; use a `meter` or a `table`",
    ),
    "flow diagram": _kept_except(
        _refused_by(
            _TARGETS_WITHOUT_DIAGRAMS_OR_MATH, "draw a flow diagram", "write the steps as a numbered list"
        )
    ),
    "fan diagram": _kept_except(
        _refused_by(
            _TARGETS_WITHOUT_DIAGRAMS_OR_MATH, "draw a fan diagram", "write the hub and its spokes as a list"
        )
    ),
    RICH_STEP_NOTE: _kept_except(
        _refused_by(
            _TARGETS_WITH_MERMAID_DIAGRAMS,
            "show a link, citation, math, struck-through text, or a subscript or superscript "
            "with no Unicode form in a flow or fan step's note, since a diagram label holds plain text only",
            "write the note as plain text and put the rest in a text block after the diagram",
            in_the_guide="this export cannot show a link, citation, inline math, struck-through text, "
            "or a subscript or superscript with no Unicode form in a flow or fan step's note, "
            "since a Mermaid label holds plain text only (the Slack canvas section lists the characters "
            "that have a Unicode form); write the note as plain text and put the rest in a text block "
            "after the diagram. Any other mark in a note, such as bold, italic, underline, "
            "a colour or inline code, keeps its characters and loses its formatting",
        )
    ),
    "chart": _kept_except(dict.fromkeys(_TARGETS_WITHOUT_DIAGRAMS_OR_MATH, _CHART_AS_ITS_TABLE)),
    "chart with several series": dict.fromkeys(EXPORT_TARGETS, _CHART_AS_ITS_TABLE),
    "math block": _kept_except(
        dict.fromkeys(_TARGETS_WITHOUT_DIAGRAMS_OR_MATH, Swap("a code block in latex"))
    ),
    "inline math": _kept_except(
        dict.fromkeys(_TARGETS_WITHOUT_DIAGRAMS_OR_MATH, Swap("inline code holding the latex"))
    ),
    "image from a data: URI": {
        **_refused_by(
            ("markdown", "notion"),
            "show an image from a data: URI",
            _HOST_THE_IMAGE,
            in_the_guide=f"this export cannot show an image from a `data:` URI; {_HOST_THE_IMAGE}",
        ),
        "adf": Rejection(
            "ADF cannot show an image from a data: URI, since Jira embeds only files attached to the issue",
            _HOST_THE_IMAGE,
            in_the_guide=f"Jira embeds only files attached to the issue; {_HOST_THE_IMAGE}",
        ),
        "slack": Rejection(
            "a Slack canvas cannot show an image from a data: URI",
            "upload the image to Slack and give its permalink",
            in_the_guide="a canvas cannot show an image from a `data:` URI; "
            "upload the image to Slack and give its permalink",
        ),
    },
}

PLACEMENTS: Final[Mapping[tuple[Holder, Held], AnyPlacementFeature]] = {
    ("callout", "table"): "table inside a callout",
    ("callout", "callout"): "callout inside a callout",
    ("callout", "quote"): "quote inside a callout",
    ("callout", "link card"): "link card inside a callout",
    ("callout", "toggle"): "toggle inside a callout",
    ("toggle inside a toggle", "table"): "table inside a toggle inside a toggle",
    ("toggle inside a toggle", "toggle"): "toggle inside a toggle inside a toggle",
    ("callout", "divider"): "divider inside a callout",
}
PANES_FEATURES: Final[Mapping[PanesKind, PanesFeature]] = {
    "tabs": "set of tabs",
    "request cases": "request with several cases",
}
GRID_CELL_FEATURES: Final[Mapping[Held, GridCellFeature]] = {
    "table": "table inside a grid cell",
    "callout": "callout inside a grid cell",
    "divider": "divider inside a grid cell",
}


def swaps(feature: Feature, target: ExportTarget) -> bool:
    return isinstance(CAPABILITIES[feature][target], Swap)


def character_without_a_unicode_form(position: ScriptPosition, text: str) -> str | None:
    forms = UNICODE_SCRIPT_FORMS[position]
    return next((character for character in text if ord(character) not in forms), None)


def in_unicode_script_form(position: ScriptPosition, text: str, subject: str) -> str:
    without_a_form = character_without_a_unicode_form(position, text)
    if without_a_form is not None:
        raise ExportInvariantError(
            f"{subject} has no {position} form for '{without_a_form}' in '{text}'; "
            "the export check should have refused it"
        )
    return text.translate(UNICODE_SCRIPT_FORMS[position])
