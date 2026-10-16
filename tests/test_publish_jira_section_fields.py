from pathlib import Path

import pytest
from pydantic import JsonValue

from skaldr.errors import PublishError
from skaldr.publish import ConnectorRegistry
from skaldr.publish.content import FIELDS
from skaldr.publish.drafts import ItemDraft, draft_targets
from skaldr.publish.engine import Applied, ApplyOutcome, apply_publish, diff_publish, prepare_publish
from skaldr.publish.jira import JiraConnector
from skaldr.publish.output import diff_lines
from skaldr.publish_block import JiraTarget
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

JsonObject = dict[str, JsonValue]

ADA_ACCOUNT = "5b10ac8d82e05b22cc7d4ef5"
ADA_HAS_A_JIRA_ID: JsonObject = {"ada": {"jira": ADA_ACCOUNT}}
TARGET_LABEL = "jira project DEMO under no parent issue"
TOOLS_FIELDS_PATH = "blocks[1].fields"
WHERE_FIELDS_PATH = "publish.targets[0].where.fields"


def _jira_publish(
    *,
    from_sections: bool = True,
    where_fields: JsonObject | None = None,
    overrides: JsonObject | None = None,
    split: tuple[str, ...] = ("tools",),
) -> JsonObject:
    where: JsonObject = {
        "project": "DEMO",
        "issue_type": "Task",
        **({"fields_from_sections": True} if from_sections else {}),
        **({"fields": where_fields} if where_fields is not None else {}),
    }
    return {
        "doc_id": DOC_ID,
        "targets": [make_jira_target(where=where, split=list(split), overrides=overrides or {})],
    }


def _blocks_with_fields(section_id: str, fields: JsonObject) -> list[JsonObject]:
    return [
        {**block, "fields": fields} if block.get("id") == section_id else block
        for block in make_garden_blocks()
    ]


def _meta(people: JsonObject | None = None) -> JsonObject:
    return make_garden_meta(**({"people": people} if people is not None else {}))


def _tools_draft(
    fields: JsonObject, *, publish: JsonObject | None = None, people: JsonObject | None = None
) -> ItemDraft:
    report = authored_garden(
        publish=publish or _jira_publish(), blocks=_blocks_with_fields("tools", fields), meta=_meta(people)
    )
    (target,) = draft_targets(report, ConnectorRegistry([JiraConnector()]))
    return target.sections[0]


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
def test_with_the_opt_in_a_split_sections_fields_become_the_fields_of_its_issue(
    section_fields: JsonObject, expected: JsonObject
) -> None:
    assert _tools_draft(section_fields, people=ADA_HAS_A_JIRA_ID).content.fields == expected


def test_without_the_opt_in_a_sections_fields_reach_no_jira_field() -> None:
    draft = _tools_draft(
        {"priority": "High", "due": "2026-10-15", "labels": ["spring"], "assignee": "ada"},
        publish=_jira_publish(from_sections=False),
        people=ADA_HAS_A_JIRA_ID,
    )

    assert (draft.content.fields, draft.paths[FIELDS]) == ({}, WHERE_FIELDS_PATH)


def test_the_target_refuses_a_non_boolean_opt_in() -> None:
    with pytest.raises(ValueError, match="fields_from_sections"):
        JiraTarget.model_validate(
            make_jira_target(where={"project": "DEMO", "issue_type": "Task", "fields_from_sections": "yes"})
        )


def test_the_targets_own_fields_win_key_by_key_over_the_sections() -> None:
    publish = _jira_publish(where_fields={"priority": {"name": "Medium"}, "components": [{"name": "Beds"}]})

    draft = _tools_draft({"priority": "High", "due": "2026-10-15", "labels": ["spring"]}, publish=publish)

    assert draft.content.fields == {
        "priority": {"name": "Medium"},
        "duedate": "2026-10-15",
        "labels": ["spring"],
        "components": [{"name": "Beds"}],
    }


def test_labels_in_the_targets_fields_replace_the_sections_labels_whole() -> None:
    publish = _jira_publish(where_fields={"labels": ["garden"]})

    assert _tools_draft({"labels": ["spring", "tools"]}, publish=publish).content.fields == {
        "labels": ["garden"]
    }


def test_an_override_wins_over_both_the_target_and_the_section() -> None:
    publish = _jira_publish(
        where_fields={"priority": {"name": "Medium"}},
        overrides={"tools": {"fields": {"priority": {"name": "Lowest"}, "duedate": "2027-01-01"}}},
    )

    assert _tools_draft({"priority": "High", "due": "2026-10-15"}, publish=publish).content.fields == {
        "priority": {"name": "Lowest"},
        "duedate": "2027-01-01",
    }


def test_a_null_priority_in_the_targets_fields_keeps_the_sections_priority_off_the_issue(
    tmp_path: Path,
) -> None:
    jira = FakeJira()
    path = write_garden_report(
        tmp_path,
        publish=_jira_publish(where_fields={"priority": None}),
        blocks=_blocks_with_fields("tools", {"priority": "High", "due": "2026-10-15"}),
    )

    _publish(path, jira)

    sent = jira.issues["DEMO-2"].fields
    assert ("priority" in sent, sent["duedate"]) == (False, "2026-10-15")


def test_a_null_priority_in_an_override_keeps_the_sections_priority_off_the_issue() -> None:
    publish = _jira_publish(overrides={"tools": {"fields": {"priority": None}}})

    assert _tools_draft({"priority": "High"}, publish=publish).content.fields == {"priority": None}


@pytest.mark.parametrize(
    "people",
    [pytest.param({"ada": {}}, id="a-person-without-a-jira-id"), pytest.param(None, id="no-such-person")],
)
def test_an_assignee_without_a_jira_account_id_is_refused(people: JsonObject | None) -> None:
    expected = (
        f"{TARGET_LABEL}, section tools: blocks[1].fields.assignee is 'ada', but that person has no jira "
        "account id in meta.people; add one under meta.people.ada.jira, or remove the assignee"
    )
    report = authored_garden(
        publish=_jira_publish(), blocks=_blocks_with_fields("tools", {"assignee": "ada"}), meta=_meta(people)
    )

    with pytest.raises(PublishError) as raised:
        draft_targets(report, ConnectorRegistry([JiraConnector()]))

    assert str(raised.value) == expected


def test_an_assignee_without_a_jira_account_id_passes_when_the_opt_in_is_off() -> None:
    draft = _tools_draft({"assignee": "ada"}, publish=_jira_publish(from_sections=False))

    assert draft.content.fields == {}


def test_a_label_holding_whitespace_is_refused_naming_where_it_was_written() -> None:
    expected = (
        f"{TARGET_LABEL}, section tools: blocks[1].fields.labels.1 is 'late spring', but Jira labels "
        "cannot hold spaces; write it with hyphens, such as 'late-spring'"
    )
    report = authored_garden(
        publish=_jira_publish(), blocks=_blocks_with_fields("tools", {"labels": ["garden", "late spring"]})
    )

    with pytest.raises(PublishError) as raised:
        draft_targets(report, ConnectorRegistry([JiraConnector()]))

    assert str(raised.value) == expected


def test_a_label_holding_whitespace_passes_when_the_opt_in_is_off() -> None:
    draft = _tools_draft({"labels": ["late spring"]}, publish=_jira_publish(from_sections=False))

    assert draft.content.fields == {}


def test_the_document_issue_gets_no_fields_from_a_section_written_into_it() -> None:
    report = authored_garden(
        publish=_jira_publish(split=("planting",)),
        blocks=_blocks_with_fields("tools", {"priority": "High", "labels": ["spring"]}),
    )

    (target,) = draft_targets(report, ConnectorRegistry([JiraConnector()]))

    assert (target.document.content.fields, target.sections[0].content.fields) == ({}, {})


@pytest.mark.parametrize(
    ("section_fields", "publish", "expected"),
    [
        pytest.param(
            {"priority": "High", "due": "2026-10-15"},
            _jira_publish(),
            TOOLS_FIELDS_PATH,
            id="the-section",
        ),
        pytest.param(
            {"priority": "High", "due": "2026-10-15"},
            _jira_publish(where_fields={"priority": {"name": "Medium"}}),
            TOOLS_FIELDS_PATH,
            id="the-target-wins-one-key-and-the-section-supplies-another",
        ),
        pytest.param(
            {"priority": "High"},
            _jira_publish(overrides={"tools": {"fields": {"priority": {"name": "Lowest"}}}}),
            "publish.targets[0].overrides.tools.fields",
            id="an-override-wins-every-key",
        ),
        pytest.param(
            {"priority": "High"},
            _jira_publish(where_fields={"priority": None}),
            WHERE_FIELDS_PATH,
            id="a-null-in-the-target-fields-wins-every-key",
        ),
    ],
)
def test_the_fields_path_is_the_sections_when_it_supplies_any_value_and_the_targets_otherwise(
    section_fields: JsonObject, publish: JsonObject, expected: str
) -> None:
    assert _tools_draft(section_fields, publish=publish).paths[FIELDS] == expected


def _connector(jira: FakeJira) -> JiraConnector:
    return JiraConnector(
        sign_in=lambda _site: make_jira_credentials(),
        http_transport=jira.transport(),
        sleep=jira.sleeps.append,
    )


def _publish(path: Path, jira: FakeJira) -> ApplyOutcome:
    return apply_publish(prepare_publish(path, ConnectorRegistry([_connector(jira)])))


def test_creating_the_issue_sends_the_mapped_fields_beside_the_documents_label(tmp_path: Path) -> None:
    jira = FakeJira()
    path = write_garden_report(
        tmp_path,
        publish=_jira_publish(),
        blocks=_blocks_with_fields(
            "tools", {"priority": "High", "due": "2026-10-15", "labels": ["spring"], "assignee": "ada"}
        ),
        meta=_meta(ADA_HAS_A_JIRA_ID),
    )

    _publish(path, jira)

    sent = jira.issues["DEMO-2"].fields
    assert {name: value for name, value in sent.items() if name != "description"} == {
        "project": {"key": "DEMO"},
        "issuetype": {"name": "Task"},
        "summary": "Tools",
        "parent": {"key": "DEMO-1"},
        "status": {"name": "To Do", "statusCategory": {"key": "new"}},
        "priority": {"name": "High"},
        "duedate": "2026-10-15",
        "labels": ["spring", "skaldr-garden-handbook"],
        "assignee": {"accountId": ADA_ACCOUNT},
    }


def test_a_target_without_the_opt_in_creates_the_issues_it_always_did(tmp_path: Path) -> None:
    jira = FakeJira()
    fields: JsonObject = {"priority": "High", "due": "2026-10-15", "labels": ["spring"], "assignee": "ada"}
    path = write_garden_report(
        tmp_path,
        publish=_jira_publish(from_sections=False),
        blocks=_blocks_with_fields("tools", fields),
        meta=_meta(ADA_HAS_A_JIRA_ID),
    )

    _publish(path, jira)

    sent = jira.issues["DEMO-2"].fields
    assert {name: value for name, value in sent.items() if name != "description"} == {
        "project": {"key": "DEMO"},
        "issuetype": {"name": "Task"},
        "summary": "Tools",
        "parent": {"key": "DEMO-1"},
        "status": {"name": "To Do", "statusCategory": {"key": "new"}},
        "labels": ["skaldr-garden-handbook"],
    }


def _publish_a_high_priority_tools_section(tmp_path: Path, jira: FakeJira) -> Path:
    path = write_garden_report(
        tmp_path, publish=_jira_publish(), blocks=_blocks_with_fields("tools", {"priority": "High"})
    )
    _publish(path, jira)
    return path


def test_changing_a_section_field_plans_a_fields_update_and_publishing_again_is_quiet(tmp_path: Path) -> None:
    jira = FakeJira()
    path = _publish_a_high_priority_tools_section(tmp_path, jira)
    write_garden_report(
        tmp_path, publish=_jira_publish(), blocks=_blocks_with_fields("tools", {"priority": "Low"})
    )

    outcome = _publish(path, jira)

    assert (outcome, jira.issues["DEMO-2"].fields["priority"], _publish(path, jira)) == (
        Applied(("update   section tools: fields", "update   section tools: tools (blocks[1])")),
        {"name": "Low"},
        Applied(()),
    )


def test_the_diff_shows_a_changed_section_field_under_the_path_of_the_section(tmp_path: Path) -> None:
    jira = FakeJira()
    path = _publish_a_high_priority_tools_section(tmp_path, jira)
    write_garden_report(
        tmp_path, publish=_jira_publish(), blocks=_blocks_with_fields("tools", {"priority": "Low"})
    )

    lines = diff_lines(diff_publish(prepare_publish(path, ConnectorRegistry([_connector(jira)]))))

    assert [line for line in lines if "fields" in line] == [
        f"--- {TARGET_LABEL}, section tools: fields ({TOOLS_FIELDS_PATH}), as published",
        f"+++ {TARGET_LABEL}, section tools: fields ({TOOLS_FIELDS_PATH}), in the YAML",
    ]


def test_a_priority_changed_in_jira_shows_as_a_remote_edit_of_the_fields_with_the_sections_path(
    tmp_path: Path,
) -> None:
    jira = FakeJira()
    path = _publish_a_high_priority_tools_section(tmp_path, jira)
    jira.edit_by_hand("DEMO-2", priority={"name": "Lowest"})

    diff = diff_publish(prepare_publish(path, ConnectorRegistry([_connector(jira)])))

    assert [(edit.item.section_id, edit.part, edit.path, edit.edited_by) for edit in diff.remote_edits] == [
        ("tools", FIELDS, TOOLS_FIELDS_PATH, "Robin Editor")
    ]


def test_publishing_an_assignee_without_a_jira_id_sends_nothing(tmp_path: Path) -> None:
    jira = FakeJira()
    path = write_garden_report(
        tmp_path,
        publish=_jira_publish(),
        blocks=_blocks_with_fields("tools", {"assignee": "ada"}),
        meta=_meta({"ada": {}}),
    )

    with pytest.raises(PublishError, match="blocks\\[1\\]\\.fields\\.assignee is 'ada'"):
        _publish(path, jira)

    assert jira.requests == []


def test_the_diff_text_of_a_target_without_the_opt_in_names_the_fields_part_plainly(tmp_path: Path) -> None:
    jira = FakeJira()
    path = write_garden_report(
        tmp_path,
        publish=_jira_publish(from_sections=False, where_fields={"priority": {"name": "High"}}),
        blocks=_blocks_with_fields("tools", {"priority": "Low"}),
    )
    _publish(path, jira)
    write_garden_report(
        tmp_path,
        publish=_jira_publish(from_sections=False, where_fields={"priority": {"name": "Low"}}),
        blocks=_blocks_with_fields("tools", {"priority": "Low"}),
    )

    lines = diff_lines(diff_publish(prepare_publish(path, ConnectorRegistry([_connector(jira)]))))

    assert [line for line in lines if "fields" in line] == [
        f"--- {TARGET_LABEL}, document: fields, as published",
        f"+++ {TARGET_LABEL}, document: fields, in the YAML",
        f"--- {TARGET_LABEL}, section tools: fields, as published",
        f"+++ {TARGET_LABEL}, section tools: fields, in the YAML",
    ]
