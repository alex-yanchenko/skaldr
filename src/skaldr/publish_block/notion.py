import re
from urllib.parse import urlsplit

from pydantic import Field, model_validator

from skaldr.frozen_model import FrozenModel
from skaldr.publish_block.target import JsonFields, Location, TargetBase
from skaldr.services import NotionService

NO_TEMPLATE = "none"
NOTION_HOSTS = ("notion.so", "notion.site", "notion.com")
DASHLESS_PAGE_ID_LENGTH = 32
DASHLESS_PAGE_ID = re.compile(rf"[0-9a-f]{{{DASHLESS_PAGE_ID_LENGTH}}}")
DASHED_PAGE_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
TITLED_PAGE_ID = re.compile(rf"[^/]+-([0-9a-f]{{{DASHLESS_PAGE_ID_LENGTH}}})")


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


def required_page_id(reference: str) -> str:
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
    workspace: str | None = Field(
        default=None,
        description="The id or name of the signed-in Notion workspace to publish with; needed only when "
        "signed in to several. Not part of the target's place.",
    )
    fields: JsonFields = Field(
        default_factory=JsonFields,
        description="Database property values when the target page is a database row; `overrides` changes "
        "them for one item.",
    )
    fields_from_sections: bool = Field(
        default=False,
        exclude_if=lambda opted_in: not opted_in,
        description="Whether each split section's own `fields` (status, priority, assignee, due, labels, "
        "estimate and extra keys) set the properties of its row, under this target's `fields` and the "
        "section's `overrides`. Off by default; turning it on makes every split section a row of the "
        "database `parent_page` names, and makes skaldr own those properties on every row.",
    )
    template: str | None = Field(
        default=None,
        exclude_if=lambda template: template is None,
        description="A Notion page URL or page id whose page settings (full width, small text) every page "
        "created under `parent_page` takes, or `none` to create them without the workspace's template. "
        "Without it the template set with `skaldr auth template notion` applies. The template page must "
        "be empty, and a parent that is a database does not take one. Not part of the target's place.",
    )

    @model_validator(mode="after")
    def _validate_page_reference(self) -> "NotionWhere":
        names_both_or_neither = (self.parent_page is None) == (self.page is None)
        if names_both_or_neither:
            raise ValueError("a notion target names exactly one of `parent_page` or `page`")
        required_page_id(self._page_reference)
        self._validate_template()
        self._validate_fields_from_sections()
        return self

    def _validate_fields_from_sections(self) -> None:
        if self.fields_from_sections and self.page is not None:
            raise ValueError(
                "`fields_from_sections` makes each split section a row of the database `parent_page` names, "
                "so it does not go with `page`"
            )

    def _validate_template(self) -> None:
        if self.template is None:
            return
        if self.page is not None:
            raise ValueError(
                "`template` applies to pages skaldr creates, so it goes with `parent_page`, not `page`"
            )
        if self.template != NO_TEMPLATE and notion_page_id(self.template) is None:
            raise ValueError(
                f"'{self.template}' is not a Notion page URL (notion.so, notion.site, notion.com) or a page "
                f"id, and not `{NO_TEMPLATE}`"
            )

    @property
    def template_page_id(self) -> str | None:
        if self.template is None or self.template == NO_TEMPLATE:
            return None
        return required_page_id(self.template)

    @property
    def _page_reference(self) -> str:
        reference = self.page if self.parent_page is None else self.parent_page
        assert reference is not None
        return reference

    @property
    def page_id(self) -> str:
        return required_page_id(self._page_reference)


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
