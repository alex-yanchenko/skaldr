from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from functools import cached_property
from typing import Final

from pydantic import JsonValue

from skaldr.auth import printable_only
from skaldr.errors import AuthError, ConnectorError, ItemNotFoundError, WriteRejectedError
from skaldr.export.budget import json_string_bytes
from skaldr.export.notion import notion_block_count
from skaldr.publish.content import ItemContent, Part, is_unset, placed_section
from skaldr.publish.keyed import (
    ReadLayouts,
    comparable_sections,
    finished_after_a_change,
    finished_after_a_create,
    refuse_a_change_since_the_read,
    refused_when_not_found,
)
from skaldr.publish.notion.api import Answer, NotionApi
from skaldr.publish.notion.icon_and_cover import (
    cover_text,
    icon_and_cover_to_change,
    icon_and_cover_to_clear,
    icon_and_cover_to_set,
    icon_text,
)
from skaldr.publish.notion.page_markdown import (
    KeyedPage,
    Replacement,
    SectionPairs,
    carried_into,
    comparable_text,
    holds_an_unknown_block,
    joined,
    keyed_page,
    release_replacements,
    section_replacement,
    stamp_line,
)
from skaldr.publish.notion.parents import DATABASE_BLOCK, ParentLookup, look_up_parent
from skaldr.publish.notion.people import KnownPeople
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
from skaldr.publish.notion.template import check_the_template_is_empty
from skaldr.publish.transport import (
    AddSection,
    ContentWrite,
    FieldsWrite,
    ItemLink,
    LinksWrite,
    NewItem,
    RawSections,
    Release,
    RemoteItem,
    RemoveSection,
    SectionRequest,
    ShownLink,
    Stamp,
)
from skaldr.publish_block import NotionTarget, TargetBase, notion_page_id
from skaldr.publish_block.notion import NO_TEMPLATE
from skaldr.publish_block.target import JsonFields

REQUEST_BLOCKS: Final = 2_500
REQUEST_JSON_BYTES: Final = 300_000
REQUEST_WRAPPER_BYTES: Final = 20_000
MARKDOWN_JSON_BYTES: Final = REQUEST_JSON_BYTES - REQUEST_WRAPPER_BYTES
STAMP_BLOCKS: Final = 1
SECTION_BLOCKS: Final = REQUEST_BLOCKS - STAMP_BLOCKS
SECTION_JSON_BYTES: Final = MARKDOWN_JSON_BYTES // 2
STAMP_KEY: Final = "skaldr stamp"
TEMPLATE_FIELD: Final = "template"
NOTION_PAGE_ADDRESS: Final = "https://www.notion.so/"


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
    blocks, size = stamp_blocks, 2 * stamp_bytes
    for text in texts:
        text_blocks, text_bytes = notion_block_count(text), json_string_bytes(text)
        too_big = blocks + text_blocks > REQUEST_BLOCKS or size + text_bytes > MARKDOWN_JSON_BYTES
        if batches[-1] and too_big:
            batches.append([])
            blocks, size = stamp_blocks, 2 * stamp_bytes
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


def _page_named(item_id: str) -> str:
    return f"Notion page {item_id}"


def _with_children_of_removed_sections(
    current: Mapping[str, str], after: SectionPairs
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
    if size <= MARKDOWN_JSON_BYTES and blocks <= REQUEST_BLOCKS:
        return
    measured = (
        f"{size:,} bytes of JSON in one request, over the {MARKDOWN_JSON_BYTES:,}"
        if size > MARKDOWN_JSON_BYTES
        else f"{blocks:,} Notion blocks in one request, over the {REQUEST_BLOCKS:,}"
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


def _makes_its_sections_rows(target: TargetBase) -> bool:
    return isinstance(target, NotionTarget) and target.where.fields_from_sections


def _no_workspace_template() -> str | None:
    return None


def _is_templated(create_body: JsonFields) -> bool:
    return TEMPLATE_FIELD in create_body


class NotionTransport:
    def __init__(
        self, api: NotionApi, workspace_template: Callable[[], str | None] = _no_workspace_template
    ) -> None:
        self._api = api
        self._people = KnownPeople(api)
        self._workspace_template = workspace_template
        self._read = ReadLayouts()
        self._editor_names: dict[str, str] = {}
        self._templates_found_empty: set[str] = set()
        self._parents_that_are_databases: dict[str, bool] = {}
        self._parents_looked_up: dict[str, ParentLookup] = {}
        self._property_names_read: dict[str, tuple[str, ...]] = {}

    @cached_property
    def _workspace_template_page(self) -> str | None:
        return self._workspace_template()

    def _sections_as_written(self, sections: Mapping[str, str]) -> dict[str, str]:
        return {key: self._people.as_written(text) for key, text in sections.items()}

    def comparable_form(self, content: ItemContent, /) -> ItemContent:
        return comparable_sections(content, comparable_text)

    def comparable_draft(self, content: ItemContent, /) -> ItemContent:
        written = content.model_copy(update={"sections": self._sections_as_written(content.sections)})
        return self.comparable_form(written)

    def read_item(self, item_id: str, keyed_like: ItemContent, /) -> RemoteItem:
        page = self._live_page(item_id)
        markdown = self._api.page_markdown(item_id).markdown
        key = _page_key(item_id)
        self._read.note_the_read(key, keyed_like)
        return self._remote(item_id, page, markdown, self._read.to_read(key, keyed_like))

    def create_item(self, request: NewItem, /) -> RemoteItem:
        if request.into_id is not None:
            return self._create_into(request.into_id, request)
        stamp = stamp_line(request.stamp)
        batches = _create_batches(list(self._sections_as_written(request.content.sections).values()), stamp)
        body = _with_nothing_sent(lambda: self._create_body(request, batches[0], stamp))
        templated = _is_templated(body)
        page = refused_when_not_found(lambda: self._api.create_page(body, asynchronous=not templated))
        item_id = _page_key(page.id)
        first_write = joined([*batches[0], stamp]) if templated else None
        return finished_after_a_create(
            _page_named(item_id),
            item_id,
            request.content.title,
            lambda: self._finish_create(item_id, request.content, batches[1:], first_write),
        )

    def fill_a_page_left_empty(self, item_id: str, request: NewItem, /) -> RemoteItem:
        return self._create_into(item_id, request)

    def write_section(self, item_id: str, request: SectionRequest, /) -> RemoteItem:
        change = request.change
        current = dict(request.raw_sections)
        if not isinstance(change, AddSection):
            current[change.key] = change.raw_current
        if isinstance(change, RemoveSection):
            keys = list(current)
            position = keys.index(change.key)
            follows = keys[position - 1] if position > 0 else None
            kept = carried_into(current[change.key], "") or None
        else:
            follows = change.follows
            kept = carried_into(current.get(change.key, ""), self._people.as_written(change.text))
        after = list(placed_section(current, change.key, kept, follows).items())
        keyed, markdown = self._unchanged_since_read(item_id, request.raw_sections)
        replacement = section_replacement(list(current.items()), after, markdown, keyed.stamp_line)
        if replacement is None:
            raise WriteRejectedError(
                f"Notion page {item_id} holds nothing skaldr can place the section next to"
            )
        missing_stamp = request.stamp if keyed.stamp is None else None
        return self._written_with(item_id, current, replacement, dict(after), markdown, missing_stamp)

    def write_content(self, item_id: str, request: ContentWrite, /) -> RemoteItem:
        keyed, markdown = self._unchanged_since_read(item_id, request.raw_sections)
        current = keyed.raw_sections
        after = _with_children_of_removed_sections(
            current,
            [
                (key, carried_into(current.get(key, ""), text))
                for key, text in self._sections_as_written(request.sections).items()
            ],
        )
        replacement = section_replacement(list(current.items()), after, markdown, keyed.stamp_line)
        if replacement is None:
            raise WriteRejectedError(
                f"Notion page {item_id} holds nothing skaldr can place its content next to"
            )
        missing_stamp = request.stamp if keyed.stamp is None else None
        return self._written_with(item_id, current, replacement, dict(after), markdown, missing_stamp)

    def write_fields(self, item_id: str, request: FieldsWrite, /) -> RemoteItem:
        layout = self._read.layouts.get(_page_key(item_id))
        if layout is None:
            raise ConnectorError(
                f"skaldr has not read Notion page {item_id} in this run, so it cannot tell its sections apart"
            )
        page = self._live_page(item_id)
        markdown = self._api.page_markdown(item_id).markdown
        stamp = keyed_page(markdown, layout).stamp
        if stamp is not None and stamp != request.stamp:
            raise WriteRejectedError(f"Notion page {item_id} is not stamped with {request.stamp.named}")
        title = title_request(request.title, title_property_name(page)) if request.changes_the_title else {}
        values: JsonFields = {**request.changed_fields, **dict.fromkeys(request.cleared_fields)}
        properties = {**title, **self._property_requests(page, values)}
        body: JsonFields = {
            **({"properties": properties} if properties else {}),
            **icon_and_cover_to_change(request),
        }
        if stamp is None:
            markdown = self._stamp_put_back(item_id, markdown, layout, request.stamp)
        if body:
            page = self._api.update_page(item_id, body)
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
        layout = self._read.published.get(key, request.raw_sections)
        for replacement in release_replacements(markdown, layout, MARKDOWN_JSON_BYTES // 2):
            self._send(item_id, keyed.raw_sections, replacement)
        self._read.note_released(key)
        page = self._live_page(item_id)
        set_now = set_property_names(page)
        cleared: dict[str, JsonValue] = dict.fromkeys(name for name in request.field_names if name in set_now)
        body: JsonFields = {
            **({"properties": self._property_requests(page, cleared)} if cleared else {}),
            **icon_and_cover_to_clear(page, request),
        }
        if body:
            self._api.update_page(item_id, body)

    def parts_edited_after(
        self, _item_id: str, _marker: str | None, _keyed_like: ItemContent, /
    ) -> tuple[Part, ...]:
        return ()

    def editor_name(self, user_id: str, /) -> str:
        if user_id not in self._editor_names:
            self._editor_names[user_id] = self._name_notion_gives(user_id)
        return self._editor_names[user_id]

    def item_link(self, item_id: str, title: str, /) -> ItemLink:
        return ItemLink(f"{NOTION_PAGE_ADDRESS}{_page_key(item_id)}", title)

    def read_links(self, item_id: str, stamp: Stamp, /) -> tuple[ShownLink, ...]:
        self._live_page(item_id)
        layout = self._read.layouts.get(_page_key(item_id), {})
        keyed = keyed_page(self._api.page_markdown(item_id).markdown, layout)
        return keyed.links if keyed.stamp == stamp else ()

    def write_links(self, item_id: str, request: LinksWrite, /) -> tuple[ShownLink, ...]:
        self._live_page(item_id)
        markdown = self._api.page_markdown(item_id).markdown
        layout = self._read.layouts.get(_page_key(item_id), {})
        keyed = keyed_page(markdown, layout)
        if keyed.stamp is not None and keyed.stamp != request.stamp:
            raise WriteRejectedError(f"Notion page {item_id} is not stamped with {request.stamp.named}")
        if request.changes_nothing:
            return keyed.links
        if keyed.stamp_line is None:
            markdown = self._stamp_put_back(item_id, markdown, layout, request.stamp, request.links)
        else:
            line = stamp_line(request.stamp, request.links)
            written = line if keyed.stamp_line.endswith("\n") else line.removesuffix("\n")
            markdown = self._send(item_id, keyed.raw_sections, Replacement(keyed.stamp_line, written))
        return keyed_page(markdown, layout).links

    def close(self) -> None:
        self._api.close()

    def _name_notion_gives(self, user_id: str) -> str:
        try:
            user = self._api.user(user_id)
        except ConnectorError:
            return user_id
        return printable_only(user.name or "") or user_id

    def _live_page(self, item_id: str) -> Page:
        if notion_page_id(item_id) is None:
            raise ItemNotFoundError(f"'{item_id}' is not a Notion page id")
        page = self._api.page(item_id)
        if page.in_trash:
            raise ItemNotFoundError(f"Notion page {item_id} is in the trash")
        return page

    def _remote(self, item_id: str, page: Page, markdown: str, layout: Mapping[str, str]) -> RemoteItem:
        keyed = keyed_page(markdown, layout)
        self._read.layouts[_page_key(item_id)] = keyed.sections
        self._property_names_read[_page_key(item_id)] = tuple(page.properties)
        edited_at = page.last_edited_time.isoformat()
        return RemoteItem(
            item_id,
            ItemContent(
                title=title_text(page),
                sections=dict(keyed.sections),
                fields=property_fields(page),
                icon=icon_text(page),
                cover=cover_text(page),
            ),
            keyed.raw_sections,
            keyed.stamp,
            marker=edited_at,
            edited_by=page.last_edited_by.id,
            edited_at=edited_at,
            child_ids=keyed.child_ids,
            set_properties=set_property_names(page),
            links=keyed.links,
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
        stamp_to_put_back: Stamp | None,
    ) -> RemoteItem:
        if not replacement.changes_nothing:
            markdown = self._send(item_id, sections, replacement)
        if stamp_to_put_back is not None:
            markdown = self._stamp_put_back(item_id, markdown, layout, stamp_to_put_back)
        self._read.note_written(_page_key(item_id), layout)
        return self._remote(item_id, self._live_page(item_id), markdown, layout)

    def _stamp_put_back(
        self,
        item_id: str,
        markdown: str,
        layout: Mapping[str, str],
        stamp: Stamp,
        links: Sequence[ShownLink] = (),
    ) -> str:
        current = list(keyed_page(markdown, layout).raw_sections.items())
        line = stamp_line(stamp, links)
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
        refuse_a_change_since_the_read(_page_named(item_id), raw_sections, keyed.raw_sections)
        return keyed, markdown

    def _property_requests(self, page: Page, values: Mapping[str, JsonValue]) -> JsonFields:
        kinds = {name: value.type for name, value in page.properties.items()}
        return _property_requests(kinds, values, f"Notion page {_page_key(page.id)}")

    def _parent(self, request: NewItem) -> _Parent:
        target = request.target
        nested_page = (
            None
            if request.parent_id is None
            else _Parent(
                {"page_id": request.parent_id}, {}, names_a_database=False, page_id=request.parent_id
            )
        )
        if nested_page is not None and not _makes_its_sections_rows(target):
            return nested_page
        if not isinstance(target, NotionTarget):
            raise WriteRejectedError(f"the Notion connector cannot publish to {target.place_label()}")
        parent_id = target.where.page_id
        if parent_id not in self._parents_looked_up:
            self._parents_looked_up[parent_id] = look_up_parent(self._api, parent_id)
        source = self._parents_looked_up[parent_id].data_source
        if source is None:
            return nested_page or _Parent(
                {"page_id": parent_id}, {}, names_a_database=False, page_id=parent_id
            )
        kinds = {name: schema.type for name, schema in source.properties.items()}
        return _Parent({"data_source_id": source.id}, kinds, names_a_database=True, page_id=parent_id)

    def where_it_creates(self, request: NewItem, /) -> str | None:
        parent = _with_nothing_sent(lambda: self._parent(request))
        return f"Notion database {parent.page_id}" if parent.names_a_database else request.parent_id

    def refuse_fields_the_item_cannot_hold(self, item_id: str, names: Sequence[str], /) -> None:
        held = self._property_names_read.get(_page_key(item_id))
        if held is None:
            return
        for name in names:
            if name not in held:
                raise WriteRejectedError(
                    f"{_page_named(item_id)} has no property '{name}'. A section published as a child page "
                    "has none, so `fields_from_sections` has to be on from the first publish, or the target "
                    "has to be a new one"
                )

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
        template = self._template_for(request, parent)
        if template is not None:
            self._refuse_a_template_that_is_not_empty(template)
        content: JsonFields = (
            {"markdown": joined([*first_batch, stamp])}
            if template is None
            else {TEMPLATE_FIELD: {"type": "template_id", "template_id": template}}
        )
        return {
            "parent": parent.request,
            "properties": properties,
            **icon_and_cover_to_set(request.content),
            **content,
        }

    def _template_for(self, request: NewItem, parent: _Parent) -> str | None:
        target = request.target
        if not isinstance(target, NotionTarget) or target.where.template == NO_TEMPLATE:
            return None
        named = target.where.template_page_id
        template = named or self._workspace_template_page
        if template is None:
            return None
        if request.parent_id is None:
            self._parents_that_are_databases[target.where.page_id] = parent.names_a_database
        if not self._parent_is_a_database(target):
            return template
        if named is not None:
            raise WriteRejectedError(
                f"Notion database {target.where.page_id} does not take a page template, so skaldr cannot "
                "create its rows from one; remove `template` from the target's `where`, or set it to "
                f"`{NO_TEMPLATE}`"
            )
        return None

    def _parent_is_a_database(self, target: NotionTarget) -> bool:
        parent_id = target.where.page_id
        if parent_id not in self._parents_that_are_databases:
            self._parents_that_are_databases[parent_id] = self._api.block(parent_id).type == DATABASE_BLOCK
        return self._parents_that_are_databases[parent_id]

    def _refuse_a_template_that_is_not_empty(self, template: str) -> None:
        if template not in self._templates_found_empty:
            check_the_template_is_empty(self._api, template)
            self._templates_found_empty.add(template)

    def _finish_create(
        self,
        item_id: str,
        content: ItemContent,
        later_batches: Sequence[Sequence[str]],
        first_write: str | None = None,
    ) -> RemoteItem:
        if first_write is not None:
            self._api.update_markdown(item_id, _replace_content(first_write))
        markdown = self._api.page_markdown(item_id).markdown
        for batch in later_batches:
            stamp = keyed_page(markdown, {}).stamp_line or ""
            markdown = self._api.update_markdown(
                item_id, _update_content(Replacement(stamp, joined([*batch, stamp])))
            ).markdown
        layout = self.comparable_draft(content).sections
        self._read.note_written(_page_key(item_id), layout)
        return self._remote(item_id, self._live_page(item_id), markdown, layout)

    def _into_page_request(self, item_id: str, request: NewItem) -> JsonFields:
        self._unchanged_since_read(item_id, request.into_raw_sections)
        page = self._live_page(item_id)
        values = {name: value for name, value in request.content.fields.items() if not is_unset(value)}
        properties = {
            **title_request(request.content.title, title_property_name(page)),
            **self._property_requests(page, values),
        }
        return {"properties": properties, **icon_and_cover_to_set(request.content)}

    def _create_into(self, item_id: str, request: NewItem) -> RemoteItem:
        content = request.content
        stamp = stamp_line(request.stamp)
        batches = _create_batches(list(self._sections_as_written(content.sections).values()), stamp)
        page_request = _with_nothing_sent(lambda: self._into_page_request(item_id, request))
        refused_when_not_found(
            lambda: self._api.update_markdown(item_id, _replace_content(joined([*batches[0], stamp])))
        )

        def finish() -> RemoteItem:
            self._api.update_page(item_id, page_request)
            return self._finish_create(item_id, content, batches[1:])

        return finished_after_a_change(_page_named(item_id), content.title, finish)


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
