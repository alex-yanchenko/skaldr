import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from skaldr.cli import main
from skaldr.errors import ReportError
from skaldr.models import parse_report
from skaldr.publish import Publish, notion_page_id, without_publish_block
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

OTHER_NOTION_PAGE_ID = "fedcba9876543210fedcba9876543210"
SPLIT_ON_INNER: dict[str, Any] = {"doc_id": "plan", "targets": [make_notion_target(split=["inner"])]}
SOURCE_WITH_PUBLISH = f"""\
version: 1
meta:
  title: "Plan"
# notion page for this plan: {NOTION_PAGE_URL}
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
blocks:
  - { type: text, body: "Hello." }
"""
CANNOT_CUT = "the publish block could not be left out of the page"


def _parse(publish: dict[str, Any]) -> Publish | None:
    return parse_report(make_publish_report(publish)).publish


def _rejects(publish: dict[str, Any], message: str) -> None:
    with pytest.raises(ReportError, match=re.escape(message)):
        _parse(publish)


def test_a_publish_block_reads_every_key_of_each_target() -> None:
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
    notion = make_notion_target(split=["st1"], removed="delete")

    publish = _parse({"doc_id": "onboarding-plan", "targets": [notion, jira]})

    assert publish is not None
    assert publish.model_dump(mode="json") == {
        "doc_id": "onboarding-plan",
        "targets": [
            {
                "to": "notion",
                "where": {"parent_page": NOTION_PAGE_URL, "page": None, "fields": {}},
                "from": None,
                "split": ["st1"],
                "overrides": {},
                "removed": "delete",
                "on_remote_edit": "refuse",
            },
            {
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
                "removed": "archive",
                "on_remote_edit": "overwrite",
            },
        ],
    }


def test_a_report_without_a_publish_block_has_none() -> None:
    assert parse_report(make_report()).publish is None


@pytest.mark.parametrize(
    ("reference", "page_id"),
    [
        pytest.param(NOTION_PAGE_URL, NOTION_PAGE_ID, id="titled-url"),
        pytest.param(f"{NOTION_PAGE_URL}?v=1#h", NOTION_PAGE_ID, id="query-and-fragment"),
        pytest.param(f"{NOTION_PAGE_URL}/", NOTION_PAGE_ID, id="trailing-slash"),
        pytest.param(f"https://notion.so/{NOTION_PAGE_ID}", NOTION_PAGE_ID, id="bare-notion-host"),
        pytest.param(f"https://app.notion.com/p/{NOTION_PAGE_ID}", NOTION_PAGE_ID, id="app-host"),
        pytest.param(f"https://team.notion.site/Page-{NOTION_PAGE_ID}", NOTION_PAGE_ID, id="site-subdomain"),
        pytest.param(NOTION_PAGE_ID.upper(), NOTION_PAGE_ID, id="uppercase-bare-id"),
        pytest.param("01234567-89ab-cdef-0123-456789abcdef", NOTION_PAGE_ID, id="dashed-id"),
        pytest.param(f"Team-Plans-{NOTION_PAGE_ID}", NOTION_PAGE_ID, id="titled-id"),
        pytest.param(f"  {NOTION_PAGE_ID}\n", NOTION_PAGE_ID, id="surrounding-whitespace"),
        pytest.param("a" * 36, None, id="too-long"),
        pytest.param(f"zz{NOTION_PAGE_ID}", None, id="junk-prefix"),
        pytest.param(f"https://example.com/{NOTION_PAGE_ID}", None, id="other-host"),
        pytest.param(f"https://evilnotion.so/{NOTION_PAGE_ID}", None, id="lookalike-host"),
        pytest.param(f"https://www.notion.so.evil.com/{NOTION_PAGE_ID}", None, id="notion-as-a-subdomain"),
        pytest.param(f"ftp://www.notion.so/{NOTION_PAGE_ID}", None, id="non-http-scheme"),
        pytest.param(f"example.com/x-{NOTION_PAGE_ID}", None, id="path-without-scheme"),
        pytest.param("https://www.notion.so/no-id-here", None, id="no-id"),
    ],
)
def test_a_notion_page_id_comes_from_a_notion_url_or_a_bare_id(reference: str, page_id: str | None) -> None:
    assert notion_page_id(reference) == page_id


@pytest.mark.parametrize(
    ("where", "message"),
    [
        pytest.param({}, "a notion target names exactly one of `parent_page` or `page`", id="neither"),
        pytest.param(
            {"parent_page": NOTION_PAGE_URL, "page": NOTION_PAGE_URL},
            "a notion target names exactly one of `parent_page` or `page`",
            id="both",
        ),
        pytest.param(
            {"page": "https://www.notion.so/no-id-here"},
            "'https://www.notion.so/no-id-here' is not a Notion page URL "
            "(notion.so, notion.site, notion.com) or a page id",
            id="no-page-id",
        ),
    ],
)
def test_a_notion_target_names_one_page(where: dict[str, Any], message: str) -> None:
    _rejects({"doc_id": "plan", "targets": [{"to": "notion", "where": where}]}, message)


@pytest.mark.parametrize(
    ("where", "message"),
    [
        pytest.param(
            {"project": "plan", "issue_type": "Task"},
            "publish.targets.0.jira.where.project: String should match pattern",
            id="lowercase-project",
        ),
        pytest.param(
            {"project": "PLAN", "issue_type": "Task", "parent": "PLAN-0"},
            "publish.targets.0.jira.where.parent: String should match pattern",
            id="parent-numbered-zero",
        ),
        pytest.param(
            {"project": "PLAN", "issue_type": "  "},
            "publish.targets.0.jira.where.issue_type: String should have at least 1 character",
            id="blank-issue-type",
        ),
    ],
)
def test_a_jira_target_checks_its_keys(where: dict[str, Any], message: str) -> None:
    _rejects({"doc_id": "plan", "targets": [{"to": "jira", "where": where}]}, message)


def test_a_jira_project_key_may_hold_digits_and_underscores() -> None:
    target = make_jira_target(where={"project": "AB_1", "issue_type": "Task", "parent": "AB_1-7"})

    publish = _parse({"doc_id": "plan", "targets": [target]})

    assert publish is not None
    assert publish.model_dump(mode="json")["targets"][0]["where"] == {
        "project": "AB_1",
        "issue_type": "Task",
        "parent": "AB_1-7",
        "fields": {},
    }


@pytest.mark.parametrize(
    ("target", "message"),
    [
        pytest.param(
            make_jira_target(removed="delete"), "a jira target cannot use `removed: delete`", id="jira-delete"
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
def test_a_target_takes_only_its_documented_keys(target: dict[str, Any], message: str) -> None:
    _rejects({"doc_id": "plan", "targets": [target]}, message)


@pytest.mark.parametrize(
    ("targets", "message"),
    [
        pytest.param(
            [make_notion_target(), make_notion_target(where={"page": NOTION_PAGE_ID})],
            f"publish targets 1 and 2 both write to notion page {NOTION_PAGE_ID}",
            id="one-notion-page-named-two-ways",
        ),
        pytest.param(
            [
                make_jira_target(),
                make_jira_target(where={"project": "PLAN", "issue_type": "Bug", "fields": {"labels": ["x"]}}),
            ],
            "publish targets 1 and 2 both write to jira project PLAN under no parent issue",
            id="one-jira-place-with-other-fields",
        ),
    ],
)
def test_two_targets_cannot_write_to_one_place(targets: list[dict[str, Any]], message: str) -> None:
    _rejects({"doc_id": "plan", "targets": targets}, message)


@pytest.mark.parametrize(
    ("targets", "locations"),
    [
        pytest.param(
            [make_notion_target(), make_notion_target(where={"parent_page": OTHER_NOTION_PAGE_ID})],
            [("notion", NOTION_PAGE_ID), ("notion", OTHER_NOTION_PAGE_ID)],
            id="two-notion-pages",
        ),
        pytest.param(
            [make_jira_target(), make_jira_target(where={"project": "OPS", "issue_type": "Task"})],
            [("jira", "PLAN", ""), ("jira", "OPS", "")],
            id="two-jira-projects",
        ),
        pytest.param(
            [
                make_jira_target(where={"project": "PLAN", "issue_type": "Task", "parent": "PLAN-1"}),
                make_jira_target(where={"project": "PLAN", "issue_type": "Task", "parent": "PLAN-2"}),
            ],
            [("jira", "PLAN", "PLAN-1"), ("jira", "PLAN", "PLAN-2")],
            id="one-jira-project-under-two-parents",
        ),
    ],
)
def test_targets_in_different_places_are_accepted(
    targets: list[dict[str, Any]], locations: list[tuple[str, ...]]
) -> None:
    publish = _parse({"doc_id": "plan", "targets": targets})

    assert publish is not None
    assert [target.location_key() for target in publish.targets] == locations


@pytest.mark.parametrize(
    ("target", "message"),
    [
        pytest.param(
            make_notion_target(split=["st1", "nope"]),
            "publish target 1 (notion) splits on 'nope', which is not the id of a top-level section "
            "(a section is named by its `id:`)",
            id="unknown-split-id",
        ),
        pytest.param(
            make_jira_target(**{"from": ["ghost"]}),
            "publish target 1 (jira) is built from 'ghost', which is not the id of a top-level section",
            id="unknown-from-id",
        ),
        pytest.param(
            make_jira_target(**{"from": ["st1", "st1"]}),
            "publish target 1 (jira) lists 'st1' more than once in `from`",
            id="repeated-from-id",
        ),
        pytest.param(
            make_jira_target(**{"from": ["st1"], "split": ["st2"]}),
            "publish target 1 (jira) splits on 'st2', which its `from` list leaves out",
            id="split-outside-from",
        ),
        pytest.param(
            make_jira_target(split=["st1"], overrides={"st2": {"fields": {"priority": "High"}}}),
            "publish target 1 (jira) overrides 'st2', which is not one of its split sections",
            id="override-outside-split",
        ),
        pytest.param(
            make_notion_target(split=["st1", "st1"]),
            "publish target 1 (notion) lists 'st1' more than once in `split`",
            id="repeated-split-id",
        ),
    ],
)
def test_a_target_names_real_sections_once(target: dict[str, Any], message: str) -> None:
    _rejects({"doc_id": "plan", "targets": [target]}, message)


def test_every_publish_mistake_is_reported_once_and_together() -> None:
    publish = {
        "doc_id": "plan",
        "targets": [make_notion_target(split=["nope", "nope"]), make_jira_target(**{"from": ["ghost"]})],
    }

    with pytest.raises(ReportError) as raised:
        _parse(publish)

    assert str(raised.value) == (
        "invalid content data: Value error, "
        "publish target 1 (notion) lists 'nope' more than once in `split`; "
        "publish target 1 (notion) splits on 'nope', which is not the id of a top-level section "
        "(a section is named by its `id:`); "
        "publish target 2 (jira) is built from 'ghost', which is not the id of a top-level section "
        "(a section is named by its `id:`)"
    )


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
    ("doc_id", "message"),
    [
        pytest.param("p", "publish.doc_id: String should have at least 2 characters", id="one-character"),
        pytest.param("Plan", "publish.doc_id: String should match pattern", id="uppercase"),
        pytest.param("-plan", "publish.doc_id: String should match pattern", id="leading-hyphen"),
        pytest.param("plan-", "publish.doc_id: String should match pattern", id="trailing-hyphen"),
        pytest.param("a--b", "publish.doc_id: String should match pattern", id="double-hyphen"),
        pytest.param("plan doc", "publish.doc_id: String should match pattern", id="space"),
    ],
)
def test_a_doc_id_is_a_slug_of_at_least_two_characters(doc_id: str, message: str) -> None:
    _rejects({"doc_id": doc_id, "targets": [make_notion_target()]}, message)


def test_a_publish_block_needs_a_target() -> None:
    _rejects({"doc_id": "plan", "targets": []}, "publish.targets: List should have at least 1 item")


def test_the_publish_block_its_leading_comments_and_every_line_up_to_the_next_key_are_left_out() -> None:
    assert without_publish_block(SOURCE_WITH_PUBLISH) == SOURCE_WITHOUT_PUBLISH


@pytest.mark.parametrize(
    ("source", "embedded"),
    [
        pytest.param('a: 1\n"publish":\n  doc_id: x\nb: 2\n', "a: 1\nb: 2\n", id="quoted-key"),
        pytest.param('a: 1\n"\\x70ublish":\n  doc_id: x\nb: 2\n', "a: 1\nb: 2\n", id="hex-escaped-key"),
        pytest.param('a: 1\n"\\u0070ublish":\n  doc_id: x\nb: 2\n', "a: 1\nb: 2\n", id="unicode-escaped-key"),
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
            "defaults: &d [a]\npublish:\n  x: *d\nb: 2\n",
            "defaults: &d [a]\nb: 2\n",
            id="alias-to-an-outside-anchor",
        ),
        pytest.param(
            "base: &b\n  k: 1\npublish: *b\nc: 2\n", "base: &b\n  k: 1\nc: 2\n", id="publish-is-an-alias"
        ),
        pytest.param("publish: &p [*p]\nb: 1\n", "b: 1\n", id="self-referencing-anchor-inside"),
    ],
)
def test_every_spelling_of_a_top_level_publish_key_is_left_out(source: str, embedded: str) -> None:
    assert without_publish_block(source) == embedded


@pytest.mark.parametrize(
    "source",
    [
        pytest.param('version: 1\nmeta: { title: "x" }\nblocks: []\n', id="no-publish-key"),
        pytest.param("a: 1\npublisher: me\n", id="a-key-that-only-starts-with-publish"),
        pytest.param("a:\n  publish: nested\n", id="a-nested-publish-key"),
        pytest.param("- publish\n- b\n", id="a-list-document"),
    ],
)
def test_a_source_without_a_top_level_publish_key_is_embedded_unchanged(source: str) -> None:
    assert without_publish_block(source) == source


@pytest.mark.parametrize(
    "source",
    [
        pytest.param("<<: {publish: {doc_id: secret-doc}}\nb: 2\n", id="merged-in-mapping"),
        pytest.param("<<: [{publish: {doc_id: secret-doc}}]\nb: 2\n", id="merged-in-list"),
        pytest.param("publish: &p\n  a: 1\nother: *p\n", id="anchor-inside-used-outside"),
        pytest.param("{publish: {a: 1}, b: 2}\n", id="one-line-flow-document"),
        pytest.param("{a: 1, publish: {b: 2}}\n", id="flow-document-ending-in-publish"),
        pytest.param("{publish: {a: 1},\nb: 2}\n", id="flow-document-over-two-lines"),
        pytest.param("a: 1\n?\n  publish\n:\n  d: X\nb: 1\n", id="explicit-key"),
    ],
)
def test_a_publish_block_that_cannot_be_cut_out_exactly_stops_the_render(source: str) -> None:
    with pytest.raises(ReportError, match=re.escape(CANNOT_CUT)):
        without_publish_block(source)


def test_a_source_that_does_not_parse_stops_the_render_naming_why() -> None:
    with pytest.raises(
        ReportError, match=re.escape("the source could not be read to leave its publish block out")
    ):
        without_publish_block("publish: [\n")


def test_a_rendered_page_carries_its_source_without_the_publish_block() -> None:
    html = render_html(parse_report(yaml.safe_load(SOURCE_WITH_PUBLISH)), source=SOURCE_WITH_PUBLISH)

    assert (extract_source(html), NOTION_PAGE_ID in html) == (SOURCE_WITHOUT_PUBLISH, False)


def test_a_render_stops_rather_than_embed_a_block_it_cannot_cut() -> None:
    source = (
        "<<: {publish: {doc_id: secret-doc}}\nversion: 1\nmeta: {title: T}\nblocks: [{type: text, body: x}]\n"
    )

    with pytest.raises(ReportError, match=re.escape(CANNOT_CUT)):
        render_html(parse_report(make_report()), source=source)


def test_the_cli_writes_a_page_without_the_publish_block(tmp_path: Path) -> None:
    data_path = tmp_path / "doc.yaml"
    data_path.write_text(SOURCE_WITH_PUBLISH, encoding="utf-8")

    assert main([str(data_path), "-o", str(tmp_path / "page.html")]) == 0

    assert extract_source((tmp_path / "page.html").read_text(encoding="utf-8")) == SOURCE_WITHOUT_PUBLISH


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
