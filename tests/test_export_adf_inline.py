import json
import re
from collections.abc import Mapping
from datetime import date
from typing import get_args

import pytest

from skaldr.errors import ConnectorError, ExportInvariantError
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
    SectionLink,
    StatusMark,
    SwimlaneMark,
    TonedLabel,
)
from skaldr.models import BadgeColorLiteral, Person, StatusState, SwimlaneStepState, ToneLiteral
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
SUPERSCRIPT = {"type": "subsup", "attrs": {"type": "sup"}}
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
    runs = (Tinted("danger", None, (Plain("x"),)),)

    assert _written(runs) == [_text("x", {"type": "textColor", "attrs": {"color": "#DE350B"}})]


@pytest.mark.parametrize(
    "tone", [pytest.param(None, id="highlight-alone"), pytest.param("danger", id="colour-and-highlight")]
)
def test_a_highlight_is_an_invariant_the_check_backs(tone: ToneLiteral | None) -> None:
    with pytest.raises(ExportInvariantError) as raised:
        _written((Tinted(tone, "warning", (Plain("x"),)),))

    assert str(raised.value) == (
        "a Jira description does not show a text highlight; the export check should have refused it"
    )


@pytest.mark.parametrize(("position", "kind"), [("subscript", "sub"), ("superscript", "sup")])
def test_a_script_becomes_a_subsup_mark(position: ScriptPosition, kind: str) -> None:
    assert _written((ScriptText(position, "2"),)) == [_text("2", {"type": "subsup", "attrs": {"type": kind}})]


def test_a_section_link_keeps_only_its_label() -> None:
    assert _written((SectionLink((Plain("Jump"),), "target"),)) == [_text("Jump")]


def test_a_toned_label_becomes_a_text_colour() -> None:
    runs = (TonedLabel("danger", (Plain("Scan"),)),)

    assert _written(runs) == [_text("Scan", {"type": "textColor", "attrs": {"color": "#DE350B"}})]


def test_an_authored_link_to_a_heading_is_an_invariant_the_check_backs() -> None:
    with pytest.raises(ExportInvariantError) as raised:
        _written((AnchorLink((Plain("the counts"),), "counts"),))

    assert str(raised.value) == (
        "a Jira description cannot link to its own headings; the export check should have refused it"
    )


def test_a_citation_with_a_url_is_its_number_as_a_superscript_over_its_link() -> None:
    assert _written((Citation("k", 3, "https://example.com/k"),)) == [
        _text("[3]", _link("https://example.com/k"), SUPERSCRIPT)
    ]


def test_a_citation_without_a_url_is_its_number_as_a_superscript() -> None:
    assert _written((Citation("k", 3),)) == [_text("[3]", SUPERSCRIPT)]


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


def test_a_citation_with_an_unsafe_url_is_its_number_alone_as_a_superscript() -> None:
    assert _written((Citation("k", 2, "javascript:alert(1)"),)) == [_text("[2]", SUPERSCRIPT)]


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
        "https://a.net/x?q=1#f",
        "https://a.net?q=1",
        "https://a.net/#f",
        "HTTPS://a.net",
        "",
    ],
)
def test_issue_links_refuse_a_site_that_is_not_https_with_a_host_and_no_user_info(site: str) -> None:
    with pytest.raises(
        ConnectorError,
        match=re.escape(
            "issue links need a lowercase https:// site URL with a host and no user info, query or "
            f"fragment, got '{site}'"
        ),
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


def _date_node(timestamp: str) -> dict[str, object]:
    return {"type": "date", "attrs": {"timestamp": timestamp}}


def test_a_date_mention_is_its_label_then_a_date_node_at_utc_midnight_in_epoch_milliseconds() -> None:
    assert _written((Plain("by "), DateMention((Plain("1 Oct"),), date(2026, 10, 1), None))) == [
        _text("by 1 Oct "),
        _date_node("1790812800000"),
    ]


def test_a_date_range_is_its_label_then_the_start_date_to_the_end_date() -> None:
    assert _written((DateMention((Plain("the week"),), date(2026, 10, 5), date(2026, 10, 9)),)) == [
        _text("the week "),
        _date_node("1791158400000"),
        _text(" to "),
        _date_node("1791504000000"),
    ]


def test_a_date_label_keeps_its_marks_and_the_space_before_the_date_node_carries_none() -> None:
    runs = (DateMention((Styled("bold", (Plain("1 Oct"),)),), date(2026, 10, 1), None),)

    assert _written(runs) == [_text("1 Oct", STRONG), _text(" "), _date_node("1790812800000")]


def test_a_date_label_that_is_an_issue_card_alone_is_kept() -> None:
    links = IssueLinks(SITE, frozenset({"PLAN"}))
    runs = (DateMention((Plain("PLAN-12"),), date(2026, 10, 1), None),)

    assert _written(runs, links) == [
        {"type": "inlineCard", "attrs": {"url": f"{SITE}/browse/PLAN-12"}},
        _text(" "),
        _date_node("1790812800000"),
    ]


def test_a_blank_date_label_is_the_date_node_alone() -> None:
    assert _written((DateMention((Plain(" "),), date(2026, 10, 1), None),)) == [_date_node("1790812800000")]


def test_an_empty_date_label_is_the_date_node_alone() -> None:
    assert _written((DateMention((), date(2026, 10, 1), None),)) == [_date_node("1790812800000")]


def test_a_person_with_a_jira_account_is_a_mention_of_that_account() -> None:
    person = Person(jira="5b10a2844c20165700ede21g")

    assert _written((PersonMention((Plain("Ada Park"),), "ada", person),)) == [
        {"type": "mention", "attrs": {"id": "5b10a2844c20165700ede21g", "text": "@Ada Park"}}
    ]


def test_a_person_mention_takes_the_text_of_a_styled_label() -> None:
    person = Person(jira="acct-1")
    label = (Styled("bold", (Plain("Ada"),)), Plain(" Park"))

    assert _written((PersonMention(label, "ada", person),)) == [
        {"type": "mention", "attrs": {"id": "acct-1", "text": "@Ada Park"}}
    ]


@pytest.mark.parametrize(
    "person",
    [
        pytest.param(Person(), id="no-ids"),
        pytest.param(Person(slack="U0EXAMPLE2"), id="slack-id-only"),
    ],
)
def test_a_person_without_a_jira_account_is_the_label_as_plain_text(person: Person) -> None:
    assert _written((PersonMention((Plain("Bo"),), "bo", person),)) == [_text("Bo")]


def test_an_issue_link_with_a_url_is_an_inline_card() -> None:
    assert _written((IssueLink((Plain("ABC-123"),), "ABC-123", f"{SITE}/browse/ABC-123"),)) == [
        {"type": "inlineCard", "attrs": {"url": f"{SITE}/browse/ABC-123"}}
    ]


def test_an_issue_link_without_a_url_is_the_label_as_plain_text() -> None:
    assert _written((IssueLink((Plain("ABC-123"),), "ABC-123", None),)) == [_text("ABC-123")]


def test_a_link_to_another_document_is_an_invariant_the_check_backs() -> None:
    with pytest.raises(ExportInvariantError) as raised:
        _written((DocumentLink((Plain("the plan"),), "onboarding-plan", "st2"),))

    assert str(raised.value) == (
        "a Jira description cannot link to another skaldr document; the export check should have refused it"
    )
