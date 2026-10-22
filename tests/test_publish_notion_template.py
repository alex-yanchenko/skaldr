import pytest

from skaldr.errors import ConnectorError, WriteRejectedError
from skaldr.publish.notion.template import check_the_template_is_empty
from tests.factories.notion_factory import InMemoryNotion, Scripted

TEMPLATE_PAGE = "0123456789abcdef0123456789abcdef"
ADVICE = "choose another template page"


def _notion(markdown: str = "") -> InMemoryNotion:
    notion = InMemoryNotion()
    notion.add_page(TEMPLATE_PAGE, "Page template", markdown)
    return notion


def _requests(notion: InMemoryNotion) -> list[tuple[str, str]]:
    return [(request.method, request.url.path) for request in notion.requests]


def test_an_empty_template_page_the_sign_in_can_read_passes() -> None:
    notion = _notion()

    check_the_template_is_empty(notion.api(), TEMPLATE_PAGE)

    assert _requests(notion) == [
        ("GET", f"/v1/pages/{TEMPLATE_PAGE}"),
        ("GET", f"/v1/pages/{TEMPLATE_PAGE}/markdown"),
    ]


def test_a_template_page_with_content_is_refused_because_notion_copies_it_into_every_page() -> None:
    with pytest.raises(WriteRejectedError) as caught:
        check_the_template_is_empty(_notion("## Boilerplate\n").api(), TEMPLATE_PAGE)

    assert str(caught.value) == (
        f"the Notion template page {TEMPLATE_PAGE} is not empty, so Notion would copy its content into every "
        f"page skaldr creates from it; empty the page in Notion, or {ADVICE}"
    )


def test_a_template_page_holding_only_an_empty_block_is_refused() -> None:
    with pytest.raises(WriteRejectedError, match="is not empty"):
        check_the_template_is_empty(_notion("<empty-block/>").api(), TEMPLATE_PAGE)


def test_a_template_page_in_the_trash_is_refused() -> None:
    notion = _notion()
    notion.pages[TEMPLATE_PAGE].in_trash = True

    with pytest.raises(WriteRejectedError) as caught:
        check_the_template_is_empty(notion.api(), TEMPLATE_PAGE)

    assert str(caught.value) == (
        f"the Notion template page {TEMPLATE_PAGE} is in the trash; restore it in Notion, or {ADVICE}"
    )


def test_a_template_page_the_sign_in_cannot_see_is_refused_with_how_to_share_it() -> None:
    with pytest.raises(WriteRejectedError) as caught:
        check_the_template_is_empty(InMemoryNotion().api(), TEMPLATE_PAGE)

    assert str(caught.value) == (
        f"the Notion template page {TEMPLATE_PAGE} cannot be read: it does not exist, or it is not shared "
        f"with the connection skaldr signs in with; share the page with the connection in Notion, or {ADVICE}"
    )


def test_a_notion_failure_that_is_not_a_missing_page_passes_through_as_it_is() -> None:
    notion = _notion()
    notion.scripted.append(
        Scripted(403, {"object": "error", "status": 403, "code": "restricted_resource", "message": "No."})
    )

    with pytest.raises(ConnectorError) as caught:
        check_the_template_is_empty(notion.api(), TEMPLATE_PAGE)

    assert (type(caught.value), str(caught.value)) == (
        ConnectorError,
        f"Notion could not read page {TEMPLATE_PAGE}: HTTP 403 restricted_resource: No.",
    )
