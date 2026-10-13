import re
from urllib.parse import urlsplit

from pydantic import Field, model_validator

from skaldr.frozen_model import FrozenModel
from skaldr.publish_block.target import JsonFields, Location, TargetBase
from skaldr.services import NotionService

NOTION_HOSTS = ("notion.so", "notion.site", "notion.com")
DASHLESS_PAGE_ID = re.compile(r"[0-9a-f]{32}")
DASHED_PAGE_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
TITLED_PAGE_ID = re.compile(r"[^/]+-([0-9a-f]{32})")


def _is_notion_host(host: str) -> bool:
    return any(host == domain or host.endswith(f".{domain}") for domain in NOTION_HOSTS)


def _last_url_segment(url: str) -> str | None:
    parsed = urlsplit(url)
    if parsed.scheme not in ("http", "https") or not _is_notion_host(parsed.hostname or ""):
        return None
    return parsed.path.rstrip("/").rsplit("/", 1)[-1]


def notion_page_id(reference: str) -> str | None:
    candidate = reference.strip()
    if "://" in candidate:
        segment = _last_url_segment(candidate)
        if segment is None:
            return None
        candidate = segment
    elif "/" in candidate:
        return None
    candidate = candidate.lower()
    if DASHLESS_PAGE_ID.fullmatch(candidate):
        return candidate
    if DASHED_PAGE_ID.fullmatch(candidate):
        return candidate.replace("-", "")
    titled = TITLED_PAGE_ID.fullmatch(candidate)
    return titled.group(1) if titled else None


def _required_page_id(reference: str) -> str:
    page_id = notion_page_id(reference)
    if page_id is None:
        raise ValueError(
            f"'{reference}' is not a Notion page URL (notion.so, notion.site, notion.com) or a page id"
        )
    return page_id


class NotionWhere(FrozenModel):
    parent_page: str | None = Field(
        default=None,
        description="A Notion page URL or page id the document is created under, as a child page.",
    )
    page: str | None = Field(
        default=None,
        description="A Notion page URL or page id the document is written into, replacing its content.",
    )
    fields: JsonFields = Field(
        default_factory=JsonFields,
        description="Database property values when the target page is a database row; `overrides` changes "
        "them for one item.",
    )

    @model_validator(mode="after")
    def _validate_page_reference(self) -> "NotionWhere":
        names_both_or_neither = (self.parent_page is None) == (self.page is None)
        if names_both_or_neither:
            raise ValueError("a notion target names exactly one of `parent_page` or `page`")
        _required_page_id(self._page_reference)
        return self

    @property
    def _page_reference(self) -> str:
        return self.parent_page if self.parent_page is not None else self.page or ""

    @property
    def page_id(self) -> str:
        return _required_page_id(self._page_reference)


class NotionTarget(TargetBase):
    to: NotionService = Field(description="Publish to Notion: `notion`.")
    where: NotionWhere = Field(description="The Notion page the document goes under or into.")

    def where_fields(self) -> JsonFields:
        return self.where.fields

    def location_label(self) -> str:
        written_into = " (written into)" if self.where.page is not None else ""
        return f"{self.place_label()}{written_into}"

    def place_key(self) -> Location:
        return ("notion", self.where.page_id)

    def place_label(self) -> str:
        return f"notion page {self.where.page_id}"
