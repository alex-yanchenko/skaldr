from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final, Literal, get_args

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
    ScriptText,
    Styled,
    Tinted,
)

Verdict = Literal["keep", "upgrade", "swap", "reject"]
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
    "chart with several series or stacked",
    "flow or fan step a diagram label cannot show",
]
FEATURES: Final[tuple[Feature, ...]] = get_args(Feature)
Holder = Literal["callout", "toggle inside a toggle"]
Held = Literal["table", "callout", "quote", "toggle"]
FIRST_LIST_NUMBER: Final = 1
CANVAS_TABLE_CELL_LIMIT: Final = 300


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


def verdict(capability: Capability) -> Verdict:
    return "reject" if isinstance(capability, Rejection) else capability


def _everywhere(capability: Capability) -> dict[ExportTarget, Capability]:
    return dict.fromkeys(EXPORT_TARGETS, capability)


def _kept_except(cells: Mapping[ExportTarget, Capability]) -> dict[ExportTarget, Capability]:
    return {**_everywhere("keep"), **cells}


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
                f"a table has {{cells}} cells, "
                f"over the {CANVAS_TABLE_CELL_LIMIT} a Slack canvas table can hold",
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
    "chart with several series or stacked": _everywhere("swap"),
    "flow or fan step a diagram label cannot show": _everywhere("keep"),
}

PLACEMENTS: Final[Mapping[tuple[Holder, Held], Feature]] = {
    ("callout", "table"): "table inside a callout",
    ("callout", "callout"): "callout inside a callout",
    ("callout", "quote"): "quote inside a callout",
    ("callout", "toggle"): "toggle inside a callout",
    ("toggle inside a toggle", "table"): "table inside a toggle inside a toggle",
    ("toggle inside a toggle", "toggle"): "toggle inside a toggle inside a toggle",
}


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
