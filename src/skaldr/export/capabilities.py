from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final, Literal

from typing_extensions import assert_never

from skaldr.export_targets import EXPORT_TARGETS, ExportTarget
from skaldr.models import Chart, FlowStep
from skaldr.richtext import (
    AnchorLink,
    Citation,
    Code,
    DateMention,
    DocumentLink,
    InlineMath,
    IssueLink,
    Link,
    PersonMention,
    Placeholder,
    Plain,
    Rich,
    Run,
    ScriptPosition,
    ScriptText,
    Styled,
    Tinted,
)

Feature = Literal[
    "table inside a callout",
    "callout inside a callout",
    "quote inside a callout",
    "toggle inside a callout",
    "table inside a toggle inside a toggle",
    "toggle inside a toggle inside a toggle",
    "block inside a list item",
    "block inside a walkthrough step",
    "numbered list starting past 1",
    "table over 300 cells",
    "grid inside a walkthrough step",
    "subscript or superscript with no Unicode form",
]
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
    held: str
    holder: str
    holder_name: str


@dataclass(frozen=True)
class HeldByAListItem:
    held: str


@dataclass(frozen=True)
class ListStart:
    start: int


@dataclass(frozen=True)
class CellCount:
    cells: int
    limit: int = CANVAS_TABLE_CELL_LIMIT


@dataclass(frozen=True)
class ScriptForm:
    position: ScriptPosition
    text: str
    character: str


@dataclass(frozen=True)
class NoDetails:
    pass


Details = Placement | HeldByAListItem | ListStart | CellCount | ScriptForm | NoDetails
FEATURE_DETAILS: Final[Mapping[Feature, type[Details]]] = {
    "table inside a callout": Placement,
    "callout inside a callout": Placement,
    "quote inside a callout": Placement,
    "toggle inside a callout": Placement,
    "table inside a toggle inside a toggle": Placement,
    "toggle inside a toggle inside a toggle": Placement,
    "block inside a list item": HeldByAListItem,
    "block inside a walkthrough step": HeldByAListItem,
    "numbered list starting past 1": ListStart,
    "table over 300 cells": CellCount,
    "grid inside a walkthrough step": NoDetails,
    "subscript or superscript with no Unicode form": ScriptForm,
}


@dataclass(frozen=True)
class Rejection:
    why: str
    instead: str
    names_the_heading: bool = False


Capability = Literal["keep", "upgrade", "swap"] | Rejection

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
}

PLACEMENTS: Final[Mapping[tuple[Holder, Held], Feature]] = {
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


def mermaid_cannot_label_its_series(block: Chart) -> bool:
    return block.stacked or len(block.series) > 1


def loses_meaning_in_a_plain_label(run: Run) -> bool:
    match run:
        case Link() | AnchorLink() | IssueLink() | DocumentLink() | Citation() | InlineMath() | ScriptText():
            return True
        case DateMention() | PersonMention():
            return any(map(loses_meaning_in_a_plain_label, run.label))
        case Styled() | Tinted():
            return any(map(loses_meaning_in_a_plain_label, run.runs))
        case Plain() | Code() | Placeholder():
            return False
        case _:
            assert_never(run)


def diagram_label_cannot_show(step: FlowStep, note: Rich) -> bool:
    return bool(step.points or step.badges) or any(map(loses_meaning_in_a_plain_label, note))
