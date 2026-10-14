from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import TypeVar
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, JsonValue, ValidationError

from skaldr.errors import ConnectorError, ItemNotFoundError, WriteRejectedError
from skaldr.export.adf import JIRA_DESCRIPTION_LIMIT, compact_adf_length
from skaldr.publish.connector import SPLIT_ADVICE
from skaldr.publish.content import (
    FIELDS,
    TITLE,
    ItemContent,
    Part,
    is_unset,
    placed_section,
    same_fields,
    section_part,
    set_fields,
    with_fields_named,
)
from skaldr.publish.jira.api import Changelog, EntityProperty, Issue, Status, Transition
from skaldr.publish.jira.client import JiraClient
from skaldr.publish.jira.description import (
    Blocks,
    Layout,
    blocks_of,
    comparable_node,
    comparable_section,
    description_doc,
    layout_of,
    section_blocks,
    section_text,
    split_description,
)
from skaldr.publish.transport import (
    AddSection,
    ContentWrite,
    FieldsWrite,
    ItemLink,
    LinksWrite,
    NewItem,
    PairedLink,
    RawSections,
    Release,
    RemoteItem,
    RemoveSection,
    SectionRequest,
    ShownLink,
    Stamp,
)
from skaldr.publish_block import JiraTarget, TargetBase
from skaldr.publish_block.jira import (
    DESCRIPTION_FIELD,
    ISSUE_TYPE_FIELD,
    PARENT_FIELD,
    PROJECT_FIELD,
    STATUS_FIELD,
    SUMMARY_FIELD,
)
from skaldr.publish_block.target import JsonFields
from skaldr.services import SERVICES, Service

GLOBAL_ID_PREFIX = "skaldr"
GLOBAL_ID_SEPARATOR = ":"
GLOBAL_ID_LIMIT = 255
DOCUMENT_ITEM = "document"
SECTION_ITEM = "section"
BROWSE_PATH = "/browse/"
STAMP_PROPERTY = "skaldr.stamp"
LAYOUT_PROPERTY = "skaldr.layout"
LABEL_PREFIX = "skaldr-"
LABELS = "labels"
NO_MARKER = -1
UNKNOWN_AUTHOR = "an unknown author"
UNKNOWN_TIME = "an unknown time"
Stored = TypeVar("Stored", bound=BaseModel)


class StampValue(BaseModel):
    model_config = ConfigDict(frozen=True)

    doc_id: str | None
    section_id: str | None = None
    commented: bool = False
    archived: bool = False

    @property
    def stamp(self) -> Stamp | None:
        return None if self.doc_id is None else Stamp(self.doc_id, self.section_id)


def doc_label(doc_id: str) -> str:
    return f"{LABEL_PREFIX}{doc_id}"


def not_a_jira_target(target: TargetBase) -> str:
    return f"the Jira connector cannot publish to a {target.service()} target"


def _changed_since_read(item_id: str) -> WriteRejectedError:
    return WriteRejectedError(
        f"{item_id} changed in Jira after skaldr read it, so skaldr did not write to it; publish again to "
        "see the change"
    )


def _labels(value: JsonValue) -> list[str]:
    if isinstance(value, list):
        return [label for label in value if isinstance(label, str)]
    return [value] if isinstance(value, str) and value else []


def _with_doc_label(value: JsonValue, doc_id: str) -> list[JsonValue]:
    return list(dict.fromkeys([*_labels(value), doc_label(doc_id)]))


def _projected(remote: JsonValue, written: JsonValue) -> JsonValue:
    if isinstance(written, dict) and isinstance(remote, dict):
        return {name: _projected(remote.get(name), shape) for name, shape in written.items()}
    if isinstance(written, list) and isinstance(remote, list):
        names = {name for member in written if isinstance(member, dict) for name in member}
        if not names:
            return remote
        return [
            {name: value for name, value in member.items() if name in names}
            if isinstance(member, dict)
            else member
            for member in remote
        ]
    return remote


def _link_prefix(stamp: Stamp) -> str:
    item = [DOCUMENT_ITEM] if stamp.section_id is None else [SECTION_ITEM, stamp.section_id]
    return GLOBAL_ID_SEPARATOR.join([GLOBAL_ID_PREFIX, stamp.doc_id, *item, ""])


def _global_id(item_id: str, stamp: Stamp, link: PairedLink) -> str:
    global_id = f"{_link_prefix(stamp)}{link.service}{GLOBAL_ID_SEPARATOR}{link.item_id}"
    if len(global_id) > GLOBAL_ID_LIMIT:
        raise WriteRejectedError(
            f"the remote link from {item_id} to {link.service} item {link.item_id} needs a globalId of "
            f"{len(global_id)} characters, over the {GLOBAL_ID_LIMIT} Jira takes; shorten the document's "
            "doc_id or the section's id"
        )
    return global_id


def _linked_service(global_id: str, prefix: str) -> Service | None:
    if not global_id.startswith(prefix):
        return None
    named, separator, item_id = global_id.removeprefix(prefix).partition(GLOBAL_ID_SEPARATOR)
    if not separator or not item_id:
        return None
    return next((service for service in SERVICES if service == named), None)


def _archive_comment(stamp: StampValue) -> JsonValue:
    document = "the document" if stamp.doc_id is None else f"the document {stamp.doc_id}"
    text = f"skaldr archived this issue: {document} no longer has the content it held."
    return description_doc([{"type": "paragraph", "content": [{"type": "text", "text": text}]}])


def _sendable_blocks(sections: Mapping[str, str]) -> dict[str, Blocks]:
    try:
        return {key: section_blocks(text) for key, text in sections.items()}
    except ConnectorError as exc:
        raise WriteRejectedError(str(exc)) from exc


def _property(name: str, value: BaseModel) -> EntityProperty:
    return EntityProperty(key=name, value=value.model_dump(mode="json"))


def _number(marker: str | None) -> int:
    return int(marker) if marker is not None and marker.isascii() and marker.isdecimal() else NO_MARKER


def _marker(number: int) -> str | None:
    return None if number == NO_MARKER else str(number)


def _newest_entry(history: Iterable[Changelog]) -> Changelog | None:
    return max(history, key=lambda entry: entry.number, default=None)


def _newest(history: Iterable[Changelog]) -> int:
    newest = _newest_entry(history)
    return NO_MARKER if newest is None else newest.number


def _names(entry: Changelog) -> set[str]:
    return {name for item in entry.items for name in item.names}


def _status(issue: Issue) -> Status:
    try:
        return Status.model_validate(issue.fields.get(STATUS_FIELD))
    except ValidationError as exc:
        raise ConnectorError(f"Jira did not say which status {issue.key} is in") from exc


@dataclass(frozen=True)
class _Read:
    issue: Issue
    remote: RemoteItem
    layout: Layout | None
    stamp: StampValue | None
    history: tuple[Changelog, ...]


def _identities(entry: Changelog) -> set[str]:
    return {item.identity for item in entry.items}


def _described(entry: Changelog, written: frozenset[str]) -> str:
    author = (entry.author and entry.author.display_name) or UNKNOWN_AUTHOR
    when = entry.created or UNKNOWN_TIME
    fields = ", ".join(sorted(_identities(entry) & written))
    return f"{fields} in changelog {entry.id} by {author} at {when}"


class JiraTransport:
    def __init__(self, client: JiraClient, field_shapes: JsonFields | None = None) -> None:
        self._client = client
        self._target_shapes: JsonFields = dict(field_shapes or {})
        self._field_shapes: dict[str, JsonFields] = {}
        self._markers: dict[str, int] = {}
        self._last_reads: dict[str, _Read] = {}
        self._account_id: str | None = None

    def comparable_form(self, content: ItemContent, /) -> ItemContent:
        sections = {key: comparable_section(text) for key, text in content.sections.items()}
        return content.model_copy(update={"sections": {key: text for key, text in sections.items() if text}})

    def read_item(self, item_id: str, keyed_like: ItemContent, /) -> RemoteItem:
        self._remember_shapes(item_id, keyed_like.fields)
        read = self._read(item_id)
        self._markers[item_id] = _newest(read.history)
        self._last_reads[item_id] = read
        return read.remote

    def create_item(self, request: NewItem, /) -> RemoteItem:
        if request.into_id is not None:
            raise WriteRejectedError(
                "Jira publishes only into issues skaldr creates, so it cannot write into "
                f"{request.into_id}; publish under it with `parent` instead"
            )
        target = request.target
        if not isinstance(target, JiraTarget):
            raise WriteRejectedError(not_a_jira_target(target))
        content = request.content
        sections = _sendable_blocks(content.sections)
        description = self._description(sections, f'the new issue "{content.title}"')
        fields: dict[str, JsonValue] = {
            **set_fields(content.fields),
            LABELS: _with_doc_label(content.fields.get(LABELS), request.stamp.doc_id),
            PROJECT_FIELD: {"key": target.where.project},
            ISSUE_TYPE_FIELD: {"name": target.where.issue_type},
            SUMMARY_FIELD: content.title,
            DESCRIPTION_FIELD: description,
        }
        parent = request.parent_id or target.where.parent
        if parent is not None:
            fields[PARENT_FIELD] = {"key": parent}
        stamp = StampValue(doc_id=request.stamp.doc_id, section_id=request.stamp.section_id)
        layout = layout_of(sections)
        created = self._client.create_issue(
            fields, [_property(STAMP_PROPERTY, stamp), _property(LAYOUT_PROPERTY, layout)]
        )
        try:
            return self._read_back_created(created.key, content, layout, stamp)
        except ConnectorError as exc:
            raise ConnectorError(f"created {created.key} but could not read it back: {exc}") from exc

    def write_section(self, item_id: str, request: SectionRequest, /) -> RemoteItem:
        current = self._read_unchanged(item_id, request.raw_sections)
        change = request.change
        if not isinstance(change, AddSection) and current.get(change.key) != change.raw_current:
            raise WriteRejectedError(
                f"section {change.key} of {item_id} no longer holds the text skaldr read, so skaldr did not "
                "write it"
            )
        text = None if isinstance(change, RemoveSection) else change.text
        follows = None if isinstance(change, RemoveSection) else change.follows
        return self._write_description(item_id, placed_section(current, change.key, text, follows))

    def write_content(self, item_id: str, request: ContentWrite, /) -> RemoteItem:
        self._read_unchanged(item_id, request.raw_sections)
        return self._write_description(item_id, request.sections)

    def write_fields(self, item_id: str, request: FieldsWrite, /) -> RemoteItem:
        self._last_reads.pop(item_id, None)
        stamped = self._stamp(item_id)
        if stamped is not None and stamped.stamp != request.stamp:
            raise WriteRejectedError(f"Jira issue {item_id} is not stamped with {request.stamp.named}")
        self._remember_shapes(item_id, request.fields)
        self._refuse_unseen_edits(item_id, self._history(item_id))
        changes: dict[str, JsonValue] = {SUMMARY_FIELD: request.title} if request.changes_the_title else {}
        for name, value in request.changed_fields.items():
            changes[name] = _with_doc_label(value, request.stamp.doc_id) if name == LABELS else value
        for name in request.cleared_fields:
            changes[name] = [doc_label(request.stamp.doc_id)] if name == LABELS else None
        if changes:
            self._client.edit_issue(item_id, changes)
        return self._verified(item_id, self._read(item_id), frozenset(changes))

    def archive_item(self, item_id: str, /) -> None:
        self._last_reads.pop(item_id, None)
        current = self._stamp(item_id) or StampValue(doc_id=None)
        if current.archived:
            return
        if current.stamp is not None:
            self._unlink(item_id, current.stamp)
        status = _status(self._client.get_issue(item_id, [STATUS_FIELD]))
        if not status.is_done:
            done = self._done_transition(item_id, status)
            if not current.commented:
                self._comment_once(item_id, _archive_comment(current))
                current = current.model_copy(update={"commented": True})
                self._client.put_property(item_id, STAMP_PROPERTY, current.model_dump(mode="json"))
            self._client.transition(item_id, done.id)
        archived = current.model_copy(update={"archived": True})
        self._client.put_property(item_id, STAMP_PROPERTY, archived.model_dump(mode="json"))

    def release_item(self, _item_id: str, _request: Release, /) -> None:
        raise ConnectorError(
            "Jira has nothing to release: skaldr writes only into issues it created, and archives those"
        )

    def parts_edited_after(
        self, item_id: str, marker: str | None, keyed_like: ItemContent, /
    ) -> tuple[Part, ...]:
        self._remember_shapes(item_id, keyed_like.fields)
        read = self._last_read_holding(item_id, keyed_like)
        since = _number(marker)
        touched = {name for entry in read.history if entry.number > since for name in _names(entry)}
        published = self.comparable_form(keyed_like)
        current = with_fields_named(read.remote.comparable, published.fields)
        retitled = SUMMARY_FIELD in touched and current.title != published.title
        refielded = bool(touched & set(published.fields)) and not same_fields(
            published.fields, current.fields
        )
        parts = [*((TITLE,) if retitled else ()), *((FIELDS,) if refielded else ())]
        if DESCRIPTION_FIELD in touched:
            keys = dict.fromkeys([*published.sections, *current.sections])
            parts += [
                section_part(key) for key in keys if published.sections.get(key) != current.sections.get(key)
            ]
        return tuple(parts)

    def editor_name(self, display_name: str, /) -> str:
        return display_name

    def item_link(self, item_id: str, _title: str, /) -> ItemLink:
        return ItemLink(f"{self._client.site}{BROWSE_PATH}{quote(item_id, safe='')}", item_id)

    def read_links(self, item_id: str, stamp: Stamp, /) -> tuple[ShownLink, ...]:
        return tuple(self._links_of(item_id, stamp).values())

    def write_links(self, item_id: str, request: LinksWrite, /) -> tuple[ShownLink, ...]:
        stamped = self._stamp(item_id)
        if stamped is not None and stamped.stamp != request.stamp:
            raise WriteRejectedError(f"Jira issue {item_id} is not stamped with {request.stamp.named}")
        wanted = {_global_id(item_id, request.stamp, link): link for link in request.links}
        current = self._links_of(item_id, request.stamp)
        for global_id in current:
            if global_id not in wanted:
                self._client.delete_remote_link(item_id, global_id)
        for global_id, link in wanted.items():
            if current.get(global_id) != link.shown:
                self._client.put_remote_link(item_id, global_id, link.url, link.title)
        return request.shown

    def close(self) -> None:
        self._client.close()

    def _links_of(self, item_id: str, stamp: Stamp) -> dict[str, ShownLink]:
        prefix = _link_prefix(stamp)
        found: dict[str, ShownLink] = {}
        for link in self._client.remote_links(item_id):
            global_id = link.global_id or ""
            service = _linked_service(global_id, prefix)
            if service is not None:
                found[global_id] = ShownLink(service=service, url=link.linked.url, title=link.linked.title)
        return found

    def _unlink(self, item_id: str, stamp: Stamp) -> None:
        for global_id in self._links_of(item_id, stamp):
            self._client.delete_remote_link(item_id, global_id)

    def _read_back_created(
        self, item_id: str, content: ItemContent, layout: Layout, stamp: StampValue
    ) -> RemoteItem:
        self._remember_shapes(item_id, content.fields)
        read = self._read_after_write(item_id, layout, stamp)
        if not self._owned_entries(item_id, read.history):
            return self._handed_over(item_id, read.remote, _newest(read.history))
        published = replace(read.remote, comparable=self.comparable_form(content))
        return self._handed_over(item_id, published, NO_MARKER)

    def _comment_once(self, item_id: str, body: JsonValue) -> None:
        wanted = comparable_node(body)
        if not any(comparable_node(comment.body) == wanted for comment in self._client.comments(item_id)):
            self._client.add_comment(item_id, body)

    def _last_read_holding(self, item_id: str, keyed_like: ItemContent) -> _Read:
        last = self._last_reads.pop(item_id, None)
        if last is not None and set(keyed_like.fields) <= set(last.remote.comparable.fields):
            return last
        return self._read(item_id)

    def _remember_shapes(self, item_id: str, fields: Mapping[str, JsonValue]) -> None:
        known = self._field_shapes.setdefault(item_id, {})
        for name, value in fields.items():
            if not is_unset(value) or name not in known:
                known[name] = value

    def _shape(self, item_id: str, name: str) -> JsonValue:
        shape = self._field_shapes.get(item_id, {}).get(name)
        return self._target_shapes.get(name) if is_unset(shape) else shape

    def _owned_names(self, item_id: str) -> set[str]:
        return {SUMMARY_FIELD, DESCRIPTION_FIELD, *self._field_shapes.get(item_id, {})}

    def _owned_entries(self, item_id: str, history: Iterable[Changelog]) -> list[Changelog]:
        owned = self._owned_names(item_id)
        return [entry for entry in history if _names(entry) & owned]

    def _account(self) -> str:
        if self._account_id is None:
            self._account_id = self._client.myself().account_id
        return self._account_id

    def _is_skaldrs(self, entry: Changelog, written: frozenset[str]) -> bool:
        author = None if entry.author is None else entry.author.account_id
        return bool(written) and _identities(entry) <= written and author == self._account()

    def _baseline(self, item_id: str, history: Sequence[Changelog]) -> int:
        return self._markers.setdefault(item_id, _newest(history))

    def _refuse_unseen_edits(self, item_id: str, history: Sequence[Changelog]) -> None:
        since = self._baseline(item_id, history)
        if self._owned_entries(item_id, (entry for entry in history if entry.number > since)):
            raise _changed_since_read(item_id)

    def _description(self, sections: Mapping[str, Blocks], which: str) -> JsonValue:
        description = description_doc([block for blocks in sections.values() for block in blocks])
        size = 0 if description is None else compact_adf_length(description)
        if size > JIRA_DESCRIPTION_LIMIT:
            raise WriteRejectedError(
                f"the description of {which} is {size:,} characters of ADF, over the "
                f"{JIRA_DESCRIPTION_LIMIT:,} Jira takes; {SPLIT_ADVICE}"
            )
        return description

    def _read_unchanged(self, item_id: str, raw_sections: RawSections) -> dict[str, str]:
        self._last_reads.pop(item_id, None)
        history = self._history(item_id)
        self._refuse_unseen_edits(item_id, history)
        current = dict(self._read_with(item_id, history).remote.raw_sections)
        if list(current.items()) != list(raw_sections.items()):
            raise _changed_since_read(item_id)
        return current

    def _write_description(self, item_id: str, sections: Mapping[str, str]) -> RemoteItem:
        blocks = _sendable_blocks(sections)
        description = self._description(blocks, item_id)
        layout = layout_of(blocks)
        self._client.edit_issue(
            item_id, {DESCRIPTION_FIELD: description}, [_property(LAYOUT_PROPERTY, layout)]
        )
        return self._verified(
            item_id, self._read_after_write(item_id, layout, None), frozenset({DESCRIPTION_FIELD})
        )

    def _verified(self, item_id: str, read: _Read, written: frozenset[str]) -> RemoteItem:
        since = self._markers.get(item_id, NO_MARKER)
        later = [entry for entry in read.history if entry.number > since]
        own = _newest_entry(entry for entry in later if self._is_skaldrs(entry, written))
        replaced = [
            entry
            for entry in later
            if own is not None and entry.number < own.number and _identities(entry) & written
        ]
        if replaced:
            raise ConnectorError(
                f"{item_id}: skaldr's write replaced an edit made in Jira just before it "
                f"({'; '.join(_described(entry, written) for entry in replaced)}); restore it from the "
                "issue's history if it should stay"
            )
        foreign = [entry for entry in self._owned_entries(item_id, later) if entry is not own]
        if foreign:
            names = sorted({name for entry in foreign for name in _names(entry)} & self._owned_names(item_id))
            raise ConnectorError(
                f"{item_id} was edited in Jira while skaldr wrote to it ({', '.join(names)}); the write "
                "landed, and the next publish shows the edit"
            )
        return self._handed_over(item_id, read.remote, since if own is None else own.number)

    def _handed_over(self, item_id: str, remote: RemoteItem, marker: int) -> RemoteItem:
        self._markers[item_id] = marker
        return replace(remote, marker=_marker(marker))

    def _read_after_write(self, item_id: str, layout: Layout, stamp: StampValue | None) -> _Read:
        read = self._read(item_id)
        repairs = [
            *([_property(LAYOUT_PROPERTY, layout)] if read.layout != layout else []),
            *([_property(STAMP_PROPERTY, stamp)] if stamp is not None and read.stamp != stamp else []),
        ]
        for repair in repairs:
            self._client.put_property(item_id, repair.key, repair.value)
        if not repairs:
            return read
        return self._assembled(item_id, read.issue, layout, stamp or read.stamp, read.history)

    def _read(self, item_id: str) -> _Read:
        return self._read_with(item_id, self._history(item_id))

    def _history(self, item_id: str) -> tuple[Changelog, ...]:
        try:
            return tuple(self._client.changelog(item_id))
        except ItemNotFoundError:
            self._client.myself()
            raise

    def _read_with(self, item_id: str, history: tuple[Changelog, ...]) -> _Read:
        stamp, layout = self._stamp(item_id), self._layout(item_id)
        names = list(dict.fromkeys([SUMMARY_FIELD, DESCRIPTION_FIELD, *self._field_shapes.get(item_id, {})]))
        issue = self._client.get_issue(item_id, names)
        return self._assembled(item_id, issue, layout, stamp, history)

    def _assembled(
        self,
        item_id: str,
        issue: Issue,
        layout: Layout | None,
        stamp: StampValue | None,
        history: tuple[Changelog, ...],
    ) -> _Read:
        if stamp is not None and stamp.archived:
            raise ItemNotFoundError(f"skaldr archived {item_id}, so it no longer publishes there")
        return _Read(issue, self._remote(item_id, issue, layout, stamp, history), layout, stamp, history)

    def _remote(
        self,
        item_id: str,
        issue: Issue,
        layout: Layout | None,
        stamp: StampValue | None,
        history: Sequence[Changelog],
    ) -> RemoteItem:
        sections = split_description(blocks_of(issue.fields.get(DESCRIPTION_FIELD)), layout)
        raw = {key: section_text(blocks) for key, blocks in sections.items()}
        summary = issue.fields.get(SUMMARY_FIELD)
        fields = {
            name: self._read_field(issue, name, self._shape(item_id, name), stamp)
            for name in self._field_shapes.get(item_id, {})
        }
        latest = _newest_entry(self._owned_entries(item_id, history))
        return RemoteItem(
            item_id,
            ItemContent(
                title=summary if isinstance(summary, str) else "",
                sections={key: comparable_section(text) for key, text in raw.items()},
                fields=fields,
            ),
            raw,
            None if stamp is None else stamp.stamp,
            _marker(_newest(history)),
            edited_by=None if latest is None or latest.author is None else latest.author.display_name,
            edited_at=None if latest is None else latest.created,
            set_properties=tuple(name for name, value in fields.items() if not is_unset(value)),
        )

    def _read_field(self, issue: Issue, name: str, shape: JsonValue, stamp: StampValue | None) -> JsonValue:
        value = issue.fields.get(name)
        if name != LABELS:
            return _projected(value, shape)
        own = None if stamp is None or stamp.doc_id is None else doc_label(stamp.doc_id)
        return [label for label in _labels(value) if label != own]

    def _property_value(self, item_id: str, name: str, model: type[Stored]) -> Stored | None:
        found = self._client.get_property(item_id, name)
        return None if found is None else model.model_validate(found.value)

    def _stamp(self, item_id: str) -> StampValue | None:
        try:
            return self._property_value(item_id, STAMP_PROPERTY, StampValue)
        except ValidationError as exc:
            raise ConnectorError(
                f"the {STAMP_PROPERTY} property of {item_id} is not one skaldr can read, so skaldr cannot "
                "tell which document the issue belongs to or whether it archived the issue"
            ) from exc

    def _layout(self, item_id: str) -> Layout | None:
        try:
            return self._property_value(item_id, LAYOUT_PROPERTY, Layout)
        except ValidationError:
            return None

    def _done_transition(self, item_id: str, status: Status) -> Transition:
        done = next((option for option in self._client.transitions(item_id) if option.to.is_done), None)
        if done is None:
            raise WriteRejectedError(
                f"{item_id} has no transition from '{status.name}' to a done status, so skaldr cannot "
                "archive it; close it in Jira, then publish again"
            )
        return done
