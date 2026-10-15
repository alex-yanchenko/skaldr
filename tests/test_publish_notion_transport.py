import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pytest

from skaldr.errors import AuthError, ConnectorError, ItemNotFoundError, WriteRejectedError
from skaldr.publish.content import (
    COVER,
    FIELDS,
    ICON,
    TITLE,
    ItemContent,
    Part,
    differing_parts,
    section_part,
)
from skaldr.publish.notion.api import NotionApi
from skaldr.publish.notion.page_markdown import UNKEYED_SECTION
from skaldr.publish.notion.transport import NotionTransport
from skaldr.publish.transport import (
    AddSection,
    ContentWrite,
    FieldsWrite,
    LinksWrite,
    NewItem,
    PairedLink,
    Release,
    RemoteItem,
    RemoveSection,
    ReplaceSection,
    SectionRequest,
    Stamp,
)
from skaldr.publish_block import JiraTarget, NotionTarget
from skaldr.publish_block.target import JsonFields
from tests.factories import NOTION_PAGE_ID, make_jira_target, make_notion_target
from tests.factories.notion_factory import (
    BOT_ID,
    PERSON_ID,
    InMemoryNotion,
    RequestLimits,
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
SEEDLING = "🌱"
SUNFLOWER = "🌻"
COVER_URL = "https://example.com/garden.png"
UPLOADED = "a file uploaded to Notion (https://files.example.com/space/trowel.png)"
CUSTOM_EMOJI_ID = "c0ffee00-0000-4000-8000-0000000000e1"
SEEDLING_ICON = {"type": "emoji", "emoji": SEEDLING}
GARDEN_COVER = {"type": "external", "external": {"url": COVER_URL}}
LOOKING = CONTENT.model_copy(update={"icon": SEEDLING, "cover": COVER_URL})


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


def _page_requests(notion: InMemoryNotion, page_id: str) -> list[tuple[str, Any]]:
    return [(method, body) for method, path, body in _sent(notion) if path == f"/v1/pages/{page_id}"]


def _created(
    notion: InMemoryNotion, content: ItemContent = CONTENT, target: NotionTarget = DATABASE_TARGET
) -> tuple[NotionTransport, RemoteItem]:
    transport = notion.transport()
    created = transport.create_item(NewItem(target, STAMP, content))
    notion.requests.clear()
    return transport, created


def _title(text: str, name: str = "title") -> dict[str, Any]:
    return {name: {"title": [{"type": "text", "text": {"content": text}}]}}


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
        links=(),
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
                "properties": {**_title("Garden handbook", "Name"), "Area": _text("Shed")},
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


@dataclass
class RefusedRenewal:
    access_token: str = "access-token"

    def renew(self) -> None:
        raise AuthError("Notion refused to renew the sign-in: invalid_grant; run `skaldr auth notion` again")


def test_a_sign_in_refused_while_following_a_create_is_not_a_rejected_write_because_the_page_may_exist() -> (
    None
):
    notion = _notion()
    notion.scripted = [
        Scripted(
            401,
            {"object": "error", "status": 401, "code": "unauthorized", "message": "expired"},
            method="GET",
            path_prefix="/v1/async_tasks/",
        )
    ]
    transport = NotionTransport(NotionApi(RefusedRenewal(), transport=notion.mock(), sleep=lambda _: None))

    with pytest.raises(ConnectorError) as caught:
        transport.create_item(NewItem(PAGE_TARGET, STAMP, CONTENT))

    assert (type(caught.value), str(caught.value)) == (
        ConnectorError,
        "Notion accepted the request to create a page as task task-2 but skaldr could not follow it: Notion "
        "refused to renew the sign-in: invalid_grant; run `skaldr auth notion` again; the change may still "
        "land, so read the page before publishing again",
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
            STAMP,
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
        SectionRequest(AddSection("tools", "## Tools\n- Spade.\n", "intro"), created.raw_sections, STAMP),
    )

    assert (
        [body for method, _, body in _sent(notion) if method == "PATCH"],
        list(written.raw_sections),
        notion.markdown_of(created.item_id),
    ) == (
        [_update("Welcome to the garden.\n", "Welcome to the garden.\n## Tools\n- Spade.\n")],
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


AREA_CLEARED: dict[str, Any] = {"properties": {"Area": {"rich_text": []}}}


@pytest.mark.parametrize(
    ("clears_icon", "clears_cover", "update"),
    [
        pytest.param(True, True, {**AREA_CLEARED, "icon": None, "cover": None}, id="both-owned"),
        pytest.param(True, False, {**AREA_CLEARED, "icon": None}, id="icon-owned"),
        pytest.param(False, False, AREA_CLEARED, id="neither-owned"),
    ],
)
def test_a_release_clears_the_icon_and_cover_skaldr_set_with_the_fields_in_one_update(
    clears_icon: bool, clears_cover: bool, update: dict[str, Any]
) -> None:
    notion = _notion()
    transport, created = _created(notion, LOOKING.model_copy(update={"fields": {"Area": "Shed"}}))

    transport.release_item(
        created.item_id,
        Release(created.raw_sections, ("Area",), clears_icon=clears_icon, clears_cover=clears_cover),
    )

    assert _page_requests(notion, FIRST_PAGE) == [("GET", None), ("PATCH", update)]


def test_a_release_sends_no_page_update_when_the_icon_skaldr_set_is_already_gone() -> None:
    notion = _notion()
    transport, created = _created(notion, LOOKING)
    notion.set_look_by_hand(created.item_id, icon=None, cover=None)
    read = transport.read_item(created.item_id, LOOKING)
    notion.requests.clear()

    transport.release_item(
        created.item_id, Release(read.raw_sections, (), clears_icon=True, clears_cover=True)
    )

    assert _page_requests(notion, FIRST_PAGE) == [("GET", None)]


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
        [
            {
                "properties": {
                    **_title("Garden guide", "Name"),
                    "Area": _text("Orchard"),
                    "Owner": {"rich_text": []},
                }
            }
        ],
        {"Area": "Orchard", "Owner": "", "Status": None},
    )


@pytest.mark.parametrize(
    ("stamped", "written", "named"),
    [
        pytest.param(STAMP, Stamp("kitchen-rota", None), "doc_id 'kitchen-rota'", id="another-document"),
        pytest.param(
            STAMP,
            Stamp("garden-handbook", "tools"),
            "doc_id 'garden-handbook', section 'tools'",
            id="the-document-page-for-a-section",
        ),
        pytest.param(
            Stamp("garden-handbook", "tools"),
            Stamp("garden-handbook", "planting"),
            "doc_id 'garden-handbook', section 'planting'",
            id="another-section",
        ),
        pytest.param(
            Stamp("garden-handbook", "tools"),
            STAMP,
            "doc_id 'garden-handbook'",
            id="a-section-page-for-the-document",
        ),
    ],
)
def test_fields_are_not_written_to_a_page_stamped_for_another_document_or_section(
    stamped: Stamp, written: Stamp, named: str
) -> None:
    notion = _notion()
    transport = notion.transport()
    created = transport.create_item(NewItem(DATABASE_TARGET, stamped, CONTENT))
    notion.requests.clear()

    with pytest.raises(WriteRejectedError) as caught:
        transport.write_fields(created.item_id, FieldsWrite("Other", {}, CONTENT.title, {}, written))

    assert (str(caught.value), notion.writes()) == (
        f"Notion page {created.item_id} is not stamped with {named}",
        [],
    )


def test_notion_reports_no_edit_the_text_comparison_does_not_already_show_and_asks_nothing() -> None:
    notion = _notion()
    transport, created = _created(notion)
    notion.edit_by_hand(created.item_id, "Sow in spring.", "Sow in June.")

    edited = transport.parts_edited_after(created.item_id, created.marker, created.comparable)

    assert (edited, notion.requests) == ((), [])


def test_a_title_or_field_a_person_changes_shows_in_the_read_so_the_engine_sees_the_edit() -> None:
    notion = _notion()
    transport, created = _created(notion, CONTENT.model_copy(update={"fields": {"Area": "Shed"}}))
    notion.set_property_by_hand(created.item_id, "Name", "Garden notes")
    notion.set_property_by_hand(created.item_id, "Area", "Orchard")

    read = transport.read_item(created.item_id, created.comparable)

    assert (
        differing_parts(created.comparable, read.comparable),
        read.comparable.title,
        read.comparable.fields["Area"],
    ) == ((TITLE, FIELDS), "Garden notes", "Orchard")


def _write_into_the_empty_row(notion: InMemoryNotion, fields: dict[str, Any]) -> None:
    transport = notion.transport()
    raw = transport.read_item(EMPTY_ROW, ItemContent(title="")).raw_sections
    notion.requests.clear()
    content = CONTENT.model_copy(update={"fields": fields})
    transport.create_item(NewItem(DATABASE_TARGET, STAMP, content, into_id=EMPTY_ROW, into_raw_sections=raw))


def test_creating_into_a_page_replaces_its_content_with_the_stamp_then_sets_its_title_and_fields() -> None:
    notion = _notion()

    _write_into_the_empty_row(notion, {"Area": "Shed"})

    assert [(method, body) for method, _, body in _sent(notion) if method != "GET"] == [
        (
            "PATCH",
            {
                "type": "replace_content",
                "replace_content": {"new_str": f"{WELCOME}{PLANTING}{STAMP_LINE}\n"},
                "allow_async": True,
            },
        ),
        ("PATCH", {"properties": {**_title("Garden handbook", "Name"), "Area": _text("Shed")}}),
    ]


def test_a_write_into_a_page_whose_content_request_fails_leaves_its_title_and_fields_alone() -> None:
    notion = _notion()
    failure = {"object": "error", "status": 500, "code": "internal_server_error", "message": "oops"}
    notion.scripted = [Scripted(500, failure, method="PATCH")]

    with pytest.raises(ConnectorError) as caught:
        _write_into_the_empty_row(notion, {"Area": "Shed"})

    assert (type(caught.value), str(caught.value), notion.pages[EMPTY_ROW].properties) == (
        ConnectorError,
        f"Notion could not change the content of page {EMPTY_ROW}: HTTP 500 internal_server_error: oops",
        {
            "Name": ("title", "Blank page"),
            "Area": ("rich_text", None),
            "Owner": ("rich_text", None),
            "Status": ("select", None),
        },
    )


def test_a_write_into_a_page_whose_property_notion_refuses_leaves_a_stamped_page_to_adopt() -> None:
    notion = _notion()
    refusal = _refusal("Shed is not a valid option.")
    notion.scripted = [Scripted(400, refusal, method="PATCH", path=f"/v1/pages/{EMPTY_ROW}")]

    with pytest.raises(ConnectorError) as caught:
        _write_into_the_empty_row(notion, {"Area": "Shed"})

    assert (type(caught.value), notion.transport().read_item(EMPTY_ROW, CONTENT).stamp) == (
        ConnectorError,
        STAMP,
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
    reference = f'<page url="https://www.notion.so/Seeds-{child}">Seeds</page>'
    notion.add_page(EMPTY_ROW, "Plans", reference)
    transport = notion.transport()

    read = transport.read_item(EMPTY_ROW, ItemContent(title=""))

    assert (read.child_ids, read.raw_sections, read.comparable.sections) == (
        (child,),
        {UNKEYED_SECTION: reference},
        {},
    )


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


def _refusal(message: str) -> dict[str, Any]:
    return {"object": "error", "status": 400, "code": "validation_error", "message": message}


def _patches(notion: InMemoryNotion) -> list[Any]:
    return [body for method, _, body in _sent(notion) if method == "PATCH"]


def test_a_moved_section_is_one_request_over_the_span_between_its_two_places() -> None:
    notion = _notion()
    transport, created = _created(notion)

    transport.write_section(
        created.item_id,
        SectionRequest(ReplaceSection("planting", PLANTING, PLANTING, None), created.raw_sections, STAMP),
    )

    assert (_patches(notion), notion.markdown_of(created.item_id)) == (
        [_update(WELCOME + PLANTING, PLANTING + WELCOME)],
        f"{PLANTING}{WELCOME}{STAMP_LINE}",
    )


def test_text_a_person_types_below_the_stamp_belongs_to_no_section_and_never_blocks_a_write() -> None:
    notion = _notion()
    transport, created = _created(notion)
    notion.edit_by_hand(created.item_id, STAMP_LINE, f"{STAMP_LINE}\nA visitor's note.")
    read = transport.read_item(created.item_id, created.comparable)

    transport.write_section(
        created.item_id,
        SectionRequest(
            ReplaceSection("planting", read.raw_sections["planting"], "## Planting\nSow in May.\n", "intro"),
            read.raw_sections,
            STAMP,
        ),
    )

    assert (read.comparable.sections, notion.markdown_of(created.item_id)) == (
        {"intro": WELCOME, "planting": PLANTING},
        f"{WELCOME}## Planting\nSow in May.\n{STAMP_LINE}\nA visitor's note.",
    )


def test_a_child_page_moved_into_a_section_stays_in_place_when_the_section_is_rewritten() -> None:
    notion = _notion()
    transport, created = _created(notion)
    child = f'<page url="https://www.notion.so/Seeds-{numbered_id(5).replace("-", "")}">Seeds</page>'
    notion.edit_by_hand(created.item_id, "Sow in spring.", f"Sow in spring.\n{child}")
    read = transport.read_item(created.item_id, created.comparable)
    notion.requests.clear()

    transport.write_section(
        created.item_id,
        SectionRequest(
            ReplaceSection("planting", read.raw_sections["planting"], "## Planting\nSow in May.\n", "intro"),
            read.raw_sections,
            STAMP,
        ),
    )

    assert _patches(notion) == [
        _update(f"## Planting\nSow in spring.\n{child}\n", f"## Planting\nSow in May.\n{child}\n")
    ]


def test_a_section_holding_a_block_notion_cannot_show_as_markdown_is_not_rewritten() -> None:
    notion = _notion()
    transport, created = _created(notion)
    notion.add_unknown_block(created.item_id, "Sow in spring.", numbered_id(40))
    read = transport.read_item(created.item_id, created.comparable)

    with pytest.raises(
        WriteRejectedError,
        match=f"^section planting of Notion page {created.item_id} holds a block Notion does not show as "
        "Markdown, so skaldr will not rewrite it; change or remove that block in Notion first$",
    ):
        transport.write_section(
            created.item_id,
            SectionRequest(
                ReplaceSection(
                    "planting", read.raw_sections["planting"], "## Planting\nSow in May.\n", "intro"
                ),
                read.raw_sections,
                STAMP,
            ),
        )
    assert notion.writes() == []


def test_a_move_that_would_not_fit_one_request_is_refused_before_anything_is_sent() -> None:
    notion = _notion()
    sections = {key: f"## {key.upper()}\n{'a' * 150_000}\n" for key in ("a", "b")}
    transport, created = _created(notion, ItemContent(title="Big", sections=sections))

    with pytest.raises(
        WriteRejectedError,
        match=f"^the write to Notion page {created.item_id} quotes sections a, b and would send 600,032 "
        "bytes of JSON in one request, over the 450,000 one request may carry; give one of those sections "
        "its own page with `split`$",
    ):
        transport.write_section(
            created.item_id,
            SectionRequest(
                ReplaceSection("b", sections["b"], sections["b"], None), created.raw_sections, STAMP
            ),
        )
    assert notion.writes() == []


def test_a_release_keeps_text_a_person_added_and_text_below_the_stamp() -> None:
    notion = _notion()
    transport, created = _created(notion)
    notion.edit_by_hand(created.item_id, "Sow in spring.", "Sow in spring.\nWater weekly.")
    notion.edit_by_hand(created.item_id, STAMP_LINE, f"{STAMP_LINE}\nA visitor's note.")
    read = transport.read_item(created.item_id, created.comparable)

    transport.release_item(created.item_id, Release(read.raw_sections, ()))

    assert notion.markdown_of(created.item_id) == "Water weekly.\nA visitor's note."


def test_a_release_keeps_a_block_notion_cannot_show_as_markdown_without_quoting_it() -> None:
    notion = _notion()
    transport, created = _created(notion)
    unknown = notion.add_unknown_block(created.item_id, "Sow in spring.", numbered_id(40))
    read = transport.read_item(created.item_id, created.comparable)
    notion.requests.clear()

    transport.release_item(created.item_id, Release(read.raw_sections, ()))

    assert (_patches(notion), notion.markdown_of(created.item_id)) == (
        [_update(f"{WELCOME}{PLANTING}", ""), _update(STAMP_LINE, "")],
        unknown,
    )


def test_a_page_larger_than_one_request_is_released_in_several() -> None:
    notion = _notion()
    sections = {key: f"## {key.upper()}\n{'a' * 150_000}\n" for key in ("a", "b", "c", "d")}
    transport, created = _created(notion, ItemContent(title="Big", sections=sections))

    transport.release_item(created.item_id, Release(created.raw_sections, ()))

    a, b, c, d = sections.values()
    assert (_patches(notion), notion.markdown_of(created.item_id)) == (
        [_update(f"{a}{b}## C\n", ""), _update(f"{c[len('## C') + 1 :]}{d}{STAMP_LINE}", "")],
        "",
    )


def test_a_fields_write_to_a_page_whose_stamp_was_deleted_puts_the_stamp_back() -> None:
    notion = _notion()
    transport, created = _created(notion)
    notion.edit_by_hand(created.item_id, f"\n{STAMP_LINE}", "")

    written = transport.write_fields(
        created.item_id, FieldsWrite("Garden guide", {}, CONTENT.title, {}, STAMP)
    )

    assert (_patches(notion), written.stamp, notion.markdown_of(created.item_id)) == (
        [
            _update("Sow in spring.", f"Sow in spring.\n{STAMP_LINE}\n"),
            {"properties": _title("Garden guide", "Name")},
        ],
        STAMP,
        f"{WELCOME}{PLANTING}{STAMP_LINE}",
    )


def test_a_section_write_to_a_page_whose_stamp_was_deleted_puts_the_stamp_back() -> None:
    notion = _notion()
    transport, created = _created(notion)
    notion.edit_by_hand(created.item_id, f"\n{STAMP_LINE}", "")
    read = transport.read_item(created.item_id, created.comparable)
    notion.requests.clear()

    written = transport.write_section(
        created.item_id,
        SectionRequest(
            ReplaceSection("planting", read.raw_sections["planting"], "## Planting\nSow in May.\n", "intro"),
            read.raw_sections,
            STAMP,
        ),
    )

    assert (_patches(notion), written.stamp, notion.markdown_of(created.item_id)) == (
        [
            _update("## Planting\nSow in spring.", "## Planting\nSow in May.\n"),
            _update("Sow in May.", f"Sow in May.\n{STAMP_LINE}\n"),
        ],
        STAMP,
        f"{WELCOME}## Planting\nSow in May.\n{STAMP_LINE}",
    )


def test_a_content_write_to_a_page_whose_stamp_was_deleted_puts_the_stamp_back() -> None:
    notion = _notion()
    transport, created = _created(notion)
    notion.edit_by_hand(created.item_id, f"\n{STAMP_LINE}", "")
    read = transport.read_item(created.item_id, created.comparable)
    notion.requests.clear()

    written = transport.write_content(
        created.item_id, ContentWrite({"intro": WELCOME, "tools": TOOLS}, read.raw_sections, STAMP)
    )

    assert (written.stamp, notion.markdown_of(created.item_id)) == (
        STAMP,
        f"{WELCOME}{TOOLS}{STAMP_LINE}",
    )


ISSUE_LINK = PairedLink("jira", "DEMO-12", "https://example.atlassian.net/browse/DEMO-12", "DEMO-12")
LINKED_STAMP_LINE = (
    "Published with skaldr from document garden-handbook · Jira "
    '[DEMO-12](https://example.atlassian.net/browse/DEMO-12) {color="gray"}'
)


def test_links_rewrite_the_stamp_line_alone_in_one_request() -> None:
    notion = _notion()
    transport, created = _created(notion)

    written = transport.write_links(created.item_id, LinksWrite(STAMP, (ISSUE_LINK,)))

    assert (written, _patches(notion), notion.markdown_of(created.item_id)) == (
        (ISSUE_LINK.shown,),
        [_update(STAMP_LINE, LINKED_STAMP_LINE)],
        f"{WELCOME}{PLANTING}{LINKED_STAMP_LINE}",
    )


def test_a_links_write_to_a_page_whose_stamp_was_deleted_puts_the_stamp_back_with_its_links() -> None:
    notion = _notion()
    transport, created = _created(notion)
    notion.edit_by_hand(created.item_id, f"\n{STAMP_LINE}", "")

    transport.write_links(created.item_id, LinksWrite(STAMP, (ISSUE_LINK,)))

    assert (_patches(notion), notion.markdown_of(created.item_id)) == (
        [_update("Sow in spring.", f"Sow in spring.\n{LINKED_STAMP_LINE}\n")],
        f"{WELCOME}{PLANTING}{LINKED_STAMP_LINE}",
    )


def test_a_section_write_keeps_the_links_on_the_stamp() -> None:
    notion = _notion()
    transport, created = _created(notion)
    transport.write_links(created.item_id, LinksWrite(STAMP, (ISSUE_LINK,)))
    read = transport.read_item(created.item_id, created.comparable)

    transport.write_section(
        created.item_id, SectionRequest(AddSection("tools", TOOLS, "planting"), read.raw_sections, STAMP)
    )

    assert notion.markdown_of(created.item_id) == f"{WELCOME}{PLANTING}{TOOLS}{LINKED_STAMP_LINE}"


def test_a_fields_write_refused_before_sending_does_not_put_a_deleted_stamp_back() -> None:
    notion = _notion()
    transport, created = _created(notion)
    notion.edit_by_hand(created.item_id, f"\n{STAMP_LINE}", "")
    notion.requests.clear()

    with pytest.raises(
        WriteRejectedError,
        match=r"^the Notion property 'Status' is a select property, so skaldr sends it a text, not 3$",
    ):
        transport.write_fields(
            created.item_id, FieldsWrite(CONTENT.title, {"Status": 3}, CONTENT.title, {}, STAMP)
        )
    assert notion.writes() == []


def test_a_fields_write_to_a_page_this_transport_never_read_is_refused() -> None:
    notion = _notion()
    _, created = _created(notion)

    with pytest.raises(
        ConnectorError,
        match=f"^skaldr has not read Notion page {created.item_id} in this run, so it cannot tell its "
        "sections apart$",
    ):
        notion.transport().write_fields(
            created.item_id, FieldsWrite("Garden guide", {}, CONTENT.title, {}, STAMP)
        )


def test_a_property_named_title_is_a_field_and_never_replaces_the_title() -> None:
    notion = InMemoryNotion()
    notion.add_database(NOTION_PAGE_ID, {"Name": "title", "title": "rich_text"})
    transport = notion.transport()

    created = transport.create_item(
        NewItem(DATABASE_TARGET, STAMP, CONTENT.model_copy(update={"fields": {"title": "Lowercase"}}))
    )

    assert (_sent(notion)[3][2]["properties"], created.comparable.title, created.comparable.fields) == (
        {**_title("Garden handbook", "Name"), "title": _text("Lowercase")},
        "Garden handbook",
        {"title": "Lowercase"},
    )


def test_a_section_write_to_a_page_edited_since_it_was_read_writes_nothing() -> None:
    notion = _notion()
    content = ItemContent(
        title="Garden", sections={"intro": "## Welcome\n- Spade.\n", "tools": "## Tools\n- Spade.\n"}
    )
    transport, created = _created(notion, content)
    notion.edit_by_hand(created.item_id, "## Welcome\n- Spade.\n", "## Welcome\n")

    with pytest.raises(
        WriteRejectedError,
        match=f"^Notion page {created.item_id} changed after skaldr read it, so nothing was written; publish "
        "again$",
    ):
        transport.write_section(
            created.item_id,
            SectionRequest(AddSection("care", "## Care\n", "tools"), created.raw_sections, STAMP),
        )
    assert notion.writes() == []


def test_a_page_is_created_with_the_icon_as_an_emoji_and_the_cover_as_an_external_image() -> None:
    notion = _notion()
    transport = notion.transport()

    created = transport.create_item(NewItem(PAGE_TARGET, STAMP, LOOKING))

    assert ([body for method, _, body in _sent(notion) if method == "POST"], created.comparable) == (
        [
            {
                "parent": {"page_id": PARENT_PAGE_ID},
                "properties": _title("Garden handbook"),
                "icon": SEEDLING_ICON,
                "cover": GARDEN_COVER,
                "markdown": f"{WELCOME}{PLANTING}{STAMP_LINE}\n",
                "allow_async": True,
            }
        ],
        LOOKING,
    )


def test_an_icon_and_cover_that_changed_are_set_and_cleared_without_the_properties() -> None:
    notion = _notion()
    transport, created = _created(notion, LOOKING, PAGE_TARGET)

    written = transport.write_fields(
        created.item_id,
        FieldsWrite(
            CONTENT.title,
            {},
            CONTENT.title,
            {},
            STAMP,
            icon=SUNFLOWER,
            cover=None,
            previous_icon=SEEDLING,
            previous_cover=COVER_URL,
        ),
    )

    assert (_patches(notion), written.comparable) == (
        [{"icon": {"type": "emoji", "emoji": SUNFLOWER}, "cover": None}],
        CONTENT.model_copy(update={"icon": SUNFLOWER}),
    )


def test_an_icon_and_cover_that_did_not_change_are_not_sent() -> None:
    notion = _notion()
    transport, created = _created(notion, LOOKING, PAGE_TARGET)

    transport.write_fields(
        created.item_id,
        FieldsWrite(
            "Garden guide",
            {},
            CONTENT.title,
            {},
            STAMP,
            icon=SEEDLING,
            cover=COVER_URL,
            previous_icon=SEEDLING,
            previous_cover=COVER_URL,
        ),
    )

    assert _patches(notion) == [{"properties": _title("Garden guide")}]


def _uploaded(signature: str, file_name: str = "trowel.png") -> dict[str, Any]:
    url = f"https://files.example.com/space/{file_name}?signature={signature}"
    return {"type": "file", "file": {"url": url, "expiry_time": "2026-10-09T13:00:00.000Z"}}


@pytest.mark.parametrize(
    ("icon", "cover", "expected", "edited"),
    [
        pytest.param(
            {"type": "emoji", "emoji": "🔥"},
            GARDEN_COVER,
            ("🔥", COVER_URL),
            (ICON,),
            id="emoji-and-external",
        ),
        pytest.param(
            {"type": "external", "external": {"url": "https://example.com/leaf.png"}},
            None,
            ("https://example.com/leaf.png", None),
            (ICON, COVER),
            id="external-icon",
        ),
        pytest.param(
            {"type": "custom_emoji", "custom_emoji": {"id": CUSTOM_EMOJI_ID, "name": "trowel"}},
            _uploaded("first"),
            (f"Notion custom emoji {CUSTOM_EMOJI_ID}", UPLOADED),
            (ICON, COVER),
            id="custom-emoji-and-uploaded-cover",
        ),
        pytest.param(
            {"type": "icon", "icon": {"name": "pizza", "color": "blue"}},
            {"type": "gallery"},
            ("Notion icon pizza (blue)", "a Notion gallery cover"),
            (ICON, COVER),
            id="native-icon-and-an-unknown-cover",
        ),
        pytest.param(
            {"type": "icon", "icon": {"name": "pizza"}},
            GARDEN_COVER,
            ("Notion icon pizza", COVER_URL),
            (ICON,),
            id="native-icon-without-a-colour",
        ),
        pytest.param(_uploaded("first"), GARDEN_COVER, (UPLOADED, COVER_URL), (ICON,), id="uploaded-icon"),
        pytest.param(
            {"type": "sticker"},
            GARDEN_COVER,
            ("a Notion sticker icon", COVER_URL),
            (ICON,),
            id="unknown-icon",
        ),
    ],
)
def test_each_kind_of_icon_and_cover_a_person_sets_reads_as_a_remote_edit(
    icon: dict[str, Any],
    cover: dict[str, Any] | None,
    expected: tuple[str | None, str | None],
    edited: tuple[Part, ...],
) -> None:
    notion = _notion()
    transport, created = _created(notion, LOOKING, PAGE_TARGET)
    notion.set_look_by_hand(created.item_id, icon=icon, cover=cover)

    read = transport.read_item(created.item_id, created.comparable)

    assert (
        (read.comparable.icon, read.comparable.cover),
        differing_parts(created.comparable, read.comparable),
    ) == (
        expected,
        edited,
    )


def test_an_uploaded_icon_and_cover_read_the_same_after_notion_signs_their_addresses_again() -> None:
    notion = _notion()
    transport, created = _created(notion, LOOKING, PAGE_TARGET)
    notion.set_look_by_hand(created.item_id, icon=_uploaded("first"), cover=_uploaded("first"))
    first = transport.read_item(created.item_id, created.comparable)
    notion.set_look_by_hand(created.item_id, icon=_uploaded("second"), cover=_uploaded("second"))

    second = transport.read_item(created.item_id, created.comparable)

    assert (differing_parts(first.comparable, second.comparable), second.comparable.icon) == ((), UPLOADED)


def test_one_uploaded_icon_and_cover_swapped_for_another_file_reads_as_an_edit() -> None:
    notion = _notion()
    transport, created = _created(notion, LOOKING, PAGE_TARGET)
    notion.set_look_by_hand(created.item_id, icon=_uploaded("first"), cover=_uploaded("first"))
    first = transport.read_item(created.item_id, created.comparable)
    notion.set_look_by_hand(
        created.item_id, icon=_uploaded("second", "rake.png"), cover=_uploaded("second", "rake.png")
    )

    second = transport.read_item(created.item_id, created.comparable)

    assert (differing_parts(first.comparable, second.comparable), second.comparable.icon) == (
        (ICON, COVER),
        "a file uploaded to Notion (https://files.example.com/space/rake.png)",
    )


def test_an_uploaded_file_notion_gives_no_address_for_reads_as_an_uploaded_file() -> None:
    notion = _notion()
    transport, created = _created(notion, LOOKING, PAGE_TARGET)
    notion.set_look_by_hand(created.item_id, icon={"type": "file"}, cover=GARDEN_COVER)

    read = transport.read_item(created.item_id, created.comparable)

    assert read.comparable.icon == "a file uploaded to Notion"


def test_writing_into_a_page_sets_the_icon_and_cover_with_its_title_and_fields() -> None:
    notion = _notion()
    transport = notion.transport()
    raw = transport.read_item(EMPTY_ROW, ItemContent(title="")).raw_sections
    notion.requests.clear()

    transport.create_item(
        NewItem(
            DATABASE_TARGET,
            STAMP,
            LOOKING.model_copy(update={"fields": {"Area": "Shed"}}),
            into_id=EMPTY_ROW,
            into_raw_sections=raw,
        )
    )

    assert _patches(notion)[1:] == [
        {
            "properties": {**_title("Garden handbook", "Name"), "Area": _text("Shed")},
            "icon": SEEDLING_ICON,
            "cover": GARDEN_COVER,
        }
    ]


def test_writing_into_a_page_without_an_icon_or_cover_keeps_the_ones_it_has() -> None:
    notion = _notion()
    notion.set_look_by_hand(EMPTY_ROW, icon={"type": "emoji", "emoji": "🔥"}, cover=GARDEN_COVER)

    _write_into_the_empty_row(notion, {})

    assert (_patches(notion)[1:], notion.pages[EMPTY_ROW].icon, notion.pages[EMPTY_ROW].cover) == (
        [{"properties": _title("Garden handbook", "Name")}],
        {"type": "emoji", "emoji": "🔥"},
        GARDEN_COVER,
    )


CHILD = f'<page url="https://www.notion.so/Seeds-{numbered_id(5).replace("-", "")}">Seeds</page>'
TOOLS = "## Tools\nSpade.\n"


@pytest.mark.parametrize(
    ("sections", "after", "written", "markdown"),
    [
        pytest.param(
            {"intro": WELCOME, "planting": PLANTING},
            "Welcome to the garden.",
            {"planting": PLANTING},
            f"{CHILD}\n{PLANTING}{STAMP_LINE}",
            id="first",
        ),
        pytest.param(
            {"intro": WELCOME, "tools": TOOLS, "planting": PLANTING},
            "Spade.",
            {"intro": WELCOME, "planting": PLANTING},
            f"{WELCOME}{CHILD}\n{PLANTING}{STAMP_LINE}",
            id="middle",
        ),
        pytest.param(
            {"intro": WELCOME},
            "Welcome to the garden.",
            {"planting": PLANTING},
            f"{CHILD}\n{PLANTING}{STAMP_LINE}",
            id="only",
        ),
    ],
)
def test_a_content_write_keeps_the_child_pages_of_a_section_it_removes(
    sections: dict[str, str], after: str, written: dict[str, str], markdown: str
) -> None:
    notion = _notion()
    transport, created = _created(notion, ItemContent(title="Garden handbook", sections=sections))
    notion.edit_by_hand(created.item_id, after, f"{after}\n{CHILD}")
    read = transport.read_item(created.item_id, created.comparable)

    transport.write_content(created.item_id, ContentWrite(written, read.raw_sections, STAMP))

    assert notion.markdown_of(created.item_id) == markdown


def test_a_removed_middle_section_is_one_request_that_quotes_only_that_section() -> None:
    notion = _notion()
    sections = {"intro": WELCOME, "tools": TOOLS, "planting": PLANTING}
    transport, created = _created(notion, ItemContent(title="Garden handbook", sections=sections))

    written = transport.write_section(
        created.item_id,
        SectionRequest(RemoveSection("tools", created.raw_sections["tools"]), created.raw_sections, STAMP),
    )

    assert (_patches(notion), list(written.raw_sections), notion.markdown_of(created.item_id)) == (
        [_update(TOOLS, "")],
        ["intro", "planting"],
        f"{WELCOME}{PLANTING}{STAMP_LINE}",
    )


TRASHED_PARENT = "abcdefabcdefabcdefabcdefabcdefab"


def _paragraph_parent(notion: InMemoryNotion) -> NotionTarget:
    notion.other_blocks[PARENT_PAGE_ID] = "paragraph"
    return PAGE_TARGET


def _database_with_sources(count: int) -> Callable[[InMemoryNotion], NotionTarget]:
    def database(notion: InMemoryNotion) -> NotionTarget:
        notion.add_database(PARENT_PAGE_ID)
        notion.data_source_counts[PARENT_PAGE_ID] = count
        return PAGE_TARGET

    return database


def _trashed_parent(notion: InMemoryNotion) -> NotionTarget:
    notion.add_page(TRASHED_PARENT, "Old plans")
    notion.pages[TRASHED_PARENT].in_trash = True
    return NotionTarget.model_validate(make_notion_target(where={"parent_page": TRASHED_PARENT}))


@pytest.mark.parametrize(
    ("place", "message"),
    [
        pytest.param(
            _paragraph_parent,
            f"Notion block {PARENT_PAGE_ID} is a paragraph, not a page or a database, so skaldr cannot "
            "create a page under it",
            id="neither-page-nor-database",
        ),
        pytest.param(
            _database_with_sources(0),
            f"Notion database {PARENT_PAGE_ID} has 0 data sources; skaldr adds rows only to a database "
            "with one",
            id="database-without-a-data-source",
        ),
        pytest.param(
            _database_with_sources(2),
            f"Notion database {PARENT_PAGE_ID} has 2 data sources; skaldr adds rows only to a database "
            "with one",
            id="database-with-two-data-sources",
        ),
        pytest.param(
            _trashed_parent,
            f"Notion page {TRASHED_PARENT} is in the trash, so skaldr cannot create a page under it",
            id="parent-in-the-trash",
        ),
    ],
)
def test_a_parent_skaldr_cannot_create_a_page_under_is_refused_before_anything_is_written(
    place: Callable[[InMemoryNotion], NotionTarget], message: str
) -> None:
    notion = InMemoryNotion()
    target = place(notion)

    with pytest.raises(WriteRejectedError) as caught:
        notion.transport().create_item(NewItem(target, STAMP, CONTENT))

    assert (str(caught.value), notion.writes()) == (message, [])


def test_a_target_of_another_service_is_refused_by_the_notion_transport() -> None:
    notion = _notion()
    target = JiraTarget.model_validate(make_jira_target())

    with pytest.raises(WriteRejectedError) as caught:
        notion.transport().create_item(NewItem(target, STAMP, CONTENT))

    assert (str(caught.value), notion.requests) == (
        f"the Notion connector cannot publish to {target.place_label()}",
        [],
    )


def test_an_empty_unstamped_page_gives_a_section_write_nothing_to_place_it_next_to() -> None:
    notion = _notion()
    transport = notion.transport()
    raw = transport.read_item(EMPTY_ROW, ItemContent(title="")).raw_sections

    with pytest.raises(WriteRejectedError) as caught:
        transport.write_section(EMPTY_ROW, SectionRequest(AddSection("tools", TOOLS, None), raw, STAMP))

    assert (str(caught.value), notion.writes()) == (
        f"Notion page {EMPTY_ROW} holds nothing skaldr can place the section next to",
        [],
    )


def test_an_empty_unstamped_page_gives_a_content_write_nothing_to_place_it_next_to() -> None:
    notion = _notion()
    transport = notion.transport()
    raw = transport.read_item(EMPTY_ROW, ItemContent(title="")).raw_sections

    with pytest.raises(WriteRejectedError) as caught:
        transport.write_content(EMPTY_ROW, ContentWrite({"tools": TOOLS}, raw, STAMP))

    assert (str(caught.value), notion.writes()) == (
        f"Notion page {EMPTY_ROW} holds nothing skaldr can place its content next to",
        [],
    )


def test_a_fields_write_to_a_page_emptied_by_hand_puts_the_stamp_back_as_its_whole_content() -> None:
    notion = _notion()
    transport, created = _created(notion)
    notion.edit_by_hand(created.item_id, f"{WELCOME}{PLANTING}{STAMP_LINE}", "")

    written = transport.write_fields(
        created.item_id, FieldsWrite("Garden guide", {}, CONTENT.title, {}, STAMP)
    )

    stamp_only = {"type": "replace_content", "replace_content": {"new_str": f"{STAMP_LINE}\n"}}
    assert (_patches(notion), written.stamp, notion.markdown_of(created.item_id)) == (
        [{**stamp_only, "allow_async": True}, {"properties": _title("Garden guide", "Name")}],
        STAMP,
        STAMP_LINE,
    )


def test_a_section_over_the_blocks_one_request_carries_is_refused_before_anything_is_sent() -> None:
    notion = _notion()
    transport, created = _created(notion)
    planting = "## Planting\n" + "- a\n" * 5_000

    with pytest.raises(WriteRejectedError) as caught:
        transport.write_section(
            created.item_id,
            SectionRequest(
                ReplaceSection("planting", created.raw_sections["planting"], planting, "intro"),
                created.raw_sections,
                STAMP,
            ),
        )

    assert (str(caught.value), notion.writes()) == (
        f"the write to Notion page {created.item_id} quotes sections planting and would send 5,001 Notion "
        "blocks in one request, over the 5,000 one request may carry; give one of those sections its own "
        "page with `split`",
        [],
    )


def test_a_page_over_the_bytes_of_one_create_is_finished_by_appends_that_stay_within_notions_limits() -> None:
    notion = _notion()
    notion.limits = RequestLimits(json_bytes=500_000, blocks=5_000)
    transport = notion.transport()
    sections = {key: f"## {key.upper()}\n{'a' * 150_000}\n" for key in ("a", "b", "c", "d")}

    created = transport.create_item(NewItem(PAGE_TARGET, STAMP, ItemContent(title="Big", sections=sections)))

    a, b, c, d = sections.values()
    assert (_sent(notion)[1][2]["markdown"], _patches(notion), notion.markdown_of(created.item_id)) == (
        f"{a}{b}{STAMP_LINE}\n",
        [_update(STAMP_LINE, f"{c}{d}{STAMP_LINE}")],
        f"{a}{b}{c}{d}{STAMP_LINE}",
    )


def test_a_create_notion_finds_too_large_is_a_rejected_write() -> None:
    notion = _notion()
    notion.limits = RequestLimits(json_bytes=100, blocks=5_000)

    with pytest.raises(WriteRejectedError) as caught:
        notion.transport().create_item(NewItem(PAGE_TARGET, STAMP, CONTENT))

    assert str(caught.value) == "Notion refused to create a page: Request body too large. (validation_error)"


def test_a_create_whose_task_fails_is_a_rejected_write_and_makes_no_page() -> None:
    notion = _notion()
    pages_before = set(notion.pages)
    notion.fail_the_next_task(400, "validation_error", "Title is too long.")

    with pytest.raises(WriteRejectedError) as caught:
        notion.transport().create_item(NewItem(PAGE_TARGET, STAMP, CONTENT))

    assert (str(caught.value), set(notion.pages)) == (
        "Notion refused to create a page: Title is too long. (validation_error)",
        pages_before,
    )


def test_a_page_notion_reads_only_in_part_is_not_read() -> None:
    notion = _notion()
    transport, created = _created(notion)
    notion.truncated_pages.add(created.item_id)

    with pytest.raises(ConnectorError) as caught:
        transport.read_item(created.item_id, created.comparable)

    assert str(caught.value) == (
        f"Notion sent only part of page {created.item_id}, which is too large to read whole; split the "
        "document further with `split`"
    )


def test_an_old_str_that_differs_from_the_page_only_in_whitespace_is_refused_like_notion_does() -> None:
    notion = _notion()
    _, created = _created(notion)
    command: JsonFields = {
        "type": "update_content",
        "update_content": {"content_updates": [{"old_str": "Sow in spring. ", "new_str": "Sow in May."}]},
    }

    with pytest.raises(WriteRejectedError) as caught:
        notion.api().update_markdown(created.item_id, command)

    assert (str(caught.value), notion.markdown_of(created.item_id)) == (
        f"Notion refused to change the content of page {created.item_id}: No matches found for old_str. "
        "(validation_error)",
        f"{WELCOME}{PLANTING}{STAMP_LINE}",
    )


def test_a_section_with_a_comment_over_two_lines_is_replaced_quoting_both_markers() -> None:
    notion = _notion()
    transport, created = _created(notion)
    notion.comment_on(created.item_id, "## Planting\nSow in spring.")
    read = transport.read_item(created.item_id, created.comparable)
    notion.requests.clear()

    transport.write_section(
        created.item_id,
        SectionRequest(
            ReplaceSection("planting", read.raw_sections["planting"], "## Planting\nSow in May.\n", "intro"),
            read.raw_sections,
            STAMP,
        ),
    )

    commented = (
        '<span discussion-urls="discussion://comment-1">## Planting</span>\n'
        '<span discussion-urls="discussion://comment-1">Sow in spring.</span>\n'
    )
    assert (read.comparable.sections, _patches(notion)) == (
        created.comparable.sections,
        [_update(commented, "## Planting\nSow in May.\n")],
    )


def test_an_edit_in_the_same_minute_as_skaldrs_write_still_reads_as_an_edit() -> None:
    notion = _notion()
    notion.seconds_per_edit = 10
    transport, created = _created(notion)
    notion.edit_by_hand(created.item_id, "Sow in spring.", "Sow in June.")

    read = transport.read_item(created.item_id, created.comparable)

    assert (read.edited_at, read.edited_by, differing_parts(created.comparable, read.comparable)) == (
        created.edited_at,
        PERSON_ID,
        (section_part("planting"),),
    )
