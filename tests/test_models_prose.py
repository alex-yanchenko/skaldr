from typing import Any, Final

import pytest
from latex2mathml.exceptions import MissingSuperScriptOrSubscriptError
from pydantic import ValidationError

from skaldr.errors import ReportError
from skaldr.models import (
    Callout,
    Code,
    DefItem,
    DefList,
    Divider,
    Heading,
    ListBlock,
    ListItem,
    Math,
    Note,
    parse_report,
)
from tests.factories import make_cell, make_grid, make_report


def test_list_parses_flat_and_nested_items_to_whole_model() -> None:
    block = {"type": "list", "items": ["flat", {"text": "parent", "items": ["a", {"text": "b"}]}]}

    report = parse_report(make_report(blocks=[block]))

    assert report.blocks[0] == ListBlock(
        type="list",
        items=["flat", ListItem(text="parent", items=["a", ListItem(text="b")])],
    )


def test_list_nesting_at_the_max_depth_is_accepted() -> None:
    four_deep = {
        "type": "list",
        "items": [{"text": "1", "items": [{"text": "2", "items": [{"text": "3", "items": ["4"]}]}]}],
    }

    report = parse_report(make_report(blocks=[four_deep]))

    assert report.blocks[0] == ListBlock(
        type="list",
        items=[ListItem(text="1", items=[ListItem(text="2", items=[ListItem(text="3", items=["4"])])])],
    )


def test_list_nesting_beyond_the_max_depth_is_rejected() -> None:
    five_deep = {
        "type": "list",
        "items": [
            {
                "text": "1",
                "items": [{"text": "2", "items": [{"text": "3", "items": [{"text": "4", "items": ["5"]}]}]}],
            }
        ],
    }

    with pytest.raises(ReportError, match=r"list nesting exceeds the maximum depth"):
        parse_report(make_report(blocks=[five_deep]))


def test_list_item_with_blank_text_is_rejected() -> None:
    block = {"type": "list", "items": [{"text": "", "items": ["x"]}]}

    with pytest.raises(ReportError, match=r"blocks\.0\.list\.items"):
        parse_report(make_report(blocks=[block]))


def test_list_item_with_an_unknown_key_is_rejected() -> None:
    block = {"type": "list", "items": [{"text": "x", "children": ["y"]}]}

    with pytest.raises(ReportError, match=r"blocks\.0\.list\.items"):
        parse_report(make_report(blocks=[block]))


def test_check_list_item_carries_a_checked_flag_defaulting_false() -> None:
    block = {"type": "list", "style": "check", "items": ["open", {"text": "closed", "checked": True}]}

    report = parse_report(make_report(blocks=[block]))

    assert report.blocks[0] == ListBlock(
        type="list",
        style="check",
        items=["open", ListItem(text="closed", checked=True)],
    )


def test_checked_on_a_non_check_style_list_is_rejected() -> None:
    block = {"type": "list", "style": "bullet", "items": [{"text": "x", "checked": True}]}

    with pytest.raises(ReportError, match=r"`checked` is only valid in a `style: check` list"):
        parse_report(make_report(blocks=[block]))


def test_checked_nested_in_a_non_check_style_list_is_rejected() -> None:
    block = {
        "type": "list",
        "style": "number",
        "items": [{"text": "parent", "items": [{"text": "kid", "checked": True}]}],
    }

    with pytest.raises(ReportError, match=r"`checked` is only valid"):
        parse_report(make_report(blocks=[block]))


def test_a_numbered_list_takes_a_start_and_a_numbering() -> None:
    block = {"type": "list", "style": "number", "start": 3, "numbering": "roman", "items": ["c"]}

    report = parse_report(make_report(blocks=[block]))

    assert report.blocks[0] == ListBlock(type="list", style="number", start=3, numbering="roman", items=["c"])


def test_a_decision_list_item_carries_a_decided_flag_defaulting_false() -> None:
    block = {"type": "list", "style": "decision", "items": ["open", {"text": "chosen", "decided": True}]}

    report = parse_report(make_report(blocks=[block]))

    assert report.blocks[0] == ListBlock(
        type="list",
        style="decision",
        items=["open", ListItem(text="chosen", decided=True)],
    )


@pytest.mark.parametrize(
    ("options", "message"),
    [
        pytest.param(
            {"style": "bullet", "start": 2, "items": ["a"]},
            "`start` is only valid in a `style: number` list",
            id="start-on-a-bullet-list",
        ),
        pytest.param(
            {"style": "check", "numbering": "letters", "items": ["a"]},
            "`numbering` is only valid in a `style: number` list",
            id="numbering-on-a-check-list",
        ),
        pytest.param(
            {"style": "decision", "numbering": "decimal", "items": ["a"]},
            "`numbering` is only valid in a `style: number` list",
            id="decimal-numbering-on-a-decision-list",
        ),
        pytest.param(
            {"style": "number", "items": [{"text": "a", "decided": True}]},
            "`decided` is only valid in a `style: decision` list",
            id="decided-in-a-number-list",
        ),
        pytest.param(
            {"style": "bullet", "items": [{"text": "a", "items": [{"text": "b", "decided": True}]}]},
            "`decided` is only valid in a `style: decision` list",
            id="decided-nested-in-a-bullet-list",
        ),
        pytest.param(
            {"style": "decision", "items": [{"text": "a", "checked": True}]},
            "`checked` is only valid in a `style: check` list",
            id="checked-in-a-decision-list",
        ),
    ],
)
def test_a_list_option_outside_its_style_is_rejected(options: dict[str, Any], message: str) -> None:
    with pytest.raises(ReportError) as raised:
        parse_report(make_report(blocks=[{"type": "list", **options}]))

    assert str(raised.value) == f"invalid content data: blocks.0.list: Value error, {message}"


@pytest.mark.parametrize(
    ("start", "message"),
    [
        pytest.param(0, "Input should be greater than or equal to 1", id="below-one"),
        pytest.param(
            1_000_000_000,
            "Input should be less than or equal to 999999999",
            id="past-the-nine-digits-a-markdown-list-marker-holds",
        ),
    ],
)
def test_a_list_start_out_of_range_is_rejected(start: int, message: str) -> None:
    block = {"type": "list", "style": "number", "start": start, "items": ["a"]}

    with pytest.raises(ReportError) as raised:
        parse_report(make_report(blocks=[block]))

    assert str(raised.value) == f"invalid content data: blocks.0.list.start: {message}"


def test_a_list_start_of_nine_digits_is_accepted() -> None:
    block = {"type": "list", "style": "number", "start": 999_999_999, "items": ["a"]}

    report = parse_report(make_report(blocks=[block]))

    assert report.blocks[0] == ListBlock(type="list", style="number", start=999_999_999, items=["a"])


def test_def_list_parses_to_whole_model() -> None:
    block = {"type": "def_list", "items": [{"term": "Action", "body": "Do it."}]}

    report = parse_report(make_report(blocks=[block]))

    assert report.blocks[0] == DefList(type="def_list", items=[DefItem(term="Action", body="Do it.")])


def test_def_list_with_no_items_is_rejected() -> None:
    with pytest.raises(ReportError, match=r"blocks\.0\.def_list\.items"):
        parse_report(make_report(blocks=[{"type": "def_list", "items": []}]))


def test_note_parses_to_whole_model_with_optional_title() -> None:
    block = {"type": "note", "body": "An aside."}

    report = parse_report(make_report(blocks=[block]))

    assert report.blocks[0] == Note(type="note", body="An aside.", title=None)


def test_math_parses_to_whole_model() -> None:
    report = parse_report(make_report(blocks=[{"type": "math", "expression": "E = mc^2"}]))

    assert report.blocks[0] == Math(type="math", expression="E = mc^2")


@pytest.mark.parametrize(
    ("expression", "message"),
    [
        pytest.param(
            "x^",
            "Value error, invalid math expression 'x^': latex2mathml cannot convert it "
            "(MissingSuperScriptOrSubscriptError)",
            id="converter-rejects-it",
        ),
        pytest.param("", "String should have at least 1 character", id="empty"),
        pytest.param(
            r"\href{https://e.com}{x}",
            r"Value error, math expression '\href{https://e.com}{x}' sets the href attribute, which is not "
            r"a MathML attribute skaldr renders: leave out \href, \class and \style",
            id="href",
        ),
        pytest.param(
            r"\class{loud}{x}",
            r"Value error, math expression '\class{loud}{x}' sets the class attribute, which is not "
            r"a MathML attribute skaldr renders: leave out \href, \class and \style",
            id="class",
        ),
        pytest.param(
            r"\style{color:red}{x}",
            r"Value error, math expression '\style{color:red}{x}' sets the style attribute, which is not "
            r"a MathML attribute skaldr renders: leave out \href, \class and \style",
            id="style",
        ),
        pytest.param(
            "a $$ b",
            r"Value error, math expression 'a $$ b' holds $$, which ends a Notion equation early: "
            r"write \$\$ for literal dollars",
            id="double-dollar",
        ),
        pytest.param(
            r"\simga",
            r"Value error, math expression '\simga' uses \simga, which latex2mathml does not know: "
            r"check its spelling, or write \text{...} for literal text",
            id="unknown-command",
        ),
        pytest.param(
            r"\color{color()} x",
            r"Value error, math expression '\color{color()} x' sets the colour 'color()', which is not a "
            "CSS colour: write a colour name like red, a hex value like #ff0000, or a colour function like "
            "rgb(255,0,0)",
            id="colour-the-css-parser-raises-on",
        ),
    ],
)
def test_a_math_block_that_cannot_render_fails_at_its_path(expression: str, message: str) -> None:
    with pytest.raises(ReportError) as raised:
        parse_report(make_report(blocks=[{"type": "math", "expression": expression}]))

    assert str(raised.value) == f"invalid content data: blocks.0.math.expression: {message}"


def test_a_math_block_that_cannot_render_keeps_the_converter_failure_as_the_cause() -> None:
    with pytest.raises(ValidationError) as raised:
        Math.model_validate({"type": "math", "expression": "x^"})

    value_error = raised.value.errors()[0].get("ctx", {})["error"]
    report_error = value_error.__cause__
    assert (type(value_error), type(report_error), type(report_error.__cause__)) == (
        ValueError,
        ReportError,
        MissingSuperScriptOrSubscriptError,
    )


def test_a_level_four_heading_parses_to_whole_model() -> None:
    report = parse_report(make_report(blocks=[{"type": "heading", "level": 4, "text": "Bin detail"}]))

    assert report.blocks[0] == Heading(type="heading", text="Bin detail", level=4)


def test_a_heading_below_level_four_is_rejected() -> None:
    with pytest.raises(ReportError) as raised:
        parse_report(make_report(blocks=[{"type": "heading", "level": 5, "text": "Too deep"}]))

    assert str(raised.value) == "invalid content data: blocks.0.heading.level: Input should be 2, 3 or 4"


def test_a_divider_parses_to_a_block_with_no_fields_of_its_own() -> None:
    report = parse_report(make_report(blocks=[{"type": "divider"}]))

    assert report.blocks[0] == Divider(type="divider")


@pytest.mark.parametrize(
    "container",
    [
        pytest.param({"type": "section", "title": "S", "blocks": [{"type": "divider"}]}, id="section"),
        pytest.param({"type": "panel", "title": "P", "blocks": [{"type": "divider"}]}, id="panel"),
        pytest.param(make_grid([make_cell(6, [{"type": "divider"}])]), id="grid-cell"),
        pytest.param(
            {"type": "walkthrough", "steps": [{"label": "Go", "detail": [{"type": "divider"}]}]},
            id="walkthrough-detail",
        ),
    ],
)
def test_a_divider_is_accepted_wherever_a_leaf_block_is(container: dict[str, Any]) -> None:
    parsed = parse_report(make_report(blocks=[container])).blocks[0]

    assert parsed.model_dump(exclude_defaults=True) == container


def test_a_divider_refuses_a_field_it_does_not_have() -> None:
    with pytest.raises(ReportError) as raised:
        parse_report(make_report(blocks=[{"type": "divider", "text": "or"}]))

    assert str(raised.value) == "invalid content data: blocks.0.divider.text: Extra inputs are not permitted"


def test_callout_accepts_a_palette_alias_of_a_semantic_tone() -> None:
    """callout is semantic-only, but a palette alias of one of its four tones works (green→success)."""
    ok = parse_report(make_report(blocks=[{"type": "callout", "tone": "green", "body": "b"}]))
    callout = ok.blocks[0]
    assert isinstance(callout, Callout)
    assert callout.tone == "success"


@pytest.mark.parametrize("tone", ["teal", "sky", "accent", "neutral", "violet", "slate"])
def test_callout_rejects_a_non_semantic_tone_with_a_self_explaining_message(tone: str) -> None:
    # the error names both the allowed set AND the offending value, so the fix needs no guide lookup
    with pytest.raises(
        ReportError,
        match=rf"callout tone must be one of info, success, warning, danger \(got '{tone}'\)",
    ):
        parse_report(make_report(blocks=[{"type": "callout", "tone": tone, "body": "b"}]))


CALLOUT_WITHOUT_ICON: Final[dict[str, Any]] = {"type": "callout", "tone": "info", "body": "b"}


@pytest.mark.parametrize(
    ("icon", "stored"),
    [
        pytest.param("🧪", "🧪", id="one-code-point"),
        pytest.param("⚠️", "⚠️", id="with-a-variation-selector"),
        pytest.param("⚠", "⚠️", id="a-text-presentation-symbol-takes-its-emoji-form"),
        pytest.param("©", "©️", id="a-text-symbol-with-an-emoji-form-takes-it"),
        pytest.param("1⃣", "1️⃣", id="an-unqualified-keycap-takes-its-emoji-form"),
        pytest.param("👍🏽", "👍🏽", id="with-a-skin-tone"),
        pytest.param("👩‍🔬", "👩‍🔬", id="joined-by-a-zero-width-joiner"),
        pytest.param("🇺🇦", "🇺🇦", id="a-flag"),
        pytest.param("1️⃣", "1️⃣", id="a-keycap"),
    ],
)
def test_a_callout_and_a_note_take_one_emoji_as_their_icon_in_its_emoji_form(icon: str, stored: str) -> None:
    blocks = [{**CALLOUT_WITHOUT_ICON, "icon": icon}, {"type": "note", "icon": icon, "body": "b"}]

    report = parse_report(make_report(blocks=blocks))

    assert report.blocks == [
        Callout(type="callout", tone="info", icon=stored, body="b"),
        Note(type="note", icon=stored, body="b"),
    ]


@pytest.mark.parametrize(
    ("block", "icon"),
    [
        pytest.param(CALLOUT_WITHOUT_ICON, "A", id="a-letter"),
        pytest.param(CALLOUT_WITHOUT_ICON, "1", id="a-digit"),
        pytest.param(CALLOUT_WITHOUT_ICON, "✓", id="a-text-symbol-that-is-no-emoji"),
        pytest.param(CALLOUT_WITHOUT_ICON, "🏽", id="a-skin-tone-alone"),
        pytest.param(CALLOUT_WITHOUT_ICON, "\N{ZERO WIDTH JOINER}", id="a-zero-width-joiner-alone"),
        pytest.param(CALLOUT_WITHOUT_ICON, "🇺", id="half-a-flag"),
        pytest.param(CALLOUT_WITHOUT_ICON, "🇺🇦🇺🇦", id="two-flags"),
        pytest.param(CALLOUT_WITHOUT_ICON, "🧪🧪", id="two-emoji"),
        pytest.param(CALLOUT_WITHOUT_ICON, " 🧪", id="an-emoji-padded-with-a-space"),
        pytest.param(CALLOUT_WITHOUT_ICON, "", id="empty"),
        pytest.param({"type": "note", "body": "b"}, "go", id="a-word-on-a-note"),
    ],
)
def test_an_icon_that_is_not_one_emoji_is_rejected(block: dict[str, Any], icon: str) -> None:
    with pytest.raises(ReportError) as raised:
        parse_report(make_report(blocks=[{**block, "icon": icon}]))

    assert str(raised.value) == (
        f"invalid content data: blocks.0.{block['type']}.icon: Value error, "
        f"icon must be a single emoji (got '{icon}')"
    )


def test_blank_heading_is_rejected() -> None:
    with pytest.raises(ReportError, match=r"blocks\.0\.heading\.text: String should match pattern '\\S'$"):
        parse_report(make_report(blocks=[{"type": "heading", "text": "   "}]))


def test_blank_heading_sub_is_rejected() -> None:
    with pytest.raises(ReportError, match=r"blocks\.0\.heading\.sub: String should match pattern '\\S'$"):
        parse_report(make_report(blocks=[{"type": "heading", "text": "Overview", "sub": "  "}]))


@pytest.mark.parametrize(
    ("block", "location"),
    [
        (
            {
                "type": "swimlane",
                "lanes": ["Eng"],
                "columns": [{"name": "S1", "sub": "  "}],
                "steps": [{"lane": "Eng", "col": "S1", "n": "1", "label": "Build"}],
            },
            "blocks.0.swimlane.columns.0.sub",
        ),
        (
            {
                "type": "walkthrough",
                "steps": [{"label": "Step", "sub": "  ", "detail": [{"type": "text", "body": "x"}]}],
            },
            "blocks.0.walkthrough.steps.0.sub",
        ),
        (
            {"type": "range", "segments": [{"label": "Q3", "span": 1, "sub": "  "}]},
            "blocks.0.range.segments.0.sub",
        ),
    ],
)
def test_blank_sub_is_rejected_on_every_sub_bearing_block(block: dict[str, object], location: str) -> None:
    with pytest.raises(ReportError) as raised:
        parse_report(make_report(blocks=[block]))

    assert str(raised.value) == f"invalid content data: {location}: String should match pattern '\\S'"


def test_fact_strip_rejects_more_than_eight_facts() -> None:
    facts = [{"label": f"l{i}", "value": f"v{i}"} for i in range(9)]

    with pytest.raises(ReportError, match=r"facts"):
        parse_report(make_report(blocks=[{"type": "fact_strip", "facts": facts}]))


@pytest.mark.parametrize(
    "lang",
    [
        pytest.param("shell", id="a-word"),
        pytest.param("c++", id="plus-signs"),
        pytest.param("c#", id="a-hash"),
        pytest.param("objective-c", id="a-dash"),
        pytest.param("plain text", id="two-words"),
        pytest.param("a" * 40, id="forty-characters"),
    ],
)
def test_a_code_language_is_one_or_more_fence_safe_words(lang: str) -> None:
    block = parse_report(make_report(blocks=[{"type": "code", "content": "x", "lang": lang}])).blocks[0]

    assert isinstance(block, Code)
    assert block.lang == lang


@pytest.mark.parametrize(
    "lang",
    [
        pytest.param("", id="empty"),
        pytest.param(" x", id="a-leading-space"),
        pytest.param("x ", id="a-trailing-space"),
        pytest.param("a  b", id="two-spaces"),
        pytest.param("a\nb", id="a-newline"),
        pytest.param("```", id="backticks"),
        pytest.param("{x}", id="braces"),
        pytest.param("a" * 41, id="forty-one-characters"),
    ],
)
def test_a_code_language_that_could_break_its_fence_is_refused(lang: str) -> None:
    with pytest.raises(ReportError, match=r"blocks\.0\.code\.lang"):
        parse_report(make_report(blocks=[{"type": "code", "content": "x", "lang": lang}]))
