import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from skaldr.cli import main
from skaldr.errors import ReportError
from skaldr.models import parse_report
from skaldr.publish import (
    JiraTarget,
    NotionTarget,
    NotionWhere,
    Publish,
    notion_page_id,
    without_publish_block,
)
from skaldr.render import extract_source, render_html
from tests.factories import (
    NOTION_PAGE_ID,
    NOTION_PAGE_URL,
    make_jira_target,
    make_notion_target,
    make_publish_report,
    make_report,
    make_section,
)

SOURCE_WITH_PUBLISH = f"""\
version: 1
meta:
  title: "Plan"
# where this document publishes
publish:
  doc_id: plan
  targets:
    - to: notion
      where:
        parent_page: "{NOTION_PAGE_URL}"
# a note on the targets above

blocks:
  - {{ type: text, body: "Hello." }}
"""
SOURCE_WITHOUT_PUBLISH = """\
version: 1
meta:
  title: "Plan"
# where this document publishes
blocks:
  - { type: text, body: "Hello." }
"""


def _parse(publish: dict[str, Any]) -> Publish | None:
    return parse_report(make_publish_report(publish)).publish


def test_a_publish_block_parses_into_one_target_per_service() -> None:
    jira = {
        "to": "jira",
        "where": {
            "project": "PLAN",
            "issue_type": "Task",
            "parent": "PLAN-100",
            "fields": {"labels": ["team"]},
        },
        "from": ["st1", "st2"],
        "split": ["st1", "st2"],
        "overrides": {"st2": {"fields": {"priority": "High"}}},
        "on_remote_edit": "overwrite",
    }
    notion = make_notion_target(split=["st1", "st2"], removed="delete")

    assert _parse({"doc_id": "onboarding-plan", "targets": [notion, jira]}) == Publish(
        doc_id="onboarding-plan",
        targets=[NotionTarget.model_validate(notion), JiraTarget.model_validate(jira)],
    )


def test_a_target_left_at_its_defaults_archives_and_refuses_remote_edits() -> None:
    assert _parse({"doc_id": "plan", "targets": [make_jira_target()]}) == Publish.model_validate(
        {
            "doc_id": "plan",
            "targets": [
                {
                    "to": "jira",
                    "where": {"project": "PLAN", "issue_type": "Task", "parent": None, "fields": {}},
                    "from": None,
                    "split": [],
                    "overrides": {},
                    "removed": "archive",
                    "on_remote_edit": "refuse",
                }
            ],
        }
    )


def test_a_target_serializes_from_under_the_key_authors_write() -> None:
    report = parse_report(
        make_publish_report({"doc_id": "plan", "targets": [make_jira_target(**{"from": ["st1"]})]})
    )

    assert report.model_dump(mode="json")["publish"]["targets"][0]["from"] == ["st1"]


def test_a_report_without_a_publish_block_has_none() -> None:
    assert parse_report(make_report()).publish is None


@pytest.mark.parametrize(
    ("reference", "page_id"),
    [
        pytest.param(NOTION_PAGE_URL, NOTION_PAGE_ID, id="titled-url"),
        pytest.param(f"{NOTION_PAGE_URL}?v=1#h", NOTION_PAGE_ID, id="query-and-fragment"),
        pytest.param(f"{NOTION_PAGE_URL}/", NOTION_PAGE_ID, id="trailing-slash"),
        pytest.param(f"https://app.notion.com/p/{NOTION_PAGE_ID}", NOTION_PAGE_ID, id="app-host"),
        pytest.param(NOTION_PAGE_ID.upper(), NOTION_PAGE_ID, id="uppercase-bare-id"),
        pytest.param("01234567-89ab-cdef-0123-456789abcdef", NOTION_PAGE_ID, id="dashed-id"),
        pytest.param(f"  {NOTION_PAGE_ID}\n", NOTION_PAGE_ID, id="surrounding-whitespace"),
        pytest.param("a" * 36, None, id="too-long"),
        pytest.param(f"zz{NOTION_PAGE_ID}", None, id="junk-prefix"),
        pytest.param(f"https://example.com/{NOTION_PAGE_ID}", None, id="not-a-notion-host"),
        pytest.param("https://www.notion.so/no-id-here", None, id="no-id"),
    ],
)
def test_a_notion_page_id_comes_from_a_notion_url_or_a_bare_id(reference: str, page_id: str | None) -> None:
    assert notion_page_id(reference) == page_id


def test_a_notion_where_reports_the_page_id_of_whichever_page_it_names() -> None:
    assert [NotionWhere(parent_page=NOTION_PAGE_URL).page_id, NotionWhere(page=NOTION_PAGE_ID).page_id] == [
        NOTION_PAGE_ID,
        NOTION_PAGE_ID,
    ]


@pytest.mark.parametrize(
    ("publish", "message"),
    [
        pytest.param(
            {"doc_id": "plan", "targets": [make_notion_target(split=["st1", "nope"])]},
            "publish target 1 (notion) splits on 'nope', which is not the id of a top-level section "
            "(a section is named by its `id:`)",
            id="unknown-split-id",
        ),
        pytest.param(
            {"doc_id": "plan", "targets": [make_jira_target(**{"from": ["ghost"]})]},
            "publish target 1 (jira) is built from 'ghost', which is not the id of a top-level section",
            id="unknown-from-id",
        ),
        pytest.param(
            {"doc_id": "plan", "targets": [make_jira_target(**{"from": ["st1", "st1"]})]},
            "publish target 1 (jira) lists 'st1' more than once in `from`",
            id="repeated-from-id",
        ),
        pytest.param(
            {"doc_id": "plan", "targets": [make_jira_target(**{"from": ["st1"], "split": ["st2"]})]},
            "publish target 1 (jira) splits on 'st2', which its `from` list leaves out",
            id="split-outside-from",
        ),
        pytest.param(
            {
                "doc_id": "plan",
                "targets": [
                    make_jira_target(split=["st1"], overrides={"st2": {"fields": {"priority": "High"}}})
                ],
            },
            "publish target 1 (jira) overrides 'st2', which is not one of its split sections",
            id="override-outside-split",
        ),
        pytest.param(
            {"doc_id": "plan", "targets": [make_notion_target(split=["st1", "st1"])]},
            "publish target 1 (notion) lists 'st1' more than once in `split`",
            id="repeated-split-id",
        ),
        pytest.param(
            {
                "doc_id": "plan",
                "targets": [make_notion_target(), make_notion_target(where={"page": NOTION_PAGE_ID})],
            },
            f"publish targets 1 and 2 both write to notion page {NOTION_PAGE_ID}",
            id="one-notion-page-named-two-ways",
        ),
        pytest.param(
            {
                "doc_id": "plan",
                "targets": [
                    make_jira_target(),
                    make_jira_target(
                        where={"project": "PLAN", "issue_type": "Bug", "fields": {"labels": ["x"]}}
                    ),
                ],
            },
            "publish targets 1 and 2 both write to jira project PLAN under no parent",
            id="one-jira-place-with-other-fields",
        ),
    ],
)
def test_a_publish_block_that_names_the_wrong_sections_fails_naming_them(
    publish: dict[str, Any], message: str
) -> None:
    with pytest.raises(ReportError, match=re.escape(message)):
        _parse(publish)


def test_every_publish_mistake_is_reported_at_once() -> None:
    publish = {
        "doc_id": "plan",
        "targets": [make_notion_target(split=["nope"]), make_jira_target(**{"from": ["ghost"]})],
    }

    with pytest.raises(ReportError) as raised:
        _parse(publish)

    assert str(raised.value) == (
        "invalid content data: Value error, "
        "publish target 1 (notion) splits on 'nope', which is not the id of a top-level section "
        "(a section is named by its `id:`); "
        "publish target 2 (jira) is built from 'ghost', which is not the id of a top-level section "
        "(a section is named by its `id:`)"
    )


SPLIT_ON_INNER = {"doc_id": "plan", "targets": [make_notion_target(split=["inner"])]}


def test_a_heading_id_is_not_a_section_a_target_can_split_on() -> None:
    report = make_report(blocks=[{"type": "heading", "text": "Inner", "id": "inner"}], publish=SPLIT_ON_INNER)

    with pytest.raises(
        ReportError, match=re.escape("splits on 'inner', which is not the id of a top-level section")
    ):
        parse_report(report)


def test_a_section_id_used_twice_cannot_name_a_publish_item() -> None:
    report = make_report(
        blocks=[make_section("inner"), make_section("inner", title="Other")], publish=SPLIT_ON_INNER
    )

    with pytest.raises(
        ReportError, match=re.escape("section id 'inner' names more than one top-level section")
    ):
        parse_report(report)


@pytest.mark.parametrize(
    ("target", "message"),
    [
        pytest.param(
            {"to": "notion", "where": {}},
            "a notion target names exactly one of `parent_page` or `page`",
            id="notion-no-page",
        ),
        pytest.param(
            {"to": "notion", "where": {"parent_page": NOTION_PAGE_URL, "page": NOTION_PAGE_URL}},
            "a notion target names exactly one of `parent_page` or `page`",
            id="notion-both",
        ),
        pytest.param(
            {"to": "notion", "where": {"page": "https://www.notion.so/no-id-here"}},
            "'https://www.notion.so/no-id-here' is not a Notion page URL or a 32-character page id",
            id="notion-bad-page",
        ),
        pytest.param(
            {"to": "jira", "where": {"project": "plan", "issue_type": "Task"}},
            "publish.targets.0.jira.where.project: String should match pattern",
            id="jira-lowercase-project",
        ),
        pytest.param(
            {"to": "jira", "where": {"project": "PLAN", "issue_type": "Task", "parent": "PLAN-0"}},
            "publish.targets.0.jira.where.parent: String should match pattern",
            id="jira-bad-parent",
        ),
        pytest.param(
            {"to": "jira", "where": {"project": "PLAN", "issue_type": "  "}},
            "publish.targets.0.jira.where.issue_type: String should have at least 1 character",
            id="jira-blank-issue-type",
        ),
        pytest.param(
            make_jira_target(removed="delete"),
            "a jira target cannot use `removed: delete`",
            id="jira-delete",
        ),
        pytest.param(
            make_jira_target(from_sections=["st1"]),
            "publish.targets.0.jira.from_sections: Extra inputs are not permitted",
            id="only-the-documented-from-spelling",
        ),
        pytest.param(
            make_jira_target(**{"from": []}),
            "publish.targets.0.jira.from: List should have at least 1 item",
            id="empty-from",
        ),
        pytest.param(
            {"to": "confluence", "where": {}},
            "does not match any of the expected tags: 'notion', 'jira'",
            id="unknown-service",
        ),
    ],
)
def test_each_connector_validates_its_own_where(target: dict[str, Any], message: str) -> None:
    with pytest.raises(ReportError, match=re.escape(message)):
        _parse({"doc_id": "plan", "targets": [target]})


def test_a_jira_parent_key_accepts_an_underscored_project() -> None:
    target = make_jira_target(where={"project": "AB_1", "issue_type": "Task", "parent": "AB_1-7"})

    assert _parse({"doc_id": "plan", "targets": [target]}) == Publish(
        doc_id="plan", targets=[JiraTarget.model_validate(target)]
    )


@pytest.mark.parametrize(
    ("publish", "message"),
    [
        pytest.param(
            {"doc_id": "plan", "targets": []},
            "publish.targets: List should have at least 1 item",
            id="no-targets",
        ),
        pytest.param(
            {"doc_id": "p", "targets": [make_notion_target()]},
            "publish.doc_id: String should have at least 2",
            id="one-character",
        ),
        pytest.param(
            {"doc_id": "Plan", "targets": [make_notion_target()]},
            "publish.doc_id: String should match pattern",
            id="uppercase",
        ),
        pytest.param(
            {"doc_id": "-plan", "targets": [make_notion_target()]},
            "publish.doc_id: String should match pattern",
            id="leading-hyphen",
        ),
        pytest.param(
            {"doc_id": "plan-", "targets": [make_notion_target()]},
            "publish.doc_id: String should match pattern",
            id="trailing-hyphen",
        ),
        pytest.param(
            {"doc_id": "a--b", "targets": [make_notion_target()]},
            "publish.doc_id: String should match pattern",
            id="double-hyphen",
        ),
        pytest.param(
            {"doc_id": "plan doc", "targets": [make_notion_target()]},
            "publish.doc_id: String should match pattern",
            id="space",
        ),
    ],
)
def test_a_doc_id_is_a_slug_of_at_least_two_characters(publish: dict[str, Any], message: str) -> None:
    with pytest.raises(ReportError, match=re.escape(message)):
        _parse(publish)


def test_the_publish_block_and_every_line_up_to_the_next_key_are_left_out_of_the_embedded_source() -> None:
    assert without_publish_block(SOURCE_WITH_PUBLISH) == SOURCE_WITHOUT_PUBLISH


@pytest.mark.parametrize(
    ("source", "embedded"),
    [
        pytest.param('a: 1\n"publish":\n  doc_id: x\nb: 2\n', "a: 1\nb: 2\n", id="quoted-key"),
        pytest.param("a: 1\npublish :\n  doc_id: x\nb: 2\n", "a: 1\nb: 2\n", id="space-before-colon"),
        pytest.param(
            "publish: {a: 1}\nversion: 1\npublish: {b: 2}\n", "version: 1\n", id="key-written-twice"
        ),
        pytest.param("\ufeffpublish:\n  doc_id: x\nb: 2\n", "b: 2\n", id="byte-order-mark"),
        pytest.param("a: 1\npublish:\n  doc_id: x\n", "a: 1\n", id="publish-last"),
        pytest.param("a: 1\npublish: !include p.yaml\nb: 2\n", "a: 1\nb: 2\n", id="include"),
        pytest.param("a: 1\r\npublish:\r\n  doc_id: x\r\nb: 2\r\n", "a: 1\r\nb: 2\r\n", id="crlf"),
        pytest.param(
            "a: 1\npublish: {doc_id: a,\ntargets: []}\nb: 2\n",
            "a: 1\nb: 2\n",
            id="flow-mapping-over-two-lines",
        ),
        pytest.param(
            'version: 1\nmeta: { title: "x" }\nblocks: []\n',
            'version: 1\nmeta: { title: "x" }\nblocks: []\n',
            id="no-publish-key",
        ),
        pytest.param(
            "a: 1\npublisher: me\n", "a: 1\npublisher: me\n", id="a-key-that-only-starts-with-publish"
        ),
        pytest.param("a:\n  publish: nested\n", "a:\n  publish: nested\n", id="a-nested-publish-key"),
    ],
)
def test_every_spelling_of_a_top_level_publish_key_is_left_out(source: str, embedded: str) -> None:
    assert without_publish_block(source) == embedded


@pytest.mark.parametrize(
    ("source", "message"),
    [
        pytest.param(
            "publish: &p\n  a: 1\nother: *p\n",
            "defines a YAML anchor another key uses",
            id="anchor-used-outside",
        ),
        pytest.param(
            "{publish: {a: 1}, b: 2}\n",
            "must be its own top-level key on its own lines",
            id="whole-document-flow-mapping",
        ),
    ],
)
def test_a_publish_block_that_cannot_be_cut_out_cleanly_stops_the_render(source: str, message: str) -> None:
    with pytest.raises(ReportError, match=re.escape(message)):
        without_publish_block(source)


def test_a_rendered_page_carries_its_source_without_the_publish_block() -> None:
    html = render_html(parse_report(yaml.safe_load(SOURCE_WITH_PUBLISH)), source=SOURCE_WITH_PUBLISH)

    assert (extract_source(html), NOTION_PAGE_ID in html) == (SOURCE_WITHOUT_PUBLISH, False)


def test_check_fails_on_a_split_id_that_names_no_section(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "doc.yaml"
    path.write_text(
        yaml.safe_dump(
            make_publish_report({"doc_id": "plan", "targets": [make_notion_target(split=["st9"])]})
        ),
        encoding="utf-8",
    )

    assert main(["--check", str(path)]) == 1

    assert "splits on 'st9', which is not the id of a top-level section" in capsys.readouterr().err
