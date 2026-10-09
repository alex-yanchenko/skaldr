import json
import re
from collections.abc import Mapping
from typing import get_args

import pytest

from skaldr.errors import ConnectorError
from skaldr.export.adf import IssueLinks, write_adf_runs
from skaldr.export.adf.colors import BADGE_LOZENGE
from skaldr.export.runs import (
    Break,
    CheckMark,
    Chip,
    DecisionMark,
    ExportRich,
    Gauge,
    IndicatorMark,
    StatusMark,
    SwimlaneMark,
)
from skaldr.models import BadgeColorLiteral, StatusState, SwimlaneStepState, ToneLiteral
from skaldr.richtext import (
    AnchorLink,
    Citation,
    Code,
    InlineMath,
    Link,
    Placeholder,
    Plain,
    ScriptPosition,
    ScriptText,
    Styled,
    StyleName,
    Tinted,
)

SITE = "https://example.atlassian.net"
PLAN_LINKS = IssueLinks(SITE, frozenset({"PLAN"}))


def _text(text: str, *marks: Mapping[str, object]) -> dict[str, object]:
    node: dict[str, object] = {"type": "text", "text": text}
    if marks:
        node["marks"] = list(marks)
    return node


STRONG = {"type": "strong"}
EM = {"type": "em"}
CODE = {"type": "code"}
UNDERLINE = {"type": "underline"}
STRIKE = {"type": "strike"}


def _link(href: str) -> dict[str, object]:
    return {"type": "link", "attrs": {"href": href}}


def _written(runs: ExportRich, links: IssueLinks | None = None) -> list[dict[str, object]]:
    return [dict(node) for node in write_adf_runs(runs, links)]


def test_plain_text_is_one_text_node() -> None:
    assert _written((Plain("hello"),)) == [_text("hello")]


def test_empty_text_writes_no_node() -> None:
    assert _written((Plain(""),)) == []


def test_adjacent_plain_runs_merge_into_one_text_node() -> None:
    assert _written((Plain("a"), Plain("b"))) == [_text("ab")]


def test_adjacent_runs_with_the_same_marks_merge() -> None:
    runs = (Styled("bold", (Plain("a"),)), Styled("bold", (Plain("b"),)))

    assert _written(runs) == [_text("ab", STRONG)]


@pytest.mark.parametrize(
    ("style", "mark"),
    [("bold", STRONG), ("italic", EM), ("underline", UNDERLINE), ("strike", STRIKE)],
)
def test_each_style_becomes_its_mark(style: StyleName, mark: Mapping[str, object]) -> None:
    assert _written((Styled(style, (Plain("x"),)),)) == [_text("x", mark)]


def test_nested_styles_carry_both_marks_in_a_fixed_order() -> None:
    inside_out = (Styled("italic", (Styled("bold", (Plain("x"),)),)),)
    outside_in = (Styled("bold", (Styled("italic", (Plain("x"),)),)),)

    assert _written(inside_out) == _written(outside_in) == [_text("x", STRONG, EM)]


def test_the_same_style_nested_in_itself_is_one_mark() -> None:
    runs = (Styled("bold", (Styled("bold", (Plain("x"),)),)),)

    assert _written(runs) == [_text("x", STRONG)]


def test_a_link_marks_every_text_node_of_its_label() -> None:
    runs = (Link((Plain("a "), Styled("bold", (Plain("b"),))), "https://example.com/x"),)

    assert _written(runs) == [
        _text("a ", _link("https://example.com/x")),
        _text("b", _link("https://example.com/x"), STRONG),
    ]


def test_inline_code_is_a_text_node_with_the_code_mark() -> None:
    assert _written((Code("x = 1"),)) == [_text("x = 1", CODE)]


def test_code_keeps_a_link_and_drops_the_styles_adf_cannot_combine_with_it() -> None:
    runs = (Styled("bold", (Link((Code("x"),), "https://example.com"),)),)

    assert _written(runs) == [_text("x", _link("https://example.com"), CODE)]


def test_code_drops_a_text_colour() -> None:
    runs = (Tinted("danger", None, (Code("x"),)),)

    assert _written(runs) == [_text("x", CODE)]


def test_a_tinted_run_becomes_a_text_colour() -> None:
    runs = (Tinted("danger", "warning", (Plain("x"),)),)

    assert _written(runs) == [_text("x", {"type": "textColor", "attrs": {"color": "#DE350B"}})]


def test_a_tinted_run_with_only_a_background_adds_no_mark() -> None:
    assert _written((Tinted(None, "warning", (Plain("x"),)),)) == [_text("x")]


@pytest.mark.parametrize(("position", "kind"), [("subscript", "sub"), ("superscript", "sup")])
def test_a_script_becomes_a_subsup_mark(position: ScriptPosition, kind: str) -> None:
    assert _written((ScriptText(position, "2"),)) == [_text("2", {"type": "subsup", "attrs": {"type": kind}})]


def test_an_anchor_link_keeps_only_its_label() -> None:
    assert _written((AnchorLink((Plain("Jump"),), "target"),)) == [_text("Jump")]


def test_a_citation_with_a_url_links_its_number() -> None:
    assert _written((Citation("k", 3, "https://example.com/k"),)) == [
        _text("[3]", _link("https://example.com/k"))
    ]


def test_a_citation_without_a_url_is_its_number() -> None:
    assert _written((Citation("k", 3),)) == [_text("[3]")]


def test_a_placeholder_is_code() -> None:
    assert _written((Placeholder("who"),)) == [_text("{{who}}", CODE)]


def test_inline_math_is_code() -> None:
    assert _written((InlineMath(r"\frac{a}{b}"),)) == [_text(r"\frac{a}{b}", CODE)]


def test_a_line_break_is_a_hard_break() -> None:
    assert _written((Plain("a"), Break(), Plain("b"))) == [
        _text("a"),
        {"type": "hardBreak"},
        _text("b"),
    ]


def test_a_gauge_is_its_text_bar() -> None:
    assert _written((Gauge(3, 10),)) == [_text("███░░░░░░░")]


@pytest.mark.parametrize(
    ("color", "lozenge"),
    [
        ("slate", "neutral"),
        ("blue", "blue"),
        ("green", "green"),
        ("amber", "yellow"),
        ("red", "red"),
        ("violet", "purple"),
        ("teal", "green"),
        ("sky", "blue"),
    ],
)
def test_a_chip_is_a_status_lozenge_in_the_nearest_of_the_six_colours(
    color: BadgeColorLiteral, lozenge: str
) -> None:
    assert _written((Chip("API", color),)) == [{"type": "status", "attrs": {"text": "API", "color": lozenge}}]


def test_every_badge_colour_has_a_lozenge_colour() -> None:
    assert set(BADGE_LOZENGE) == set(get_args(BadgeColorLiteral))


def test_a_chip_with_no_label_writes_nothing() -> None:
    assert _written((Chip("", "blue"),)) == []


@pytest.mark.parametrize(
    ("state", "lozenge"),
    [
        ("done", "green"),
        ("current", "blue"),
        ("pending", "neutral"),
        ("failed", "red"),
        ("blocked", "yellow"),
    ],
)
def test_a_status_mark_is_a_lozenge_named_for_its_state(state: StatusState, lozenge: str) -> None:
    assert _written((StatusMark(state),)) == [{"type": "status", "attrs": {"text": state, "color": lozenge}}]


@pytest.mark.parametrize(
    ("state", "lozenge"),
    [
        ("done", "green"),
        ("current", "blue"),
        ("todo", "neutral"),
        ("blocked", "yellow"),
        ("deferred", "purple"),
    ],
)
def test_a_swimlane_mark_is_a_lozenge_named_for_its_state(state: SwimlaneStepState, lozenge: str) -> None:
    assert _written((SwimlaneMark(state),)) == [
        {"type": "status", "attrs": {"text": state, "color": lozenge}}
    ]


def test_an_indicator_a_check_and_a_decision_mark_are_their_glyph() -> None:
    tone: ToneLiteral = "success"

    assert _written((IndicatorMark(tone), CheckMark(True), DecisionMark(False))) == [_text("🟢✓❓")]


def test_an_issue_key_of_a_known_project_is_an_inline_card_when_the_site_is_known() -> None:
    assert _written((Plain("see PLAN-12, then more"),), PLAN_LINKS) == [
        _text("see "),
        {"type": "inlineCard", "attrs": {"url": f"{SITE}/browse/PLAN-12"}},
        _text(", then more"),
    ]


def test_the_site_url_may_end_in_a_slash() -> None:
    links = IssueLinks(SITE + "/", frozenset({"PLAN"}))

    assert _written((Plain("PLAN-1"),), links) == [
        {"type": "inlineCard", "attrs": {"url": f"{SITE}/browse/PLAN-1"}}
    ]


def test_an_issue_key_stays_text_when_no_site_is_known() -> None:
    assert _written((Plain("see PLAN-12"),)) == [_text("see PLAN-12")]


@pytest.mark.parametrize("text", ["UTF-8", "XPLAN-1", "PLAN-1x", "PLAN-", "plan-1", "A-PLAN-1", "PLAN-1-2"])
def test_a_text_that_only_looks_like_an_issue_key_stays_text(text: str) -> None:
    assert _written((Plain(text),), PLAN_LINKS) == [_text(text)]


def test_an_issue_key_inside_code_stays_code() -> None:
    assert _written((Code("PLAN-12"),), PLAN_LINKS) == [_text("PLAN-12", CODE)]


def test_an_issue_key_inside_a_link_label_stays_linked_text() -> None:
    runs = (Link((Plain("PLAN-12"),), "https://example.com"),)

    assert _written(runs, PLAN_LINKS) == [_text("PLAN-12", _link("https://example.com"))]


def test_an_issue_key_can_be_styled_and_still_becomes_a_card() -> None:
    runs = (Styled("bold", (Plain("PLAN-12"),)),)

    assert _written(runs, PLAN_LINKS) == [{"type": "inlineCard", "attrs": {"url": f"{SITE}/browse/PLAN-12"}}]


HOSTILE_TEXT = [
    "*not bold* _nor this_ `nor code` [nor](link) <b>nor html</b> # nor heading",
    '{"type": "paragraph"} "quoted" \\ back\\slash',
    "line one\nline two\ttabbed",
    "emoji 😀 and accents é and 日本語",
    "&amp; &#60; {{placeholder}}",
]


@pytest.mark.parametrize("text", HOSTILE_TEXT)
def test_text_is_carried_verbatim_and_survives_a_json_round_trip(text: str) -> None:
    nodes = write_adf_runs((Plain(text),), None)

    assert json.loads(json.dumps(list(nodes))) == [{"type": "text", "text": text}]


@pytest.mark.parametrize(
    "url",
    ["javascript:alert(1)", "data:text/html;base64,AAAA", "/relative/path", "ftp://example.com/x", "#frag"],
)
def test_a_link_to_an_unsafe_or_relative_url_is_written_as_its_label_alone(url: str) -> None:
    assert _written((Link((Styled("bold", (Plain("x"),)),), url),)) == [_text("x", STRONG)]


@pytest.mark.parametrize("url", ["http://example.com", "https://example.com/a?b=c", "mailto:a@example.com"])
def test_a_link_to_an_allowed_scheme_is_kept(url: str) -> None:
    assert _written((Link((Plain("x"),), url),)) == [_text("x", _link(url))]


def test_a_citation_with_an_unsafe_url_is_its_number_alone() -> None:
    assert _written((Citation("k", 2, "javascript:alert(1)"),)) == [_text("[2]")]


def test_a_text_node_with_a_link_strong_and_em_carries_them_in_the_fixed_order() -> None:
    runs = (Styled("italic", (Styled("bold", (Link((Plain("x"),), "https://example.com"),)),)),)

    assert _written(runs) == [_text("x", _link("https://example.com"), STRONG, EM)]


def test_two_adjacent_links_to_different_urls_stay_separate_nodes() -> None:
    runs = (Link((Plain("a"),), "https://example.com/1"), Link((Plain("b"),), "https://example.com/2"))

    assert _written(runs) == [
        _text("a", _link("https://example.com/1")),
        _text("b", _link("https://example.com/2")),
    ]


@pytest.mark.parametrize(
    "site",
    [
        "http://example.atlassian.net",
        "example.atlassian.net",
        "https://",
        "https://user:secret@example.atlassian.net",
        "https://user@example.atlassian.net",
        "",
    ],
)
def test_issue_links_refuse_a_site_that_is_not_https_with_a_host_and_no_user_info(site: str) -> None:
    with pytest.raises(
        ConnectorError,
        match=re.escape(f"issue links need an https site URL with a host and no user info, got '{site}'"),
    ):
        IssueLinks(site, frozenset({"PLAN"}))


@pytest.mark.parametrize("key", ["", "P", "plan", "1PLAN", "PL AN", "PLAN-1", "PLAN/../x"])
def test_issue_links_refuse_a_project_key_that_is_not_a_jira_project_key(key: str) -> None:
    with pytest.raises(
        ConnectorError,
        match=re.escape(
            f"'{key}' is not a Jira project key: capital letters, digits and underscores, "
            "starting with a letter, at least two characters"
        ),
    ):
        IssueLinks(SITE, frozenset({"PLAN", key}))


def test_issue_links_accept_keys_with_digits_and_underscores() -> None:
    links = IssueLinks(SITE, frozenset({"AB_2"}))

    assert _written((Plain("AB_2-7"),), links) == [
        {"type": "inlineCard", "attrs": {"url": f"{SITE}/browse/AB_2-7"}}
    ]
