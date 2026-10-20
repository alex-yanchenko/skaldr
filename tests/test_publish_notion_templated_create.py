import json
from collections.abc import Callable
from typing import Any

import pytest

from skaldr.errors import CreatedButUnfinishedError, WriteRejectedError
from skaldr.publish.content import ItemContent
from skaldr.publish.transport import NewItem, Stamp
from skaldr.publish_block import NotionTarget
from tests.factories import NOTION_PAGE_ID, make_notion_target
from tests.factories.notion_factory import InMemoryNotion, Scripted, numbered_id

PARENT_PAGE_ID = "fedcba9876543210fedcba9876543210"
TEMPLATE_PAGE = "aabbccddeeff00112233445566778899"
OTHER_TEMPLATE_PAGE = "00112233445566778899aabbccddeeff"
BLANK_PAGE = "ffeeddccbbaa99887766554433221100"
FIRST_PAGE = numbered_id(1).replace("-", "")
STAMP = Stamp("garden-handbook", None)
STAMP_LINE = 'Published with skaldr from document garden-handbook {color="gray"}'
WELCOME = "## Welcome\nWelcome to the garden.\n"
PLANTING = "## Planting\nSow in spring.\n"
CONTENT = ItemContent(title="Garden handbook", sections={"intro": WELCOME, "planting": PLANTING})
TEMPLATE = {"type": "template_id", "template_id": TEMPLATE_PAGE}
TITLE = {"title": {"title": [{"type": "text", "text": {"content": "Garden handbook"}}]}}
PAGE_TARGET = NotionTarget.model_validate(make_notion_target(where={"parent_page": PARENT_PAGE_ID}))
TEMPLATED_TARGET = NotionTarget.model_validate(
    make_notion_target(where={"parent_page": PARENT_PAGE_ID, "template": TEMPLATE_PAGE})
)
UNTEMPLATED_TARGET = NotionTarget.model_validate(
    make_notion_target(where={"parent_page": PARENT_PAGE_ID, "template": "none"})
)
DATABASE_TARGET = NotionTarget.model_validate(make_notion_target())
TEMPLATED_DATABASE_TARGET = NotionTarget.model_validate(
    make_notion_target(where={"parent_page": NOTION_PAGE_ID, "template": TEMPLATE_PAGE})
)


def _notion(template_markdown: str = "") -> InMemoryNotion:
    notion = InMemoryNotion()
    notion.add_database(NOTION_PAGE_ID)
    notion.add_page(PARENT_PAGE_ID, "Team plans")
    notion.add_page(TEMPLATE_PAGE, "Page template", template_markdown)
    notion.add_page(OTHER_TEMPLATE_PAGE, "Another template", "")
    notion.add_page(BLANK_PAGE, "Blank page", "")
    return notion


def _workspace_template(page: str | None) -> Callable[[], str | None]:
    return lambda: page


def _sent(notion: InMemoryNotion) -> list[tuple[str, str, Any]]:
    return [
        (request.method, request.url.path, json.loads(request.content) if request.content else None)
        for request in notion.requests
    ]


def _created_with_markdown(notion: InMemoryNotion) -> list[dict[str, Any]]:
    return [body for method, path, body in _sent(notion) if (method, path) == ("POST", "/v1/pages")]


def _fills(markdown: str) -> dict[str, Any]:
    return {
        "type": "replace_content",
        "replace_content": {"new_str": markdown},
        "allow_async": True,
    }


def _templated_create_requests(
    template: str, parent: str = PARENT_PAGE_ID, first_page: str = FIRST_PAGE, task: int = 5
) -> list[tuple[str, str, Any]]:
    markdown = f"{WELCOME}{PLANTING}{STAMP_LINE}\n"
    return [
        ("GET", f"/v1/blocks/{parent}", None),
        ("GET", f"/v1/pages/{template}", None),
        ("GET", f"/v1/pages/{template}/markdown", None),
        (
            "POST",
            "/v1/pages",
            {
                "parent": {"page_id": parent},
                "properties": TITLE,
                "template": {"type": "template_id", "template_id": template},
            },
        ),
        ("PATCH", f"/v1/pages/{first_page}/markdown", _fills(markdown)),
        ("GET", f"/v1/async_tasks/task-{task}", None),
        ("GET", f"/v1/pages/{first_page}/markdown", None),
        ("GET", f"/v1/pages/{first_page}", None),
    ]


def test_a_page_is_created_from_the_template_the_target_names_with_no_content_and_filled_after() -> None:
    notion = _notion()

    created = notion.transport().create_item(NewItem(TEMPLATED_TARGET, STAMP, CONTENT))

    assert (_sent(notion), notion.markdown_of(created.item_id), list(created.raw_sections)) == (
        _templated_create_requests(TEMPLATE_PAGE),
        f"{WELCOME}{PLANTING}{STAMP_LINE}",
        ["intro", "planting"],
    )


def test_a_page_is_created_from_the_workspace_template_when_the_target_names_none() -> None:
    notion = _notion()

    notion.transport(_workspace_template(TEMPLATE_PAGE)).create_item(NewItem(PAGE_TARGET, STAMP, CONTENT))

    assert _sent(notion) == _templated_create_requests(TEMPLATE_PAGE)


def test_a_template_the_target_names_wins_over_the_workspace_template() -> None:
    notion = _notion()

    notion.transport(_workspace_template(OTHER_TEMPLATE_PAGE)).create_item(
        NewItem(TEMPLATED_TARGET, STAMP, CONTENT)
    )

    assert _sent(notion) == _templated_create_requests(TEMPLATE_PAGE)


def test_a_target_that_turns_the_template_off_sends_the_same_requests_as_a_workspace_without_one() -> None:
    with_default = _notion()
    without = _notion()

    with_default.transport(_workspace_template(TEMPLATE_PAGE)).create_item(
        NewItem(UNTEMPLATED_TARGET, STAMP, CONTENT)
    )
    without.transport().create_item(NewItem(PAGE_TARGET, STAMP, CONTENT))

    assert (_sent(with_default), "template" in json.dumps(_sent(with_default))) == (_sent(without), False)


def test_a_workspace_without_a_template_creates_with_the_markdown_in_the_create_request() -> None:
    notion = _notion()

    notion.transport().create_item(NewItem(PAGE_TARGET, STAMP, CONTENT))

    assert _created_with_markdown(notion) == [
        {
            "parent": {"page_id": PARENT_PAGE_ID},
            "properties": TITLE,
            "markdown": f"{WELCOME}{PLANTING}{STAMP_LINE}\n",
            "allow_async": True,
        }
    ]


def test_the_workspace_template_is_read_once_for_a_run_and_checked_once() -> None:
    notion = _notion()
    reads: list[str] = []

    def workspace_template() -> str:
        reads.append("read")
        return TEMPLATE_PAGE

    transport = notion.transport(workspace_template)
    document = transport.create_item(NewItem(PAGE_TARGET, STAMP, CONTENT))
    child = transport.create_item(NewItem(PAGE_TARGET, STAMP, CONTENT, parent_id=document.item_id))

    sent = _sent(notion)
    assert (
        reads,
        [path for _, path, _ in sent if path == f"/v1/pages/{TEMPLATE_PAGE}/markdown"],
        [body for method, path, body in sent if (method, path) == ("POST", "/v1/pages")],
        child.item_id,
    ) == (
        ["read"],
        [f"/v1/pages/{TEMPLATE_PAGE}/markdown"],
        [
            {"parent": {"page_id": PARENT_PAGE_ID}, "properties": TITLE, "template": TEMPLATE},
            {"parent": {"page_id": document.item_id}, "properties": TITLE, "template": TEMPLATE},
        ],
        numbered_id(2).replace("-", ""),
    )


def test_a_template_that_is_not_empty_stops_the_create_before_anything_is_made() -> None:
    notion = _notion("## Boilerplate\n")

    with pytest.raises(WriteRejectedError) as caught:
        notion.transport().create_item(NewItem(TEMPLATED_TARGET, STAMP, CONTENT))

    assert (str(caught.value), notion.writes()) == (
        f"the Notion template page {TEMPLATE_PAGE} is not empty, so Notion would copy its content into every "
        "page skaldr creates from it; empty the page in Notion, or choose another template page",
        [],
    )


def test_a_refused_template_is_checked_again_by_the_next_create_of_the_run() -> None:
    notion = _notion("## Boilerplate\n")
    transport = notion.transport(_workspace_template(TEMPLATE_PAGE))
    with pytest.raises(WriteRejectedError, match="is not empty"):
        transport.create_item(NewItem(PAGE_TARGET, STAMP, CONTENT))
    notion.pages[TEMPLATE_PAGE].markdown = ""

    created = transport.create_item(NewItem(PAGE_TARGET, STAMP, CONTENT))

    assert notion.markdown_of(created.item_id) == f"{WELCOME}{PLANTING}{STAMP_LINE}"


def test_a_template_the_sign_in_cannot_see_stops_the_create_before_anything_is_made() -> None:
    notion = InMemoryNotion()
    notion.add_page(PARENT_PAGE_ID, "Team plans")

    with pytest.raises(WriteRejectedError) as caught:
        notion.transport(_workspace_template(TEMPLATE_PAGE)).create_item(NewItem(PAGE_TARGET, STAMP, CONTENT))

    assert (str(caught.value), notion.writes()) == (
        f"the Notion template page {TEMPLATE_PAGE} cannot be read: it does not exist, or it is not shared "
        "with the connection skaldr signs in with; share the page with the connection in Notion, or choose "
        "another template page",
        [],
    )


def test_a_template_named_for_a_database_parent_is_refused_before_anything_is_made() -> None:
    notion = _notion()

    with pytest.raises(WriteRejectedError) as caught:
        notion.transport().create_item(NewItem(TEMPLATED_DATABASE_TARGET, STAMP, CONTENT))

    assert (str(caught.value), notion.writes()) == (
        f"Notion database {NOTION_PAGE_ID} does not take a page template, so skaldr cannot create its rows "
        "from one; remove `template` from the target's `where`, or set it to `none`",
        [],
    )


def test_the_workspace_template_is_not_applied_to_a_row_of_a_database() -> None:
    notion = _notion()

    notion.transport(_workspace_template(TEMPLATE_PAGE)).create_item(NewItem(DATABASE_TARGET, STAMP, CONTENT))

    assert (
        "template" in json.dumps(_sent(notion)),
        [path for _, path, _ in _sent(notion) if TEMPLATE_PAGE in path],
    ) == (False, [])


def test_a_page_under_a_row_of_a_database_is_not_created_from_the_workspace_template() -> None:
    notion = _notion()
    transport = notion.transport(_workspace_template(TEMPLATE_PAGE))
    row = transport.create_item(NewItem(DATABASE_TARGET, STAMP, CONTENT))
    notion.requests.clear()
    fresh_run = notion.transport(_workspace_template(TEMPLATE_PAGE))

    fresh_run.create_item(NewItem(DATABASE_TARGET, STAMP, CONTENT, parent_id=row.item_id))

    assert _sent(notion)[:2] == [
        ("GET", f"/v1/blocks/{NOTION_PAGE_ID}", None),
        (
            "POST",
            "/v1/pages",
            {
                "parent": {"page_id": row.item_id},
                "properties": TITLE,
                "markdown": f"{WELCOME}{PLANTING}{STAMP_LINE}\n",
                "allow_async": True,
            },
        ),
    ]


def test_a_page_under_a_page_in_a_later_run_is_created_from_the_template_after_one_read_of_its_parent() -> (
    None
):
    notion = _notion()
    document = notion.transport().create_item(NewItem(PAGE_TARGET, STAMP, CONTENT))
    notion.requests.clear()

    notion.transport(_workspace_template(TEMPLATE_PAGE)).create_item(
        NewItem(PAGE_TARGET, STAMP, CONTENT, parent_id=document.item_id)
    )

    assert _sent(notion)[:4] == [
        ("GET", f"/v1/blocks/{PARENT_PAGE_ID}", None),
        ("GET", f"/v1/pages/{TEMPLATE_PAGE}", None),
        ("GET", f"/v1/pages/{TEMPLATE_PAGE}/markdown", None),
        (
            "POST",
            "/v1/pages",
            {"parent": {"page_id": document.item_id}, "properties": TITLE, "template": TEMPLATE},
        ),
    ]


def test_a_templated_page_over_one_create_is_filled_by_a_replace_then_appends_before_the_stamp() -> None:
    notion = _notion()
    sections = {
        key: f"## {key}\n" + "".join(f"- {key} {n}\n" for n in range(1_000)) for key in ("a", "b", "c")
    }

    created = notion.transport(_workspace_template(TEMPLATE_PAGE)).create_item(
        NewItem(PAGE_TARGET, STAMP, ItemContent(title="Big", sections=sections))
    )

    a, b, c = sections.values()
    patches = [body for method, _, body in _sent(notion) if method == "PATCH"]
    assert (patches, notion.markdown_of(created.item_id), list(created.raw_sections)) == (
        [
            _fills(f"{a}{b}{STAMP_LINE}\n"),
            {
                "type": "update_content",
                "update_content": {
                    "content_updates": [{"old_str": STAMP_LINE, "new_str": f"{c}{STAMP_LINE}"}]
                },
                "allow_async": True,
            },
        ],
        f"{a}{b}{c}{STAMP_LINE}",
        ["a", "b", "c"],
    )


def test_a_fill_that_fails_after_the_templated_create_is_not_a_rejected_write_because_the_page_exists() -> (
    None
):
    notion = _notion()
    refusal = {"object": "error", "status": 400, "code": "validation_error", "message": "refused"}
    notion.scripted = [Scripted(400, refusal, method="PATCH")]

    with pytest.raises(CreatedButUnfinishedError) as caught:
        notion.transport(_workspace_template(TEMPLATE_PAGE)).create_item(NewItem(PAGE_TARGET, STAMP, CONTENT))

    assert (caught.value.item_id, str(caught.value), notion.markdown_of(FIRST_PAGE)) == (
        FIRST_PAGE,
        "skaldr created Notion page "
        f'{FIRST_PAGE} for "Garden handbook" but could not finish writing it: Notion refused to change the '
        f"content of page {FIRST_PAGE}: refused (validation_error); the next publish records it",
        "",
    )


def test_writing_into_an_existing_page_is_not_created_from_a_template() -> None:
    notion = _notion()

    notion.transport(_workspace_template(TEMPLATE_PAGE)).create_item(
        NewItem(PAGE_TARGET, STAMP, CONTENT, into_id=BLANK_PAGE)
    )

    assert (
        "template" in json.dumps(_sent(notion)),
        [path for _, path, _ in _sent(notion) if TEMPLATE_PAGE in path],
        notion.markdown_of(BLANK_PAGE),
    ) == (False, [], f"{WELCOME}{PLANTING}{STAMP_LINE}")
