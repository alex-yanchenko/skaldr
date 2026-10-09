from datetime import date
from typing import Any

import pytest

from skaldr.errors import ReportError
from skaldr.models import Person, parse_report
from skaldr.render import render_html, render_richtext
from skaldr.richtext import (
    DateMention,
    DocumentLink,
    IssueLink,
    PersonMention,
    Plain,
    RichContext,
    Styled,
    parse_rich,
    visible_text,
)
from tests.factories import make_report, markdown_of, notion_of

ADA = Person(notion="user://11111111-2222-3333-4444-555555555555", jira="5b10a2844c20165700ede21g")
SITE = "https://example.atlassian.net"
CONTEXT = RichContext(people={"ada": ADA, "bo": Person()}, jira_site=SITE)
PEOPLE_META: dict[str, Any] = {
    "title": "Plan",
    "jira_site": SITE,
    "people": {
        "ada": {"notion": "user://11111111-2222-3333-4444-555555555555", "jira": "5b10a2844c20165700ede21g"},
        "bo": {},
    },
}
TYPED_BODY = (
    "Due [1 Oct](date:2026-10-01) or [the week](date:2026-10-05/2026-10-09); "
    "[Ada](user:ada) owns [ABC-123](jira:ABC-123); see [the plan](doc:onboarding-plan#st2)."
)


def _text_block(body: str) -> list[dict[str, Any]]:
    return [{"type": "text", "body": body}]


def test_every_typed_link_parses_to_its_own_run() -> None:
    assert parse_rich(TYPED_BODY, CONTEXT) == (
        Plain("Due "),
        DateMention((Plain("1 Oct"),), date(2026, 10, 1), None),
        Plain(" or "),
        DateMention((Plain("the week"),), date(2026, 10, 5), date(2026, 10, 9)),
        Plain("; "),
        PersonMention((Plain("Ada"),), "ada", ADA),
        Plain(" owns "),
        IssueLink((Plain("ABC-123"),), "ABC-123", f"{SITE}/browse/ABC-123"),
        Plain("; see "),
        DocumentLink((Plain("the plan"),), "onboarding-plan", "st2"),
        Plain("."),
    )


def test_a_document_link_without_a_section_names_the_document_alone() -> None:
    assert parse_rich("[plan](doc:onboarding-plan)", CONTEXT) == (
        DocumentLink((Plain("plan"),), "onboarding-plan", None),
    )


def test_a_typed_link_label_keeps_its_marks() -> None:
    assert parse_rich("[**Ada**](user:ada)", CONTEXT) == (
        PersonMention((Styled("bold", (Plain("Ada"),)),), "ada", ADA),
    )


def test_an_issue_link_has_no_url_when_the_document_names_no_jira_site() -> None:
    assert parse_rich("[ABC-123](jira:ABC-123)", RichContext()) == (
        IssueLink((Plain("ABC-123"),), "ABC-123", None),
    )


def test_a_typed_link_reads_as_its_label_in_visible_text() -> None:
    assert visible_text(parse_rich(TYPED_BODY, CONTEXT)) == (
        "Due 1 Oct or the week; Ada owns ABC-123; see the plan."
    )


@pytest.mark.parametrize(
    ("text", "message"),
    [
        pytest.param(
            "[x](date:2026-13-01)",
            "invalid date '2026-13-01' in link target date:2026-13-01: write a date as YYYY-MM-DD",
            id="month-out-of-range",
        ),
        pytest.param(
            "[x](date:2026-10-1)",
            "invalid date '2026-10-1' in link target date:2026-10-1: write a date as YYYY-MM-DD",
            id="short-day",
        ),
        pytest.param(
            "[x](date:20261001)",
            "invalid date '20261001' in link target date:20261001: write a date as YYYY-MM-DD",
            id="compact-form",
        ),
        pytest.param(
            "[x](date:)",
            "invalid date '' in link target date:: write a date as YYYY-MM-DD",
            id="empty",
        ),
        pytest.param(
            "[x](date:2026-10-01/2026-02-30)",
            "invalid date '2026-02-30' in link target date:2026-10-01/2026-02-30: write a date as YYYY-MM-DD",
            id="range-end-not-a-day",
        ),
        pytest.param(
            "[x](date:2026-10-05/2026-10-01)",
            "date range date:2026-10-05/2026-10-01 ends before it starts: write the earlier date first",
            id="range-backwards",
        ),
        pytest.param(
            "[x](jira:abc-1)",
            "invalid Jira issue key 'abc-1' in link target jira:abc-1: write a project key in capitals, "
            "a hyphen and a number, as in jira:ABC-123",
            id="lowercase-issue-key",
        ),
        pytest.param(
            "[x](jira:)",
            "invalid Jira issue key '' in link target jira:: write a project key in capitals, "
            "a hyphen and a number, as in jira:ABC-123",
            id="empty-issue-key",
        ),
        pytest.param(
            "[x](doc:Plan)",
            "invalid document id 'Plan' in link target doc:Plan: a document id is lowercase letters and "
            "digits joined by single hyphens",
            id="uppercase-document-id",
        ),
        pytest.param(
            "[x](doc:plan#ST2)",
            "invalid section id 'ST2' in link target doc:plan#ST2: a section id is lowercase letters and "
            "digits joined by single hyphens",
            id="uppercase-section-id",
        ),
        pytest.param(
            "[x](doc:plan#)",
            "invalid section id '' in link target doc:plan#: a section id is lowercase letters and "
            "digits joined by single hyphens",
            id="empty-section-id",
        ),
        pytest.param(
            "[x](user:Ada!)",
            "invalid person key 'Ada!' in link target user:Ada!: a person key is letters, digits, '_' or "
            "'-' only",
            id="malformed-person-key",
        ),
        pytest.param(
            "[x](user:grace)",
            "rich text links to unknown person 'grace': declare it under meta.people",
            id="person-not-in-the-people-map",
        ),
    ],
)
def test_a_bad_typed_link_fails_naming_what_is_wrong(text: str, message: str) -> None:
    with pytest.raises(ReportError) as error:
        parse_rich(text, CONTEXT)

    assert str(error.value) == message


def test_a_person_link_fails_when_the_context_holds_no_people() -> None:
    with pytest.raises(ReportError) as error:
        parse_rich("[Ada](user:ada)", RichContext())

    assert str(error.value) == "rich text links to unknown person 'ada': declare it under meta.people"


def test_a_typed_link_in_a_field_fails_the_build_at_its_path() -> None:
    report = parse_report(make_report(blocks=_text_block("[Ada](user:ada)")))

    with pytest.raises(ReportError) as error:
        render_html(report)

    assert str(error.value) == (
        "blocks.0.body: rich text links to unknown person 'ada': declare it under meta.people"
    )


def test_a_person_without_a_notion_id_can_still_be_linked_by_key() -> None:
    assert parse_rich("[Bo](user:bo)", CONTEXT) == (PersonMention((Plain("Bo"),), "bo", Person()),)


def test_a_notion_id_must_be_a_user_uri() -> None:
    meta = {"title": "T", "people": {"ada": {"notion": "https://www.notion.so/ada"}}}

    with pytest.raises(ReportError) as error:
        parse_report(make_report(meta=meta))

    assert str(error.value) == (
        "invalid content data: meta.people.ada.notion: String should match pattern '^user://[0-9A-Fa-f-]+$'"
    )


def test_a_jira_site_loses_its_trailing_slash() -> None:
    report = parse_report(make_report(meta={"title": "T", "jira_site": f"{SITE}/"}))

    assert report.meta.jira_site == SITE


def test_a_jira_site_must_be_an_https_url() -> None:
    with pytest.raises(ReportError) as error:
        parse_report(make_report(meta={"title": "T", "jira_site": "http://example.atlassian.net"}))

    assert (
        str(error.value)
        == "invalid content data: meta.jira_site: Value error, jira_site must be an https:// URL"
    )


def test_a_jira_site_must_be_a_valid_url() -> None:
    with pytest.raises(ReportError) as error:
        parse_report(make_report(meta={"title": "T", "jira_site": "https://exa mple.com"}))

    assert str(error.value) == (
        "invalid content data: meta.jira_site: Value error, "
        "jira_site 'https://exa mple.com' is not a valid URL (it holds whitespace)"
    )


def test_a_person_key_must_be_a_plain_key() -> None:
    with pytest.raises(ReportError) as error:
        parse_report(make_report(meta={"title": "T", "people": {"Ada Lovelace": {}}}))

    assert str(error.value) == (
        "invalid content data: meta.people.Ada Lovelace.[key]: String should match pattern '^[A-Za-z0-9_-]+$'"
    )


def test_render_richtext_writes_each_typed_link_as_html() -> None:
    html = str(render_richtext(TYPED_BODY, people={"ada": ADA}, jira_site=SITE))

    assert html == (
        'Due <time class="date-chip" datetime="2026-10-01">1 Oct</time> or '
        '<span class="date-chip" data-range="2026-10-05/2026-10-09">the week</span>; '
        '<span class="person-chip" data-person="ada">Ada</span> owns '
        '<a class="issue-link" href="https://example.atlassian.net/browse/ABC-123">ABC-123</a>; '
        'see <a class="doc-link" href="onboarding-plan.html#st2">the plan</a>.'
    )


def test_an_issue_link_without_a_site_is_a_chip_not_a_link() -> None:
    assert str(render_richtext("[ABC-123](jira:ABC-123)")) == '<span class="issue-link">ABC-123</span>'


def test_a_document_link_without_a_section_has_no_fragment() -> None:
    assert (
        str(render_richtext("[plan](doc:onboarding-plan)"))
        == '<a class="doc-link" href="onboarding-plan.html">plan</a>'
    )


def test_a_typed_link_label_is_escaped_in_html() -> None:
    assert (
        str(render_richtext("[a <b>](date:2026-10-01)"))
        == '<time class="date-chip" datetime="2026-10-01">a &lt;b&gt;</time>'
    )


def test_a_full_page_render_resolves_people_from_the_meta_map() -> None:
    html = render_html(parse_report(make_report(meta=PEOPLE_META, blocks=_text_block(TYPED_BODY))))

    assert '<span class="person-chip" data-person="ada">Ada</span>' in html
    assert '<a class="issue-link" href="https://example.atlassian.net/browse/ABC-123">ABC-123</a>' in html


def test_github_markdown_keeps_the_label_and_links_issues_and_documents() -> None:
    assert markdown_of(_text_block(TYPED_BODY), meta=PEOPLE_META) == (
        "Due 1 Oct or the week; Ada owns [ABC-123](https://example.atlassian.net/browse/ABC-123); "
        "see [the plan](onboarding-plan.md).\n"
    )


def test_github_markdown_drops_the_section_since_a_github_heading_slug_comes_from_its_title() -> None:
    assert markdown_of(_text_block("[a](doc:plan#st2) [b](doc:plan)"), meta=PEOPLE_META) == (
        "[a](plan.md) [b](plan.md)\n"
    )


def test_github_markdown_leaves_an_issue_key_as_text_without_a_site() -> None:
    meta = {"title": "Plan"}

    assert markdown_of(_text_block("[ABC-123](jira:ABC-123)"), meta=meta) == "ABC-123\n"


def test_notion_markdown_writes_mentions_for_dates_and_people_and_links_for_issues() -> None:
    assert notion_of(_text_block(TYPED_BODY), meta=PEOPLE_META) == (
        'Due <mention-date start="2026-10-01"/> or <mention-date start="2026-10-05" end="2026-10-09"/>; '
        '<mention-user url="user://11111111-2222-3333-4444-555555555555">Ada</mention-user> owns '
        "[ABC-123](https://example.atlassian.net/browse/ABC-123); see the plan.\n"
    )


def test_notion_markdown_writes_a_person_without_a_notion_id_as_its_label() -> None:
    assert notion_of(_text_block("[Bo](user:bo)"), meta=PEOPLE_META) == "Bo\n"


def test_emit_json_carries_people_and_the_jira_site_in_the_meta() -> None:
    meta = parse_report(make_report(meta=PEOPLE_META)).model_dump(mode="json")["meta"]

    assert meta["jira_site"] == SITE
    assert meta["people"] == {
        "ada": {"notion": "user://11111111-2222-3333-4444-555555555555", "jira": "5b10a2844c20165700ede21g"},
        "bo": {"notion": None, "jira": None},
    }


@pytest.mark.parametrize(
    ("site", "message"),
    [
        pytest.param(
            "https://u:p@evil.example/x",
            "jira_site 'https://u:p@evil.example/x' must not hold a username or password",
            id="userinfo",
        ),
        pytest.param(
            "https://u@evil.example",
            "jira_site 'https://u@evil.example' must not hold a username or password",
            id="username-only",
        ),
        pytest.param(
            "https://example.atlassian.net?q=1",
            "jira_site 'https://example.atlassian.net?q=1' must not hold a query",
            id="query",
        ),
        pytest.param(
            "https://example.atlassian.net#f",
            "jira_site 'https://example.atlassian.net#f' must not hold a fragment",
            id="fragment",
        ),
        pytest.param(
            "https:///path",
            "jira_site 'https:///path' names no host: write it as https://<your-site>",
            id="no-host",
        ),
    ],
)
def test_a_jira_site_refuses_what_would_misplace_the_browse_path(site: str, message: str) -> None:
    with pytest.raises(ReportError) as error:
        parse_report(make_report(meta={"title": "T", "jira_site": site}))

    assert str(error.value) == f"invalid content data: meta.jira_site: Value error, {message}"


def test_a_jira_site_may_carry_a_path_for_a_jira_served_below_one() -> None:
    meta = {"title": "T", "jira_site": "https://example.org/jira/"}
    html = render_html(parse_report(make_report(meta=meta, blocks=_text_block("[A-1](jira:A-1)"))))

    assert '<a class="issue-link" href="https://example.org/jira/browse/A-1">A-1</a>' in html


def test_a_date_range_of_three_dates_names_the_range_form() -> None:
    with pytest.raises(ReportError) as error:
        parse_rich("[x](date:2026-10-01/2026-10-01/2026-10-02)", CONTEXT)

    assert str(error.value) == (
        "date range date:2026-10-01/2026-10-01/2026-10-02 holds more than two dates: "
        "write a range as date:YYYY-MM-DD/YYYY-MM-DD"
    )


@pytest.mark.parametrize("text", ["[x](USER:ada)", "[x](Date:2026-10-01)", "`[x](date:2026-10-01)`"])
def test_a_scheme_in_capitals_or_inside_inline_code_stays_literal(text: str) -> None:
    runs = parse_rich(text, CONTEXT)

    assert not any(isinstance(run, DateMention | PersonMention) for run in runs)


def test_a_typed_link_in_inline_code_is_written_as_code() -> None:
    assert str(render_richtext("`[x](date:2026-10-01)`")) == "<code>[x](date:2026-10-01)</code>"


def test_a_flow_note_reads_typed_links_as_their_labels_and_lists_the_links_a_diagram_loses() -> None:
    flow = {
        "type": "flow",
        "numbered": False,
        "steps": [
            {"label": "Scan", "note": "[Ada](user:ada) by [1 Oct](date:2026-10-01)"},
            {"label": "Fix", "note": "see [ABC-1](jira:ABC-1) and [plan](doc:plan#st2)"},
        ],
    }

    assert markdown_of([flow], meta=PEOPLE_META) == (
        "```mermaid\n"
        "flowchart LR\n"
        '    s1["Scan<br>Ada by 1 Oct"]\n'
        '    s2["Fix<br>see ABC-1 and plan"]\n'
        "    s1 --> s2\n"
        "```\n"
        "\n"
        "- **Fix**: see [ABC-1](https://example.atlassian.net/browse/ABC-1) and [plan](plan.md)\n"
    )


def test_notion_writes_typed_links_in_a_table_cell_and_a_heading_caption() -> None:
    table = {
        "type": "table",
        "columns": [{"key": "who", "label": "Who", "kind": "rich"}, {"key": "n", "label": "N"}],
        "rows": [{"who": "[Ada](user:ada) on [1 Oct](date:2026-10-01)", "n": "x"}],
    }
    heading = {"type": "heading", "text": "Plan", "sub": "due [1 Oct](date:2026-10-01)"}

    assert notion_of([heading, table], meta=PEOPLE_META) == (
        "## Plan\n"
        '*due <mention-date start="2026-10-01"/>* {color="gray"}\n'
        '<table fit-page-width="true" header-row="true">\n'
        "\t<tr>\n"
        "\t\t<td>**Who**</td>\n"
        "\t\t<td>**N**</td>\n"
        "\t</tr>\n"
        "\t<tr>\n"
        '\t\t<td><mention-user url="user://11111111-2222-3333-4444-555555555555">Ada</mention-user> '
        'on <mention-date start="2026-10-01"/></td>\n'
        "\t\t<td>x</td>\n"
        "\t</tr>\n"
        "</table>\n"
    )


def test_a_person_label_is_escaped_inside_a_notion_mention() -> None:
    assert notion_of(_text_block("[a <b>](user:ada)"), meta=PEOPLE_META) == (
        '<mention-user url="user://11111111-2222-3333-4444-555555555555">a \\<b\\></mention-user>\n'
    )


def test_a_person_without_a_notion_id_is_a_chip_in_html_and_its_label_in_both_markdown_exports() -> None:
    body = _text_block("[a <b>](user:bo)")

    html = render_html(parse_report(make_report(meta=PEOPLE_META, blocks=body)))

    assert '<span class="person-chip" data-person="bo">a &lt;b&gt;</span>' in html
    assert markdown_of(body, meta=PEOPLE_META) == "a \\<b\\>\n"
    assert notion_of(body, meta=PEOPLE_META) == "a \\<b\\>\n"


def test_an_issue_and_a_document_label_are_escaped_in_html() -> None:
    html = str(
        render_richtext("[a <b>](jira:ABC-1) [c <i>](doc:plan#st2)", jira_site=SITE),
    )

    assert html == (
        '<a class="issue-link" href="https://example.atlassian.net/browse/ABC-1">a &lt;b&gt;</a> '
        '<a class="doc-link" href="plan.html#st2">c &lt;i&gt;</a>'
    )
