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
CalloutPlacementFeature = Literal["divider inside a callout"]
AnyPlacementFeature = Literal[PlacementFeature, CalloutPlacementFeature]
GridCellFeature = Literal[
    "table inside a grid cell", "callout inside a grid cell", "divider inside a grid cell"
]
GridCellsFeature = Literal["grid with more than three cells"]
TonedCellFeature = Literal["toned grid cell"]
GridInAGridCellFeature = Literal["grid inside a grid cell"]
DividerInAStepFeature = Literal["divider inside a walkthrough step"]
PanesFeature = Literal["set of tabs", "request with several cases"]
Feature = Literal[
    PlacementFeature,
    ListItemFeature,
    ListStartFeature,
    CellCountFeature,
    GridInAStepFeature,
    ScriptFormFeature,
    CalloutPlacementFeature,
    GridCellFeature,
    GridCellsFeature,
    TonedCellFeature,
    GridInAGridCellFeature,
    DividerInAStepFeature,
    PanesFeature,
]
Holder = Literal["callout", "toggle inside a toggle"]
Container = Literal["document", "toggle", Holder]
Held = Literal["table", "callout", "quote", "toggle", "divider"]
FIRST_LIST_NUMBER: Final = 1
CANVAS_TABLE_CELL_LIMIT: Final = 300
CANVAS_LAYOUT_COLUMN_LIMIT: Final = 3
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
    tone: str
    feature: TonedCellFeature = field(default="toned grid cell", init=False)


@dataclass(frozen=True)
class GridInAGridCell:
    feature: GridInAGridCellFeature = field(default="grid inside a grid cell", init=False)


@dataclass(frozen=True)
class DividerInAStep:
    feature: DividerInAStepFeature = field(default="divider inside a walkthrough step", init=False)


@dataclass(frozen=True)
class Panes:
    feature: PanesFeature


Details = (
    Placement
    | HeldByAListItem
    | ListStart
    | CellCount
    | GridInAStep
    | ScriptForm
    | HeldByAGridCell
    | GridCells
    | TonedCell
    | GridInAGridCell
    | DividerInAStep
    | Panes
)


@dataclass(frozen=True)
class Rejection:
    why: str
    instead: str
    names_the_heading: bool = False


@dataclass(frozen=True)
class Swap:
    writes: str


Capability = Literal["keep"] | Rejection | Swap

_ADF_CANNOT_PLACE: Final = Rejection(
    "ADF cannot place a {held} inside {holder}",
    "move the {held} out of the {holder_name}",
    names_the_heading=True,
)
_CANVAS_LIST_ITEM_WHY: Final = (
    "a Slack canvas list item holds only text and one nested list, so it cannot show {held}"
)


def _kept_except(cells: Mapping[ExportTarget, Capability]) -> dict[ExportTarget, Capability]:
    kept: dict[ExportTarget, Capability] = dict.fromkeys(EXPORT_TARGETS, "keep")
    return {**kept, **cells}


_CANVAS_CALLOUT_CANNOT_HOLD: Final = Rejection(
    "a Slack canvas callout holds only text, headings, lists, quotes, code blocks and images, "
    "so it cannot show the {held} inside {holder}",
    "move the {held} out of the {holder_name}",
    names_the_heading=True,
)
_CANVAS_COLUMN_CANNOT_HOLD: Final = Rejection(
    "a Slack canvas column holds no table, callout or divider, "
    "so it cannot show the {held} inside a grid cell",
    "move the {held} out of the grid",
    names_the_heading=True,
)

CAPABILITIES: Final[Mapping[Feature, Mapping[ExportTarget, Capability]]] = {
    "table inside a callout": _kept_except({"adf": _ADF_CANNOT_PLACE, "slack": _CANVAS_CALLOUT_CANNOT_HOLD}),
    "callout inside a callout": _kept_except(
        {"adf": _ADF_CANNOT_PLACE, "slack": _CANVAS_CALLOUT_CANNOT_HOLD}
    ),
    "quote inside a callout": _kept_except({"adf": _ADF_CANNOT_PLACE}),
    "toggle inside a callout": _kept_except({"adf": _ADF_CANNOT_PLACE, "slack": _CANVAS_CALLOUT_CANNOT_HOLD}),
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
            "slack": Rejection(
                "a Slack canvas numbers every list from 1, so it cannot show a numbered list "
                "that starts at {start}",
                "number the list from 1, or export it elsewhere",
            )
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
                "write the text without the {position} or export the document elsewhere",
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
            )
        }
    ),
    "table inside a grid cell": _kept_except(
        {
            "adf": Rejection(
                "ADF cannot place a {held} inside a grid cell",
                "move the {held} out of the grid",
                names_the_heading=True,
            ),
            "slack": _CANVAS_COLUMN_CANNOT_HOLD,
        }
    ),
    "callout inside a grid cell": _kept_except({"slack": _CANVAS_COLUMN_CANNOT_HOLD}),
    "divider inside a grid cell": _kept_except({"slack": _CANVAS_COLUMN_CANNOT_HOLD}),
    "toned grid cell": _kept_except(
        {
            "slack": Rejection(
                "a Slack canvas column has no tone, so it cannot show a grid cell with the tone '{tone}'",
                "drop the tone from the grid cell",
                names_the_heading=True,
            )
        }
    ),
    "grid inside a grid cell": _kept_except(
        {
            "slack": Rejection(
                "a Slack canvas column layout cannot nest, so it cannot show a grid inside a grid cell",
                "write the inner grid's cells as cells of the outer grid",
                names_the_heading=True,
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
            )
        }
    ),
    "set of tabs": _kept_except(
        {
            "notion": Swap("one toggle per tab, its title led by the icon of the tab's tone"),
            "adf": Swap("one expand per tab, its title led by the icon of the tab's tone"),
        }
    ),
    "request with several cases": _kept_except(
        {
            "notion": Swap("one toggle per case, its title led by the icon of the case's status"),
            "adf": Swap("one expand per case, its title led by the icon of the case's status"),
        }
    ),
}

PLACEMENTS: Final[Mapping[tuple[Holder, Held], AnyPlacementFeature]] = {
    ("callout", "table"): "table inside a callout",
    ("callout", "callout"): "callout inside a callout",
    ("callout", "quote"): "quote inside a callout",
    ("callout", "toggle"): "toggle inside a callout",
    ("toggle inside a toggle", "table"): "table inside a toggle inside a toggle",
    ("toggle inside a toggle", "toggle"): "toggle inside a toggle inside a toggle",
    ("callout", "divider"): "divider inside a callout",
}
GRID_CELL_FEATURES: Final[Mapping[Held, GridCellFeature]] = {
    "table": "table inside a grid cell",
    "callout": "callout inside a grid cell",
    "divider": "divider inside a grid cell",
}


def character_without_a_unicode_form(position: ScriptPosition, text: str) -> str | None:
    forms = UNICODE_SCRIPT_FORMS[position]
    return next((character for character in text if ord(character) not in forms), None)
