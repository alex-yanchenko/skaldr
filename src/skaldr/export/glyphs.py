import math
from collections.abc import Mapping
from typing import Final

from typing_extensions import assert_never

from skaldr.export.runs import CheckMark, DecisionMark, IndicatorMark, Mark, StatusMark, SwimlaneMark
from skaldr.export.tree import ToneName
from skaldr.models import StatusState, SwimlaneStepState, ToneLiteral

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


def tab_icon(tone: ToneName | None) -> str | None:
    return CALLOUT_ICON[tone] if tone in TAB_TONES else None


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
            return "⛔"
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
