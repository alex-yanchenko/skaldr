import json
import re
from dataclasses import dataclass
from typing import Any

import pytest

from skaldr.errors import AuthError, ConnectorError, ItemNotFoundError, WriteRejectedError
from skaldr.publish.content import ItemContent
from skaldr.publish.notion.api import NotionApi
from skaldr.publish.notion.page_markdown import UNKEYED_SECTION
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


def test_notion_reports_no_edit_the_text_comparison_does_not_already_show_and_asks_nothing() -> None:
    notion = _notion()
    transport, created = _created(notion)
    notion.edit_by_hand(created.item_id, "Sow in spring.", "Sow in June.")

    edited = transport.parts_edited_after(created.item_id, created.marker, created.comparable)

    assert (edited, notion.requests) == ((), [])


def test_creating_into_a_page_sets_its_title_and_fields_then_replaces_its_content() -> None:
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
            ("PATCH", {"properties": {**_title("Garden handbook", "Name"), "Area": _text("Shed")}}),
            (
                "PATCH",
                {
                    "type": "replace_content",
                    "replace_content": {"new_str": f"{WELCOME}{PLANTING}{STAMP_LINE}\n"},
                    "allow_async": True,
                },
            ),
        ],
        EMPTY_ROW,
    )


def test_creating_into_a_page_whose_property_notion_refuses_writes_nothing() -> None:
    notion = _notion()
    transport = notion.transport()
    raw = transport.read_item(EMPTY_ROW, ItemContent(title="")).raw_sections
    notion.scripted = [Scripted(400, _refusal("Shed is not a valid option."), method="PATCH")]
    content = CONTENT.model_copy(update={"fields": {"Area": "Shed"}})

    with pytest.raises(
        WriteRejectedError,
        match=f"^Notion refused to change page {EMPTY_ROW}: Shed is not a valid option. "
        r"\(validation_error\)$",
    ):
        transport.create_item(
            NewItem(DATABASE_TARGET, STAMP, content, into_id=EMPTY_ROW, into_raw_sections=raw)
        )
    assert (notion.markdown_of(EMPTY_ROW), notion.pages[EMPTY_ROW].properties["Area"]) == (
        "",
        ("rich_text", None),
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
        SectionRequest(ReplaceSection("planting", PLANTING, PLANTING, None), created.raw_sections),
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
        ),
    )

    assert _patches(notion) == [
        _update(f"## Planting\nSow in spring.\n{child}\n", f"## Planting\nSow in May.\n{child}\n")
    ]


def test_a_section_holding_a_block_notion_cannot_show_as_markdown_is_not_rewritten() -> None:
    notion = _notion()
    transport, created = _created(notion)
    unknown = '<unknown url="https://www.notion.so/bookmark" alt="bookmark"/>'
    notion.edit_by_hand(created.item_id, "Sow in spring.", f"Sow in spring.\n{unknown}")
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
            SectionRequest(ReplaceSection("b", sections["b"], sections["b"], None), created.raw_sections),
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
    unknown = '<unknown url="https://www.notion.so/bookmark" alt="bookmark"/>'
    notion.edit_by_hand(created.item_id, "Sow in spring.", f"Sow in spring.\n{unknown}")
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
