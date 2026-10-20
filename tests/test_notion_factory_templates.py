from typing import Any

import httpx2

from tests.factories.notion_factory import InMemoryNotion

TEMPLATE_PAGE = "0123456789abcdef0123456789abcdef"
PARENT_PAGE = "fedcba9876543210fedcba9876543210"
CONTENT_REFUSAL = (
    "Cannot specify 'content', 'children', or 'markdown' when using a template. "
    "The template will provide the page content."
)
TEMPLATE = {"type": "template_id", "template_id": TEMPLATE_PAGE}


def _notion(template_markdown: str) -> InMemoryNotion:
    notion = InMemoryNotion()
    notion.add_page(PARENT_PAGE, "Team plans")
    notion.add_page(TEMPLATE_PAGE, "Page template", template_markdown)
    return notion


def _client(notion: InMemoryNotion) -> httpx2.Client:
    return httpx2.Client(
        base_url="https://api.notion.com",
        transport=notion.mock(),
        headers={"Authorization": f"Bearer {notion.accepted_token}"},
    )


def _create(client: httpx2.Client, **fields: Any) -> httpx2.Response:
    return client.post(
        "/v1/pages",
        json={
            "parent": {"page_id": PARENT_PAGE},
            "properties": {"title": {"title": [{"text": {"content": "Garden"}}]}},
            **fields,
        },
    )


def _markdown_of(client: httpx2.Client, page_id: str) -> str:
    markdown: str = client.get(f"/v1/pages/{page_id}/markdown").json()["markdown"]
    return markdown


def test_a_page_created_from_a_template_with_no_content_is_made_synchronously_and_empty() -> None:
    client = _client(_notion(""))

    created = _create(client, template=TEMPLATE)

    assert (created.status_code, created.json()["object"], _markdown_of(client, created.json()["id"])) == (
        200,
        "page",
        "",
    )


def test_a_create_that_names_a_template_and_markdown_is_refused_with_the_live_text() -> None:
    client = _client(_notion(""))

    refused = _create(client, template=TEMPLATE, markdown="Welcome.")

    assert (refused.status_code, refused.json()) == (
        400,
        {"object": "error", "status": 400, "code": "validation_error", "message": CONTENT_REFUSAL},
    )


def test_a_create_that_names_a_template_and_children_or_content_is_refused_the_same_way() -> None:
    client = _client(_notion(""))

    refused = [_create(client, template=TEMPLATE, **{field: []}) for field in ("children", "content")]

    assert [(answer.status_code, answer.json()["message"]) for answer in refused] == [
        (400, CONTENT_REFUSAL),
        (400, CONTENT_REFUSAL),
    ]


def test_a_create_from_a_template_that_does_not_exist_is_not_found() -> None:
    client = _client(_notion(""))

    refused = _create(
        client, template={"type": "template_id", "template_id": "ffffffffffffffffffffffffffffffff"}
    )

    assert (refused.status_code, refused.json()["code"]) == (404, "object_not_found")


def test_the_content_of_a_non_empty_template_arrives_after_the_next_request_and_not_before() -> None:
    notion = _notion("## Boilerplate\n")
    client = _client(notion)
    page_id = _create(client, template=TEMPLATE).json()["id"]

    read_at_once = _markdown_of(client, page_id)
    read_a_moment_later = _markdown_of(client, page_id)

    assert (read_at_once, read_a_moment_later) == ("", "## Boilerplate")


def test_content_written_at_once_to_a_page_made_from_a_non_empty_template_gets_the_template_after_it() -> (
    None
):
    notion = _notion("## Boilerplate\n")
    client = _client(notion)
    page_id = _create(client, template=TEMPLATE).json()["id"]

    client.patch(
        f"/v1/pages/{page_id}/markdown",
        json={"type": "replace_content", "replace_content": {"new_str": "## Welcome\nHello.\n"}},
    )

    assert notion.markdown_of(page_id) == "## Welcome\nHello.\n## Boilerplate"


def test_content_written_at_once_to_a_page_made_from_an_empty_template_stays_as_written() -> None:
    notion = _notion("")
    client = _client(notion)
    page_id = _create(client, template=TEMPLATE).json()["id"]

    client.patch(
        f"/v1/pages/{page_id}/markdown",
        json={"type": "replace_content", "replace_content": {"new_str": "## Welcome\nHello.\n"}},
    )
    _markdown_of(client, page_id)

    assert notion.markdown_of(page_id) == "## Welcome\nHello."


def test_a_template_page_is_listed_under_its_parent_like_any_created_page() -> None:
    notion = _notion("")
    client = _client(notion)

    created = _create(client, template=TEMPLATE).json()

    assert notion.markdown_of(PARENT_PAGE).endswith(
        f'<page url="https://www.notion.so/{created["id"].replace("-", "")}">Garden</page>'
    )
