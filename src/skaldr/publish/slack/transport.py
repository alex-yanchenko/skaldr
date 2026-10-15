import hashlib
from collections.abc import Mapping, Sequence
from typing import Final

from skaldr.errors import ConnectorError, ItemNotFoundError, WriteRejectedError
from skaldr.publish.content import ItemContent, Part, differing_parts, placed_section
from skaldr.publish.keyed import (
    ReadLayouts,
    comparable_sections,
    finished_after_a_change,
    refuse_a_change_since_the_read,
    refused_when_not_found,
)
from skaldr.publish.slack.api import SlackApi, markdown_content
from skaldr.publish.slack.canvas_markdown import (
    KeyedCanvas,
    archived_line,
    canvas_blocks,
    canvas_markdown_of,
    canvas_stamp_line,
    comparable_text,
    is_a_list,
    keyed_canvas,
    section_ids,
)
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
from skaldr.publish_block import SlackTarget, slack_canvas_id
from skaldr.publish_block.target import JsonFields

ARCHIVED_TITLE_MARKER: Final = " (archived by skaldr)"
RELEASED_ROLES: Final = frozenset({"published", "blank", "stamp"})


def _digest(markdown: str) -> str:
    return hashlib.sha256(markdown.encode("utf-8")).hexdigest()


def _rename(title: str) -> JsonFields:
    return {"operation": "rename", "title_content": markdown_content(title)}


def _canvas_named(canvas_id: str) -> str:
    return f"Slack canvas {canvas_id}"


def _named_fields(request: FieldsWrite) -> list[str]:
    return list(dict.fromkeys([*request.changed_fields, *request.cleared_fields]))


class _Edits:
    def __init__(self, api: SlackApi, canvas_id: str, blocks: int) -> None:
        self._api = api
        self._canvas_id = canvas_id
        self._blocks = blocks
        self._sent = 0

    def delete(self, position: int) -> None:
        ids = self._section_ids()
        self._send({"operation": "delete", "section_id": ids[position]})
        self._blocks -= 1

    def insert(self, position: int, markdown: str) -> None:
        if not markdown:
            return
        content = markdown_content(markdown)
        if position == 0:
            self._send({"operation": "insert_at_start", "document_content": content})
        else:
            ids = self._section_ids()
            self._send(
                {"operation": "insert_after", "section_id": ids[position - 1], "document_content": content}
            )
        self._blocks += len(canvas_blocks(markdown))

    def append(self, markdown: str) -> None:
        self._send({"operation": "insert_at_end", "document_content": markdown_content(markdown)})
        self._blocks += len(canvas_blocks(markdown))

    def replace(self, position: int, markdown: str) -> None:
        ids = self._section_ids()
        content = markdown_content(markdown)
        self._send({"operation": "replace", "section_id": ids[position], "document_content": content})
        self._blocks += len(canvas_blocks(markdown)) - 1

    def rewrite(self, keyed: KeyedCanvas, old: Sequence[int], at: int, markdown: str) -> None:
        added = canvas_blocks(markdown)
        if added and not _lists_would_meet(keyed, old, at, added):
            self.insert(at, markdown)
            for position in reversed(old):
                self.delete(position + len(added) if position >= at else position)
            return
        for position in reversed(old):
            self.delete(position)
        self.insert(at - sum(position < at for position in old), markdown)

    def _send(self, change: JsonFields) -> None:
        try:
            self._api.edit_canvas(self._canvas_id, change)
        except ConnectorError as exc:
            if self._sent == 0:
                raise
            raise ConnectorError(
                f"Slack canvas {self._canvas_id} is partly written, so publish again to finish: {exc}"
            ) from exc
        self._sent += 1

    def _section_ids(self) -> list[str]:
        listed = section_ids(self._api.canvas_html(self._canvas_id))
        ids = [section_id for section_id in listed if section_id is not None]
        if len(ids) == len(listed) == self._blocks:
            return ids
        mismatch = (
            f"Slack lists {len(ids)} sections for canvas {self._canvas_id} but its Markdown holds "
            f"{self._blocks} blocks, so skaldr cannot tell which to change"
        )
        if self._sent == 0:
            raise WriteRejectedError(f"{mismatch}; nothing was written")
        raise ConnectorError(f"{mismatch}; the canvas is partly written, so publish again to finish")


def _lists_would_meet(keyed: KeyedCanvas, old: Sequence[int], at: int, added: Sequence[str]) -> bool:
    meets_the_block_before = at - 1 in old and is_a_list(keyed.blocks[at - 1].raw) and is_a_list(added[0])
    meets_the_block_after = at in old and is_a_list(keyed.blocks[at].raw) and is_a_list(added[-1])
    return meets_the_block_before or meets_the_block_after


class SlackTransport:
    def __init__(self, api: SlackApi) -> None:
        self._api = api
        self._read = ReadLayouts()

    def comparable_form(self, content: ItemContent, /) -> ItemContent:
        return comparable_sections(content, comparable_text)

    def read_item(self, item_id: str, keyed_like: ItemContent, /) -> RemoteItem:
        markdown = self._markdown(item_id)
        self._read.note_the_read(item_id, keyed_like)
        return self._remote(item_id, markdown, self._read.to_read(item_id, keyed_like))

    def create_item(self, request: NewItem, /) -> RemoteItem:
        content = request.content
        markdown = canvas_markdown_of([*content.sections.values(), canvas_stamp_line(request.stamp)])
        if request.into_id is not None:
            return self._create_into(request.into_id, request, markdown)
        canvas_id = refused_when_not_found(lambda: self._api.create_canvas(content.title, markdown))
        target = request.target
        conversation = target.where.conversation if isinstance(target, SlackTarget) else None

        def finish() -> RemoteItem:
            if conversation is not None:
                link = self.item_link(canvas_id, content.title)
                self._api.post_message(conversation, f"{content.title}: {link.url}")
            return self._written_with(canvas_id, self.comparable_form(content).sections)

        return finished_after_a_change(_canvas_named(canvas_id), content.title, finish)

    def write_section(self, item_id: str, request: SectionRequest, /) -> RemoteItem:
        change = request.change
        keyed = self._unchanged_since_read(item_id, request.raw_sections)
        current = dict(request.raw_sections)
        if not isinstance(change, AddSection) and current.get(change.key) != change.raw_current:
            raise WriteRejectedError(
                f"Slack canvas {item_id} no longer holds section {change.key} as skaldr read it, so nothing "
                "was written; publish again"
            )
        text = None if isinstance(change, RemoveSection) else change.text
        follows = None if isinstance(change, RemoveSection) else change.follows
        after = placed_section(current, change.key, text, follows)
        old = keyed.positions_of(change.key) if change.key in current else []
        order = list(after)
        before = order[: order.index(change.key)] if change.key in after else []
        edits = _Edits(self._api, item_id, len(keyed.blocks))
        edits.rewrite(
            keyed, old, keyed.position_after(before), "" if text is None else canvas_markdown_of([text])
        )
        if keyed.stamp is None:
            edits.append(canvas_stamp_line(request.stamp))
        return self._written_with(item_id, after)

    def write_content(self, item_id: str, request: ContentWrite, /) -> RemoteItem:
        keyed = self._unchanged_since_read(item_id, request.raw_sections)
        edits = _Edits(self._api, item_id, len(keyed.blocks))
        old = range(keyed.content_start, keyed.content_end)
        edits.rewrite(keyed, old, keyed.content_start, canvas_markdown_of(list(request.sections.values())))
        if keyed.stamp is None:
            edits.append(canvas_stamp_line(request.stamp))
        return self._written_with(item_id, request.sections)

    def write_fields(self, item_id: str, request: FieldsWrite, /) -> RemoteItem:
        layout = self._read.layouts.get(item_id, {})
        keyed = keyed_canvas(self._markdown(item_id), layout)
        if keyed.stamp is not None and keyed.stamp != request.stamp:
            raise WriteRejectedError(f"Slack canvas {item_id} is not stamped with {request.stamp.named}")
        named = _named_fields(request)
        if named:
            raise WriteRejectedError(
                f"a Slack canvas has no fields, so skaldr cannot change {', '.join(named)} on canvas "
                f"{item_id}"
            )
        if request.changes_the_title:
            self._api.edit_canvas(item_id, _rename(request.title))
        if keyed.stamp is None:
            _Edits(self._api, item_id, len(keyed.blocks)).append(canvas_stamp_line(request.stamp))
        return self._remote(item_id, self._markdown(item_id), layout)

    def archive_item(self, item_id: str, /) -> None:
        try:
            keyed = keyed_canvas(self._markdown(item_id), {})
        except ItemNotFoundError:
            return
        if not keyed.title.endswith(ARCHIVED_TITLE_MARKER):
            self._api.edit_canvas(item_id, _rename(f"{keyed.title}{ARCHIVED_TITLE_MARKER}"))
        doc_id = None if keyed.stamp is None else keyed.stamp.doc_id
        content = markdown_content(canvas_markdown_of([archived_line(doc_id)]))
        self._api.edit_canvas(item_id, {"operation": "replace", "document_content": content})

    def release_item(self, item_id: str, request: Release, /) -> None:
        self._unchanged_since_read(item_id, request.raw_sections)
        keyed = keyed_canvas(self._markdown(item_id), self._read.published.get(item_id, request.raw_sections))
        edits = _Edits(self._api, item_id, len(keyed.blocks))
        for position, block in reversed(list(enumerate(keyed.blocks))):
            if block.role in RELEASED_ROLES:
                edits.delete(position)
        self._read.note_released(item_id)

    def parts_edited_after(
        self, item_id: str, marker: str | None, keyed_like: ItemContent, /
    ) -> tuple[Part, ...]:
        markdown = self._markdown(item_id)
        if marker is not None and _digest(markdown) == marker:
            return ()
        keyed = keyed_canvas(markdown, self._read.to_read(item_id, keyed_like))
        published = ItemContent(title=keyed_like.title, sections=self.comparable_form(keyed_like).sections)
        return differing_parts(published, ItemContent(title=keyed.title, sections=keyed.sections))

    def editor_name(self, user_id: str, /) -> str:
        return user_id

    def item_link(self, item_id: str, title: str, /) -> ItemLink:
        identity = self._api.signed_in_as()
        if identity.url is None or identity.team_id is None:
            raise ConnectorError(
                f"Slack named no workspace address for this sign-in, so skaldr cannot link canvas {item_id}"
            )
        return ItemLink(f"{identity.url.rstrip('/')}/docs/{identity.team_id}/{item_id}", title)

    def read_links(self, item_id: str, stamp: Stamp, /) -> tuple[ShownLink, ...]:
        keyed = keyed_canvas(self._markdown(item_id), self._read.layouts.get(item_id, {}))
        return keyed.links if keyed.stamp == stamp else ()

    def write_links(self, item_id: str, request: LinksWrite, /) -> tuple[ShownLink, ...]:
        layout = self._read.layouts.get(item_id, {})
        keyed = keyed_canvas(self._markdown(item_id), layout)
        if keyed.stamp is not None and keyed.stamp != request.stamp:
            raise WriteRejectedError(f"Slack canvas {item_id} is not stamped with {request.stamp.named}")
        if request.changes_nothing:
            return keyed.links
        line = canvas_markdown_of([canvas_stamp_line(request.stamp, request.links)])
        edits = _Edits(self._api, item_id, len(keyed.blocks))
        if keyed.stamp_at is None:
            edits.append(line)
        else:
            edits.replace(keyed.stamp_at, line)
        return keyed_canvas(self._markdown(item_id), layout).links

    def close(self) -> None:
        self._api.close()

    def _markdown(self, item_id: str) -> str:
        if slack_canvas_id(item_id) != item_id:
            raise ItemNotFoundError(f"'{item_id}' is not a Slack canvas id")
        markdown = self._api.canvas_markdown(item_id)
        if keyed_canvas(markdown, {}).archived:
            raise ItemNotFoundError(f"Slack canvas {item_id} was archived by skaldr")
        return markdown

    def _remote(self, item_id: str, markdown: str, layout: Mapping[str, str]) -> RemoteItem:
        keyed = keyed_canvas(markdown, layout)
        self._read.layouts[item_id] = keyed.raw_sections
        return RemoteItem(
            item_id,
            ItemContent(title=keyed.title, sections=keyed.sections),
            keyed.raw_sections,
            keyed.stamp,
            marker=_digest(markdown),
            links=keyed.links,
        )

    def _written_with(self, item_id: str, layout: Mapping[str, str]) -> RemoteItem:
        self._read.note_written(item_id, layout)
        return self._remote(item_id, self._markdown(item_id), layout)

    def _unchanged_since_read(self, item_id: str, raw_sections: RawSections) -> KeyedCanvas:
        keyed = keyed_canvas(self._markdown(item_id), raw_sections)
        refuse_a_change_since_the_read(_canvas_named(item_id), raw_sections, keyed.raw_sections)
        return keyed

    def _create_into(self, item_id: str, request: NewItem, markdown: str) -> RemoteItem:
        title = request.content.title
        keyed = refused_when_not_found(lambda: self._unchanged_since_read(item_id, request.into_raw_sections))
        replace: JsonFields = {"operation": "replace", "document_content": markdown_content(markdown)}
        refused_when_not_found(lambda: self._api.edit_canvas(item_id, replace))

        def finish() -> RemoteItem:
            if keyed.title != title:
                self._api.edit_canvas(item_id, _rename(title))
            return self._written_with(item_id, self.comparable_form(request.content).sections)

        return finished_after_a_change(_canvas_named(item_id), title, finish)
