from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Final, TypeVar

from pydantic import JsonValue

from skaldr.errors import AuthError, ConnectorError, ItemNotFoundError, WriteRejectedError
from skaldr.export.budget import json_string_bytes
from skaldr.export.notion import notion_block_count
from skaldr.publish.content import ItemContent, Part, is_unset, placed_section
from skaldr.publish.notion.api import NotionApi
from skaldr.publish.notion.page_markdown import (
    KeyedPage,
    Replacement,
    carried_into,
    comparable_text,
    holds_an_unknown_block,
    joined,
    keyed_page,
    release_replacements,
    section_replacement,
    stamp_line,
)
from skaldr.publish.notion.properties import (
    TITLE_PROPERTY_ID,
    property_fields,
    property_request,
    set_property_names,
    title_property_name,
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
    Stamp,
)
from skaldr.publish_block import NotionTarget, notion_page_id
from skaldr.publish_block.target import JsonFields

CREATE_BLOCKS: Final = 5000
REQUEST_JSON_BYTES: Final = 450_000
STAMP_BLOCKS: Final = 1
SECTION_BLOCKS: Final = CREATE_BLOCKS - STAMP_BLOCKS
SECTION_JSON_BYTES: Final = 200_000
DATABASE_BLOCK: Final = "child_database"
PAGE_BLOCK: Final = "child_page"
STAMP_KEY: Final = "skaldr stamp"

Answer = TypeVar("Answer")


def _page_key(item_id: str) -> str:
    return notion_page_id(item_id) or item_id


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
        too_big = blocks + text_blocks > CREATE_BLOCKS or size + text_bytes > REQUEST_JSON_BYTES
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


def _with_children_of_removed_sections(
    current: Mapping[str, str], after: Sequence[tuple[str, str]]
) -> list[tuple[str, str]]:
    texts = dict(after)
    order = list(current)
    for index, key in enumerate(order):
        children = "" if key in texts else carried_into(current[key], "")
        if not children:
            continue
        earlier = next((other for other in reversed(order[:index]) if other in texts), None)
        later = next((other for other in [*order[index + 1 :], *texts] if other in texts), None)
        if earlier is not None:
            texts[earlier] = joined([texts[earlier], children])
        elif later is not None:
            texts[later] = joined([children, texts[later]])
    return [(key, texts[key]) for key, _ in after]


def _quoted_sections(replacement: Replacement) -> str:
    return ", ".join(replacement.quoted) or "none"


def _refuse_what_one_request_cannot_carry(item_id: str, replacement: Replacement) -> None:
    size = json_string_bytes(replacement.old_str) + json_string_bytes(replacement.new_str)
    blocks = notion_block_count(replacement.new_str)
    if size <= REQUEST_JSON_BYTES and blocks <= CREATE_BLOCKS:
        return
    measured = (
        f"{size:,} bytes of JSON in one request, over the {REQUEST_JSON_BYTES:,}"
        if size > REQUEST_JSON_BYTES
        else f"{blocks:,} Notion blocks in one request, over the {CREATE_BLOCKS:,}"
    )
    raise WriteRejectedError(
        f"the write to Notion page {item_id} quotes sections {_quoted_sections(replacement)} and would send "
        f"{measured} one request may carry; give one of those sections its own page with `split`"
    )


def _refuse_unknown_blocks(item_id: str, sections: Mapping[str, str], replacement: Replacement) -> None:
    if not holds_an_unknown_block(replacement.old_str):
        return
    holding = next((key for key in replacement.quoted if holds_an_unknown_block(sections.get(key, ""))), None)
    where = f"section {holding} of " if holding is not None else ""
    raise WriteRejectedError(
        f"{where}Notion page {item_id} holds a block Notion does not show as Markdown, so skaldr will not "
        "rewrite it; change or remove that block in Notion first"
    )


@dataclass(frozen=True)
class _Parent:
    request: JsonFields
    property_kinds: Mapping[str, str]
    names_a_database: bool
    page_id: str

    @property
    def title_name(self) -> str:
        return next(
            (name for name, kind in self.property_kinds.items() if kind == "title"), TITLE_PROPERTY_ID
        )


class NotionTransport:
    def __init__(self, api: NotionApi) -> None:
        self._api = api
        self._layouts: dict[str, Mapping[str, str]] = {}
        self._published: dict[str, Mapping[str, str]] = {}
        self._written: set[str] = set()

    def comparable_form(self, content: ItemContent, /) -> ItemContent:
        sections = {key: comparable_text(text) for key, text in content.sections.items()}
        return content.model_copy(update={"sections": {key: text for key, text in sections.items() if text}})

    def read_item(self, item_id: str, keyed_like: ItemContent, /) -> RemoteItem:
        page = self._live_page(item_id)
        markdown = self._api.page_markdown(item_id).markdown
        key = _page_key(item_id)
        if key not in self._written and keyed_like.sections:
            self._published[key] = keyed_like.sections
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
        current = dict(request.raw_sections)
        if not isinstance(change, AddSection):
            current[change.key] = change.raw_current
        keys = list(current)
        follows = (
            (keys[keys.index(change.key) - 1] if keys.index(change.key) > 0 else None)
            if isinstance(change, RemoveSection)
            else change.follows
        )
        new_text = carried_into(
            current.get(change.key, ""), "" if isinstance(change, RemoveSection) else change.text
        )
        kept = new_text or None if isinstance(change, RemoveSection) else new_text
        after = list(placed_section(current, change.key, kept, follows).items())
        keyed, markdown = self._unchanged_since_read(item_id, request.raw_sections)
        replacement = section_replacement(list(current.items()), after, markdown, keyed.stamp_line)
        if replacement is None:
            raise WriteRejectedError(
                f"Notion page {item_id} holds nothing skaldr can place the section next to"
            )
        return self._written_with(item_id, current, replacement, dict(after), markdown)

    def write_content(self, item_id: str, request: ContentWrite, /) -> RemoteItem:
        keyed, markdown = self._unchanged_since_read(item_id, request.raw_sections)
        current = keyed.raw_sections
        after = _with_children_of_removed_sections(
            current,
            [(key, carried_into(current.get(key, ""), text)) for key, text in request.sections.items()],
        )
        replacement = section_replacement(list(current.items()), after, markdown, keyed.stamp_line)
        if replacement is None:
            raise WriteRejectedError(
                f"Notion page {item_id} holds nothing skaldr can place its content next to"
            )
        return self._written_with(item_id, current, replacement, dict(after), markdown)

    def write_fields(self, item_id: str, request: FieldsWrite, /) -> RemoteItem:
        layout = self._layouts.get(_page_key(item_id))
        if layout is None:
            raise ConnectorError(
                f"skaldr has not read Notion page {item_id} in this run, so it cannot tell its sections apart"
            )
        page = self._live_page(item_id)
        markdown = self._api.page_markdown(item_id).markdown
        stamp = keyed_page(markdown, layout).stamp
        if stamp is not None and stamp.doc_id != request.stamp.doc_id:
            raise WriteRejectedError(
                f"Notion page {item_id} is not stamped with doc_id '{request.stamp.doc_id}'"
            )
        title = title_request(request.title, title_property_name(page)) if request.changes_the_title else {}
        values: JsonFields = {**request.changed_fields, **dict.fromkeys(request.cleared_fields)}
        properties = {**title, **self._property_requests(page, values)}
        if stamp is None:
            markdown = self._stamp_put_back(item_id, markdown, layout, request.stamp)
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
        keyed, markdown = self._unchanged_since_read(item_id, request.raw_sections)
        key = _page_key(item_id)
        layout = self._published.get(key, request.raw_sections)
        for replacement in release_replacements(markdown, layout, REQUEST_JSON_BYTES):
            self._send(item_id, keyed.raw_sections, replacement)
        self._layouts[key] = {}
        self._published[key] = {}
        self._written.add(key)
        page = self._live_page(item_id)
        set_now = set_property_names(page)
        cleared: dict[str, JsonValue] = {name: None for name in request.field_names if name in set_now}
        if cleared:
            self._api.update_page(item_id, {"properties": self._property_requests(page, cleared)})

    def parts_edited_after(
        self, _item_id: str, _marker: str | None, _keyed_like: ItemContent, /
    ) -> tuple[Part, ...]:
        return ()

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

    def _send(self, item_id: str, sections: Mapping[str, str], replacement: Replacement) -> str:
        _refuse_unknown_blocks(item_id, sections, replacement)
        _refuse_what_one_request_cannot_carry(item_id, replacement)
        return self._api.update_markdown(item_id, _update_content(replacement)).markdown

    def _written_with(
        self,
        item_id: str,
        sections: Mapping[str, str],
        replacement: Replacement,
        layout: Mapping[str, str],
        markdown: str,
    ) -> RemoteItem:
        if not replacement.changes_nothing:
            markdown = self._send(item_id, sections, replacement)
        key = _page_key(item_id)
        self._written.add(key)
        self._published[key] = layout
        return self._remote(item_id, self._live_page(item_id), markdown, layout)

    def _stamp_put_back(self, item_id: str, markdown: str, layout: Mapping[str, str], stamp: Stamp) -> str:
        current = list(keyed_page(markdown, layout).raw_sections.items())
        line = stamp_line(stamp)
        if not markdown.strip():
            return self._api.update_markdown(item_id, _replace_content(line)).markdown
        replacement = section_replacement(current, [*current, (STAMP_KEY, line)], markdown, None)
        if replacement is None:
            raise WriteRejectedError(
                f"Notion page {item_id} holds nothing skaldr can place its stamp next to"
            )
        return self._send(item_id, dict(current), replacement)

    def _unchanged_since_read(self, item_id: str, raw_sections: RawSections) -> tuple[KeyedPage, str]:
        markdown = self._api.page_markdown(item_id).markdown
        keyed = keyed_page(markdown, raw_sections)
        if list(keyed.raw_sections.items()) != list(raw_sections.items()):
            raise WriteRejectedError(
                f"Notion page {item_id} changed after skaldr read it, so nothing was written; publish again"
            )
        return keyed, markdown

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
            **title_request(request.content.title, parent.title_name),
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
        key = _page_key(item_id)
        self._written.add(key)
        self._published[key] = layout
        return self._remote(item_id, self._live_page(item_id), markdown, layout)

    def _into_properties(self, item_id: str, request: NewItem) -> JsonFields:
        self._unchanged_since_read(item_id, request.into_raw_sections)
        page = self._live_page(item_id)
        values = {name: value for name, value in request.content.fields.items() if not is_unset(value)}
        return {
            **title_request(request.content.title, title_property_name(page)),
            **self._property_requests(page, values),
        }

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
