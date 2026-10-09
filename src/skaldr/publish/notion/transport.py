from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Final, TypeVar

from pydantic import JsonValue

from skaldr.errors import AuthError, ConnectorError, ItemNotFoundError, WriteRejectedError
from skaldr.export.budget import json_string_bytes
from skaldr.export.notion import notion_block_count
from skaldr.publish.content import (
    ItemContent,
    Part,
    differing_parts,
    is_unset,
    placed_section,
    with_fields_named,
)
from skaldr.publish.notion.api import NotionApi
from skaldr.publish.notion.page_markdown import (
    KeyedPage,
    Replacement,
    comparable_text,
    joined,
    keyed_page,
    section_replacement,
    stamp_line,
)
from skaldr.publish.notion.properties import (
    property_fields,
    property_request,
    set_property_names,
    title_request,
    title_text,
)
from skaldr.publish.notion.responses import Page
from skaldr.publish.transport import (
    AddSection,
    ContentWrite,
    FieldsWrite,
    NewItem,
    RawSections,
    Release,
    RemoteItem,
    RemoveSection,
    SectionRequest,
)
from skaldr.publish_block import NotionTarget, notion_page_id
from skaldr.publish_block.target import JsonFields

CREATE_BLOCKS: Final = 5000
CREATE_JSON_BYTES: Final = 450_000
STAMP_BLOCKS: Final = 1
SECTION_BLOCKS: Final = CREATE_BLOCKS - STAMP_BLOCKS
SECTION_JSON_BYTES: Final = 200_000
DATABASE_BLOCK: Final = "child_database"
PAGE_BLOCK: Final = "child_page"

Answer = TypeVar("Answer")


def _page_key(item_id: str) -> str:
    return notion_page_id(item_id) or item_id


def _pairs(sections: Mapping[str, str]) -> list[tuple[str, str]]:
    return list(sections.items())


def _update_content(replacement: Replacement) -> JsonFields:
    return {
        "type": "update_content",
        "update_content": {
            "content_updates": [{"old_str": replacement.old_str, "new_str": replacement.new_str}]
        },
    }


def _replace_content(markdown: str) -> JsonFields:
    return {"type": "replace_content", "replace_content": {"new_str": markdown}}


def _create_batches(texts: Sequence[str], stamp: str) -> list[list[str]]:
    stamp_blocks, stamp_bytes = notion_block_count(stamp), json_string_bytes(stamp)
    batches: list[list[str]] = [[]]
    blocks, size = stamp_blocks, stamp_bytes
    for text in texts:
        text_blocks, text_bytes = notion_block_count(text), json_string_bytes(text)
        too_big = blocks + text_blocks > CREATE_BLOCKS or size + text_bytes > CREATE_JSON_BYTES
        if batches[-1] and too_big:
            batches.append([])
            blocks, size = stamp_blocks, stamp_bytes
        batches[-1].append(text)
        blocks += text_blocks
        size += text_bytes
    return batches


def _with_nothing_sent(prepare: Callable[[], Answer]) -> Answer:
    try:
        return prepare()
    except WriteRejectedError:
        raise
    except (ConnectorError, AuthError) as exc:
        raise WriteRejectedError(str(exc)) from exc


def _refused_or_unknown(send: Callable[[], Answer]) -> Answer:
    try:
        return send()
    except (ItemNotFoundError, AuthError) as exc:
        raise WriteRejectedError(str(exc)) from exc


def _finished_after_a_change(page_id: str, title: str, finish: Callable[[], Answer]) -> Answer:
    try:
        return finish()
    except (ConnectorError, AuthError) as exc:
        raise ConnectorError(
            f'skaldr wrote Notion page {page_id} for "{title}" but could not finish writing it: {exc}'
        ) from exc


@dataclass(frozen=True)
class _Parent:
    request: JsonFields
    property_kinds: Mapping[str, str]
    names_a_database: bool
    page_id: str


class NotionTransport:
    def __init__(self, api: NotionApi) -> None:
        self._api = api
        self._layouts: dict[str, dict[str, str]] = {}
        self._written: set[str] = set()
        self._bot_id: str | None = None

    def comparable_form(self, content: ItemContent, /) -> ItemContent:
        sections = {key: comparable_text(text) for key, text in content.sections.items()}
        return content.model_copy(update={"sections": {key: text for key, text in sections.items() if text}})

    def read_item(self, item_id: str, keyed_like: ItemContent, /) -> RemoteItem:
        page = self._live_page(item_id)
        markdown = self._api.page_markdown(item_id).markdown
        return self._remote(item_id, page, markdown, self._layout_to_read(item_id, keyed_like))

    def create_item(self, request: NewItem, /) -> RemoteItem:
        if request.into_id is not None:
            return self._create_into(request.into_id, request)
        stamp = stamp_line(request.stamp)
        batches = _create_batches(list(request.content.sections.values()), stamp)
        body = _with_nothing_sent(lambda: self._create_body(request, batches[0], stamp))
        page = _refused_or_unknown(lambda: self._api.create_page(body))
        item_id = _page_key(page.id)
        return _finished_after_a_change(
            item_id, request.content.title, lambda: self._finish_create(item_id, request.content, batches[1:])
        )

    def write_section(self, item_id: str, request: SectionRequest, /) -> RemoteItem:
        change = request.change
        current = _pairs(request.raw_sections)
        if not isinstance(change, AddSection):
            current = [(key, change.raw_current if key == change.key else text) for key, text in current]
        text = None if isinstance(change, RemoveSection) else change.text
        follows = None if isinstance(change, RemoveSection) else change.follows
        after = _pairs(placed_section(dict(current), change.key, text, follows))
        replacement = section_replacement(current, after, None) or self._anchored_on_the_stamp(
            item_id, current, after
        )
        return self._written_with(item_id, replacement, dict(after))

    def write_content(self, item_id: str, request: ContentWrite, /) -> RemoteItem:
        keyed = self._unchanged_since_read(item_id, request.raw_sections)
        replacement = section_replacement(
            _pairs(keyed.raw_sections), _pairs(request.sections), keyed.stamp_line
        )
        if replacement is None:
            raise WriteRejectedError(
                f"Notion page {item_id} holds nothing skaldr can place its content next to"
            )
        return self._written_with(item_id, replacement, request.sections)

    def write_fields(self, item_id: str, request: FieldsWrite, /) -> RemoteItem:
        page = self._live_page(item_id)
        markdown = self._api.page_markdown(item_id).markdown
        layout = self._layouts.get(_page_key(item_id), {})
        stamp = keyed_page(markdown, layout).stamp
        if stamp is None or stamp.doc_id != request.stamp.doc_id:
            raise WriteRejectedError(
                f"Notion page {item_id} is not stamped with doc_id '{request.stamp.doc_id}'"
            )
        title = title_request(request.title) if request.changes_the_title else {}
        values: JsonFields = {
            **request.changed_fields,
            **dict.fromkeys(request.cleared_fields),
        }
        properties = {**title, **self._property_requests(page, values)}
        if properties:
            page = self._api.update_page(item_id, {"properties": properties})
        return self._remote(item_id, page, markdown, layout)

    def archive_item(self, item_id: str, /) -> None:
        try:
            self._live_page(item_id)
        except ItemNotFoundError:
            return
        self._api.update_page(item_id, {"in_trash": True})

    def release_item(self, item_id: str, request: Release, /) -> None:
        keyed = self._unchanged_since_read(item_id, request.raw_sections)
        written = joined([*keyed.raw_sections.values(), keyed.stamp_line or ""])
        if written:
            self._api.update_markdown(item_id, _update_content(Replacement(written, "")))
        self._layouts[_page_key(item_id)] = {}
        self._written.add(_page_key(item_id))
        page = self._live_page(item_id)
        set_now = set_property_names(page)
        cleared = {name: None for name in request.field_names if name in set_now}
        if cleared:
            self._api.update_page(item_id, {"properties": self._property_requests(page, dict(cleared))})

    def parts_edited_after(
        self, item_id: str, marker: str | None, keyed_like: ItemContent, /
    ) -> tuple[Part, ...]:
        page = self._live_page(item_id)
        if not self._edited_by_someone_else(page, marker):
            return ()
        markdown = self._api.page_markdown(item_id).markdown
        read = self._remote(item_id, page, markdown, self._layout_to_read(item_id, keyed_like))
        current = with_fields_named(read.comparable, list(keyed_like.fields))
        return differing_parts(self.comparable_form(keyed_like), current)

    def _live_page(self, item_id: str) -> Page:
        if notion_page_id(item_id) is None:
            raise ItemNotFoundError(f"'{item_id}' is not a Notion page id")
        page = self._api.page(item_id)
        if page.in_trash:
            raise ItemNotFoundError(f"Notion page {item_id} is in the trash")
        return page

    def _layout_to_read(self, item_id: str, keyed_like: ItemContent) -> Mapping[str, str]:
        key = _page_key(item_id)
        if key in self._written:
            return self._layouts[key]
        return keyed_like.sections or self._layouts.get(key, {})

    def _remote(self, item_id: str, page: Page, markdown: str, layout: Mapping[str, str]) -> RemoteItem:
        keyed = keyed_page(markdown, layout)
        self._layouts[_page_key(item_id)] = keyed.sections
        edited_at = page.last_edited_time.isoformat()
        return RemoteItem(
            item_id,
            ItemContent(title=title_text(page), sections=keyed.sections, fields=property_fields(page)),
            keyed.raw_sections,
            keyed.stamp,
            marker=edited_at,
            edited_by=page.last_edited_by.id,
            edited_at=edited_at,
            child_ids=keyed.child_ids,
            set_properties=set_property_names(page),
        )

    def _written_with(self, item_id: str, replacement: Replacement, layout: Mapping[str, str]) -> RemoteItem:
        key = _page_key(item_id)
        if replacement.changes_nothing:
            markdown = self._api.page_markdown(item_id).markdown
        else:
            markdown = self._api.update_markdown(item_id, _update_content(replacement)).markdown
        self._written.add(key)
        return self._remote(item_id, self._live_page(item_id), markdown, layout)

    def _anchored_on_the_stamp(
        self, item_id: str, current: Sequence[tuple[str, str]], after: Sequence[tuple[str, str]]
    ) -> Replacement:
        stamp = keyed_page(self._api.page_markdown(item_id).markdown, dict(current)).stamp_line
        replacement = section_replacement(current, after, stamp)
        if replacement is None:
            raise WriteRejectedError(
                f"Notion page {item_id} holds nothing skaldr can place the section next to"
            )
        return replacement

    def _unchanged_since_read(self, item_id: str, raw_sections: RawSections) -> KeyedPage:
        keyed = keyed_page(self._api.page_markdown(item_id).markdown, raw_sections)
        if _pairs(keyed.raw_sections) != _pairs(raw_sections):
            raise WriteRejectedError(
                f"Notion page {item_id} changed after skaldr read it, so nothing was written; publish again"
            )
        return keyed

    def _edited_by_someone_else(self, page: Page, marker: str | None) -> bool:
        if self._bot_id is None:
            self._bot_id = self._api.me().id
        if page.last_edited_by.id == self._bot_id:
            return False
        if marker is None:
            return True
        try:
            published_at = datetime.fromisoformat(marker)
        except ValueError:
            return True
        return page.last_edited_time >= published_at

    def _property_requests(self, page: Page, values: Mapping[str, JsonValue]) -> JsonFields:
        kinds = {name: value.type for name, value in page.properties.items()}
        return _property_requests(kinds, values, f"Notion page {_page_key(page.id)}")

    def _parent(self, request: NewItem) -> _Parent:
        if request.parent_id is not None:
            return _Parent(
                {"page_id": request.parent_id}, {}, names_a_database=False, page_id=request.parent_id
            )
        target = request.target
        if not isinstance(target, NotionTarget):
            raise WriteRejectedError(f"the Notion connector cannot publish to {target.place_label()}")
        parent_id = target.where.page_id
        block = self._api.block(parent_id)
        if block.type == PAGE_BLOCK:
            return _Parent({"page_id": parent_id}, {}, names_a_database=False, page_id=parent_id)
        if block.type != DATABASE_BLOCK:
            raise WriteRejectedError(
                f"Notion block {parent_id} is a {block.type}, not a page or a database, so skaldr cannot "
                "create a page under it"
            )
        sources = self._api.database(parent_id).data_sources
        if len(sources) != 1:
            raise WriteRejectedError(
                f"Notion database {parent_id} has {len(sources)} data sources; skaldr adds rows only to a "
                "database with one"
            )
        source = self._api.data_source(sources[0].id)
        kinds = {name: schema.type for name, schema in source.properties.items()}
        return _Parent({"data_source_id": source.id}, kinds, names_a_database=True, page_id=parent_id)

    def _create_body(self, request: NewItem, first_batch: Sequence[str], stamp: str) -> JsonFields:
        parent = self._parent(request)
        values = {name: value for name, value in request.content.fields.items() if not is_unset(value)}
        if values and not parent.names_a_database:
            name = next(iter(values))
            raise WriteRejectedError(
                f"the field '{name}' cannot be set on a page created under the Notion page {parent.page_id}: "
                "only a row of a Notion database has properties; clear it for this item with `overrides`, or "
                "publish under a database"
            )
        properties = {
            **title_request(request.content.title),
            **_property_requests(parent.property_kinds, values, f"Notion database {parent.page_id}"),
        }
        return {"parent": parent.request, "properties": properties, "markdown": joined([*first_batch, stamp])}

    def _finish_create(
        self, item_id: str, content: ItemContent, later_batches: Sequence[Sequence[str]]
    ) -> RemoteItem:
        markdown = self._api.page_markdown(item_id).markdown
        for batch in later_batches:
            stamp = keyed_page(markdown, {}).stamp_line or ""
            markdown = self._api.update_markdown(
                item_id, _update_content(Replacement(stamp, joined([*batch, stamp])))
            ).markdown
        layout = self.comparable_form(content).sections
        self._written.add(_page_key(item_id))
        return self._remote(item_id, self._live_page(item_id), markdown, layout)

    def _into_properties(self, item_id: str, request: NewItem) -> JsonFields:
        self._unchanged_since_read(item_id, request.into_raw_sections)
        page = self._live_page(item_id)
        values = {name: value for name, value in request.content.fields.items() if not is_unset(value)}
        return {**title_request(request.content.title), **self._property_requests(page, values)}

    def _create_into(self, item_id: str, request: NewItem) -> RemoteItem:
        content = request.content
        stamp = stamp_line(request.stamp)
        batches = _create_batches(list(content.sections.values()), stamp)
        properties = _with_nothing_sent(lambda: self._into_properties(item_id, request))
        _refused_or_unknown(
            lambda: self._api.update_markdown(item_id, _replace_content(joined([*batches[0], stamp])))
        )

        def finish() -> RemoteItem:
            self._api.update_page(item_id, {"properties": properties})
            return self._finish_create(item_id, content, batches[1:])

        return _finished_after_a_change(item_id, content.title, finish)


def _property_requests(kinds: Mapping[str, str], values: Mapping[str, JsonValue], holder: str) -> JsonFields:
    requests: JsonFields = {}
    for name, value in values.items():
        kind = kinds.get(name)
        if kind is None:
            raise WriteRejectedError(f"{holder} has no property '{name}'")
        if kind == "title":
            raise WriteRejectedError(
                f"'{name}' is the title of {holder}; skaldr sets it from the document's title, not from "
                "`fields`"
            )
        requests[name] = property_request(name, kind, value)
    return requests
