import hashlib
import html
import sys
from collections.abc import Callable, Mapping, Sequence
from typing import Final

from skaldr.errors import ConnectorError, ItemNotFoundError, WriteRejectedError
from skaldr.publish.content import ItemContent, Part, placed_section
from skaldr.publish.keyed import (
    ReadLayouts,
    comparable_sections,
    finished_after_a_change,
    finished_after_a_create,
    refuse_a_change_since_the_read,
    refused_when_not_found,
)
from skaldr.publish.slack.api import SlackApi, markdown_content
from skaldr.publish.slack.canvas_markdown import (
    ARCHIVED_TITLE_MARKER,
    KeyedCanvas,
    archived_line,
    body_with_content_swapped,
    canvas_body,
    canvas_markdown_of,
    canvas_stamp_line,
    comparable_text,
    keyed_canvas,
    with_the_stamp_line,
)
from skaldr.publish.transport import (
    NO_PUBLISHED,
    AddSection,
    ContentWrite,
    FieldsWrite,
    ItemLink,
    LinksWrite,
    NewItem,
    PublishedSections,
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

Warn = Callable[[str], None]
RELEASED_ROLES: Final = frozenset({"published", "blank", "stamp"})


def _digest(markdown: str) -> str:
    return hashlib.sha256(markdown.encode("utf-8")).hexdigest()


def _rename(title: str) -> JsonFields:
    return {"operation": "rename", "title_content": markdown_content(title)}


def _canvas_named(canvas_id: str) -> str:
    return f"Slack canvas {canvas_id}"


def _named_fields(request: FieldsWrite) -> list[str]:
    return list(dict.fromkeys([*request.changed_fields, *request.cleared_fields]))


def _as_skaldr_wrote_it(
    markdown: str, layout: Mapping[str, str], published: PublishedSections
) -> KeyedCanvas:
    return keyed_canvas(markdown, layout).in_the_markdown_skaldr_wrote(
        published.rendered, published.saved_remote
    )


def warn_on_stderr(message: str) -> None:
    print(f"warning: {message}", file=sys.stderr, flush=True)


class SlackTransport:
    def __init__(self, api: SlackApi, *, warn: Warn = warn_on_stderr) -> None:
        self._api = api
        self._warn = warn
        self._read = ReadLayouts()

    def comparable_draft(self, content: ItemContent, /) -> ItemContent:
        return self.comparable_form(content)

    def comparable_form(self, content: ItemContent, /) -> ItemContent:
        return comparable_sections(content, comparable_text)

    def read_item(self, item_id: str, published: ItemContent, /) -> RemoteItem:
        markdown = self._markdown(item_id)
        self._read.note_the_read(item_id, published)
        return self._remote(item_id, markdown, self._read.to_read(item_id, published))

    def create_item(self, request: NewItem, /) -> RemoteItem:
        content = request.content
        markdown = canvas_markdown_of([*content.sections.values(), canvas_stamp_line(request.stamp)])
        if request.into_id is not None:
            return self._create_into(request.into_id, request, markdown)
        canvas_id = refused_when_not_found(lambda: self._api.create_canvas(content.title, markdown))
        target = request.target
        conversation = target.where.conversation if isinstance(target, SlackTarget) else None
        if conversation is not None:
            opens_the_document = request.stamp.section_id is None
            self._share(canvas_id, content.title, conversation, posts_the_link=opens_the_document)
        return finished_after_a_create(
            _canvas_named(canvas_id),
            canvas_id,
            content.title,
            lambda: self._written_with(canvas_id, self.comparable_form(content).sections),
        )

    def write_section(self, item_id: str, request: SectionRequest, /) -> RemoteItem:
        change = request.change
        keyed = self._unchanged_since_read(item_id, request.raw_sections, request.published)
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
        markdown = "" if text is None else canvas_markdown_of([text])
        body = body_with_content_swapped(keyed, old, keyed.position_after(before), markdown)
        self._replace_body(item_id, with_the_stamp_line(keyed, body, request.stamp))
        return self._written_with(item_id, after)

    def write_content(self, item_id: str, request: ContentWrite, /) -> RemoteItem:
        keyed = self._unchanged_since_read(item_id, request.raw_sections, NO_PUBLISHED)
        old = range(keyed.content_start, keyed.content_end)
        markdown = canvas_markdown_of(list(request.sections.values()))
        body = body_with_content_swapped(keyed, old, keyed.content_start, markdown)
        self._replace_body(item_id, with_the_stamp_line(keyed, body, request.stamp))
        return self._written_with(item_id, request.sections)

    def write_fields(self, item_id: str, request: FieldsWrite, /) -> RemoteItem:
        layout = self._read.layouts.get(item_id, {})
        keyed = _as_skaldr_wrote_it(self._markdown(item_id), layout, request.published)
        if keyed.stamp is not None and keyed.stamp != request.stamp:
            raise WriteRejectedError(f"Slack canvas {item_id} is not stamped with {request.stamp.named}")
        named = _named_fields(request)
        if named:
            raise WriteRejectedError(
                f"a Slack canvas has no fields, so skaldr cannot change {', '.join(named)} on canvas "
                f"{item_id}"
            )
        if keyed.stamp is None:
            self._replace_body(item_id, with_the_stamp_line(keyed, keyed.body, request.stamp))
        if request.changes_the_title:
            self._api.edit_canvas(item_id, _rename(request.title))
        return self._remote(item_id, self._markdown(item_id), layout)

    def archive_item(self, item_id: str, /) -> None:
        try:
            markdown = self._markdown_of_any_canvas(item_id)
        except ItemNotFoundError:
            return
        read = self._read.layouts.get(item_id)
        keyed = keyed_canvas(markdown, {} if read is None else read)
        if keyed.archived:
            return
        replaced = True
        if not keyed.opens_with_the_archived_line:
            if read is not None:
                refuse_a_change_since_the_read(_canvas_named(item_id), read, keyed.raw_sections)
            doc_id = None if keyed.stamp is None else keyed.stamp.doc_id
            self._replace_body(item_id, [archived_line(doc_id), *keyed.below_the_stamp])
        elif keyed.stamp_at is not None:
            raws = [block.raw for block in keyed.content]
            self._replace_body(item_id, [*raws, *keyed.below_the_stamp])
        else:
            replaced = False
        try:
            self._api.edit_canvas(item_id, _rename(f"{keyed.title}{ARCHIVED_TITLE_MARKER}"))
        except ConnectorError as exc:
            if not replaced:
                raise
            raise ConnectorError(
                f"Slack canvas {item_id} holds the archived line but is not renamed yet, so publish again to "
                f"finish: {exc}"
            ) from exc

    def release_item(self, item_id: str, request: Release, /) -> None:
        self._unchanged_since_read(item_id, request.raw_sections, NO_PUBLISHED)
        keyed = keyed_canvas(self._markdown(item_id), self._read.published.get(item_id, request.raw_sections))
        kept = [
            block.raw for block in keyed.blocks[keyed.content_start :] if block.role not in RELEASED_ROLES
        ]
        if len(kept) < len(keyed.body):
            self._replace_body(item_id, kept)
        self._read.note_released(item_id)

    def parts_edited_after(
        self, _item_id: str, _marker: str | None, _published: ItemContent, /
    ) -> tuple[Part, ...]:
        return ()

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
        keyed = _as_skaldr_wrote_it(self._markdown(item_id), layout, request.published)
        if keyed.stamp is not None and keyed.stamp != request.stamp:
            raise WriteRejectedError(f"Slack canvas {item_id} is not stamped with {request.stamp.named}")
        if request.changes_nothing:
            return keyed.links
        line = canvas_stamp_line(request.stamp, request.links)
        body = keyed.body
        if keyed.stamp_at is None:
            body.append(line)
        else:
            body[keyed.stamp_at - keyed.content_start] = line
        self._replace_body(item_id, body)
        return keyed_canvas(self._markdown(item_id), layout).links

    def close(self) -> None:
        self._api.close()

    def _replace_body(self, item_id: str, raws: Sequence[str]) -> None:
        replace: JsonFields = {
            "operation": "replace",
            "document_content": markdown_content(canvas_body(raws)),
        }
        self._api.edit_canvas(item_id, replace)

    def _share(self, canvas_id: str, title: str, conversation: str, *, posts_the_link: bool) -> None:
        created = f'skaldr created Slack canvas {canvas_id} for "{title}"'
        try:
            self._api.let_read(canvas_id, conversation)
        except ConnectorError as exc:
            self._warn(
                f"{created} but could not let {conversation} read it: {exc}; share the canvas with "
                f"{conversation} in Slack"
            )
        if not posts_the_link:
            return
        try:
            link = self.item_link(canvas_id, title)
        except ConnectorError as exc:
            self._warn(
                f"{created} but could not link it in {conversation}: {exc}; post its link there yourself"
            )
            return
        try:
            self._api.post_message(conversation, f"{html.escape(title, quote=False)}: {link.url}")
        except ConnectorError as exc:
            self._warn(
                f"{created} but could not post its link in {conversation}: {exc}; post {link.url} there "
                "yourself"
            )

    def _markdown_of_any_canvas(self, item_id: str) -> str:
        if slack_canvas_id(item_id) != item_id:
            raise ItemNotFoundError(f"'{item_id}' is not a Slack canvas id")
        return self._api.canvas_markdown(item_id)

    def _markdown(self, item_id: str) -> str:
        markdown = self._markdown_of_any_canvas(item_id)
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

    def _unchanged_since_read(
        self, item_id: str, raw_sections: RawSections, published: PublishedSections
    ) -> KeyedCanvas:
        markdown = self._markdown(item_id)
        keyed = keyed_canvas(markdown, raw_sections)
        refuse_a_change_since_the_read(_canvas_named(item_id), raw_sections, keyed.raw_sections)
        return _as_skaldr_wrote_it(markdown, raw_sections, published)

    def _create_into(self, item_id: str, request: NewItem, markdown: str) -> RemoteItem:
        title = request.content.title
        keyed = refused_when_not_found(
            lambda: self._unchanged_since_read(item_id, request.into_raw_sections, NO_PUBLISHED)
        )
        replace: JsonFields = {"operation": "replace", "document_content": markdown_content(markdown)}
        refused_when_not_found(lambda: self._api.edit_canvas(item_id, replace))

        def finish() -> RemoteItem:
            if keyed.title != title:
                self._api.edit_canvas(item_id, _rename(title))
            return self._written_with(item_id, self.comparable_form(request.content).sections)

        return finished_after_a_change(_canvas_named(item_id), title, finish)
