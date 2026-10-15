import re
from collections.abc import Callable

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
    LinksWrite,
    NewItem,
    Release,
    RemoteItem,
    RemoveSection,
    SectionRequest,
    ShownLink,
    Stamp,
)
from skaldr.publish_block import JiraTarget, NotionTarget
from tests.factories import make_jira_target, make_notion_target
from tests.factories.auth_factory import summarise
from tests.factories.jira_factory import (
    DONE,
    DONE_RESOLUTION,
    EDITOR,
    IN_PROGRESS,
    NOT_FOUND,
    SITE,
    WRITER,
    FakeJira,
    Reply,
    summarised_request,
)

DOC_ID = "garden-handbook"
DOC_LABEL = "skaldr-garden-handbook"
STAMP = Stamp(DOC_ID, None)
SECTION_STAMP = Stamp(DOC_ID, "planting")
LONGEST_LINKABLE_DOC_ID = "garden-" + "a" * 192
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
TABLE_AS_COMPARED: JsonValue = {
    "type": "table",
    "content": [{"type": "tableRow", "content": [{"type": "tableHeader", "content": [_words("Tool")]}]}],
}
CONTENT_AS_COMPARED = CONTENT.model_copy(
    update={
        "sections": {"intro": section_text([INTRO, TABLE_AS_COMPARED]), "planting": section_text([PLANTING])}
    }
)
RAW_AFTER_CREATE = {
    "intro": section_text([INTRO, _table("jira-0001")]),
    "planting": section_text([PLANTING]),
}


def _stamp_value(
    stamp: Stamp, *, commented: bool = False, archived: bool = False, linked: bool = False
) -> JsonValue:
    return {
        "doc_id": stamp.doc_id,
        "section_id": stamp.section_id,
        "commented": commented,
        "archived": archived,
        "linked": linked,
    }


def _layout_value(sections: dict[str, list[JsonValue]]) -> JsonValue:
    return layout_of(sections).model_dump(mode="json")


def _transport(jira: FakeJira) -> JiraTransport:
    return JiraTransport(jira.client())


def _transition_bodies(jira: FakeJira) -> list[object]:
    return [
        summarise(request)["body"]
        for request in jira.requests
        if request.method == "POST" and request.url.path.endswith("/transitions")
    ]


def _created(jira: FakeJira, content: ItemContent = CONTENT) -> tuple[JiraTransport, RemoteItem]:
    transport = _transport(jira)
    created = transport.create_item(NewItem(TARGET, STAMP, content))
    jira.forget_requests()
    return transport, created


def _read_calls(key: str) -> list[tuple[str, str]]:
    return [
        ("GET", f"/rest/api/3/issue/{key}/changelog"),
        ("GET", f"/rest/api/3/issue/{key}/properties/skaldr.stamp"),
        ("GET", f"/rest/api/3/issue/{key}/properties/skaldr.layout"),
        ("GET", f"/rest/api/3/issue/{key}"),
    ]


CHANGED_SINCE_READ = (
    "DEMO-1 changed in Jira after skaldr read it, so skaldr did not write to it; publish again to see the "
    "change"
)


def _description(*blocks: JsonValue) -> JsonValue:
    return {"version": 1, "type": "doc", "content": list(blocks)}


def test_a_description_edit_made_after_the_read_stops_a_fields_write_before_it_is_sent() -> None:
    jira = FakeJira()
    transport, created = _created(jira)
    jira.edit_by_hand(created.item_id, description=_description(INTRO, _table(), SOW_IN_MAY))

    with pytest.raises(WriteRejectedError, match=_exactly(CHANGED_SINCE_READ)):
        transport.write_fields(created.item_id, _fields_write(FIELDS_WRITTEN, "Garden guide"))
    assert jira.calls() == [
        ("GET", "/rest/api/3/issue/DEMO-1/properties/skaldr.stamp"),
        ("GET", "/rest/api/3/issue/DEMO-1/changelog"),
    ]


@pytest.mark.parametrize(
    ("written", "named"),
    [
        pytest.param(Stamp("other-handbook", None), "doc_id 'other-handbook'", id="another-document"),
        pytest.param(SECTION_STAMP, f"doc_id '{DOC_ID}', section 'planting'", id="a-section-of-the-document"),
    ],
)
def test_fields_are_not_written_to_an_issue_stamped_for_another_document_or_section(
    written: Stamp, named: str
) -> None:
    jira = FakeJira()
    transport, created = _created(jira)

    with pytest.raises(WriteRejectedError) as caught:
        transport.write_fields(created.item_id, FieldsWrite("Other", {}, CONTENT.title, {}, written))

    assert (str(caught.value), jira.calls()) == (
        f"Jira issue {created.item_id} is not stamped with {named}",
        [("GET", "/rest/api/3/issue/DEMO-1/properties/skaldr.stamp")],
    )


def test_a_description_edit_landing_during_a_fields_write_is_not_taken_as_published() -> None:
    jira = FakeJira()
    transport, created = _created(jira)
    jira.edit_right_after_the_next_write(
        created.item_id, description=_description(INTRO, _table(), SOW_IN_MAY)
    )

    with pytest.raises(ConnectorError) as raised:
        transport.write_fields(created.item_id, _fields_write(FIELDS_WRITTEN, "Garden guide"))
    with pytest.raises(WriteRejectedError, match=_exactly(CHANGED_SINCE_READ)):
        transport.write_content(
            created.item_id, ContentWrite(dict(CONTENT.sections), created.raw_sections, STAMP)
        )

    assert (type(raised.value), str(raised.value), jira.issues["DEMO-1"].fields["description"]) == (
        ConnectorError,
        "DEMO-1 was edited in Jira while skaldr wrote to it (description); the write landed, and the next "
        "publish shows the edit",
        _description(INTRO, _table(), SOW_IN_MAY),
    )


def test_an_edit_landing_between_a_content_write_and_its_read_back_is_reported_later() -> None:
    jira = FakeJira()
    transport, created = _created(jira)
    jira.edit_right_after_the_next_write(created.item_id, summary="Garden guide")
    sections = {"planting": section_text([SOW_IN_MAY])}

    with pytest.raises(ConnectorError) as raised:
        transport.write_content(created.item_id, ContentWrite(sections, created.raw_sections, STAMP))

    assert (str(raised.value), transport.parts_edited_after(created.item_id, created.marker, CONTENT)) == (
        "DEMO-1 was edited in Jira while skaldr wrote to it (summary); the write landed, and the next "
        "publish shows the edit",
        (TITLE, section_part("intro"), section_part("planting")),
    )


def test_the_marker_after_a_write_is_skaldrs_own_entry_even_when_others_change_fields_it_does_not_own() -> (
    None
):
    jira = FakeJira()
    transport, created = _created(jira)
    jira.edit_right_after_the_next_write(created.item_id, status=IN_PROGRESS)

    written = transport.write_fields(created.item_id, _fields_write(FIELDS_WRITTEN, "Garden guide"))

    assert (written.marker, [entry["id"] for entry in jira.histories["DEMO-1"]]) == (
        "10001",
        ["10001", "10002"],
    )


@pytest.mark.parametrize(
    ("author", "named"), [(EDITOR, "Robin Editor"), (WRITER, "Example Reader")], ids=["someone-else", "you"]
)
def test_an_edit_landing_just_before_skaldrs_write_to_the_same_field_is_named_so_it_can_be_restored(
    author: dict[str, JsonValue], named: str
) -> None:
    jira = FakeJira()
    transport, created = _created(jira)
    jira.edit_right_before_the_next_write(created.item_id, author=author, summary="Garden notes")

    with pytest.raises(ConnectorError) as raised:
        transport.write_fields(created.item_id, _fields_write(FIELDS_WRITTEN, "Garden guide"))

    assert (str(raised.value), jira.issues["DEMO-1"].fields["summary"]) == (
        "DEMO-1: skaldr's write replaced an edit made in Jira just before it (summary in changelog 10001 by "
        f"{named} at 2026-10-01T10:00:00.000+0000); restore it from the issue's history if it should stay",
        "Garden guide",
    )


def test_skaldrs_own_change_to_a_custom_field_jira_logs_by_its_display_name_is_its_own() -> None:
    jira = FakeJira()
    fields: dict[str, JsonValue] = {**FIELDS_WRITTEN, "customfield_10010": 3}
    transport, created = _created(jira, CONTENT.model_copy(update={"fields": fields}))
    write = FieldsWrite(
        "Garden handbook", {**fields, "customfield_10010": 5}, "Garden handbook", fields, STAMP
    )

    written = transport.write_fields(created.item_id, write)

    assert (written.marker, written.comparable.fields["customfield_10010"]) == ("10001", 5)


def test_a_read_back_jira_saved_in_a_form_skaldr_does_not_expect_is_taken_as_published() -> None:
    jira = FakeJira(adds_to_paragraphs={"indentation": 0})
    transport, created = _created(jira)
    sections = {"planting": section_text([SOW_IN_MAY])}

    written = transport.write_content(created.item_id, ContentWrite(sections, created.raw_sections, STAMP))

    saved: JsonValue = {
        "type": "paragraph",
        "attrs": {"indentation": 0},
        "content": [{"type": "text", "text": "Sow in May."}],
    }
    assert (written.marker, written.comparable.sections) == ("10001", {"planting": section_text([saved])})


def _saved_words(text: str) -> JsonValue:
    return {"type": "paragraph", "attrs": {"indentation": 0}, "content": [{"type": "text", "text": text}]}


def test_a_new_issue_jira_saved_in_a_form_skaldr_does_not_expect_is_taken_as_published() -> None:
    jira = FakeJira(adds_to_paragraphs={"indentation": 0})
    transport = _transport(jira)

    created = transport.create_item(NewItem(TARGET, STAMP, CONTENT))

    saved_table: JsonValue = {
        "type": "table",
        "content": [
            {"type": "tableRow", "content": [{"type": "tableHeader", "content": [_saved_words("Tool")]}]}
        ],
    }
    saved = CONTENT.model_copy(
        update={
            "sections": {
                "intro": section_text([_saved_words("Welcome."), saved_table]),
                "planting": section_text([_saved_words("Sow in spring.")]),
            }
        }
    )
    assert (
        created.marker,
        created.comparable,
        transport.read_item(created.item_id, CONTENT).comparable,
        transport.parts_edited_after(created.item_id, created.marker, CONTENT),
    ) == (None, saved, saved, ())


GARDENER = "account-gardener"
WEEDER = "account-weeder"


def _asking(account_id: str) -> JsonValue:
    mention: JsonValue = {"type": "mention", "attrs": {"id": account_id, "text": "@Robin"}}
    return {"type": "paragraph", "content": [{"type": "text", "text": "Ask "}, mention]}


def _with_planting(*blocks: JsonValue) -> ItemContent:
    return CONTENT.model_copy(
        update={"sections": {"intro": CONTENT.sections["intro"], "planting": section_text(list(blocks))}}
    )


def test_a_mention_jira_saves_under_the_persons_display_name_stays_in_sync_after_a_create_and_an_update() -> (
    None
):
    jira = FakeJira(names_in_mentions={GARDENER: "Robin Gardener (Robin)"})
    content = _with_planting(_asking(GARDENER))
    transport, created = _created(jira, content)
    after_create = transport.read_item(created.item_id, content)
    edited_after_create = transport.parts_edited_after(created.item_id, created.marker, content)
    updated = _with_planting(_asking(GARDENER), SOW_IN_MAY)

    written = transport.write_content(
        created.item_id, ContentWrite(dict(updated.sections), after_create.raw_sections, STAMP)
    )
    after_update = transport.read_item(created.item_id, updated)

    assert (
        created.comparable,
        after_create.comparable,
        edited_after_create,
        written.comparable,
        after_update.comparable,
        transport.parts_edited_after(created.item_id, written.marker, updated),
    ) == (
        transport.comparable_form(content),
        transport.comparable_form(content),
        (),
        transport.comparable_form(updated),
        transport.comparable_form(updated),
        (),
    )


def test_a_mention_pointed_at_another_person_in_jira_is_an_edit() -> None:
    jira = FakeJira(names_in_mentions={GARDENER: "Robin Gardener (Robin)", WEEDER: "Robin Weeder"})
    content = _with_planting(_asking(GARDENER))
    transport, created = _created(jira, content)
    jira.edit_by_hand(created.item_id, description=_description(INTRO, _table(), _asking(WEEDER)))

    assert (
        transport.parts_edited_after(created.item_id, created.marker, content),
        transport.read_item(created.item_id, content).comparable.sections["planting"],
    ) == (
        (section_part("planting"),),
        section_text(
            [
                {
                    "type": "paragraph",
                    "content": [
                        {"type": "text", "text": "Ask "},
                        {"type": "mention", "attrs": {"id": WEEDER}},
                    ],
                }
            ]
        ),
    )


def test_a_change_made_to_a_new_issue_right_after_its_create_is_left_for_the_next_publish_to_report() -> None:
    jira = FakeJira()
    jira.edit_right_after_the_next_write("DEMO-1", labels=["garden", "triaged", DOC_LABEL])
    transport = _transport(jira)

    created = transport.create_item(NewItem(TARGET, STAMP, CONTENT))

    assert (
        created.marker,
        created.comparable,
        transport.parts_edited_after(created.item_id, created.marker, CONTENT),
    ) == (None, CONTENT_AS_COMPARED, (FIELDS,))


def test_a_fresh_transport_reads_a_newly_owned_field_in_the_shape_the_target_writes_it() -> None:
    jira = FakeJira()
    jira.seed("DEMO-3", summary="Notes", priority={"name": "High", "id": "2"})
    transport = JiraTransport(jira.client(), field_shapes={"priority": {"name": "High"}})

    read = transport.read_item("DEMO-3", ItemContent(title="", fields={"priority": None}))

    assert read.comparable.fields == {"priority": {"name": "High"}}


@pytest.mark.parametrize(("extra", "accepted"), [(0, True), (1, False)], ids=["at-the-limit", "one-over"])
def test_a_description_of_exactly_the_limit_is_sent_and_one_character_more_is_not(
    extra: int, accepted: bool
) -> None:
    jira = FakeJira()
    base = compact_adf_length({"version": 1, "type": "doc", "content": [_words("")]})
    text = _words("x" * (JIRA_DESCRIPTION_LIMIT - base + extra))
    content = CONTENT.model_copy(update={"sections": {"intro": section_text([text])}})
    size = compact_adf_length({"version": 1, "type": "doc", "content": [text]})

    if accepted:
        _transport(jira).create_item(NewItem(TARGET, STAMP, content))
    else:
        with pytest.raises(WriteRejectedError):
            _transport(jira).create_item(NewItem(TARGET, STAMP, content))

    assert (size, "DEMO-1" in jira.issues) == (JIRA_DESCRIPTION_LIMIT + extra, accepted)


def test_creating_an_issue_sends_the_description_fields_label_stamp_and_layout_in_one_request() -> None:
    jira = FakeJira()

    created = _transport(jira).create_item(NewItem(UNDER_A_PARENT, STAMP, CONTENT))

    assert (jira.calls(), summarise(jira.requests[0])["body"], str(jira.requests[4].url)) == (
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
        "DEMO-1", CONTENT_AS_COMPARED, RAW_AFTER_CREATE, STAMP, None, set_properties=("labels", "priority")
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


def test_when_jira_drops_the_properties_of_a_create_skaldr_puts_them_without_reading_again() -> None:
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
        ],
    )


def test_the_edit_check_after_a_read_reuses_that_read_and_sends_nothing_more() -> None:
    jira = FakeJira()
    transport, created = _created(jira)
    jira.edit_by_hand(created.item_id, summary="Garden guide", description=_description(INTRO, _table()))
    jira.forget_requests()

    transport.read_item(created.item_id, CONTENT)
    edited = transport.parts_edited_after(created.item_id, created.marker, CONTENT)

    assert (edited, jira.calls()) == ((TITLE, section_part("planting")), _read_calls("DEMO-1"))


def test_a_write_between_a_read_and_the_edit_check_makes_the_check_read_again() -> None:
    jira = FakeJira()
    transport, created = _created(jira)
    transport.read_item(created.item_id, CONTENT)
    written = transport.write_fields(created.item_id, _fields_write(FIELDS_WRITTEN, "Garden guide"))
    jira.edit_by_hand(created.item_id, summary="Garden notes")
    jira.forget_requests()

    edited = transport.parts_edited_after(created.item_id, written.marker, CONTENT)

    assert (edited, jira.calls()) == ((TITLE,), _read_calls("DEMO-1"))


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


def test_creating_into_an_existing_issue_is_a_rejected_write_and_sends_nothing() -> None:
    jira = FakeJira()

    with pytest.raises(
        WriteRejectedError,
        match=_exactly(
            "Jira publishes only into issues skaldr creates, so it cannot write into DEMO-5; publish under "
            "it with `parent` instead"
        ),
    ):
        _transport(jira).create_item(NewItem(TARGET, STAMP, CONTENT, into_id="DEMO-5"))
    assert jira.requests == []


def test_creating_for_a_notion_target_is_a_rejected_write_and_sends_nothing() -> None:
    jira = FakeJira()
    target = NotionTarget.model_validate(make_notion_target())

    with pytest.raises(
        WriteRejectedError, match=_exactly("the Jira connector cannot publish to a notion target")
    ):
        _transport(jira).create_item(NewItem(target, STAMP, CONTENT))
    assert jira.requests == []


def test_a_section_that_is_not_a_list_of_adf_blocks_is_a_rejected_write_and_sends_nothing() -> None:
    jira = FakeJira()
    content = CONTENT.model_copy(update={"sections": {"intro": '{"type": "paragraph"}'}})

    with pytest.raises(
        WriteRejectedError,
        match=_exactly(
            'a Jira section holds a JSON list of ADF blocks, and this one does not: \'{"type": "paragraph"}\''
        ),
    ):
        _transport(jira).create_item(NewItem(TARGET, STAMP, content))
    assert jira.requests == []


def test_a_content_write_of_a_section_that_is_not_adf_blocks_is_a_rejected_write_and_writes_nothing() -> None:
    jira = FakeJira()
    transport, created = _created(jira)

    with pytest.raises(
        WriteRejectedError,
        match=_exactly(
            "a Jira section holds a JSON list of ADF blocks, and this one does not: 'Sow in May.'"
        ),
    ):
        transport.write_content(
            created.item_id, ContentWrite({"planting": "Sow in May."}, created.raw_sections, STAMP)
        )
    assert jira.calls() == _read_calls("DEMO-1")


def test_fields_with_no_value_are_left_out_of_a_create() -> None:
    jira = FakeJira()
    fields: dict[str, JsonValue] = {
        "priority": {"name": "High"},
        "duedate": None,
        "components": [],
        "customfield_10020": "",
        "customfield_10030": {},
    }

    _transport(jira).create_item(NewItem(TARGET, STAMP, CONTENT.model_copy(update={"fields": fields})))

    assert summarise(jira.requests[0])["body"] == {
        "fields": {
            "priority": {"name": "High"},
            "labels": [DOC_LABEL],
            "project": {"key": "DEMO"},
            "issuetype": {"name": "Task"},
            "summary": "Garden handbook",
            "description": {"version": 1, "type": "doc", "content": [INTRO, _table(), PLANTING]},
        },
        "properties": [
            {"key": "skaldr.stamp", "value": _stamp_value(STAMP)},
            {
                "key": "skaldr.layout",
                "value": _layout_value({"intro": [INTRO, _table()], "planting": [PLANTING]}),
            },
        ],
    }


@pytest.mark.parametrize(
    ("honours_properties", "method", "path", "refusal", "cause"),
    [
        pytest.param(
            True,
            "GET",
            "/rest/api/3/issue/DEMO-1/changelog",
            Reply(403, {"errorMessages": ["Forbidden"]}),
            "Jira refused GET /rest/api/3/issue/DEMO-1/changelog (HTTP 403): Forbidden",
            id="read-refused",
        ),
        pytest.param(
            False,
            "PUT",
            "/rest/api/3/issue/DEMO-1/properties/skaldr.layout",
            Reply(400, {"errorMessages": ["Bad property"]}),
            "Jira refused PUT /rest/api/3/issue/DEMO-1/properties/skaldr.layout (HTTP 400): Bad property",
            id="property-refused",
        ),
    ],
)
def test_a_failure_after_the_issue_is_created_names_the_created_issue(
    honours_properties: bool, method: str, path: str, refusal: Reply, cause: str
) -> None:
    jira = FakeJira(honours_properties_on_create=honours_properties)
    jira.answer_next(method, path, refusal)

    with pytest.raises(ConnectorError) as raised:
        _transport(jira).create_item(NewItem(TARGET, STAMP, CONTENT))

    assert (type(raised.value), str(raised.value), list(jira.issues)) == (
        ConnectorError,
        f"created DEMO-1 but could not read it back: {cause}",
        ["DEMO-1"],
    )


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


def test_a_missing_issue_reads_as_not_found_once_the_sign_in_is_confirmed() -> None:
    jira = FakeJira()

    with pytest.raises(
        ItemNotFoundError,
        match=_exactly(
            "Jira has no issue DEMO-9 that this account can see (HTTP 404 to GET "
            "/rest/api/3/issue/DEMO-9/changelog)"
        ),
    ):
        _transport(jira).read_item("DEMO-9", CONTENT)
    assert jira.calls() == [("GET", "/rest/api/3/issue/DEMO-9/changelog"), ("GET", "/rest/api/3/myself")]


def test_a_not_found_answered_to_a_sign_in_jira_no_longer_accepts_is_not_a_missing_issue() -> None:
    jira = FakeJira()
    jira.answer_next("GET", "/rest/api/3/issue/DEMO-1/changelog", Reply(404, NOT_FOUND))
    jira.answer_next("GET", "/rest/api/3/myself", Reply(401, {"errorMessages": ["Unauthorized"]}))

    with pytest.raises(ConnectorError) as raised:
        _transport(jira).read_item("DEMO-1", CONTENT)

    assert (type(raised.value), str(raised.value)) == (
        ConnectorError,
        f"Jira at {SITE} rejected the sign-in (HTTP 401); the API token may have expired or been revoked, "
        "so run `skaldr auth jira`",
    )


def test_a_description_without_a_layout_reads_as_one_section() -> None:
    jira = FakeJira()
    jira.seed("DEMO-3", summary="Notes", description={"version": 1, "type": "doc", "content": [INTRO]})

    read = _transport(jira).read_item("DEMO-3", ItemContent(title=""))

    assert (read.comparable, read.stamp) == (
        ItemContent(title="Notes", sections={"(description)": section_text([INTRO])}),
        None,
    )


def test_a_content_write_replaces_the_description_and_layout_in_one_request() -> None:
    jira = FakeJira()
    transport, created = _created(jira)
    sections = {"planting": section_text([SOW_IN_MAY]), "tools": section_text([_words("Spade.")])}

    written = transport.write_content(created.item_id, ContentWrite(sections, created.raw_sections, STAMP))

    assert (jira.calls(), summarise(jira.requests[4])["body"], written.comparable.sections) == (
        [
            *_read_calls("DEMO-1"),
            ("PUT", "/rest/api/3/issue/DEMO-1"),
            *_read_calls("DEMO-1"),
            ("GET", "/rest/api/3/myself"),
        ],
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


def test_when_jira_drops_the_properties_of_an_edit_skaldr_puts_the_layout_without_reading_again() -> None:
    jira = FakeJira(honours_properties_on_edit=False)
    transport, created = _created(jira)
    sections = {"planting": section_text([SOW_IN_MAY])}

    written = transport.write_content(created.item_id, ContentWrite(sections, created.raw_sections, STAMP))

    assert (list(written.raw_sections), jira.calls()[5:]) == (
        ["planting"],
        [
            *_read_calls("DEMO-1"),
            ("PUT", "/rest/api/3/issue/DEMO-1/properties/skaldr.layout"),
            ("GET", "/rest/api/3/myself"),
        ],
    )


def test_a_content_write_against_a_description_edited_since_the_read_is_refused_unsent() -> None:
    jira = FakeJira()
    transport, created = _created(jira)
    jira.edit_by_hand(created.item_id, description={"version": 1, "type": "doc", "content": [PLANTING]})

    with pytest.raises(WriteRejectedError, match=_exactly(CHANGED_SINCE_READ)):
        transport.write_content(
            created.item_id, ContentWrite({"planting": "[]"}, created.raw_sections, STAMP)
        )
    assert jira.calls() == [("GET", "/rest/api/3/issue/DEMO-1/changelog")]


def test_a_block_rewritten_by_hand_inside_a_section_is_refused_unsent() -> None:
    jira = FakeJira()
    transport, created = _created(jira)
    jira.edit_by_hand(
        created.item_id, description=_description(_words("Welcome, gardeners."), _table(), PLANTING)
    )

    with pytest.raises(WriteRejectedError, match=_exactly(CHANGED_SINCE_READ)):
        transport.write_content(
            created.item_id, ContentWrite(dict(created.raw_sections), created.raw_sections, STAMP)
        )
    assert (jira.calls(), list(transport.read_item(created.item_id, CONTENT).raw_sections)) == (
        [("GET", "/rest/api/3/issue/DEMO-1/changelog")],
        ["intro", "planting"],
    )


def test_a_write_quoting_section_text_jira_does_not_hold_under_the_same_keys_is_refused_unsent() -> None:
    jira = FakeJira()
    transport, created = _created(jira)
    stale = {**created.raw_sections, "intro": section_text([_words("Welcome, gardeners.")])}

    with pytest.raises(WriteRejectedError, match=_exactly(CHANGED_SINCE_READ)):
        transport.write_content(created.item_id, ContentWrite(dict(created.raw_sections), stale, STAMP))
    assert jira.calls() == _read_calls("DEMO-1")


def test_an_empty_content_write_clears_the_description() -> None:
    jira = FakeJira()
    transport, created = _created(jira)

    written = transport.write_content(created.item_id, ContentWrite({}, created.raw_sections, STAMP))

    assert (jira.issues["DEMO-1"].fields["description"], written.raw_sections) == (None, {})


def test_a_section_write_rewrites_the_whole_description_with_that_section_changed() -> None:
    jira = FakeJira()
    transport, created = _created(jira)
    tools = section_text([_words("Spade.")])

    written = transport.write_section(
        created.item_id, SectionRequest(AddSection("tools", tools, "intro"), created.raw_sections, STAMP)
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
            created.item_id, SectionRequest(RemoveSection("planting", "[]"), created.raw_sections, STAMP)
        )
    assert jira.calls() == _read_calls("DEMO-1")


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

    assert (jira.calls()[:3], summarise(jira.requests[2])["body"]) == (
        [
            ("GET", "/rest/api/3/issue/DEMO-1/properties/skaldr.stamp"),
            ("GET", "/rest/api/3/issue/DEMO-1/changelog"),
            ("PUT", "/rest/api/3/issue/DEMO-1"),
        ],
        {"fields": sent},
    )


def test_a_fields_write_with_nothing_changed_sends_nothing_and_reads_back() -> None:
    jira = FakeJira()
    transport, created = _created(jira)

    read = transport.write_fields(created.item_id, _fields_write({**FIELDS_WRITTEN, "labels": ["garden"]}))

    assert (jira.calls(), read.comparable) == (
        [
            ("GET", "/rest/api/3/issue/DEMO-1/properties/skaldr.stamp"),
            ("GET", "/rest/api/3/issue/DEMO-1/changelog"),
            *_read_calls("DEMO-1"),
        ],
        CONTENT_AS_COMPARED,
    )


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
            ("GET", "/rest/api/3/issue/DEMO-1/comment"),
            ("POST", "/rest/api/3/issue/DEMO-1/comment"),
            ("PUT", "/rest/api/3/issue/DEMO-1/properties/skaldr.stamp"),
            ("POST", "/rest/api/3/issue/DEMO-1/transitions"),
            ("PUT", "/rest/api/3/issue/DEMO-1/properties/skaldr.stamp"),
        ],
        DONE,
        [{"version": 1, "type": "doc", "content": [_words(why)]}],
        _stamp_value(STAMP, commented=True, archived=True),
    )


def _archive_comment_body(document: str) -> JsonValue:
    why = f"skaldr archived this issue: {document} no longer has the content it held."
    return {"version": 1, "type": "doc", "content": [_words(why)]}


def test_an_archive_retried_after_its_stamp_was_not_saved_finds_its_comment_and_does_not_post_another() -> (
    None
):
    jira = FakeJira()
    transport, created = _created(jira)
    jira.answer_next(
        "PUT",
        "/rest/api/3/issue/DEMO-1/properties/skaldr.stamp",
        Reply(400, {"errorMessages": ["Bad value"]}),
    )

    with pytest.raises(
        WriteRejectedError,
        match=_exactly(
            "Jira refused PUT /rest/api/3/issue/DEMO-1/properties/skaldr.stamp (HTTP 400): Bad value"
        ),
    ):
        transport.archive_item(created.item_id)
    transport.archive_item(created.item_id)

    issue = jira.issues["DEMO-1"]
    assert (issue.comments, issue.fields["status"], issue.properties["skaldr.stamp"]) == (
        [_archive_comment_body("the document garden-handbook")],
        DONE,
        _stamp_value(STAMP, commented=True, archived=True),
    )


def test_an_archive_comment_jira_saved_with_attributes_of_its_own_still_counts_as_skaldrs() -> None:
    jira = FakeJira()
    transport, created = _created(jira)
    saved: JsonValue = {
        "version": 1,
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "attrs": {"localId": "jira-0042"},
                "content": [
                    {
                        "type": "text",
                        "text": "skaldr archived this issue: the document garden-handbook no longer has the "
                        "content it held.",
                    }
                ],
            }
        ],
    }
    jira.issues["DEMO-1"].comments.append(saved)

    transport.archive_item(created.item_id)

    issue = jira.issues["DEMO-1"]
    assert (issue.comments, issue.fields["status"]) == ([saved], DONE)


def test_archiving_an_issue_without_a_stamp_comments_without_a_doc_id_and_stamps_it_archived() -> None:
    jira = FakeJira()
    jira.seed("DEMO-3", summary="Notes")

    _transport(jira).archive_item("DEMO-3")

    issue = jira.issues["DEMO-3"]
    assert (issue.comments, issue.fields["status"], issue.properties) == (
        [_archive_comment_body("the document")],
        DONE,
        {
            "skaldr.stamp": {
                "doc_id": None,
                "section_id": None,
                "commented": True,
                "archived": True,
                "linked": False,
            }
        },
    )


UNREADABLE_STAMP = (
    "the skaldr.stamp property of DEMO-3 is not one skaldr can read, so skaldr cannot tell which document "
    "the issue belongs to or whether it archived the issue"
)


@pytest.mark.parametrize(
    "stamp", [pytest.param("junk", id="not-an-object"), pytest.param({"doc_id": ["x"]}, id="foreign-shape")]
)
def test_an_unreadable_stamp_stops_a_read_and_an_archive(stamp: JsonValue) -> None:
    jira = FakeJira()
    jira.seed("DEMO-3", summary="Notes").properties["skaldr.stamp"] = stamp
    transport = _transport(jira)

    with pytest.raises(ConnectorError, match=_exactly(UNREADABLE_STAMP)):
        transport.read_item("DEMO-3", ItemContent(title=""))
    with pytest.raises(ConnectorError, match=_exactly(UNREADABLE_STAMP)):
        transport.archive_item("DEMO-3")
    assert jira.issues["DEMO-3"].comments == []


def test_an_unreadable_layout_reads_the_description_as_one_section() -> None:
    jira = FakeJira()
    issue = jira.seed("DEMO-3", summary="Notes", description=_description(INTRO, PLANTING))
    issue.properties["skaldr.layout"] = "junk"

    read = _transport(jira).read_item("DEMO-3", ItemContent(title=""))

    assert (read.comparable, read.raw_sections) == (
        ItemContent(title="Notes", sections={"(description)": section_text([INTRO, PLANTING])}),
        {"(description)": section_text([INTRO, PLANTING])},
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

    assert ([call for call in jira.calls() if call[0] != "GET"], jira.issues["DEMO-1"].comments) == (
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

    assert _transition_bodies(jira) == [{"transition": {"id": "31"}}]


@pytest.mark.parametrize(
    ("refusals", "message"),
    [
        pytest.param(
            [Reply(500, {"errorMessages": ["Boom"]})],
            "Jira answered HTTP 500 to POST /rest/api/3/issue/DEMO-1/transitions: Boom",
            id="server-error",
        ),
        pytest.param(
            [Reply(400, {"errorMessages": ["Resolution is required."]})] * 2,
            "Jira refused POST /rest/api/3/issue/DEMO-1/transitions (HTTP 400): Resolution is required.",
            id="workflow-validator-twice",
        ),
    ],
)
def test_a_transition_that_fails_after_the_comment_never_gets_the_comment_posted_twice(
    refusals: list[Reply], message: str
) -> None:
    jira = FakeJira()
    transport, created = _created(jira)
    raised: list[str] = []

    for refusal in refusals:
        jira.answer_next("POST", "/rest/api/3/issue/DEMO-1/transitions", refusal)
        with pytest.raises(ConnectorError) as failed:
            transport.archive_item(created.item_id)
        raised.append(str(failed.value))
    transport.archive_item(created.item_id)

    issue = jira.issues["DEMO-1"]
    assert (raised, len(issue.comments), issue.fields["status"], issue.properties["skaldr.stamp"]) == (
        [message] * len(refusals),
        1,
        DONE,
        _stamp_value(STAMP, commented=True, archived=True),
    )


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
    ("edits", "parts"),
    [
        pytest.param({"summary": "Garden guide"}, (TITLE,), id="summary"),
        pytest.param({"priority": {"name": "Low"}}, (FIELDS,), id="owned-field"),
        pytest.param({"labels": ["shed", DOC_LABEL]}, (FIELDS,), id="owned-labels"),
        pytest.param(
            {"status": IN_PROGRESS, "resolution": {"name": "Done"}}, (), id="fields-skaldr-never-set"
        ),
        pytest.param({"summary": "Garden guide", "priority": {"name": "Low"}}, (TITLE, FIELDS), id="both"),
    ],
)
def test_a_changelog_entry_after_the_marker_reports_the_part_it_changed(
    edits: dict[str, JsonValue], parts: tuple[object, ...]
) -> None:
    jira = FakeJira()
    transport, created = _created(jira)
    jira.edit_by_hand(created.item_id, **edits)

    assert transport.parts_edited_after(created.item_id, created.marker, CONTENT) == parts


def test_a_title_and_field_edit_made_in_jira_and_then_reverted_is_not_an_edit() -> None:
    jira = FakeJira()
    transport, created = _created(jira)
    jira.edit_by_hand(created.item_id, summary="Garden guide", priority={"name": "Low"})
    jira.edit_by_hand(created.item_id, summary="Garden handbook", priority={"name": "High"})

    assert transport.parts_edited_after(created.item_id, created.marker, CONTENT) == ()


def test_an_entry_naming_the_summary_and_a_field_without_changing_them_is_not_an_edit() -> None:
    jira = FakeJira()
    transport, created = _created(jira)
    jira.log_by_hand(created.item_id, "summary", "priority", "labels")

    assert transport.parts_edited_after(created.item_id, created.marker, CONTENT) == ()


def test_skaldrs_own_write_after_the_marker_is_not_an_edit_once_the_issue_holds_what_it_wrote() -> None:
    jira = FakeJira()
    transport, created = _created(jira)
    retitled = CONTENT.model_copy(update={"title": "Garden guide", "fields": {"priority": {"name": "Low"}}})
    transport.write_fields(
        created.item_id, FieldsWrite("Garden guide", retitled.fields, CONTENT.title, FIELDS_WRITTEN, STAMP)
    )

    assert transport.parts_edited_after(created.item_id, created.marker, retitled) == ()


def test_labels_skaldr_does_not_own_are_not_an_edit() -> None:
    jira = FakeJira()
    content = CONTENT.model_copy(update={"fields": {"priority": {"name": "High"}}})
    transport, created = _created(jira, content)
    jira.edit_by_hand(created.item_id, labels=["triaged", DOC_LABEL])

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
    jira.edit_by_hand(created.item_id, summary="Garden guide")

    assert transport.parts_edited_after(created.item_id, None, CONTENT) == (TITLE,)


@pytest.mark.parametrize(
    "marker", ["²", "next", "-3", ""], ids=["superscript-digit", "word", "signed", "empty"]
)
def test_a_marker_that_is_not_ascii_digits_reads_as_no_marker(marker: str) -> None:
    jira = FakeJira()
    transport, created = _created(jira)
    jira.edit_by_hand(created.item_id, summary="Garden guide")

    assert transport.parts_edited_after(created.item_id, marker, CONTENT) == (TITLE,)


@pytest.mark.parametrize(
    ("author", "dated", "described"),
    [
        pytest.param(None, True, "an unknown author at 2026-10-01T10:00:00.000+0000", id="no-author"),
        pytest.param(
            {"accountId": "account-editor", "displayName": ""},
            True,
            "an unknown author at 2026-10-01T10:00:00.000+0000",
            id="blank-display-name",
        ),
        pytest.param(EDITOR, False, "Robin Editor at an unknown time", id="no-created-time"),
    ],
)
def test_a_replaced_edit_without_an_author_or_a_time_is_named_as_unknown(
    author: dict[str, JsonValue] | None, dated: bool, described: str
) -> None:
    jira = FakeJira()
    transport, created = _created(jira)
    jira.edit_right_before_the_next_write(created.item_id, author, dated=dated, summary="Garden notes")

    with pytest.raises(ConnectorError) as raised:
        transport.write_fields(created.item_id, _fields_write(FIELDS_WRITTEN, "Garden guide"))

    assert str(raised.value) == (
        f"DEMO-1: skaldr's write replaced an edit made in Jira just before it (summary in changelog 10001 by "
        f"{described}); restore it from the issue's history if it should stay"
    )


def test_a_read_names_no_editor_for_an_edit_jira_logged_without_an_author() -> None:
    jira = FakeJira()
    transport, created = _created(jira)
    jira.edit_right_after_the_next_write(created.item_id, None, dated=False, summary="Garden notes")
    with pytest.raises(ConnectorError):
        transport.write_fields(
            created.item_id, _fields_write({**FIELDS_WRITTEN, "priority": {"name": "Low"}})
        )

    read = transport.read_item(created.item_id, CONTENT)

    assert (read.edited_by, read.edited_at, read.comparable.title) == (None, None, "Garden notes")


@pytest.mark.parametrize(
    ("labels", "read_as"),
    [
        pytest.param("garden", ["garden"], id="bare-string"),
        pytest.param("", [], id="blank-string"),
        pytest.param(
            ["garden", 5, None, {"name": "x"}, DOC_LABEL], ["garden"], id="members-that-are-not-strings"
        ),
    ],
)
def test_labels_jira_returns_in_an_unexpected_shape_read_as_their_string_members(
    labels: JsonValue, read_as: list[str]
) -> None:
    jira = FakeJira()
    jira.seed("DEMO-3", summary="Notes", labels=labels).properties["skaldr.stamp"] = _stamp_value(STAMP)

    read = _transport(jira).read_item("DEMO-3", ItemContent(title="", fields={"labels": None}))

    assert read.comparable.fields == {"labels": read_as}


@pytest.mark.parametrize("status", [pytest.param(None, id="absent"), pytest.param({}, id="empty")])
def test_an_issue_whose_status_jira_does_not_name_cannot_be_archived(status: JsonValue) -> None:
    jira = FakeJira()
    issue = jira.seed("DEMO-3", summary="Notes")
    if status is None:
        del issue.fields["status"]
    else:
        issue.fields["status"] = status

    with pytest.raises(ConnectorError, match=_exactly("Jira did not say which status DEMO-3 is in")):
        _transport(jira).archive_item("DEMO-3")
    assert (issue.comments, issue.properties) == ([], {})


def test_two_writes_on_one_transport_ask_jira_who_is_signed_in_once() -> None:
    jira = FakeJira()
    transport, created = _created(jira)

    transport.write_fields(created.item_id, _fields_write(FIELDS_WRITTEN, "Garden guide"))
    transport.write_content(
        created.item_id, ContentWrite({"planting": section_text([SOW_IN_MAY])}, RAW_AFTER_CREATE, STAMP)
    )

    assert [call for call in jira.calls() if call == ("GET", "/rest/api/3/myself")] == [
        ("GET", "/rest/api/3/myself")
    ]


def _missing(path: str) -> str:
    return f"Jira has no issue DEMO-1 that this account can see (HTTP 404 to GET {path})"


def _write_the_same_content(transport: JiraTransport, created: RemoteItem) -> object:
    return transport.write_content(
        created.item_id, ContentWrite(dict(created.raw_sections), created.raw_sections, STAMP)
    )


def _retitle(transport: JiraTransport, created: RemoteItem) -> object:
    return transport.write_fields(created.item_id, _fields_write(FIELDS_WRITTEN, "Garden guide"))


def _archive(transport: JiraTransport, created: RemoteItem) -> object:
    transport.archive_item(created.item_id)
    return None


@pytest.mark.parametrize(
    ("write", "message"),
    [
        pytest.param(_write_the_same_content, _missing("/rest/api/3/issue/DEMO-1/changelog"), id="content"),
        pytest.param(_retitle, _missing("/rest/api/3/issue/DEMO-1/changelog"), id="fields"),
        pytest.param(_archive, _missing("/rest/api/3/issue/DEMO-1"), id="archive"),
    ],
)
def test_a_write_to_an_issue_deleted_after_the_read_is_item_not_found(
    write: Callable[[JiraTransport, RemoteItem], object], message: str
) -> None:
    jira = FakeJira()
    transport, created = _created(jira)
    transport.read_item(created.item_id, CONTENT)
    jira.delete_by_hand(created.item_id)

    with pytest.raises(ItemNotFoundError, match=_exactly(message)):
        write(transport, created)
    assert [call for call in jira.calls() if call[0] != "GET"] == []


def test_a_doc_id_that_starts_with_skaldr_still_gets_the_prefix_so_no_two_documents_share_a_label() -> None:
    jira = FakeJira()
    stamp = Stamp("skaldr-plan", None)
    content = CONTENT.model_copy(update={"fields": {"labels": ["skaldr-plan"]}})
    transport = _transport(jira)

    created = transport.create_item(NewItem(TARGET, stamp, content))

    assert (jira.issues["DEMO-1"].fields["labels"], created.comparable.fields) == (
        ["skaldr-plan", "skaldr-skaldr-plan"],
        {"labels": ["skaldr-plan"]},
    )


def test_archiving_through_a_close_that_sets_a_resolution_leaves_the_resolution_jira_chose() -> None:
    jira = FakeJira()
    transport, created = _created(jira)

    transport.archive_item(created.item_id)

    issue = jira.issues["DEMO-1"]
    assert (issue.fields["status"], issue.fields["resolution"], _transition_bodies(jira)) == (
        DONE,
        DONE_RESOLUTION,
        [{"transition": {"id": "31"}}],
    )


def test_a_close_whose_screen_requires_a_resolution_stops_the_archive_and_never_comments_twice() -> None:
    jira = FakeJira(close_screen_requires_resolution=True)
    transport, created = _created(jira)
    refusal = (
        "Jira refused POST /rest/api/3/issue/DEMO-1/transitions (HTTP 400): resolution: Resolution is "
        "required."
    )

    for _ in range(2):
        with pytest.raises(WriteRejectedError, match=_exactly(refusal)):
            transport.archive_item(created.item_id)

    issue = jira.issues["DEMO-1"]
    assert (issue.comments, issue.fields["status"], issue.properties["skaldr.stamp"]) == (
        [_archive_comment_body("the document garden-handbook")],
        {"name": "To Do", "statusCategory": {"key": "new"}},
        _stamp_value(STAMP, commented=True),
    )


SPADE_ROW: JsonValue = {
    "type": "tableRow",
    "content": [
        {"type": "tableHeader", "content": [_words("Tool")]},
        {"type": "tableCell", "content": [_words("Spade.")]},
    ],
}
SAVED_SPADE_ROW: JsonValue = {
    "type": "tableRow",
    "content": [
        {"type": "tableHeader", "attrs": {"colspan": 1, "rowspan": 1}, "content": [_words("Tool")]},
        {"type": "tableCell", "attrs": {"colspan": 1, "rowspan": 1}, "content": [_words("Spade.")]},
    ],
}
DIG: JsonValue = {"type": "listItem", "content": [_words("Dig.")]}


@pytest.mark.parametrize(
    ("sent", "saved"),
    [
        pytest.param(
            {"type": "table", "attrs": {}, "content": [SPADE_ROW]},
            {
                "type": "table",
                "attrs": {
                    "isNumberColumnEnabled": False,
                    "layout": "center",
                    "displayMode": "default",
                    "localId": "jira-0001",
                },
                "content": [SAVED_SPADE_ROW],
            },
            id="table-and-cells",
        ),
        pytest.param(
            {"type": "orderedList", "content": [DIG]},
            {"type": "orderedList", "attrs": {"order": 1}, "content": [DIG]},
            id="ordered-list",
        ),
        pytest.param(
            {
                "type": "paragraph",
                "content": [{"type": "mention", "attrs": {"id": GARDENER, "text": "@Robin"}}],
            },
            {
                "type": "paragraph",
                "content": [
                    {
                        "type": "mention",
                        "attrs": {"accessLevel": "", "userType": "DEFAULT", "id": GARDENER, "text": "@Robin"},
                    }
                ],
            },
            id="mention",
        ),
    ],
)
def test_the_attributes_jira_fills_in_when_it_saves_a_block_are_not_an_edit(
    sent: JsonValue, saved: JsonValue
) -> None:
    jira = FakeJira(fills_in_saved_defaults=True)
    content = CONTENT.model_copy(update={"sections": {"planting": section_text([sent])}})
    transport, created = _created(jira, content)

    read = transport.read_item(created.item_id, content)

    assert (jira.issues["DEMO-1"].fields["description"], read.comparable) == (
        _description(saved),
        transport.comparable_form(content),
    )


def test_closing_the_transport_closes_its_client() -> None:
    jira = FakeJira()

    _transport(jira).close()

    assert jira.closes == 1


def test_the_comparable_form_normalises_each_section_and_drops_empty_ones() -> None:
    content = ItemContent(
        title="Garden handbook",
        sections={"intro": section_text([INTRO, _table("skaldr-1")]), "header": ""},
        fields=FIELDS_WRITTEN,
    )

    assert _transport(FakeJira()).comparable_form(content) == ItemContent(
        title="Garden handbook",
        sections={"intro": section_text([INTRO, TABLE_AS_COMPARED])},
        fields=FIELDS_WRITTEN,
    )


HANDBOOK_PAGE_ID = "0123456789abcdef0123456789abcdef"
ROTA_PAGE_ID = "fedcba9876543210fedcba9876543210"


def _page_link(page_id: str, title: str) -> ShownLink:
    return ShownLink(service="notion", item_id=page_id, url=f"https://www.notion.so/{page_id}", title=title)


HANDBOOK_PAGE = _page_link(HANDBOOK_PAGE_ID, "Garden handbook")
ROTA_PAGE = _page_link(ROTA_PAGE_ID, "Kitchen rota")


def _remote_link(global_id: str | None, link: ShownLink, link_id: int) -> dict[str, JsonValue]:
    return {"id": link_id, "globalId": global_id, "object": {"url": link.url, "title": link.title}}


@pytest.mark.parametrize(
    ("stamp", "global_id"),
    [
        pytest.param(STAMP, f"skaldr:garden-handbook:document:notion:{HANDBOOK_PAGE_ID}", id="document"),
        pytest.param(
            SECTION_STAMP, f"skaldr:garden-handbook:section:planting:notion:{HANDBOOK_PAGE_ID}", id="section"
        ),
    ],
)
def test_a_link_is_a_remote_link_whose_global_id_names_the_document_the_item_and_the_page(
    stamp: Stamp, global_id: str
) -> None:
    jira = FakeJira()
    transport = _transport(jira)
    created = transport.create_item(NewItem(TARGET, stamp, CONTENT))
    jira.forget_requests()

    written = transport.write_links(created.item_id, LinksWrite(stamp, (HANDBOOK_PAGE,)))

    assert (written, [summarise(request) for request in jira.requests]) == (
        (HANDBOOK_PAGE,),
        [
            summarised_request("GET", "/rest/api/3/issue/DEMO-1/properties/skaldr.stamp"),
            summarised_request(
                "PUT", "/rest/api/3/issue/DEMO-1/properties/skaldr.stamp", _stamp_value(stamp, linked=True)
            ),
            summarised_request(
                "POST",
                "/rest/api/3/issue/DEMO-1/remotelink",
                {
                    "globalId": global_id,
                    "object": {
                        "url": "https://www.notion.so/0123456789abcdef0123456789abcdef",
                        "title": "Garden handbook",
                    },
                },
            ),
        ],
    )


def test_a_retitled_page_updates_its_link_in_place_and_a_page_no_longer_paired_loses_its_link() -> None:
    jira = FakeJira()
    transport, created = _created(jira)
    transport.write_links(created.item_id, LinksWrite(STAMP, (HANDBOOK_PAGE, ROTA_PAGE)))
    retitled = HANDBOOK_PAGE.model_copy(update={"title": "Garden guide"})
    jira.forget_requests()

    transport.write_links(created.item_id, LinksWrite(STAMP, (retitled,), (HANDBOOK_PAGE, ROTA_PAGE)))

    assert (jira.issues["DEMO-1"].remote_links, jira.calls()) == (
        [_remote_link(f"skaldr:garden-handbook:document:notion:{HANDBOOK_PAGE_ID}", retitled, 10_001)],
        [
            ("GET", "/rest/api/3/issue/DEMO-1/properties/skaldr.stamp"),
            ("DELETE", "/rest/api/3/issue/DEMO-1/remotelink"),
            ("POST", "/rest/api/3/issue/DEMO-1/remotelink"),
        ],
    )


def test_a_links_write_that_changes_nothing_sends_nothing() -> None:
    jira = FakeJira()
    transport, created = _created(jira)
    transport.write_links(created.item_id, LinksWrite(STAMP, (HANDBOOK_PAGE,)))
    jira.forget_requests()

    written = transport.write_links(created.item_id, LinksWrite(STAMP, (HANDBOOK_PAGE,), (HANDBOOK_PAGE,)))

    assert (written, jira.calls()) == (
        (HANDBOOK_PAGE,),
        [("GET", "/rest/api/3/issue/DEMO-1/properties/skaldr.stamp")],
    )


def test_remote_links_skaldr_did_not_write_for_this_item_are_neither_read_nor_removed() -> None:
    jira = FakeJira()
    transport, created = _created(jira)
    global_ids = [
        None,
        f"skaldr:kitchen-rota:document:notion:{ROTA_PAGE_ID}",
        f"skaldr:garden-handbook:section:tools:notion:{ROTA_PAGE_ID}",
        f"skaldr:garden-handbook:document:slack:{ROTA_PAGE_ID}",
        "skaldr:garden-handbook:document:notion:",
        "skaldr:garden-handbook:document:notion",
    ]
    for global_id in global_ids:
        jira.link_by_hand("DEMO-1", global_id, ROTA_PAGE.url, ROTA_PAGE.title)

    read = transport.read_links(created.item_id, STAMP)
    transport.write_links(created.item_id, LinksWrite(STAMP, (), read))

    assert (read, jira.issues["DEMO-1"].remote_links, [call[0] for call in jira.calls()]) == (
        (),
        [_remote_link(global_id, ROTA_PAGE, 10_001 + index) for index, global_id in enumerate(global_ids)],
        ["GET", "GET"],
    )


def test_a_web_link_someone_adds_in_jira_is_logged_without_a_field_id_and_is_not_an_edit() -> None:
    jira = FakeJira()
    transport, created = _created(jira)

    jira.link_by_hand("DEMO-1", None, ROTA_PAGE.url, ROTA_PAGE.title)

    assert (
        jira.histories["DEMO-1"][-1]["items"],
        transport.parts_edited_after(created.item_id, created.marker, CONTENT),
    ) == ([{"field": "RemoteWorkItemLink", "fieldtype": "jira", "toString": "Kitchen rota"}], ())


def test_a_global_id_of_exactly_the_length_jira_takes_is_sent() -> None:
    jira = FakeJira()
    transport = _transport(jira)
    stamp = Stamp(LONGEST_LINKABLE_DOC_ID, None)
    created = transport.create_item(NewItem(TARGET, stamp, CONTENT))

    transport.write_links(created.item_id, LinksWrite(stamp, (HANDBOOK_PAGE,)))

    assert [link["globalId"] for link in jira.issues["DEMO-1"].remote_links] == [
        f"skaldr:{LONGEST_LINKABLE_DOC_ID}:document:notion:{HANDBOOK_PAGE_ID}"
    ]


def test_a_global_id_longer_than_jira_takes_is_refused_before_anything_is_sent() -> None:
    jira = FakeJira()
    transport = _transport(jira)
    stamp = Stamp(f"{LONGEST_LINKABLE_DOC_ID}a", None)
    created = transport.create_item(NewItem(TARGET, stamp, CONTENT))
    jira.forget_requests()
    expected = (
        "DEMO-1: the remote link to the paired Notion item needs a globalId of 256 characters, over the 255 "
        "Jira takes; shorten the document's doc_id or the section's id"
    )

    with pytest.raises(WriteRejectedError, match=_exactly(expected)):
        transport.write_links(created.item_id, LinksWrite(stamp, (HANDBOOK_PAGE,)))
    assert [call for call in jira.calls() if call[0] != "GET"] == []


def test_a_links_write_to_an_issue_of_another_document_is_refused_naming_the_stamp() -> None:
    jira = FakeJira()
    transport, created = _created(jira)

    with pytest.raises(
        WriteRejectedError, match=_exactly("Jira issue DEMO-1 is not stamped with doc_id 'kitchen-rota'")
    ):
        transport.write_links(created.item_id, LinksWrite(Stamp("kitchen-rota", None), (HANDBOOK_PAGE,)))
    assert jira.issues["DEMO-1"].remote_links == []


def test_removing_the_last_link_clears_the_mark_so_archiving_reads_no_remote_links() -> None:
    jira = FakeJira()
    transport, created = _created(jira)
    transport.write_links(created.item_id, LinksWrite(STAMP, (HANDBOOK_PAGE,)))
    transport.write_links(created.item_id, LinksWrite(STAMP, (), (HANDBOOK_PAGE,)))
    marked = jira.issues["DEMO-1"].properties["skaldr.stamp"]
    jira.forget_requests()

    transport.archive_item(created.item_id)

    assert (marked, [call for call in jira.calls() if call[1].endswith("/remotelink")]) == (
        _stamp_value(STAMP),
        [],
    )


def test_a_remote_link_already_gone_when_archiving_deletes_it_does_not_stop_the_archive() -> None:
    jira = FakeJira()
    transport, created = _created(jira)
    transport.write_links(created.item_id, LinksWrite(STAMP, (HANDBOOK_PAGE,)))
    jira.answer_next(
        "DELETE",
        "/rest/api/3/issue/DEMO-1/remotelink",
        Reply(404, {"errorMessages": ["No remote link with that globalId."]}),
    )

    transport.archive_item(created.item_id)

    issue = jira.issues["DEMO-1"]
    assert (issue.fields["status"], issue.properties["skaldr.stamp"]) == (
        DONE,
        _stamp_value(STAMP, commented=True, archived=True, linked=True),
    )


def test_archiving_removes_the_links_skaldr_wrote_for_the_item_and_keeps_the_others() -> None:
    jira = FakeJira()
    transport, created = _created(jira)
    transport.write_links(created.item_id, LinksWrite(STAMP, (HANDBOOK_PAGE, ROTA_PAGE)))
    jira.link_by_hand("DEMO-1", None, ROTA_PAGE.url, ROTA_PAGE.title)

    transport.archive_item(created.item_id)

    assert (jira.issues["DEMO-1"].remote_links, jira.issues["DEMO-1"].fields["status"]) == (
        [_remote_link(None, ROTA_PAGE, 10_003)],
        DONE,
    )
