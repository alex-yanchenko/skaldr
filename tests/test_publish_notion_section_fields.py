import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import JsonValue

from skaldr.errors import PublishError
from skaldr.publish import ConnectorRegistry
from skaldr.publish.content import FIELDS
from skaldr.publish.drafts import ItemDraft, draft_targets
from skaldr.publish.engine import Applied, ApplyOutcome, apply_publish, diff_publish, prepare_publish
from skaldr.publish.notion.connector import NotionConnector
from skaldr.publish.output import diff_lines
from skaldr.publish_block import NotionTarget
from tests.factories import NOTION_PAGE_ID, NOTION_PAGE_URL, make_notion_target
from tests.factories.auth_factory import make_notion_credentials, seed_notion
from tests.factories.notion_factory import InMemoryNotion, numbered_id
from tests.factories.publish_factory import (
    TARGET_LABEL,
    authored_garden,
    make_garden_blocks,
    make_garden_meta,
    make_notion_publish,
    write_garden_report,
)

JsonObject = dict[str, JsonValue]

ADA_NOTION_URI = "user://9E9E9E9E-0000-4000-8000-000000000002"
ADA_USER_ID = "9e9e9e9e-0000-4000-8000-000000000002"
ADA_HAS_A_NOTION_ID: JsonObject = {"ada": {"notion": ADA_NOTION_URI}}
DATABASE_SCHEMA = {
    "Name": "title",
    "Status": "status",
    "Priority": "select",
    "Assignee": "people",
    "Due": "date",
    "Labels": "multi_select",
    "Estimate": "number",
    "Area": "rich_text",
}
DATABASE_OPTIONS = {
    "Status": ["Not started", "In progress", "Done"],
    "Priority": ["High", "Low"],
    "Labels": ["garden"],
}
TOOLS_FIELDS_PATH = "blocks[1].fields"
WHERE_FIELDS_PATH = "publish.targets[0].where.fields"
SOURCE_ID = f"source-{NOTION_PAGE_ID}"
DOCUMENT_PAGE = numbered_id(1).replace("-", "")
TOOLS_PAGE = numbered_id(2).replace("-", "")


@pytest.fixture(autouse=True)
def signed_in_to_notion() -> None:
    seed_notion(make_notion_credentials())


def _database(
    schema: dict[str, str] | None = None, options: dict[str, list[str]] | None = None
) -> InMemoryNotion:
    notion = InMemoryNotion()
    notion.add_database(
        NOTION_PAGE_ID,
        DATABASE_SCHEMA if schema is None else schema,
        DATABASE_OPTIONS if options is None else options,
    )
    return notion


def _registry(notion: InMemoryNotion) -> ConnectorRegistry:
    return ConnectorRegistry([NotionConnector(http=notion.mock(), sleep=lambda _: None)])


def _notion_publish(
    *,
    from_sections: bool = True,
    where_fields: JsonObject | None = None,
    overrides: JsonObject | None = None,
    split: tuple[str, ...] = ("tools",),
) -> JsonObject:
    where: JsonObject = {
        "parent_page": NOTION_PAGE_URL,
        **({"fields_from_sections": True} if from_sections else {}),
        **({"fields": where_fields} if where_fields is not None else {}),
    }
    return make_notion_publish(where=where, split=list(split), overrides=overrides or {})


def _blocks_with_fields(section_id: str, fields: JsonObject) -> list[JsonObject]:
    return [
        {**block, "fields": fields} if block.get("id") == section_id else block
        for block in make_garden_blocks()
    ]


def _meta(people: JsonObject | None = None) -> JsonObject:
    return make_garden_meta(**({"people": people} if people is not None else {}))


def _drafts(
    notion: InMemoryNotion,
    fields: JsonObject,
    *,
    publish: JsonObject | None = None,
    people: JsonObject | None = None,
) -> Any:
    report = authored_garden(
        publish=publish or _notion_publish(), blocks=_blocks_with_fields("tools", fields), meta=_meta(people)
    )
    (target,) = draft_targets(report, _registry(notion))
    return target


def _tools_draft(
    fields: JsonObject,
    *,
    notion: InMemoryNotion | None = None,
    publish: JsonObject | None = None,
    people: JsonObject | None = None,
) -> ItemDraft:
    return _drafts(notion or _database(), fields, publish=publish, people=people).sections[0]


@pytest.mark.parametrize(
    ("section_fields", "expected"),
    [
        pytest.param({"status": "In progress"}, {"Status": "In progress"}, id="status"),
        pytest.param({"priority": "High"}, {"Priority": "High"}, id="priority"),
        pytest.param({"due": "2026-10-15"}, {"Due": "2026-10-15"}, id="due"),
        pytest.param({"labels": ["garden", "spring"]}, {"Labels": ["garden", "spring"]}, id="labels"),
        pytest.param({"estimate": 3}, {"Estimate": 3}, id="estimate"),
        pytest.param({"estimate": 2.5}, {"Estimate": 2.5}, id="a-fractional-estimate"),
        pytest.param(
            {"assignee": "ada"}, {"Assignee": [ADA_USER_ID]}, id="assignee-as-a-lowercase-dashed-id"
        ),
        pytest.param({"Area": "Shed"}, {"Area": "Shed"}, id="an-extra-key-by-its-exact-name"),
        pytest.param({"links": {"blocks": ["planting"]}}, {}, id="links-are-not-mapped"),
    ],
)
def test_with_the_opt_in_a_split_sections_fields_become_the_properties_of_its_row(
    section_fields: JsonObject, expected: JsonObject
) -> None:
    assert _tools_draft(section_fields, people=ADA_HAS_A_NOTION_ID).content.fields == expected


def test_the_properties_of_one_section_carry_every_mapped_field_together() -> None:
    draft = _tools_draft(
        {
            "status": "Done",
            "priority": "Low",
            "assignee": "ada",
            "due": "2026-10-15",
            "labels": ["garden"],
            "estimate": 5,
            "Area": "Shed",
        },
        people=ADA_HAS_A_NOTION_ID,
    )

    assert draft.content.fields == {
        "Status": "Done",
        "Priority": "Low",
        "Assignee": [ADA_USER_ID],
        "Due": "2026-10-15",
        "Labels": ["garden"],
        "Estimate": 5,
        "Area": "Shed",
    }


@pytest.mark.parametrize(
    ("kind", "section_fields", "expected"),
    [
        pytest.param("select", {"priority": "High"}, {"Priority": "High"}, id="text-to-a-select"),
        pytest.param("status", {"priority": "Done"}, {"Priority": "Done"}, id="text-to-a-status"),
        pytest.param("rich_text", {"priority": "High"}, {"Priority": "High"}, id="text-to-a-rich-text"),
        pytest.param(
            "multi_select", {"priority": "High"}, {"Priority": ["High"]}, id="text-to-a-multi-select"
        ),
        pytest.param(
            "multi_select", {"Season": "Spring"}, {"Season": ["Spring"]}, id="an-extra-text-to-a-multi-select"
        ),
        pytest.param(
            "multi_select",
            {"Season": [1, "Spring"]},
            {"Season": ["1", "Spring"]},
            id="an-extra-list-to-a-multi-select",
        ),
        pytest.param("number", {"Season": 4}, {"Season": 4}, id="an-extra-number-to-a-number"),
    ],
)
def test_a_text_is_written_in_the_shape_of_the_property_it_goes_to(
    kind: str, section_fields: JsonObject, expected: JsonObject
) -> None:
    name = next(iter(expected))
    notion = _database({"Name": "title", name: kind}, {name: ["Done"]} if kind == "status" else {})

    assert _tools_draft(section_fields, notion=notion).content.fields == expected


def test_a_named_field_finds_its_property_in_any_capitalisation() -> None:
    notion = _database({"Name": "title", "PRIORITY": "select"}, {})

    assert _tools_draft({"priority": "High"}, notion=notion).content.fields == {"PRIORITY": "High"}


def test_a_named_field_does_not_find_a_property_with_another_name() -> None:
    notion = _database({"Name": "title", "Due date": "date"}, {})
    expected = _reason(
        "blocks[1].fields.due has no property named 'due', in any capitalisation, in Notion database "
        f"{NOTION_PAGE_ID}; add one there, or remove the field from the section"
    )

    assert _refusal_of(notion, {"due": "2026-10-15"}) == expected


def test_a_property_with_the_exact_name_wins_over_one_that_differs_only_in_capitalisation() -> None:
    notion = _database({"Name": "title", "priority": "select", "Priority": "select"}, {})

    assert _tools_draft({"priority": "High"}, notion=notion).content.fields == {"priority": "High"}


def test_an_extra_key_matches_its_property_by_the_exact_name_only() -> None:
    notion = _database({"Name": "title", "area": "rich_text"}, {})

    with pytest.raises(PublishError, match="blocks\\[1\\]\\.fields\\.Area has no property named 'Area'"):
        _tools_draft({"Area": "Shed"}, notion=notion)


@pytest.mark.parametrize(
    ("kind", "section_fields", "options", "expected"),
    [
        pytest.param(
            "status", {"status": "in progress"}, DATABASE_OPTIONS, {"Status": "In progress"}, id="status"
        ),
        pytest.param("select", {"priority": "high"}, DATABASE_OPTIONS, {"Priority": "High"}, id="select"),
        pytest.param(
            "select",
            {"priority": "Urgent"},
            DATABASE_OPTIONS,
            {"Priority": "Urgent"},
            id="a-new-select-option",
        ),
        pytest.param(
            "multi_select",
            {"labels": ["Garden", "spring"]},
            DATABASE_OPTIONS,
            {"Labels": ["garden", "spring"]},
            id="multi-select",
        ),
    ],
)
def test_an_option_is_written_with_the_capitalisation_the_database_already_holds(
    kind: str, section_fields: JsonObject, options: dict[str, list[str]], expected: JsonObject
) -> None:
    name = next(iter(expected))
    notion = _database({"Name": "title", name: kind}, {name: options[name]})

    assert _tools_draft(section_fields, notion=notion).content.fields == expected


def test_without_the_opt_in_a_sections_fields_reach_no_property_and_notion_is_not_asked() -> None:
    notion = _database()

    draft = _tools_draft(
        {"priority": "High", "assignee": "ada"},
        notion=notion,
        publish=_notion_publish(from_sections=False),
        people=ADA_HAS_A_NOTION_ID,
    )

    assert (draft.content.fields, draft.paths[FIELDS], notion.requests) == ({}, WHERE_FIELDS_PATH, [])


def test_a_section_with_nothing_to_map_does_not_ask_notion_for_the_schema() -> None:
    notion = _database()

    draft = _tools_draft({"links": {"blocks": ["planting"]}}, notion=notion)

    assert (draft.content.fields, notion.requests) == ({}, [])


def test_the_schema_of_a_database_is_read_once_for_every_section_that_needs_it() -> None:
    notion = _database()
    report = authored_garden(
        publish=_notion_publish(split=("tools", "planting")),
        blocks=[
            {**block, "fields": {"priority": "High"}} if block.get("type") == "section" else block
            for block in make_garden_blocks()
        ],
    )

    draft_targets(report, _registry(notion))

    assert ([(request.method, request.url.path) for request in notion.requests], notion.closes) == (
        [
            ("GET", f"/v1/blocks/{NOTION_PAGE_ID}"),
            ("GET", f"/v1/databases/{NOTION_PAGE_ID}"),
            ("GET", f"/v1/data_sources/{SOURCE_ID}"),
        ],
        1,
    )


def test_a_notion_user_id_written_without_dashes_or_in_upper_case_is_sent_as_the_dashed_lowercase_id() -> (
    None
):
    people: JsonObject = {"ada": {"notion": "user://9E9E9E9E00004000800000000000002A"}}

    draft = _tools_draft({"assignee": "ada"}, people=people)

    assert draft.content.fields == {"Assignee": ["9e9e9e9e-0000-4000-8000-00000000002a"]}


def test_a_target_that_opts_in_dumps_the_setting_and_one_that_does_not_leaves_it_out() -> None:
    opted_in = NotionTarget.model_validate(
        make_notion_target(where={"parent_page": NOTION_PAGE_URL, "fields_from_sections": True})
    )
    default = NotionTarget.model_validate(make_notion_target())

    assert (
        opted_in.model_dump(mode="json")["where"],
        default.model_dump(mode="json")["where"],
    ) == (
        {
            "parent_page": NOTION_PAGE_URL,
            "page": None,
            "workspace": None,
            "fields": {},
            "fields_from_sections": True,
        },
        {"parent_page": NOTION_PAGE_URL, "page": None, "workspace": None, "fields": {}},
    )


def test_the_target_refuses_a_non_boolean_opt_in() -> None:
    with pytest.raises(ValueError, match="fields_from_sections"):
        NotionTarget.model_validate(
            make_notion_target(where={"parent_page": NOTION_PAGE_URL, "fields_from_sections": "yes"})
        )


def test_the_opt_in_does_not_go_with_a_page_the_document_is_written_into() -> None:
    with pytest.raises(
        ValueError,
        match="`fields_from_sections` makes each split section a row of the database `parent_page` names, "
        "so it does not go with `page`",
    ):
        NotionTarget.model_validate(
            make_notion_target(where={"page": NOTION_PAGE_URL, "fields_from_sections": True})
        )


def test_the_targets_own_fields_win_key_by_key_over_the_sections() -> None:
    publish = _notion_publish(where_fields={"Priority": "Low", "Area": "Shed"})

    draft = _tools_draft({"priority": "High", "due": "2026-10-15", "labels": ["garden"]}, publish=publish)

    assert draft.content.fields == {
        "Priority": "Low",
        "Due": "2026-10-15",
        "Labels": ["garden"],
        "Area": "Shed",
    }


def test_labels_in_the_targets_fields_replace_the_sections_labels_whole() -> None:
    publish = _notion_publish(where_fields={"Labels": ["garden"]})

    assert _tools_draft({"labels": ["spring", "tools"]}, publish=publish).content.fields == {
        "Labels": ["garden"]
    }


def test_an_override_wins_over_both_the_target_and_the_section() -> None:
    publish = _notion_publish(
        where_fields={"Priority": "Low"},
        overrides={"tools": {"fields": {"Priority": "High", "Due": "2027-01-01"}}},
    )

    assert _tools_draft({"priority": "Low", "due": "2026-10-15"}, publish=publish).content.fields == {
        "Priority": "High",
        "Due": "2027-01-01",
    }


def test_a_null_in_the_targets_fields_keeps_the_sections_value_off_the_row() -> None:
    publish = _notion_publish(where_fields={"Priority": None})

    assert _tools_draft({"priority": "High", "due": "2026-10-15"}, publish=publish).content.fields == {
        "Priority": None,
        "Due": "2026-10-15",
    }


def test_the_document_row_gets_no_properties_from_a_section_written_into_it() -> None:
    notion = _database()
    report = authored_garden(
        publish=_notion_publish(split=("planting",)),
        blocks=_blocks_with_fields("tools", {"priority": "High", "labels": ["garden"]}),
    )

    (target,) = draft_targets(report, _registry(notion))

    assert (target.document.content.fields, target.sections[0].content.fields) == ({}, {})


def _refusal_of(notion: InMemoryNotion, fields: JsonObject, *, people: JsonObject | None = None) -> str:
    report = authored_garden(
        publish=_notion_publish(), blocks=_blocks_with_fields("tools", fields), meta=_meta(people)
    )
    with pytest.raises(PublishError) as raised:
        draft_targets(report, _registry(notion))
    return str(raised.value)


def _reason(text: str) -> str:
    return f"{TARGET_LABEL}, section tools: {text}"


@pytest.mark.parametrize(
    ("schema", "fields", "expected"),
    [
        pytest.param(
            {"Name": "title"},
            {"priority": "High"},
            f"blocks[1].fields.priority has no property named 'priority', in any capitalisation, in Notion "
            f"database {NOTION_PAGE_ID}; add one there, or remove the field from the section",
            id="a-named-field-without-a-property",
        ),
        pytest.param(
            {"Name": "title"},
            {"Area": "Shed"},
            f"blocks[1].fields.Area has no property named 'Area' in Notion database {NOTION_PAGE_ID}; add "
            "one there, or remove the field from the section",
            id="an-extra-key-without-a-property",
        ),
        pytest.param(
            {"Name": "title", "PRIORITY": "select", "Priority": "select"},
            {"priority": "High"},
            f"blocks[1].fields.priority matches the properties 'PRIORITY', 'Priority' of Notion database "
            f"{NOTION_PAGE_ID}, which differ only in capitalisation; rename one of them in Notion",
            id="two-properties-differing-only-in-capitalisation",
        ),
        pytest.param(
            {"Name": "title", "Priority": "checkbox"},
            {"priority": "High"},
            f"blocks[1].fields.priority is a text, but 'Priority' in Notion database {NOTION_PAGE_ID} is a "
            "checkbox property; skaldr writes a text to a select, status, multi_select or rich_text property",
            id="text-to-a-checkbox",
        ),
        pytest.param(
            {"Name": "title", "Labels": "rich_text"},
            {"labels": ["garden"]},
            "blocks[1].fields.labels is a list of texts, but 'Labels' in Notion database "
            f"{NOTION_PAGE_ID} is a rich_text property; skaldr writes a list of texts to a multi_select "
            "property",
            id="labels-to-a-rich-text",
        ),
        pytest.param(
            {"Name": "title", "Estimate": "select"},
            {"estimate": 3},
            f"blocks[1].fields.estimate is a number, but 'Estimate' in Notion database {NOTION_PAGE_ID} is a "
            "select property; skaldr writes a number to a number property",
            id="estimate-to-a-select",
        ),
        pytest.param(
            {"Name": "title", "Due": "rich_text"},
            {"due": "2026-10-15"},
            f"blocks[1].fields.due is a date, but 'Due' in Notion database {NOTION_PAGE_ID} is a rich_text "
            "property; skaldr writes a date to a date property",
            id="due-to-a-rich-text",
        ),
        pytest.param(
            {"Name": "title", "Assignee": "select"},
            {"assignee": "ada"},
            f"blocks[1].fields.assignee is a person, but 'Assignee' in Notion database {NOTION_PAGE_ID} is a "
            "select property; skaldr writes a person to a people property",
            id="assignee-to-a-select",
        ),
        pytest.param(
            {"Name": "title", "Area": "formula"},
            {"Area": "Shed"},
            f"blocks[1].fields.Area is a text, but 'Area' in Notion database {NOTION_PAGE_ID} is a formula "
            "property; skaldr writes a text to a select, status, multi_select or rich_text property",
            id="text-to-a-formula",
        ),
        pytest.param(
            {"Name": "title", "Status": "status"},
            {"Name": "Plan"},
            f"blocks[1].fields.Name would set 'Name', the title of Notion database {NOTION_PAGE_ID}; skaldr "
            "sets the title from the section's title",
            id="an-extra-key-naming-the-title",
        ),
    ],
)
def test_a_field_the_database_cannot_hold_is_refused_before_anything_is_written(
    schema: dict[str, str], fields: JsonObject, expected: str
) -> None:
    notion = _database(schema, {})

    assert _refusal_of(notion, fields, people=ADA_HAS_A_NOTION_ID) == _reason(expected)
    assert notion.writes() == []


def test_a_status_the_property_has_no_option_for_is_refused_with_the_options_it_has() -> None:
    expected = _reason(
        "blocks[1].fields.status is 'Blocked', but the status property 'Status' in Notion database "
        f"{NOTION_PAGE_ID} has no option 'Blocked'; its options are 'Not started', 'In progress', 'Done'"
    )

    assert _refusal_of(_database(), {"status": "Blocked"}) == expected


def test_a_status_property_without_options_refuses_every_status() -> None:
    expected = _reason(
        "blocks[1].fields.status is 'Done', but the status property 'Status' in Notion database "
        f"{NOTION_PAGE_ID} has no option 'Done'; it has no options"
    )

    assert _refusal_of(_database(options={"Status": []}), {"status": "Done"}) == expected


@pytest.mark.parametrize(
    ("fields", "position"),
    [
        pytest.param({"labels": ["garden", "a,b"]}, "blocks[1].fields.labels.1"),
        pytest.param({"priority": "a,b"}, "blocks[1].fields.priority"),
    ],
)
def test_a_value_with_a_comma_for_a_multi_select_is_refused(fields: JsonObject, position: str) -> None:
    schema = {"Name": "title", "Labels": "multi_select", "Priority": "multi_select"}
    expected = _reason(
        f"{position} is 'a,b', but a Notion multi-select option cannot hold a comma; remove the comma"
    )

    assert _refusal_of(_database(schema, {}), fields) == expected


def test_a_comma_is_fine_in_a_select_a_status_or_a_text() -> None:
    notion = _database({"Name": "title", "Priority": "select", "Area": "rich_text"}, {})

    assert _tools_draft({"priority": "a,b", "Area": "c,d"}, notion=notion).content.fields == {
        "Priority": "a,b",
        "Area": "c,d",
    }


@pytest.mark.parametrize(
    "people",
    [pytest.param({"ada": {}}, id="a-person-without-a-notion-id"), pytest.param(None, id="no-such-person")],
)
def test_an_assignee_without_a_notion_user_id_is_refused_without_reading_the_schema(
    people: JsonObject | None,
) -> None:
    notion = _database()
    expected = _reason(
        "blocks[1].fields.assignee is 'ada', but that person has no notion user id in meta.people; add one "
        "under meta.people.ada.notion, or remove the assignee"
    )

    assert (_refusal_of(notion, {"assignee": "ada"}, people=people), notion.requests) == (expected, [])


def test_an_assignee_without_a_notion_user_id_passes_when_the_opt_in_is_off() -> None:
    draft = _tools_draft({"assignee": "ada"}, publish=_notion_publish(from_sections=False))

    assert draft.content.fields == {}


def test_a_parent_that_is_a_page_gives_its_sections_no_properties_to_set() -> None:
    notion = InMemoryNotion()
    notion.add_page(NOTION_PAGE_ID, "Team plans")
    expected = _reason(
        f"blocks[1].fields.priority has no property to go to: the target's `parent_page` {NOTION_PAGE_ID} is "
        "a page, not a database; point `parent_page` at a database, or remove `fields_from_sections`"
    )

    assert _refusal_of(notion, {"priority": "High"}) == expected


def test_a_parent_that_is_a_page_takes_a_section_with_no_mappable_field_as_it_always_did() -> None:
    notion = InMemoryNotion()
    notion.add_page(NOTION_PAGE_ID, "Team plans")

    assert _tools_draft({"links": {"blocks": ["planting"]}}, notion=notion).content.fields == {}


def test_a_database_with_two_data_sources_is_refused_in_the_words_of_the_create() -> None:
    notion = _database()
    notion.data_source_counts[NOTION_PAGE_ID] = 2
    expected = _reason(
        f"Notion database {NOTION_PAGE_ID} has 2 data sources; skaldr adds rows only to a database with one"
    )

    assert _refusal_of(notion, {"priority": "High"}) == expected


def test_a_parent_in_the_trash_is_refused_in_the_words_of_the_create() -> None:
    notion = InMemoryNotion()
    notion.add_page(NOTION_PAGE_ID, "Old plans")
    notion.pages[NOTION_PAGE_ID].in_trash = True
    expected = _reason(
        f"Notion page {NOTION_PAGE_ID} is in the trash, so skaldr cannot create a page under it"
    )

    assert _refusal_of(notion, {"priority": "High"}) == expected


@pytest.mark.parametrize(
    ("section_fields", "publish", "expected"),
    [
        pytest.param(
            {"priority": "High", "due": "2026-10-15"}, _notion_publish(), TOOLS_FIELDS_PATH, id="the-section"
        ),
        pytest.param(
            {"priority": "High", "due": "2026-10-15"},
            _notion_publish(where_fields={"Priority": "Low"}),
            TOOLS_FIELDS_PATH,
            id="the-target-wins-one-key-and-the-section-supplies-another",
        ),
        pytest.param(
            {"priority": "High"},
            _notion_publish(overrides={"tools": {"fields": {"Priority": "Low"}}}),
            "publish.targets[0].overrides.tools.fields",
            id="an-override-wins-every-key",
        ),
        pytest.param(
            {"priority": "High"},
            _notion_publish(where_fields={"Priority": None}),
            WHERE_FIELDS_PATH,
            id="a-null-in-the-target-fields-wins-every-key",
        ),
    ],
)
def test_the_fields_path_is_the_sections_when_it_supplies_any_value_and_the_targets_otherwise(
    section_fields: JsonObject, publish: JsonObject, expected: str
) -> None:
    assert _tools_draft(section_fields, publish=publish).paths[FIELDS] == expected


def _publish(path: Path, notion: InMemoryNotion) -> ApplyOutcome:
    return apply_publish(prepare_publish(path, _registry(notion)))


def _created_pages(notion: InMemoryNotion) -> list[dict[str, Any]]:
    return [
        json.loads(request.content)
        for request in notion.requests
        if (request.method, request.url.path) == ("POST", "/v1/pages")
    ]


def _title(text: str) -> JsonObject:
    return {"title": [{"type": "text", "text": {"content": text}}]}


def test_publishing_creates_each_split_section_as_a_row_of_the_database_with_its_properties(
    tmp_path: Path,
) -> None:
    notion = _database()
    path = write_garden_report(
        tmp_path,
        publish=_notion_publish(),
        blocks=_blocks_with_fields(
            "tools",
            {
                "status": "In progress",
                "priority": "High",
                "due": "2026-10-15",
                "labels": ["garden"],
                "assignee": "ada",
            },
        ),
        meta=_meta(ADA_HAS_A_NOTION_ID),
    )

    outcome = _publish(path, notion)

    document, tools = _created_pages(notion)
    assert (
        outcome.__class__,
        document["parent"],
        document["properties"],
        tools["parent"],
        tools["properties"],
    ) == (
        Applied,
        {"data_source_id": SOURCE_ID},
        {"Name": _title("Garden handbook")},
        {"data_source_id": SOURCE_ID},
        {
            "Name": _title("Tools"),
            "Status": {"status": {"name": "In progress"}},
            "Priority": {"select": {"name": "High"}},
            "Due": {"date": {"start": "2026-10-15"}},
            "Labels": {"multi_select": [{"name": "garden"}]},
            "Assignee": {"people": [{"id": ADA_USER_ID}]},
        },
    )


def test_a_target_without_the_opt_in_nests_its_sections_under_the_document_row_as_it_always_did(
    tmp_path: Path,
) -> None:
    notion = _database()
    path = write_garden_report(
        tmp_path,
        publish=_notion_publish(from_sections=False),
        blocks=_blocks_with_fields("tools", {"priority": "High"}),
    )

    _publish(path, notion)

    document, tools = _created_pages(notion)
    assert (document["parent"], tools["parent"], tools["properties"]) == (
        {"data_source_id": SOURCE_ID},
        {"page_id": DOCUMENT_PAGE},
        {"title": _title("Tools")},
    )


def test_with_the_opt_in_under_a_page_the_sections_stay_child_pages_of_the_document(
    tmp_path: Path,
) -> None:
    notion = InMemoryNotion()
    notion.add_page(NOTION_PAGE_ID, "Team plans")
    path = write_garden_report(
        tmp_path,
        publish=_notion_publish(),
        blocks=_blocks_with_fields("tools", {"links": {"blocks": ["planting"]}}),
    )

    _publish(path, notion)

    document, tools = _created_pages(notion)
    assert (document["parent"], tools["parent"]) == ({"page_id": NOTION_PAGE_ID}, {"page_id": DOCUMENT_PAGE})


def _publish_a_high_priority_tools_section(tmp_path: Path, notion: InMemoryNotion) -> Path:
    path = write_garden_report(
        tmp_path, publish=_notion_publish(), blocks=_blocks_with_fields("tools", {"priority": "High"})
    )
    _publish(path, notion)
    return path


def test_publishing_again_changes_nothing_and_a_changed_section_field_updates_only_its_row(
    tmp_path: Path,
) -> None:
    notion = _database()
    path = _publish_a_high_priority_tools_section(tmp_path, notion)
    quiet = _publish(path, notion)
    write_garden_report(
        tmp_path, publish=_notion_publish(), blocks=_blocks_with_fields("tools", {"priority": "Low"})
    )

    changed = _publish(path, notion)

    assert (quiet, changed, notion.pages[TOOLS_PAGE].properties["Priority"]) == (
        Applied(()),
        Applied(("update   section tools: fields", "update   section tools: tools (blocks[1])")),
        ("select", "Low"),
    )


def test_the_diff_shows_a_changed_section_field_under_the_path_of_the_section(tmp_path: Path) -> None:
    notion = _database()
    path = _publish_a_high_priority_tools_section(tmp_path, notion)
    write_garden_report(
        tmp_path, publish=_notion_publish(), blocks=_blocks_with_fields("tools", {"priority": "Low"})
    )

    lines = diff_lines(diff_publish(prepare_publish(path, _registry(notion))))

    assert [line for line in lines if "fields" in line] == [
        f"--- {TARGET_LABEL}, section tools: fields ({TOOLS_FIELDS_PATH}), as published",
        f"+++ {TARGET_LABEL}, section tools: fields ({TOOLS_FIELDS_PATH}), in the YAML",
    ]


def test_a_property_changed_in_notion_shows_as_a_remote_edit_of_the_fields_with_the_sections_path(
    tmp_path: Path,
) -> None:
    notion = _database()
    path = _publish_a_high_priority_tools_section(tmp_path, notion)
    notion.set_property_by_hand(TOOLS_PAGE, "Priority", "Low")

    diff = diff_publish(prepare_publish(path, _registry(notion)))

    assert [(edit.item.section_id, edit.part, edit.path) for edit in diff.remote_edits] == [
        ("tools", FIELDS, TOOLS_FIELDS_PATH)
    ]


def test_publishing_a_property_the_database_lacks_sends_nothing(tmp_path: Path) -> None:
    notion = _database({"Name": "title"}, {})
    path = write_garden_report(
        tmp_path, publish=_notion_publish(), blocks=_blocks_with_fields("tools", {"priority": "High"})
    )

    with pytest.raises(PublishError, match="blocks\\[1\\]\\.fields\\.priority has no property named"):
        _publish(path, notion)

    assert notion.writes() == []


def test_a_section_already_published_as_a_page_under_the_document_cannot_take_properties_later(
    tmp_path: Path,
) -> None:
    notion = _database()
    path = write_garden_report(
        tmp_path,
        publish=_notion_publish(from_sections=False),
        blocks=_blocks_with_fields("tools", {"priority": "High"}),
    )
    _publish(path, notion)
    write_garden_report(
        tmp_path, publish=_notion_publish(), blocks=_blocks_with_fields("tools", {"priority": "High"})
    )

    with pytest.raises(Exception, match=f"Notion page {TOOLS_PAGE} has no property 'Priority'"):
        _publish(path, notion)
