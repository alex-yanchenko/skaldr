from skaldr.errors import ItemNotFoundError, WriteRejectedError
from skaldr.publish.notion.api import NotionApi

_ANOTHER_PAGE = "choose another template page"


def check_the_template_is_empty(api: NotionApi, page_id: str) -> None:
    try:
        page = api.page(page_id)
    except ItemNotFoundError as exc:
        raise WriteRejectedError(
            f"the Notion template page {page_id} cannot be read: it does not exist, or it is not shared with "
            "the connection skaldr signs in with; share the page with the connection in Notion, or "
            f"{_ANOTHER_PAGE}"
        ) from exc
    if page.in_trash:
        raise WriteRejectedError(
            f"the Notion template page {page_id} is in the trash; restore it in Notion, or {_ANOTHER_PAGE}"
        )
    if api.page_markdown(page_id).markdown.strip():
        raise WriteRejectedError(
            f"the Notion template page {page_id} is not empty, so Notion would copy its content into every "
            f"page skaldr creates from it; empty the page in Notion, or {_ANOTHER_PAGE}"
        )
