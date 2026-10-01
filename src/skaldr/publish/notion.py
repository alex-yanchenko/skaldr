import re
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, JsonValue, model_validator

from skaldr.frozen_model import FrozenModel
from skaldr.publish.target import Fields, PublishTargetBase

NOTION_HOSTS = ("notion.so", "notion.site", "notion.com")
DASHLESS_PAGE_ID = re.compile(r"[0-9a-f]{32}")
DASHED_PAGE_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
TITLED_PAGE_ID = re.compile(r".+-([0-9a-f]{32})")


def _is_notion_host(host: str) -> bool:
    return any(host == domain or host.endswith(f".{domain}") for domain in NOTION_HOSTS)


def notion_page_id(reference: str) -> str | None:
    candidate = reference.strip()
    if "://" in candidate:
        parsed = urlsplit(candidate)
        if parsed.scheme not in ("http", "https") or not _is_notion_host(parsed.hostname or ""):
            return None
        candidate = parsed.path.rstrip("/").rsplit("/", 1)[-1]
    candidate = candidate.lower()
    if DASHLESS_PAGE_ID.fullmatch(candidate):
        return candidate
    if DASHED_PAGE_ID.fullmatch(candidate):
        return candidate.replace("-", "")
    titled = TITLED_PAGE_ID.fullmatch(candidate)
    return titled.group(1) if titled else None


class NotionWhere(FrozenModel):
    parent_page: str | None = Field(
        default=None,
        description="A Notion page URL or page id the document is created under, as a child page.",
    )
    page: str | None = Field(
        default=None,
        description="A Notion page URL or page id the document is written into, replacing its content.",
    )
    fields: Fields = Field(
        default_factory=dict[str, JsonValue],
        description="Database property values, when the target page is a database row.",
    )

    @model_validator(mode="after")
    def _one_page_reference(self) -> "NotionWhere":
        if (self.parent_page is None) == (self.page is None):
            raise ValueError("a notion target names exactly one of `parent_page` or `page`")
        _required_page_id(self.page_reference)
        return self

    @property
    def page_reference(self) -> str:
        return self.parent_page if self.parent_page is not None else self.page or ""

    @property
    def page_id(self) -> str:
        return _required_page_id(self.page_reference)


def _required_page_id(reference: str) -> str:
    page_id = notion_page_id(reference)
    if page_id is None:
        raise ValueError(f"'{reference}' is not a Notion page URL or a 32-character page id")
    return page_id


class NotionTarget(PublishTargetBase):
    to: Literal["notion"] = Field(description="Publish to Notion.")
    where: NotionWhere = Field(description="The Notion page the document goes under or into.")

    def location_key(self) -> str:
        return f"notion page {self.where.page_id}"
