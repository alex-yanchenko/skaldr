from pathlib import Path
from typing import Any

import pytest
from pydantic import JsonValue

from skaldr.publish import ConnectorRegistry
from skaldr.publish.drafts import draft_targets
from skaldr.publish.engine import Applied, apply_publish, prepare_publish
from skaldr.publish.jira import JiraConnector
from tests.factories import make_jira_target
from tests.factories.auth_factory import make_jira_credentials
from tests.factories.jira_factory import FakeJira
from tests.factories.publish_factory import (
    DOC_ID,
    authored_garden,
    make_garden_blocks,
    make_garden_meta,
    write_garden_report,
)

ADA_ACCOUNT = "5b10ac8d82e05b22cc7d4ef5"


def _jira_publish(**target: Any) -> dict[str, Any]:
    return {"doc_id": DOC_ID, "targets": [make_jira_target(split=["tools"], **target)]}


def _blocks_with_tools_fields(fields: dict[str, Any]) -> list[dict[str, Any]]:
    blocks = make_garden_blocks()
    blocks[1] = {**blocks[1], "fields": fields}
    return blocks


def _tools_fields(
    fields: dict[str, Any], *, publish: dict[str, Any] | None = None, people: dict[str, Any] | None = None
) -> dict[str, JsonValue]:
    meta = make_garden_meta(**({"people": people} if people is not None else {}))
    report = authored_garden(
        publish=publish or _jira_publish(), blocks=_blocks_with_tools_fields(fields), meta=meta
    )
    (target,) = draft_targets(report, ConnectorRegistry([JiraConnector()]))
    return target.sections[0].content.fields


@pytest.mark.parametrize(
    ("section_fields", "expected"),
    [
        pytest.param({"priority": "High"}, {"priority": {"name": "High"}}, id="priority"),
        pytest.param({"due": "2026-10-15"}, {"duedate": "2026-10-15"}, id="due"),
        pytest.param({"labels": ["garden", "spring"]}, {"labels": ["garden", "spring"]}, id="labels"),
        pytest.param(
            {"assignee": "ada"}, {"assignee": {"accountId": ADA_ACCOUNT}}, id="assignee-with-a-jira-id"
        ),
        pytest.param(
            {"status": "In Progress", "estimate": 3, "links": {"blocks": ["planting"]}, "area": "Shed"},
            {},
            id="status-estimate-links-and-custom-keys-are-not-mapped",
        ),
    ],
)
def test_a_split_sections_fields_become_the_fields_of_its_issue(
    section_fields: dict[str, Any], expected: dict[str, JsonValue]
) -> None:
    assert _tools_fields(section_fields, people={"ada": {"jira": ADA_ACCOUNT}}) == expected


def test_an_assignee_without_a_jira_id_is_left_out() -> None:
    assert _tools_fields({"assignee": "ada", "priority": "Low"}, people={"ada": {}}) == {
        "priority": {"name": "Low"}
    }


def test_an_assignee_who_is_not_in_the_people_list_is_left_out() -> None:
    assert _tools_fields({"assignee": "ada"}) == {}


def test_the_targets_own_fields_win_key_by_key_over_the_sections() -> None:
    publish = _jira_publish(
        where={
            "project": "DEMO",
            "issue_type": "Task",
            "fields": {"priority": {"name": "Medium"}, "components": [{"name": "Beds"}]},
        }
    )

    assert _tools_fields(
        {"priority": "High", "due": "2026-10-15", "labels": ["spring"]}, publish=publish
    ) == {
        "duedate": "2026-10-15",
        "labels": ["spring"],
        "priority": {"name": "Medium"},
        "components": [{"name": "Beds"}],
    }


def test_an_override_wins_over_both_the_target_and_the_section() -> None:
    publish = _jira_publish(
        where={"project": "DEMO", "issue_type": "Task", "fields": {"priority": {"name": "Medium"}}},
        overrides={"tools": {"fields": {"priority": {"name": "Lowest"}, "duedate": "2027-01-01"}}},
    )

    assert _tools_fields({"priority": "High", "due": "2026-10-15"}, publish=publish) == {
        "priority": {"name": "Lowest"},
        "duedate": "2027-01-01",
    }


def test_the_document_issue_and_sections_without_fields_are_unchanged() -> None:
    report = authored_garden(publish=_jira_publish(), blocks=_blocks_with_tools_fields({"priority": "High"}))
    (target,) = draft_targets(report, ConnectorRegistry([JiraConnector()]))

    plain = authored_garden(publish=_jira_publish())
    (plain_target,) = draft_targets(plain, ConnectorRegistry([JiraConnector()]))

    assert (target.document.content.fields, plain_target.sections[0].content.fields) == ({}, {})


def _publish(path: Path, jira: FakeJira) -> Any:
    connector = JiraConnector(
        sign_in=lambda _site: make_jira_credentials(),
        http_transport=jira.transport(),
        sleep=jira.sleeps.append,
    )
    return apply_publish(prepare_publish(path, ConnectorRegistry([connector])))


def test_creating_the_issue_sends_the_mapped_fields_beside_the_documents_label(tmp_path: Path) -> None:
    jira = FakeJira()
    path = write_garden_report(
        tmp_path,
        publish=_jira_publish(),
        blocks=_blocks_with_tools_fields(
            {"priority": "High", "due": "2026-10-15", "labels": ["spring"], "assignee": "ada"}
        ),
        meta=make_garden_meta(people={"ada": {"jira": ADA_ACCOUNT}}),
    )

    _publish(path, jira)

    sent = jira.issues["DEMO-2"].fields
    assert {name: sent[name] for name in ("priority", "duedate", "labels", "assignee")} == {
        "priority": {"name": "High"},
        "duedate": "2026-10-15",
        "labels": ["spring", "skaldr-garden-handbook"],
        "assignee": {"accountId": ADA_ACCOUNT},
    }


def test_changing_a_section_field_plans_a_fields_update_and_publishing_again_is_quiet(tmp_path: Path) -> None:
    jira = FakeJira()
    path = write_garden_report(
        tmp_path, publish=_jira_publish(), blocks=_blocks_with_tools_fields({"priority": "High"})
    )
    _publish(path, jira)
    write_garden_report(
        tmp_path, publish=_jira_publish(), blocks=_blocks_with_tools_fields({"priority": "Low"})
    )

    outcome = _publish(path, jira)

    assert (outcome, jira.issues["DEMO-2"].fields["priority"], _publish(path, jira)) == (
        Applied(("update   section tools: fields", "update   section tools: tools (blocks[1])")),
        {"name": "Low"},
        Applied(()),
    )
