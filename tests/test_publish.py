from pathlib import Path
from typing import Any

import pytest
import yaml

from skaldr.cli import main
from skaldr.errors import ReportError
from skaldr.models import (
    JiraTarget,
    JiraWhere,
    NotionTarget,
    NotionWhere,
    Publish,
    TargetOverride,
    parse_report,
    without_publish_block,
)
from skaldr.render import extract_source, render_html
from tests.factories import make_report

NOTION_PAGE = "https://www.notion.so/Team-Plans-0123456789abcdef0123456789abcdef"


def _sections(*ids: str) -> list[dict[str, Any]]:
    return [
        {"type": "section", "id": section_id, "title": section_id, "blocks": [{"type": "text", "body": "x"}]}
        for section_id in ids
    ]


def _report(publish: dict[str, Any], section_ids: tuple[str, ...] = ("st1", "st2")) -> dict[str, Any]:
    return make_report(publish=publish, blocks=[{"type": "text", "body": "Intro."}, *_sections(*section_ids)])


def _notion_target(**overrides: Any) -> dict[str, Any]:
    return {"to": "notion", "where": {"parent_page": NOTION_PAGE}, **overrides}


def _jira_target(**overrides: Any) -> dict[str, Any]:
    return {"to": "jira", "where": {"project": "PLAN", "issue_type": "Task"}, **overrides}


def test_a_publish_block_parses_into_one_target_per_service() -> None:
    publish = {
        "doc_id": "onboarding-plan",
        "targets": [
            _notion_target(split=["st1", "st2"]),
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
                "on_remote_edit": "overwrite",
            },
        ],
    }

    assert parse_report(_report(publish)).publish == Publish(
        doc_id="onboarding-plan",
        targets=[
            NotionTarget(to="notion", where=NotionWhere(parent_page=NOTION_PAGE), split=["st1", "st2"]),
            JiraTarget(
                to="jira",
                where=JiraWhere(
                    project="PLAN", issue_type="Task", parent="PLAN-100", fields={"labels": ["team"]}
                ),
                from_sections=["st1", "st2"],
                split=["st1", "st2"],
                overrides={"st2": TargetOverride(fields={"priority": "High"})},
                on_remote_edit="overwrite",
            ),
        ],
    )


def test_a_target_serializes_its_from_list_under_the_key_authors_write() -> None:
    report = parse_report(_report({"doc_id": "plan", "targets": [_jira_target(**{"from": ["st1"]})]}))

    assert report.model_dump(mode="json")["publish"]["targets"][0]["from"] == ["st1"]


def test_a_report_without_a_publish_block_has_none() -> None:
    assert parse_report(make_report()).publish is None


def test_a_notion_target_takes_its_page_id_from_a_url_or_a_bare_id() -> None:
    dashed = "01234567-89ab-cdef-0123-456789abcdef"

    assert (NotionWhere(parent_page=NOTION_PAGE).page_id, NotionWhere(page=dashed).page_id) == (
        "0123456789abcdef0123456789abcdef",
        "0123456789abcdef0123456789abcdef",
    )


@pytest.mark.parametrize(
    ("publish", "message"),
    [
        pytest.param(
            {"doc_id": "plan", "targets": [_notion_target(split=["st1", "nope"])]},
            "publish target 1 (notion) splits on 'nope', which is not the id of a top-level section",
            id="unknown-split-id",
        ),
        pytest.param(
            {"doc_id": "plan", "targets": [_jira_target(**{"from": ["ghost"]})]},
            "publish target 1 (jira) is built from 'ghost', which is not the id of a top-level section",
            id="unknown-from-id",
        ),
        pytest.param(
            {"doc_id": "plan", "targets": [_jira_target(**{"from": ["st1"], "split": ["st2"]})]},
            "publish target 1 (jira) splits on 'st2', which its `from` list leaves out",
            id="split-outside-from",
        ),
        pytest.param(
            {
                "doc_id": "plan",
                "targets": [_jira_target(split=["st1"], overrides={"st2": {"fields": {"x": 1}}})],
            },
            "publish target 1 (jira) overrides 'st2', which is not one of its split sections",
            id="override-outside-split",
        ),
        pytest.param(
            {"doc_id": "plan", "targets": [_notion_target(), _notion_target()]},
            "publish targets 1 and 2 both write to the same notion location",
            id="duplicate-target",
        ),
        pytest.param(
            {"doc_id": "plan", "targets": [_notion_target(split=["st1", "st1"])]},
            "publish target 1 (notion) lists 'st1' more than once in `split`",
            id="repeated-split-id",
        ),
    ],
)
def test_a_publish_block_that_names_the_wrong_sections_fails_naming_them(
    publish: dict[str, Any], message: str
) -> None:
    with pytest.raises(ReportError, match=message.replace("(", r"\(").replace(")", r"\)")):
        parse_report(_report(publish))


@pytest.mark.parametrize(
    ("target", "message"),
    [
        pytest.param(
            {"to": "notion", "where": {}},
            "a notion target names exactly one of `parent_page` or `page`",
            id="notion-no-page",
        ),
        pytest.param(
            {"to": "notion", "where": {"parent_page": NOTION_PAGE, "page": NOTION_PAGE}},
            "a notion target names exactly one of `parent_page` or `page`",
            id="notion-both",
        ),
        pytest.param(
            {"to": "notion", "where": {"page": "https://www.notion.so/no-id-here"}},
            "is not a Notion page URL or a 32-character page id",
            id="notion-bad-page",
        ),
        pytest.param(
            {"to": "jira", "where": {"project": "plan", "issue_type": "Task"}},
            "String should match pattern",
            id="jira-lowercase-project",
        ),
        pytest.param(
            {"to": "jira", "where": {"project": "PLAN", "issue_type": "Task", "parent": "100"}},
            "String should match pattern",
            id="jira-bad-parent",
        ),
        pytest.param(
            _jira_target(removed="delete"), "a jira target cannot use `removed: delete`", id="jira-delete"
        ),
        pytest.param(
            {"to": "confluence", "where": {}},
            "does not match any of the expected tags: 'notion', 'jira'",
            id="unknown-service",
        ),
    ],
)
def test_each_connector_validates_its_own_where(target: dict[str, Any], message: str) -> None:
    with pytest.raises(ReportError, match=message):
        parse_report(_report({"doc_id": "plan", "targets": [target]}))


@pytest.mark.parametrize("doc_id", ["Plan", "-plan", "plan-", "plan doc", "p"])
def test_a_doc_id_is_a_lowercase_slug(doc_id: str) -> None:
    with pytest.raises(ReportError, match=r"publish.doc_id"):
        parse_report(_report({"doc_id": doc_id, "targets": [_notion_target()]}))


SOURCE_WITH_PUBLISH = (
    """\
version: 1
meta:
  title: "Plan"
# where this document publishes
publish:
  doc_id: plan
  targets:
    - to: notion
      where: { parent_page: "NOTION_PAGE" }

blocks:
  - { type: text, body: "Hello." }
"""
).replace("NOTION_PAGE", NOTION_PAGE)


def test_the_publish_block_is_left_out_of_the_source_a_page_embeds() -> None:
    assert without_publish_block(SOURCE_WITH_PUBLISH) == (
        'version: 1\nmeta:\n  title: "Plan"\n# where this document publishes\nblocks:\n'
        '  - { type: text, body: "Hello." }\n'
    )


@pytest.mark.parametrize(
    "source",
    [
        pytest.param('version: 1\nmeta: { title: "x" }\nblocks: []\n', id="no-publish-block"),
        pytest.param(
            'version: 1\nmeta: { title: "x" }\npublisher: me\nblocks: []\n',
            id="a-key-that-only-starts-with-publish",
        ),
    ],
)
def test_a_source_without_a_publish_block_is_embedded_unchanged(source: str) -> None:
    assert without_publish_block(source) == source


def test_a_rendered_page_carries_its_source_without_the_publish_block() -> None:
    report = parse_report(yaml.safe_load(SOURCE_WITH_PUBLISH))

    recovered = extract_source(render_html(report, source=SOURCE_WITH_PUBLISH))

    assert recovered == without_publish_block(SOURCE_WITH_PUBLISH)


def test_check_fails_on_a_split_id_that_names_no_section(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "doc.yaml"
    report = _report({"doc_id": "plan", "targets": [_notion_target(split=["st9"])]})
    path.write_text(yaml.safe_dump(report), encoding="utf-8")

    assert main(["--check", str(path)]) == 1

    assert "splits on 'st9', which is not the id of a top-level section" in capsys.readouterr().err
