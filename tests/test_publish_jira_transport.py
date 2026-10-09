import re

import pytest
from pydantic import JsonValue

from skaldr.errors import ConnectorError, ItemNotFoundError, WriteRejectedError
from skaldr.export.adf import JIRA_DESCRIPTION_LIMIT, compact_adf_length
from skaldr.publish.content import FIELDS, TITLE, ItemContent, section_part
from skaldr.publish.jira.description import layout_of, section_text
from skaldr.publish.jira.transport import JiraTransport
from skaldr.publish.transport import (
    AddSection,
    ContentWrite,
    FieldsWrite,
    NewItem,
    Release,
    RemoteItem,
    RemoveSection,
    SectionRequest,
    Stamp,
)
from skaldr.publish_block import JiraTarget
from tests.factories import make_jira_target
from tests.factories.auth_factory import summarise
from tests.factories.jira_factory import DONE, IN_PROGRESS, SITE, FakeJira

DOC_ID = "garden-handbook"
DOC_LABEL = "skaldr-garden-handbook"
STAMP = Stamp(DOC_ID, None)
SECTION_STAMP = Stamp(DOC_ID, "planting")
TARGET = JiraTarget.model_validate(make_jira_target(where={"project": "DEMO", "issue_type": "Task"}))
UNDER_A_PARENT = JiraTarget.model_validate(
    make_jira_target(where={"project": "DEMO", "issue_type": "Task", "parent": "DEMO-100"})
)


def _words(text: str) -> JsonValue:
    return {"type": "paragraph", "content": [{"type": "text", "text": text}]}


def _table(local_id: str | None = None) -> JsonValue:
    attrs: dict[str, JsonValue] = {"isNumberColumnEnabled": False, "layout": "default"}
    if local_id is not None:
        attrs["localId"] = local_id
    return {
        "type": "table",
        "attrs": attrs,
        "content": [{"type": "tableRow", "content": [{"type": "tableHeader", "content": [_words("Tool")]}]}],
    }


def _exactly(message: str) -> str:
    return f"^{re.escape(message)}$"


INTRO = _words("Welcome.")
PLANTING = _words("Sow in spring.")
SOW_IN_MAY = _words("Sow in May.")
FIELDS_WRITTEN: dict[str, JsonValue] = {"labels": ["garden"], "priority": {"name": "High"}}
CONTENT = ItemContent(
    title="Garden handbook",
    sections={"intro": section_text([INTRO, _table()]), "planting": section_text([PLANTING])},
    fields=FIELDS_WRITTEN,
)
COMPARABLE_CONTENT = CONTENT
RAW_AFTER_CREATE = {
    "intro": section_text([INTRO, _table("jira-0001")]),
    "planting": section_text([PLANTING]),
}


def _stamp_value(stamp: Stamp, *, archived: bool = False) -> JsonValue:
    return {"doc_id": stamp.doc_id, "section_id": stamp.section_id, "archived": archived}


def _layout_value(sections: dict[str, list[JsonValue]]) -> JsonValue:
    return layout_of(sections).model_dump(mode="json")


def _transport(jira: FakeJira) -> JiraTransport:
    return JiraTransport(jira.client())


def _created(jira: FakeJira, content: ItemContent = CONTENT) -> tuple[JiraTransport, RemoteItem]:
    transport = _transport(jira)
    created = transport.create_item(NewItem(TARGET, STAMP, content))
    jira.forget_requests()
    return transport, created


def _read_calls(key: str) -> list[tuple[str, str]]:
    return [
        ("GET", f"/rest/api/3/issue/{key}"),
        ("GET", f"/rest/api/3/issue/{key}/properties/skaldr.stamp"),
        ("GET", f"/rest/api/3/issue/{key}/properties/skaldr.layout"),
        ("GET", f"/rest/api/3/issue/{key}/changelog"),
    ]


def test_creating_an_issue_sends_the_description_fields_label_stamp_and_layout_in_one_request() -> None:
    jira = FakeJira()

    created = _transport(jira).create_item(NewItem(UNDER_A_PARENT, STAMP, CONTENT))

    assert (jira.calls(), summarise(jira.requests[0])["body"], str(jira.requests[1].url)) == (
        [("POST", "/rest/api/3/issue"), *_read_calls("DEMO-1")],
        {
            "fields": {
                "labels": ["garden", DOC_LABEL],
                "priority": {"name": "High"},
                "project": {"key": "DEMO"},
                "issuetype": {"name": "Task"},
                "summary": "Garden handbook",
                "description": {"version": 1, "type": "doc", "content": [INTRO, _table(), PLANTING]},
                "parent": {"key": "DEMO-100"},
            },
            "properties": [
                {"key": "skaldr.stamp", "value": _stamp_value(STAMP)},
                {
                    "key": "skaldr.layout",
                    "value": _layout_value({"intro": [INTRO, _table()], "planting": [PLANTING]}),
                },
            ],
        },
        f"{SITE}/rest/api/3/issue/DEMO-1?fields=summary%2Cdescription%2Clabels%2Cpriority",
    )
    assert created == RemoteItem(
        "DEMO-1", COMPARABLE_CONTENT, RAW_AFTER_CREATE, STAMP, None, set_properties=("labels", "priority")
    )


def test_a_split_section_is_created_under_the_documents_issue() -> None:
    jira = FakeJira()

    _transport(jira).create_item(NewItem(UNDER_A_PARENT, SECTION_STAMP, CONTENT, parent_id="DEMO-7"))

    assert jira.issues["DEMO-1"].fields["parent"] == {"key": "DEMO-7"}


def test_an_issue_without_a_parent_sends_none() -> None:
    jira = FakeJira()

    _transport(jira).create_item(NewItem(TARGET, STAMP, CONTENT))

    assert "parent" not in jira.issues["DEMO-1"].fields


def test_a_label_the_author_already_wrote_is_not_sent_twice() -> None:
    jira = FakeJira()
    content = CONTENT.model_copy(update={"fields": {"labels": [DOC_LABEL, "garden", "garden"]}})

    _transport(jira).create_item(NewItem(TARGET, STAMP, content))

    assert jira.issues["DEMO-1"].fields["labels"] == [DOC_LABEL, "garden"]


def test_when_jira_drops_the_properties_of_a_create_skaldr_puts_them_and_reads_again() -> None:
    jira = FakeJira(honours_properties_on_create=False)

    created = _transport(jira).create_item(NewItem(TARGET, STAMP, CONTENT))

    assert (created.stamp, created.raw_sections, jira.calls()) == (
        STAMP,
        RAW_AFTER_CREATE,
        [
            ("POST", "/rest/api/3/issue"),
            *_read_calls("DEMO-1"),
            ("PUT", "/rest/api/3/issue/DEMO-1/properties/skaldr.layout"),
            ("PUT", "/rest/api/3/issue/DEMO-1/properties/skaldr.stamp"),
            *_read_calls("DEMO-1"),
        ],
    )


def test_a_description_over_jiras_limit_is_refused_before_anything_is_sent() -> None:
    jira = FakeJira()
    long_text = _words("x" * JIRA_DESCRIPTION_LIMIT)
    content = CONTENT.model_copy(update={"sections": {"intro": section_text([long_text])}})
    size = compact_adf_length({"version": 1, "type": "doc", "content": [long_text]})

    with pytest.raises(
        WriteRejectedError,
        match=_exactly(
            f'the description of the new issue "Garden handbook" is {size:,} characters of ADF, over the '
            "32,767 Jira takes; split the document further with `split`, or shorten it"
        ),
    ):
        _transport(jira).create_item(NewItem(TARGET, STAMP, content))
    assert jira.requests == []


def test_creating_into_an_existing_issue_is_refused() -> None:
    jira = FakeJira()

    with pytest.raises(
        ConnectorError,
        match=_exactly(
            "Jira publishes only into issues skaldr creates, so it cannot write into DEMO-5; publish under "
            "it with `parent` instead"
        ),
    ):
        _transport(jira).create_item(NewItem(TARGET, STAMP, CONTENT, into_id="DEMO-5"))
    assert jira.requests == []


def test_a_rejected_issue_type_is_a_rejected_write() -> None:
    jira = FakeJira()
    target = JiraTarget.model_validate(make_jira_target(where={"project": "DEMO", "issue_type": "Saga"}))

    with pytest.raises(
        WriteRejectedError,
        match=_exactly(
            "Jira refused POST /rest/api/3/issue (HTTP 400): issuetype: Specify a valid issue type"
        ),
    ):
        _transport(jira).create_item(NewItem(target, STAMP, CONTENT))


def test_a_read_keeps_the_fields_skaldr_wrote_in_the_shape_it_wrote_them_and_drops_its_own_label() -> None:
    jira = FakeJira()
    transport, created = _created(jira)
    jira.edit_by_hand(created.item_id, components=[{"name": "Beds"}])

    read = transport.read_item(created.item_id, CONTENT)

    assert (read.comparable.fields, read.set_properties) == (FIELDS_WRITTEN, ("labels", "priority"))


def test_a_list_of_objects_reads_back_as_the_keys_skaldr_wrote_and_a_scalar_as_jira_has_it() -> None:
    jira = FakeJira()
    fields: dict[str, JsonValue] = {"components": [{"name": "Beds"}], "customfield_10010": 3}
    transport, created = _created(jira, CONTENT.model_copy(update={"fields": fields}))
    jira.edit_by_hand(created.item_id, components=[{"name": "Beds"}, {"name": "Paths", "id": "7"}])

    read = transport.read_item(created.item_id, CONTENT.model_copy(update={"fields": fields}))

    assert read.comparable.fields == {
        "components": [{"name": "Beds"}, {"name": "Paths"}],
        "customfield_10010": 3,
    }


def test_a_field_cleared_in_jira_reads_as_unset() -> None:
    jira = FakeJira()
    transport, created = _created(jira)
    jira.edit_by_hand(created.item_id, priority=None, labels=[DOC_LABEL])

    read = transport.read_item(created.item_id, CONTENT)

    assert (read.comparable.fields, read.set_properties) == ({"labels": [], "priority": None}, ())


def test_a_read_names_the_latest_edit_to_what_skaldr_writes_and_marks_the_newest_change() -> None:
    jira = FakeJira()
    transport, created = _created(jira)
    jira.edit_by_hand(created.item_id, summary="Garden guide")
    jira.log_by_hand(created.item_id, "status")

    read = transport.read_item(created.item_id, CONTENT)

    assert (read.edited_by, read.edited_at, read.marker) == (
        "Robin Editor",
        "2026-10-01T10:00:00.000+0000",
        "10002",
    )


def test_a_missing_issue_reads_as_not_found() -> None:
    with pytest.raises(ItemNotFoundError):
        _transport(FakeJira()).read_item("DEMO-9", CONTENT)


def test_a_description_without_a_layout_reads_as_one_section() -> None:
    jira = FakeJira()
    jira.seed("DEMO-3", summary="Notes", description={"version": 1, "type": "doc", "content": [INTRO]})

    read = _transport(jira).read_item("DEMO-3", ItemContent(title=""))

    assert (read.comparable, read.stamp) == (
        ItemContent(title="Notes", sections={"description": section_text([INTRO])}),
        None,
    )


def test_a_content_write_replaces_the_description_and_layout_in_one_request() -> None:
    jira = FakeJira()
    transport, created = _created(jira)
    sections = {"planting": section_text([SOW_IN_MAY]), "tools": section_text([_words("Spade.")])}

    written = transport.write_content(created.item_id, ContentWrite(sections, created.raw_sections))

    assert (jira.calls(), summarise(jira.requests[4])["body"], written.comparable.sections) == (
        [*_read_calls("DEMO-1"), ("PUT", "/rest/api/3/issue/DEMO-1"), *_read_calls("DEMO-1")],
        {
            "fields": {
                "description": {"version": 1, "type": "doc", "content": [SOW_IN_MAY, _words("Spade.")]}
            },
            "properties": [
                {
                    "key": "skaldr.layout",
                    "value": _layout_value({"planting": [SOW_IN_MAY], "tools": [_words("Spade.")]}),
                }
            ],
        },
        sections,
    )
    assert written.comparable.fields == FIELDS_WRITTEN


def test_when_jira_drops_the_properties_of_an_edit_skaldr_puts_the_layout_and_reads_again() -> None:
    jira = FakeJira(honours_properties_on_edit=False)
    transport, created = _created(jira)
    sections = {"planting": section_text([SOW_IN_MAY])}

    written = transport.write_content(created.item_id, ContentWrite(sections, created.raw_sections))

    assert (list(written.raw_sections), jira.calls()[5:]) == (
        ["planting"],
        [
            *_read_calls("DEMO-1"),
            ("PUT", "/rest/api/3/issue/DEMO-1/properties/skaldr.layout"),
            *_read_calls("DEMO-1"),
        ],
    )


def test_a_content_write_against_a_description_edited_since_the_read_is_refused_unsent() -> None:
    jira = FakeJira()
    transport, created = _created(jira)
    jira.edit_by_hand(created.item_id, description={"version": 1, "type": "doc", "content": [PLANTING]})

    with pytest.raises(
        WriteRejectedError,
        match=_exactly(
            "DEMO-1 changed in Jira after skaldr read it, so skaldr did not write its description; publish "
            "again to see the change"
        ),
    ):
        transport.write_content(created.item_id, ContentWrite({"planting": "[]"}, created.raw_sections))
    assert [method for method, _ in jira.calls()] == ["GET"] * 4


def test_an_empty_content_write_clears_the_description() -> None:
    jira = FakeJira()
    transport, created = _created(jira)

    written = transport.write_content(created.item_id, ContentWrite({}, created.raw_sections))

    assert (jira.issues["DEMO-1"].fields["description"], written.raw_sections) == (None, {})


def test_a_section_write_rewrites_the_whole_description_with_that_section_changed() -> None:
    jira = FakeJira()
    transport, created = _created(jira)
    tools = section_text([_words("Spade.")])

    written = transport.write_section(
        created.item_id, SectionRequest(AddSection("tools", tools, "intro"), created.raw_sections)
    )

    assert (list(written.raw_sections), jira.issues["DEMO-1"].fields["description"]) == (
        ["intro", "tools", "planting"],
        {
            "version": 1,
            "type": "doc",
            "content": [INTRO, _table("jira-0002"), _words("Spade."), PLANTING],
        },
    )


def test_a_section_write_quoting_text_jira_no_longer_holds_is_refused_unsent() -> None:
    jira = FakeJira()
    transport, created = _created(jira)

    with pytest.raises(
        WriteRejectedError,
        match=_exactly(
            "section planting of DEMO-1 no longer holds the text skaldr read, so skaldr did not write it"
        ),
    ):
        transport.write_section(
            created.item_id, SectionRequest(RemoveSection("planting", "[]"), created.raw_sections)
        )
    assert [method for method, _ in jira.calls()] == ["GET"] * 4


def _fields_write(fields: dict[str, JsonValue], title: str = "Garden handbook") -> FieldsWrite:
    return FieldsWrite(title, fields, "Garden handbook", FIELDS_WRITTEN, STAMP)


@pytest.mark.parametrize(
    ("write", "sent"),
    [
        pytest.param(_fields_write(FIELDS_WRITTEN, "Garden guide"), {"summary": "Garden guide"}, id="title"),
        pytest.param(
            _fields_write({**FIELDS_WRITTEN, "priority": {"name": "Low"}}),
            {"priority": {"name": "Low"}},
            id="one-field",
        ),
        pytest.param(
            _fields_write({**FIELDS_WRITTEN, "labels": ["shed", "garden"]}),
            {"labels": ["shed", "garden", DOC_LABEL]},
            id="labels-keep-the-stamp",
        ),
        pytest.param(_fields_write({"labels": ["garden"]}), {"priority": None}, id="cleared-field"),
        pytest.param(
            _fields_write({"priority": {"name": "High"}}), {"labels": [DOC_LABEL]}, id="cleared-labels"
        ),
    ],
)
def test_a_fields_write_sends_only_what_changed(write: FieldsWrite, sent: dict[str, JsonValue]) -> None:
    jira = FakeJira()
    transport, created = _created(jira)

    transport.write_fields(created.item_id, write)

    assert (jira.calls()[0], summarise(jira.requests[0])["body"]) == (
        ("PUT", "/rest/api/3/issue/DEMO-1"),
        {"fields": sent},
    )


def test_a_fields_write_with_nothing_changed_sends_nothing_and_reads_back() -> None:
    jira = FakeJira()
    transport, created = _created(jira)

    read = transport.write_fields(created.item_id, _fields_write({**FIELDS_WRITTEN, "labels": ["garden"]}))

    assert (jira.calls(), read.comparable) == (_read_calls("DEMO-1"), COMPARABLE_CONTENT)


def test_a_field_jira_does_not_know_is_a_rejected_write() -> None:
    jira = FakeJira()
    transport, created = _created(jira)

    with pytest.raises(
        WriteRejectedError,
        match=_exactly(
            "Jira refused PUT /rest/api/3/issue/DEMO-1 (HTTP 400): story_points: Field 'story_points' cannot "
            "be set. It is not on the appropriate screen, or unknown."
        ),
    ):
        transport.write_fields(created.item_id, _fields_write({**FIELDS_WRITTEN, "story_points": 3}))


def test_archiving_closes_the_issue_comments_why_and_marks_it_archived() -> None:
    jira = FakeJira()
    transport, created = _created(jira)

    transport.archive_item(created.item_id)

    issue = jira.issues["DEMO-1"]
    why = "skaldr archived this issue: the document garden-handbook no longer has the content it held."
    assert (jira.calls(), issue.fields["status"], issue.comments, issue.properties["skaldr.stamp"]) == (
        [
            ("GET", "/rest/api/3/issue/DEMO-1/properties/skaldr.stamp"),
            ("GET", "/rest/api/3/issue/DEMO-1"),
            ("GET", "/rest/api/3/issue/DEMO-1/transitions"),
            ("POST", "/rest/api/3/issue/DEMO-1/transitions"),
            ("POST", "/rest/api/3/issue/DEMO-1/comment"),
            ("PUT", "/rest/api/3/issue/DEMO-1/properties/skaldr.stamp"),
        ],
        DONE,
        [{"version": 1, "type": "doc", "content": [_words(why)]}],
        _stamp_value(STAMP, archived=True),
    )


def test_an_archived_issue_reads_as_not_found_and_archiving_it_again_sends_nothing() -> None:
    jira = FakeJira()
    transport, created = _created(jira)
    transport.archive_item(created.item_id)
    jira.forget_requests()

    transport.archive_item(created.item_id)
    archived_again = jira.calls()
    with pytest.raises(
        ItemNotFoundError, match=_exactly("skaldr archived DEMO-1, so it no longer publishes there")
    ):
        transport.read_item(created.item_id, CONTENT)

    assert (archived_again, len(jira.issues["DEMO-1"].comments)) == (
        [("GET", "/rest/api/3/issue/DEMO-1/properties/skaldr.stamp")],
        1,
    )


def test_an_issue_already_done_is_marked_archived_without_a_transition_or_a_comment() -> None:
    jira = FakeJira()
    transport, created = _created(jira)
    jira.edit_by_hand(created.item_id, status=DONE)

    transport.archive_item(created.item_id)

    assert (jira.calls()[2:], jira.issues["DEMO-1"].comments) == (
        [("PUT", "/rest/api/3/issue/DEMO-1/properties/skaldr.stamp")],
        [],
    )


def test_an_issue_with_no_way_to_a_done_status_is_not_archived() -> None:
    jira = FakeJira()
    transport, created = _created(jira)
    jira.issues["DEMO-1"].fields["status"] = {"name": "Blocked", "statusCategory": {"key": "indeterminate"}}

    with pytest.raises(
        WriteRejectedError,
        match=_exactly(
            "DEMO-1 has no transition from 'Blocked' to a done status, so skaldr cannot archive it; close it "
            "in Jira, then publish again"
        ),
    ):
        transport.archive_item(created.item_id)
    assert jira.issues["DEMO-1"].comments == []


def test_a_done_transition_is_found_by_its_status_category_not_its_name() -> None:
    jira = FakeJira()
    transport, created = _created(jira)
    jira.issues["DEMO-1"].fields["status"] = IN_PROGRESS

    transport.archive_item(created.item_id)

    assert summarise(jira.requests[3])["body"] == {"transition": {"id": "31"}}


def test_jira_has_nothing_to_release() -> None:
    jira = FakeJira()
    transport, created = _created(jira)

    with pytest.raises(
        ConnectorError,
        match=_exactly(
            "Jira has nothing to release: skaldr writes only into issues it created, and archives those"
        ),
    ):
        transport.release_item(created.item_id, Release(created.raw_sections, ("labels",)))
    assert jira.requests == []


def test_the_marker_after_a_write_covers_skaldrs_own_changes() -> None:
    jira = FakeJira()
    transport, created = _created(jira)

    written = transport.write_fields(created.item_id, _fields_write(FIELDS_WRITTEN, "Garden guide"))

    assert (written.marker, transport.parts_edited_after(created.item_id, written.marker, CONTENT)) == (
        "10001",
        (),
    )


@pytest.mark.parametrize(
    ("field_ids", "parts"),
    [
        pytest.param(("summary",), (TITLE,), id="summary"),
        pytest.param(("priority",), (FIELDS,), id="owned-field"),
        pytest.param(("labels",), (FIELDS,), id="owned-labels"),
        pytest.param(("status", "Sprint", "resolution"), (), id="fields-skaldr-never-set"),
        pytest.param(("summary", "priority"), (TITLE, FIELDS), id="both"),
    ],
)
def test_a_changelog_entry_after_the_marker_reports_the_part_it_touched(
    field_ids: tuple[str, ...], parts: tuple[object, ...]
) -> None:
    jira = FakeJira()
    transport, created = _created(jira)
    jira.log_by_hand(created.item_id, *field_ids)

    assert transport.parts_edited_after(created.item_id, created.marker, CONTENT) == parts


def test_labels_skaldr_does_not_own_are_not_an_edit() -> None:
    jira = FakeJira()
    content = CONTENT.model_copy(update={"fields": {"priority": {"name": "High"}}})
    transport, created = _created(jira, content)
    jira.log_by_hand(created.item_id, "labels")

    assert transport.parts_edited_after(created.item_id, created.marker, content) == ()


def test_a_description_edit_reports_only_the_sections_whose_text_changed() -> None:
    jira = FakeJira()
    transport, created = _created(jira)
    jira.edit_by_hand(
        created.item_id,
        description={"version": 1, "type": "doc", "content": [INTRO, _table("jira-0009"), SOW_IN_MAY]},
    )

    assert transport.parts_edited_after(created.item_id, created.marker, CONTENT) == (
        section_part("planting"),
    )


def test_without_a_marker_every_entry_counts() -> None:
    jira = FakeJira()
    transport, created = _created(jira)
    jira.log_by_hand(created.item_id, "summary")

    assert transport.parts_edited_after(created.item_id, None, CONTENT) == (TITLE,)


def test_the_comparable_form_normalises_each_section_and_drops_empty_ones() -> None:
    content = ItemContent(
        title="Garden handbook",
        sections={"intro": section_text([INTRO, _table("skaldr-1")]), "header": ""},
        fields=FIELDS_WRITTEN,
    )

    assert _transport(FakeJira()).comparable_form(content) == ItemContent(
        title="Garden handbook", sections={"intro": section_text([INTRO, _table()])}, fields=FIELDS_WRITTEN
    )
