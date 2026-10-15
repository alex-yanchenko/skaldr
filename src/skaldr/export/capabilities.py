from collections.abc import Iterable, Mapping
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
OccurrenceFeature = Literal[
    "range",
    "flow diagram",
    "fan diagram",
    "link, citation or math in a flow or fan step's note",
    "chart",
    "chart with several series or stacked",
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
    OccurrenceFeature,
]
RICH_STEP_NOTE: Final[OccurrenceFeature] = "link, citation or math in a flow or fan step's note"
Holder = Literal["callout", "toggle inside a toggle"]
Container = Literal["document", "toggle", Holder]
Held = Literal["table", "callout", "quote", "toggle"]
FIRST_LIST_NUMBER: Final = 1
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
class Occurrence:
    feature: OccurrenceFeature


Details = Placement | HeldByAListItem | ListStart | CellCount | GridInAStep | ScriptForm | Occurrence


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


TARGET_SUBJECTS: Final[Mapping[ExportTarget, str]] = {
    "markdown": "GitHub",
    "notion": "Notion",
    "adf": "ADF",
    "slack": "a Slack canvas",
}


_TARGETS_WITHOUT_DIAGRAMS_OR_MATH: Final[tuple[ExportTarget, ...]] = ("adf", "slack")
_CHART_AS_ITS_TABLE: Final = Swap(
    "the chart's data table: a row per slice with its value and share and a total row for a donut, "
    "a row per series with a column per category for a bar or line chart"
)


def _refused_by(
    targets: Iterable[ExportTarget], cannot: str, instead: str
) -> Mapping[ExportTarget, Capability]:
    return {target: Rejection(f"{TARGET_SUBJECTS[target]} cannot {cannot}", instead) for target in targets}


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
    "range": _refused_by(EXPORT_TARGETS, "draw a range bar", "use a meter or a table"),
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
    RICH_STEP_NOTE: _refused_by(
        EXPORT_TARGETS,
        "show a link, citation, math, subscript or superscript in a flow or fan step's note, "
        "since a diagram label holds plain text only",
        "write the note as plain text and put the rest in a text block after the diagram",
    ),
    "chart": _kept_except(dict.fromkeys(_TARGETS_WITHOUT_DIAGRAMS_OR_MATH, _CHART_AS_ITS_TABLE)),
    "chart with several series or stacked": {
        **_refused_by(
            ("markdown", "notion"),
            "draw a chart with several series or stacked bars, "
            "since its Mermaid chart has no legend and no stacking",
            "draw one chart per series, or write the values in a table",
        ),
        **dict.fromkeys(_TARGETS_WITHOUT_DIAGRAMS_OR_MATH, _CHART_AS_ITS_TABLE),
    },
    "math block": _kept_except(
        dict.fromkeys(_TARGETS_WITHOUT_DIAGRAMS_OR_MATH, Swap("a code block in latex"))
    ),
    "inline math": _kept_except(
        dict.fromkeys(_TARGETS_WITHOUT_DIAGRAMS_OR_MATH, Swap("inline code holding the latex"))
    ),
    "image from a data: URI": _kept_except(
        {
            "notion": Rejection(
                "Notion cannot show an image from a data: URI", "host the image and give its https address"
            ),
            "adf": Rejection(
                "ADF cannot show an image from a data: URI, "
                "since Jira embeds only files attached to the issue",
                "host the image and give its https address",
            ),
            "slack": Rejection(
                "a Slack canvas cannot show an image from a data: URI",
                "upload the image to Slack and give its permalink",
            ),
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


def swaps(feature: Feature, target: ExportTarget) -> bool:
    return isinstance(CAPABILITIES[feature][target], Swap)


def character_without_a_unicode_form(position: ScriptPosition, text: str) -> str | None:
    forms = UNICODE_SCRIPT_FORMS[position]
    return next((character for character in text if ord(character) not in forms), None)
