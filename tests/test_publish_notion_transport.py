import json
import re
from typing import Any

import pytest

from skaldr.errors import ConnectorError, ItemNotFoundError, WriteRejectedError
from skaldr.publish.content import ItemContent, section_part
from skaldr.publish.notion.transport import NotionTransport
from skaldr.publish.transport import (
    AddSection,
    FieldsWrite,
    NewItem,
    Release,
    RemoteItem,
    ReplaceSection,
    SectionRequest,
    Stamp,
)
from skaldr.publish_block import NotionTarget
from tests.factories import NOTION_PAGE_ID, make_notion_target
from tests.factories.notion_factory import (
    BOT_ID,
    PERSON_ID,
    InMemoryNotion,
    Scripted,
    dashed,
    numbered_id,
)

PARENT_PAGE_ID = "fedcba9876543210fedcba9876543210"
STAMP = Stamp("garden-handbook", None)
STAMP_LINE = 'Published with skaldr from document garden-handbook {color="gray"}'
WELCOME = "## Welcome\nWelcome to the garden.\n"
PLANTING = "## Planting\nSow in spring.\n"
CONTENT = ItemContent(title="Garden handbook", sections={"intro": WELCOME, "planting": PLANTING})
DATABASE_TARGET = NotionTarget.model_validate(make_notion_target())
PAGE_TARGET = NotionTarget.model_validate(make_notion_target(where={"parent_page": PARENT_PAGE_ID}))
FIRST_PAGE = numbered_id(1).replace("-", "")
EMPTY_ROW = numbered_id(900).replace("-", "")


def _notion() -> InMemoryNotion:
    notion = InMemoryNotion()
    notion.add_database(NOTION_PAGE_ID)
    notion.add_page(PARENT_PAGE_ID, "Team plans")
    notion.add_row(EMPTY_ROW, "Blank page", NOTION_PAGE_ID)
    return notion


def _sent(notion: InMemoryNotion) -> list[tuple[str, str, Any]]:
    return [
        (request.method, request.url.path, json.loads(request.content) if request.content else None)
        for request in notion.requests
    ]


def _created(
    notion: InMemoryNotion, content: ItemContent = CONTENT, target: NotionTarget = DATABASE_TARGET
) -> tuple[NotionTransport, RemoteItem]:
    transport = notion.transport()
    created = transport.create_item(NewItem(target, STAMP, content))
    notion.requests.clear()
    return transport, created


def _title(text: str) -> dict[str, Any]:
    return {"title": {"title": [{"type": "text", "text": {"content": text}}]}}


def _text(text: str) -> dict[str, Any]:
    return {"rich_text": [{"type": "text", "text": {"content": text}}]}


def _update(old: str, new: str) -> dict[str, Any]:
    return {
        "type": "update_content",
        "update_content": {"content_updates": [{"old_str": old, "new_str": new}]},
        "allow_async": True,
    }


def test_a_page_under_a_page_is_created_with_its_sections_and_the_stamp_in_one_request() -> None:
    notion = _notion()
    transport = notion.transport()

    created = transport.create_item(NewItem(PAGE_TARGET, STAMP, CONTENT))

    markdown = f"{WELCOME}{PLANTING}{STAMP_LINE}"
    assert (notion.markdown_of(created.item_id), _sent(notion)) == (
        markdown,
        [
            ("GET", f"/v1/blocks/{PARENT_PAGE_ID}", None),
            (
                "POST",
                "/v1/pages",
                {
                    "parent": {"page_id": PARENT_PAGE_ID},
                    "properties": _title("Garden handbook"),
                    "markdown": f"{markdown}\n",
                    "allow_async": True,
                },
            ),
            ("GET", "/v1/async_tasks/task-2", None),
            ("GET", f"/v1/pages/{FIRST_PAGE}/markdown", None),
            ("GET", f"/v1/pages/{FIRST_PAGE}", None),
        ],
    )
    assert created == RemoteItem(
        FIRST_PAGE,
        ItemContent(title="Garden handbook", sections={"intro": WELCOME, "planting": PLANTING}),
        {"intro": WELCOME, "planting": PLANTING},
        STAMP,
        marker="2026-10-09T12:03:00+00:00",
        edited_by=BOT_ID,
        edited_at="2026-10-09T12:03:00+00:00",
    )


def test_a_row_of_a_database_is_created_in_its_data_source_with_the_fields_as_properties() -> None:
    notion = _notion()
    transport = notion.transport()
    content = CONTENT.model_copy(update={"fields": {"Area": "Shed", "Status": None}})

    created = transport.create_item(NewItem(DATABASE_TARGET, STAMP, content))

    assert _sent(notion)[:4] == [
        ("GET", f"/v1/blocks/{NOTION_PAGE_ID}", None),
        ("GET", f"/v1/databases/{NOTION_PAGE_ID}", None),
        ("GET", f"/v1/data_sources/source-{NOTION_PAGE_ID}", None),
        (
            "POST",
            "/v1/pages",
            {
                "parent": {"data_source_id": f"source-{NOTION_PAGE_ID}"},
                "properties": {**_title("Garden handbook"), "Area": _text("Shed")},
                "markdown": f"{WELCOME}{PLANTING}{STAMP_LINE}\n",
                "allow_async": True,
            },
        ),
    ]
    assert (created.comparable.fields, created.set_properties) == (
        {"Area": "Shed", "Owner": "", "Status": None},
        ("Area",),
    )


@pytest.mark.parametrize(
    ("target", "fields", "message"),
    [
        pytest.param(
            PAGE_TARGET,
            {"Area": "Shed"},
            f"the field 'Area' cannot be set on a page created under the Notion page {PARENT_PAGE_ID}: "
            "only a row of a Notion database has properties; clear it for this item with `overrides`, or "
            "publish under a database",
            id="field-on-a-plain-page",
        ),
        pytest.param(
            DATABASE_TARGET,
            {"Season": "Spring"},
            f"Notion database {NOTION_PAGE_ID} has no property 'Season'",
            id="property-the-database-lacks",
        ),
        pytest.param(
            DATABASE_TARGET,
            {"Name": "Other"},
            f"'Name' is the title of Notion database {NOTION_PAGE_ID}; skaldr sets it from the document's "
            "title, not from `fields`",
            id="the-title-property",
        ),
    ],
)
def test_a_field_the_new_page_cannot_hold_is_refused_before_anything_is_written(
    target: NotionTarget, fields: dict[str, Any], message: str
) -> None:
    notion = _notion()
    transport = notion.transport()

    with pytest.raises(WriteRejectedError, match=f"^{re.escape(message)}$"):
        transport.create_item(NewItem(target, STAMP, CONTENT.model_copy(update={"fields": fields})))
    assert notion.writes() == []


def test_a_parent_notion_cannot_find_is_a_rejected_create_because_nothing_was_made() -> None:
    notion = InMemoryNotion()
    transport = notion.transport()

    with pytest.raises(
        WriteRejectedError,
        match=f"^Notion could not read block {NOTION_PAGE_ID}: it has no such object, or this sign-in cannot "
        "see it$",
    ):
        transport.create_item(NewItem(DATABASE_TARGET, STAMP, CONTENT))
    assert notion.writes() == []


def _long_section(title: str, items: int) -> str:
    return f"## {title}\n" + "".join(f"- {title} {number}\n" for number in range(items))


def test_a_page_over_one_create_is_finished_by_appends_before_the_stamp_and_no_section_is_split() -> None:
    notion = _notion()
    transport = notion.transport()
    sections = {key: _long_section(key, 1_999) for key in ("beds", "paths", "sheds")}

    created = transport.create_item(NewItem(PAGE_TARGET, STAMP, ItemContent(title="Big", sections=sections)))

    beds, paths, sheds = sections.values()
    created_with = _sent(notion)[1][2]["markdown"]
    appended = [body for method, _, body in _sent(notion) if method == "PATCH"]
    assert (created_with, appended, notion.markdown_of(created.item_id), list(created.raw_sections)) == (
        f"{beds}{paths}{STAMP_LINE}\n",
        [_update(STAMP_LINE, f"{sheds}{STAMP_LINE}")],
        f"{beds}{paths}{sheds}{STAMP_LINE}",
        ["beds", "paths", "sheds"],
    )


def test_an_append_that_fails_after_the_create_is_not_a_rejected_write_because_the_page_exists() -> None:
    notion = _notion()
    transport = notion.transport()
    sections = {key: _long_section(key, 2_600) for key in ("beds", "paths")}
    refusal = {"object": "error", "status": 400, "code": "validation_error", "message": "too large"}
    notion.scripted = [Scripted(400, refusal, method="PATCH")]

    with pytest.raises(ConnectorError) as caught:
        transport.create_item(NewItem(PAGE_TARGET, STAMP, ItemContent(title="Big", sections=sections)))

    assert (type(caught.value), str(caught.value)) == (
        ConnectorError,
        f'skaldr wrote Notion page {FIRST_PAGE} for "Big" but could not finish writing it: Notion refused to '
        f"change the content of page {FIRST_PAGE}: too large (validation_error)",
    )


def test_a_section_is_replaced_by_one_search_and_replace_that_quotes_its_comment_markers() -> None:
    notion = _notion()
    transport, created = _created(notion)
    notion.comment_on(created.item_id, "Welcome to the garden.")
    notion.comment_on(created.item_id, "Sow in spring.")
    read = transport.read_item(created.item_id, created.comparable)
    notion.requests.clear()

    transport.write_section(
        created.item_id,
        SectionRequest(
            ReplaceSection("planting", read.raw_sections["planting"], "## Planting\nSow in May.\n", "intro"),
            read.raw_sections,
        ),
    )

    commented_planting = '## Planting\n<span discussion-urls="discussion://comment-1">Sow in spring.</span>\n'
    assert (
        [body for method, _, body in _sent(notion) if method == "PATCH"],
        notion.markdown_of(created.item_id),
    ) == (
        [_update(commented_planting, "## Planting\nSow in May.\n")],
        '## Welcome\n<span discussion-urls="discussion://comment-1">Welcome to the garden.</span>\n'
        f"## Planting\nSow in May.\n{STAMP_LINE}",
    )


def test_an_added_section_is_placed_after_the_section_it_follows() -> None:
    notion = _notion()
    transport, created = _created(notion)

    written = transport.write_section(
        created.item_id,
        SectionRequest(AddSection("tools", "## Tools\n- Spade.\n", "intro"), created.raw_sections),
    )

    assert (list(written.raw_sections), notion.markdown_of(created.item_id)) == (
        ["intro", "tools", "planting"],
        f"{WELCOME}## Tools\n- Spade.\n{PLANTING}{STAMP_LINE}",
    )


def test_a_reading_ignores_an_empty_block_below_the_stamp_and_keeps_markers_only_in_the_raw_text() -> None:
    notion = _notion()
    transport, created = _created(notion)
    notion.comment_on(created.item_id, "Sow in spring.")
    notion.click_below_the_last_block(created.item_id)

    read = transport.read_item(created.item_id, created.comparable)

    assert (read.comparable.sections, read.raw_sections["planting"], read.edited_by) == (
        {"intro": WELCOME, "planting": PLANTING},
        '## Planting\n<span discussion-urls="discussion://comment-1">Sow in spring.</span>\n',
        PERSON_ID,
    )


def test_a_page_in_the_trash_is_not_found_and_archiving_it_again_sends_nothing() -> None:
    notion = _notion()
    transport, created = _created(notion)

    transport.archive_item(created.item_id)
    transport.archive_item(created.item_id)

    assert [(method, path, body) for method, path, body in _sent(notion) if method != "GET"] == [
        ("PATCH", f"/v1/pages/{created.item_id}", {"in_trash": True})
    ]
    with pytest.raises(ItemNotFoundError, match=f"^Notion page {created.item_id} is in the trash$"):
        transport.read_item(created.item_id, CONTENT)


def test_archiving_a_page_notion_no_longer_has_sends_nothing() -> None:
    notion = _notion()
    transport = notion.transport()

    transport.archive_item(numbered_id(77))

    assert notion.writes() == []


def test_a_release_removes_skaldrs_sections_and_stamp_in_one_request_and_clears_only_set_owned_fields() -> (
    None
):
    notion = _notion()
    transport, created = _created(
        notion, CONTENT.model_copy(update={"fields": {"Area": "Shed", "Owner": "Rowan"}})
    )
    notion.set_property_by_hand(created.item_id, "Owner", "")
    read = transport.read_item(created.item_id, created.comparable)
    notion.requests.clear()

    transport.release_item(created.item_id, Release(read.raw_sections, ("Area", "Owner")))

    assert (
        [(method, body) for method, _, body in _sent(notion) if method == "PATCH"],
        notion.markdown_of(created.item_id),
    ) == (
        [
            ("PATCH", _update(f"{WELCOME}{PLANTING}{STAMP_LINE}", "")),
            ("PATCH", {"properties": {"Area": {"rich_text": []}}}),
        ],
        "",
    )


def test_a_release_sent_with_a_layout_the_page_no_longer_has_changes_nothing() -> None:
    notion = _notion()
    transport, created = _created(notion)

    with pytest.raises(
        WriteRejectedError,
        match=f"^Notion page {created.item_id} changed after skaldr read it, so nothing was written; publish "
        "again$",
    ):
        transport.release_item(created.item_id, Release({"intro": WELCOME}, ()))
    assert notion.writes() == []


def test_fields_and_title_are_written_in_one_request_and_a_cleared_field_is_emptied() -> None:
    notion = _notion()
    transport, created = _created(
        notion, CONTENT.model_copy(update={"fields": {"Area": "Shed", "Owner": "Rowan"}})
    )

    written = transport.write_fields(
        created.item_id,
        FieldsWrite(
            "Garden guide", {"Area": "Orchard"}, CONTENT.title, {"Area": "Shed", "Owner": "Rowan"}, STAMP
        ),
    )

    assert ([body for method, _, body in _sent(notion) if method == "PATCH"], written.comparable.fields) == (
        [{"properties": {**_title("Garden guide"), "Area": _text("Orchard"), "Owner": {"rich_text": []}}}],
        {"Area": "Orchard", "Owner": "", "Status": None},
    )


def test_fields_are_not_written_to_a_page_stamped_by_another_document() -> None:
    notion = _notion()
    transport, created = _created(notion)

    with pytest.raises(
        WriteRejectedError, match=f"^Notion page {created.item_id} is not stamped with doc_id 'kitchen-rota'$"
    ):
        transport.write_fields(
            created.item_id, FieldsWrite("Other", {}, CONTENT.title, {}, Stamp("kitchen-rota", None))
        )
    assert notion.writes() == []


def test_an_edit_by_skaldrs_own_bot_is_never_reported_and_needs_no_content_read() -> None:
    notion = _notion()
    transport, created = _created(notion)

    edited = transport.parts_edited_after(created.item_id, None, created.comparable)

    assert (edited, [path for _, path, _ in _sent(notion)]) == (
        (),
        [f"/v1/pages/{created.item_id}", "/v1/users/me"],
    )


def test_an_edit_by_a_person_after_the_marker_reports_the_parts_it_changed() -> None:
    notion = _notion()
    transport, created = _created(notion)
    notion.edit_by_hand(created.item_id, "Sow in spring.", "Sow in June.")

    assert transport.parts_edited_after(created.item_id, created.marker, created.comparable) == (
        section_part("planting"),
    )


def test_a_person_editing_only_what_skaldr_does_not_own_reports_nothing() -> None:
    notion = _notion()
    transport, created = _created(notion)
    notion.set_property_by_hand(created.item_id, "Owner", "Rowan")
    published_without_fields = created.comparable.model_copy(update={"fields": {}})

    assert transport.parts_edited_after(created.item_id, created.marker, published_without_fields) == ()


def test_creating_into_a_page_replaces_its_content_then_sets_its_title_and_fields() -> None:
    notion = _notion()
    transport = notion.transport()
    raw = transport.read_item(EMPTY_ROW, ItemContent(title="")).raw_sections
    notion.requests.clear()
    content = CONTENT.model_copy(update={"fields": {"Area": "Shed"}})

    created = transport.create_item(
        NewItem(DATABASE_TARGET, STAMP, content, into_id=EMPTY_ROW, into_raw_sections=raw)
    )

    assert ([(method, body) for method, _, body in _sent(notion) if method != "GET"], created.item_id) == (
        [
            (
                "PATCH",
                {
                    "type": "replace_content",
                    "replace_content": {"new_str": f"{WELCOME}{PLANTING}{STAMP_LINE}\n"},
                    "allow_async": True,
                },
            ),
            ("PATCH", {"properties": {**_title("Garden handbook"), "Area": _text("Shed")}}),
        ],
        EMPTY_ROW,
    )


def test_creating_into_a_page_that_changed_since_it_was_read_writes_nothing() -> None:
    notion = _notion()
    transport = notion.transport()
    raw = transport.read_item(EMPTY_ROW, ItemContent(title="")).raw_sections
    notion.pages[EMPTY_ROW].markdown = "A person's note."

    with pytest.raises(WriteRejectedError, match=f"^Notion page {EMPTY_ROW} changed after skaldr read it"):
        transport.create_item(
            NewItem(DATABASE_TARGET, STAMP, CONTENT, into_id=EMPTY_ROW, into_raw_sections=raw)
        )
    assert notion.writes() == []


def test_a_page_holding_child_pages_reports_them() -> None:
    notion = _notion()
    child = numbered_id(5).replace("-", "")
    notion.add_page(EMPTY_ROW, "Plans", f'<page url="https://www.notion.so/Seeds-{child}">Seeds</page>')
    transport = notion.transport()

    read = transport.read_item(EMPTY_ROW, ItemContent(title=""))

    assert (read.child_ids, read.raw_sections) == ((child,), {})


def test_the_comparable_form_mirrors_notions_normalisation_and_drops_empty_sections() -> None:
    transport = InMemoryNotion().transport()
    content = ItemContent(
        title="t", sections={"table": "<table>\n\t<tr>\n\t\t<td>a</td>\n\t</tr>\n</table>\n", "empty": ""}
    )

    assert transport.comparable_form(content) == ItemContent(
        title="t", sections={"table": "<table>\n<tr>\n<td>a</td>\n</tr>\n</table>\n"}
    )


def test_an_id_that_cannot_be_a_notion_page_is_not_found_without_a_request() -> None:
    notion = InMemoryNotion()

    with pytest.raises(ItemNotFoundError, match=r"^'page-1' is not a Notion page id$"):
        notion.transport().read_item("page-1", CONTENT)
    assert notion.requests == []


def test_page_ids_in_answers_are_given_back_without_dashes() -> None:
    assert dashed(FIRST_PAGE) == numbered_id(1)
