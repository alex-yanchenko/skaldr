import math
from collections.abc import Mapping
from typing import Final

from typing_extensions import assert_never

from skaldr.export.runs import (
    CheckMark,
    DecisionMark,
    ExportRich,
    IndicatorMark,
    Mark,
    StatusMark,
    SwimlaneMark,
)
from skaldr.export.tree import Callout, Tab, ToneName
from skaldr.models import StatusState, SwimlaneStepState, ToneLiteral
from skaldr.richtext import Plain

CALLOUT_ICON: Final[Mapping[ToneName, str]] = {
    "info": "💡",
    "success": "✅",
    "warning": "⚠️",
    "danger": "🛑",
    "accent": "📌",
    "neutral": "📝",
    "muted": "📝",
    "teal": "💡",
    "sky": "💡",
}
TAB_TONES: Final[frozenset[ToneName]] = frozenset({"success", "info", "warning", "danger"})
GAUGE_CELLS: Final = 10


def gauge_bar(value: float, maximum: float) -> str:
    filled = max(0, min(GAUGE_CELLS, math.floor(value / maximum * GAUGE_CELLS + 0.5)))
    return "█" * filled + "░" * (GAUGE_CELLS - filled)


def callout_icon(callout: Callout) -> str | None:
    return (callout.icon or CALLOUT_ICON[callout.tone]) if callout.shows_icon else None


def tab_icon(tone: ToneName | None) -> str | None:
    return CALLOUT_ICON[tone] if tone in TAB_TONES else None


def tab_title_led_by_its_icon(tab: Tab) -> ExportRich:
    icon = tab_icon(tab.tone)
    if icon is None:
        return tab.title
    return (Plain(f"{icon} "), *tab.title) if tab.title else (Plain(icon),)


def status_glyph(state: StatusState) -> str:
    match state:
        case "done":
            return "✅"
        case "current":
            return "🔵"
        case "pending":
            return "⚪"
        case "failed":
            return "❌"
        case "blocked":
            return "⏸️"
        case _:
            assert_never(state)


def swimlane_glyph(state: SwimlaneStepState) -> str:
    match state:
        case "done":
            return "✅"
        case "current":
            return "🔵"
        case "todo":
            return "⚪"
        case "blocked":
            return "⛔"
        case "deferred":
            return "⏸️"
        case _:
            assert_never(state)


def indicator_glyph(tone: ToneLiteral) -> str:
    match tone:
        case "success" | "teal":
            return "🟢"
        case "warning":
            return "🟡"
        case "danger":
            return "🔴"
        case "info" | "sky":
            return "🔵"
        case "neutral":
            return "⚪"
        case "accent":
            return "🟣"
        case _:
            assert_never(tone)


def check_glyph(checked: bool) -> str:
    match checked:
        case True:
            return "✓"
        case False:
            return "✗"
        case _:
            assert_never(checked)


def decision_glyph(decided: bool) -> str:
    match decided:
        case True:
            return "☑️"
        case False:
            return "❓"
        case _:
            assert_never(decided)


def mark_glyph(mark: Mark) -> str:
    match mark:
        case StatusMark():
            return status_glyph(mark.state)
        case SwimlaneMark():
            return swimlane_glyph(mark.state)
        case IndicatorMark():
            return indicator_glyph(mark.tone)
        case CheckMark():
            return check_glyph(mark.checked)
        case DecisionMark():
            return decision_glyph(mark.decided)
        case _:
            assert_never(mark)
