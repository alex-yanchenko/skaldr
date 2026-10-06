from typing import get_args

import pytest

from skaldr.export.glyphs import (
    CALLOUT_ICON,
    check_glyph,
    decision_glyph,
    gauge_bar,
    indicator_glyph,
    mark_glyph,
    status_glyph,
    swimlane_glyph,
    tab_icon,
)
from skaldr.export.runs import CheckMark, DecisionMark, IndicatorMark, Mark, StatusMark, SwimlaneMark
from skaldr.export.tree import ToneName
from skaldr.models import StatusState, SwimlaneStepState, ToneLiteral


def test_a_state_glyph_is_a_coloured_emoji_because_markdown_has_no_css_class_to_colour_it() -> None:
    assert {state: status_glyph(state) for state in get_args(StatusState)} == {
        "done": "✅",
        "current": "🔵",
        "pending": "⚪",
        "failed": "❌",
        "blocked": "⛔",
    }


def test_a_swimlane_step_glyph_is_a_coloured_emoji_for_every_step_state() -> None:
    assert {state: swimlane_glyph(state) for state in get_args(SwimlaneStepState)} == {
        "done": "✅",
        "current": "🔵",
        "todo": "⚪",
        "blocked": "⛔",
        "deferred": "⏸️",
    }


def test_an_indicator_glyph_is_a_coloured_dot_for_every_tone() -> None:
    assert {tone: indicator_glyph(tone) for tone in get_args(ToneLiteral)} == {
        "neutral": "⚪",
        "info": "🔵",
        "success": "🟢",
        "warning": "🟡",
        "danger": "🔴",
        "accent": "🟣",
        "teal": "🟢",
        "sky": "🔵",
    }


def test_a_check_glyph_is_a_tick_or_a_cross() -> None:
    assert (check_glyph(checked=True), check_glyph(checked=False)) == ("✓", "✗")


def test_a_decision_glyph_is_a_tick_for_decided_and_a_question_mark_for_open() -> None:
    assert (decision_glyph(decided=True), decision_glyph(decided=False)) == ("☑️", "❓")


def test_a_decided_glyph_differs_from_the_done_status_and_the_checked_glyphs() -> None:
    assert decision_glyph(decided=True) not in {status_glyph("done"), check_glyph(checked=True)}


def test_a_mark_reads_as_the_glyph_of_its_own_kind() -> None:
    marks: list[Mark] = [
        StatusMark("failed"),
        SwimlaneMark("deferred"),
        IndicatorMark("accent"),
        CheckMark(checked=False),
        DecisionMark(decided=True),
    ]

    assert [mark_glyph(mark) for mark in marks] == ["❌", "⏸️", "🟣", "✗", "☑️"]


@pytest.mark.parametrize(
    ("value", "maximum", "bar"),
    [
        pytest.param(5, 10, "█████░░░░░", id="half"),
        pytest.param(0, 10, "░░░░░░░░░░", id="empty"),
        pytest.param(12, 10, "██████████", id="over-the-maximum-stays-full"),
        pytest.param(-1, 10, "░░░░░░░░░░", id="below-zero-stays-empty"),
        pytest.param(1, 4, "███░░░░░░░", id="two-and-a-half-cells-fill-three"),
        pytest.param(3, 4, "████████░░", id="seven-and-a-half-cells-fill-eight"),
        pytest.param(5, 100, "█░░░░░░░░░", id="a-half-cell-fills-one-so-a-small-share-shows"),
    ],
)
def test_a_gauge_is_ten_cells_filled_in_proportion(value: float, maximum: float, bar: str) -> None:
    assert gauge_bar(value, maximum) == bar


def test_every_tone_has_a_callout_icon() -> None:
    assert sorted(CALLOUT_ICON) == sorted(get_args(ToneName))


def test_only_the_four_case_tones_give_a_tab_an_icon() -> None:
    assert {tone: tab_icon(tone) for tone in (*get_args(ToneName), None)} == {
        "neutral": None,
        "info": "💡",
        "success": "✅",
        "warning": "⚠️",
        "danger": "🛑",
        "accent": None,
        "teal": None,
        "sky": None,
        "muted": None,
        None: None,
    }
