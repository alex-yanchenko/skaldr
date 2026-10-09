from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace

from pydantic import BaseModel, ConfigDict, JsonValue, ValidationError

from skaldr.errors import ConnectorError, ItemNotFoundError, WriteRejectedError
from skaldr.export.adf import JIRA_DESCRIPTION_LIMIT, compact_adf_length
from skaldr.publish.content import (
    FIELDS,
    TITLE,
    ItemContent,
    Part,
    is_unset,
    placed_section,
    same_value,
    section_part,
)
from skaldr.publish.drafts import SPLIT_ADVICE
from skaldr.publish.jira.api import Changelog, EntityProperty, Issue, Status, Transition
from skaldr.publish.jira.client import JiraClient
from skaldr.publish.jira.description import (
    Blocks,
    Layout,
    blocks_of,
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
    NewItem,
    RawSections,
    Release,
    RemoteItem,
    RemoveSection,
    SectionRequest,
    Stamp,
)
from skaldr.publish_block import JiraTarget
from skaldr.publish_block.target import JsonFields

STAMP_PROPERTY = "skaldr.stamp"
LAYOUT_PROPERTY = "skaldr.layout"
LABEL_PREFIX = "skaldr-"
SUMMARY = "summary"
DESCRIPTION = "description"
LABELS = "labels"
NO_MARKER = -1
NOTHING_TO_RELEASE = (
    "Jira has nothing to release: skaldr writes only into issues it created, and archives those"
)


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


def _archive_comment(stamp: StampValue | None) -> JsonValue:
    document = "the document" if stamp is None or stamp.doc_id is None else f"the document {stamp.doc_id}"
    text = f"skaldr archived this issue: {document} no longer has the content it held."
    return description_doc([{"type": "paragraph", "content": [{"type": "text", "text": text}]}])


def _property(name: str, value: BaseModel) -> EntityProperty:
    return EntityProperty(key=name, value=value.model_dump(mode="json"))


def _number(marker: str | None) -> int:
    return int(marker) if marker is not None and marker.isdigit() else NO_MARKER


def _marker(number: int) -> str | None:
    return None if number == NO_MARKER else str(number)


def _newest(history: Iterable[Changelog]) -> int:
    return max((entry.number for entry in history), default=NO_MARKER)


def _names(entry: Changelog) -> set[str]:
    return {name for item in entry.items for name in item.names}


@dataclass(frozen=True)
class _Read:
    remote: RemoteItem
    layout: Layout | None
    stamp: StampValue | None
    history: tuple[Changelog, ...]


def _identities(entry: Changelog) -> set[str]:
    return {item.identity for item in entry.items}


def _described(entry: Changelog, written: frozenset[str]) -> str:
    author = "an unknown author" if entry.author is None else entry.author.display_name or "an unknown author"
    when = entry.created or "an unknown time"
    fields = ", ".join(sorted(_identities(entry) & written))
    return f"{fields} in changelog {entry.id} by {author} at {when}"


def _reads_as(remote: ItemContent, expected: ItemContent) -> bool:
    return (
        remote.title == expected.title
        and list(remote.sections.items()) == list(expected.sections.items())
        and all(same_value(value, remote.fields.get(name)) for name, value in expected.fields.items())
    )


class JiraTransport:
    def __init__(self, client: JiraClient, field_shapes: Mapping[str, JsonValue] | None = None) -> None:
        self._client = client
        self._target_shapes: dict[str, JsonValue] = dict(field_shapes or {})
        self._field_shapes: dict[str, JsonFields] = {}
        self._markers: dict[str, int] = {}
        self._account_id: str | None = None

    def comparable_form(self, content: ItemContent, /) -> ItemContent:
        sections = {key: comparable_section(text) for key, text in content.sections.items()}
        return content.model_copy(update={"sections": {key: text for key, text in sections.items() if text}})

    def read_item(self, item_id: str, keyed_like: ItemContent, /) -> RemoteItem:
        self._remember_shapes(item_id, keyed_like.fields)
        read = self._read(item_id)
        self._markers[item_id] = _newest(read.history)
        return read.remote

    def create_item(self, request: NewItem, /) -> RemoteItem:
        if request.into_id is not None:
            raise ConnectorError(
                "Jira publishes only into issues skaldr creates, so it cannot write into "
                f"{request.into_id}; publish under it with `parent` instead"
            )
        target = request.target
        if not isinstance(target, JiraTarget):
            raise ConnectorError(f"the Jira connector cannot publish to a {target.service()} target")
        content = request.content
        sections = {key: section_blocks(text) for key, text in content.sections.items()}
        description = self._description(sections, f'the new issue "{content.title}"')
        fields: dict[str, JsonValue] = {
            **content.fields,
            LABELS: _with_doc_label(content.fields.get(LABELS), request.stamp.doc_id),
            "project": {"key": target.where.project},
            "issuetype": {"name": target.where.issue_type},
            SUMMARY: content.title,
            DESCRIPTION: description,
        }
        parent = request.parent_id or target.where.parent
        if parent is not None:
            fields["parent"] = {"key": parent}
        stamp = StampValue(doc_id=request.stamp.doc_id, section_id=request.stamp.section_id)
        layout = layout_of(sections)
        created = self._client.create_issue(
            fields, [_property(STAMP_PROPERTY, stamp), _property(LAYOUT_PROPERTY, layout)]
        )
        self._remember_shapes(created.key, content.fields)
        read = self._read_after_write(created.key, layout, stamp)
        expected = self.comparable_form(content)
        if not self._owned_entries(created.key, read.history) and _reads_as(read.remote.comparable, expected):
            return self._handed_over(created.key, read.remote, _newest(read.history))
        published = replace(read.remote, comparable=expected)
        return self._handed_over(created.key, published, NO_MARKER)

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
        self._remember_shapes(item_id, request.fields)
        self._refuse_unseen_edits(item_id, self._client.changelog(item_id))
        changes: dict[str, JsonValue] = {SUMMARY: request.title} if request.changes_the_title else {}
        for name, value in request.changed_fields.items():
            changes[name] = _with_doc_label(value, request.stamp.doc_id) if name == LABELS else value
        for name in request.cleared_fields:
            changes[name] = [doc_label(request.stamp.doc_id)] if name == LABELS else None
        if changes:
            self._client.edit_issue(item_id, changes)
        return self._verified(item_id, self._read(item_id), frozenset(changes))

    def archive_item(self, item_id: str, /) -> None:
        stamp = self._stamp(item_id)
        if stamp is not None and stamp.archived:
            return
        current = stamp or StampValue(doc_id=None)
        status = self._status(self._client.get_issue(item_id, ["status"]))
        if not status.is_done:
            done = self._done_transition(item_id, status)
            if not current.commented:
                self._client.add_comment(item_id, _archive_comment(stamp))
                current = current.model_copy(update={"commented": True})
                self._client.put_property(item_id, STAMP_PROPERTY, current.model_dump(mode="json"))
            self._client.transition(item_id, done.id)
        archived = current.model_copy(update={"archived": True})
        self._client.put_property(item_id, STAMP_PROPERTY, archived.model_dump(mode="json"))

    def release_item(self, _item_id: str, _request: Release, /) -> None:
        raise ConnectorError(NOTHING_TO_RELEASE)

    def parts_edited_after(
        self, item_id: str, marker: str | None, keyed_like: ItemContent, /
    ) -> tuple[Part, ...]:
        self._remember_shapes(item_id, keyed_like.fields)
        since = _number(marker)
        touched = {
            name
            for entry in self._client.changelog(item_id)
            if entry.number > since
            for name in _names(entry)
        }
        parts = [
            *((TITLE,) if SUMMARY in touched else ()),
            *((FIELDS,) if touched & set(keyed_like.fields) else ()),
        ]
        if DESCRIPTION in touched:
            published = self.comparable_form(keyed_like).sections
            current = self._read(item_id).remote.comparable.sections
            keys = dict.fromkeys([*published, *current])
            parts += [section_part(key) for key in keys if published.get(key) != current.get(key)]
        return tuple(parts)

    def _remember_shapes(self, item_id: str, fields: Mapping[str, JsonValue]) -> None:
        known = self._field_shapes.setdefault(item_id, {})
        for name, value in fields.items():
            if not is_unset(value) or name not in known:
                known[name] = value

    def _shape(self, item_id: str, name: str) -> JsonValue:
        shape = self._field_shapes.get(item_id, {}).get(name)
        return self._target_shapes.get(name) if is_unset(shape) else shape

    def _owned_names(self, item_id: str) -> set[str]:
        return {SUMMARY, DESCRIPTION, *self._field_shapes.get(item_id, {})}

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
            raise WriteRejectedError(
                f"{item_id} changed in Jira after skaldr read it, so skaldr did not write to it; publish "
                "again to see the change"
            )

    def _description(self, sections: Mapping[str, Blocks], which: str) -> JsonValue:
        description = description_doc([block for blocks in sections.values() for block in blocks])
        size = compact_adf_length(description) if isinstance(description, dict) else 0
        if size > JIRA_DESCRIPTION_LIMIT:
            raise WriteRejectedError(
                f"the description of {which} is {size:,} characters of ADF, over the "
                f"{JIRA_DESCRIPTION_LIMIT:,} Jira takes; {SPLIT_ADVICE}"
            )
        return description

    def _read_unchanged(self, item_id: str, raw_sections: RawSections) -> dict[str, str]:
        current = dict(self._read(item_id, history_first=True).remote.raw_sections)
        if list(current.items()) != list(raw_sections.items()):
            raise WriteRejectedError(
                f"{item_id} changed in Jira after skaldr read it, so skaldr did not write to it; publish "
                "again to see the change"
            )
        return current

    def _write_description(self, item_id: str, sections: Mapping[str, str]) -> RemoteItem:
        blocks = {key: section_blocks(text) for key, text in sections.items()}
        description = self._description(blocks, item_id)
        layout = layout_of(blocks)
        self._client.edit_issue(item_id, {DESCRIPTION: description}, [_property(LAYOUT_PROPERTY, layout)])
        return self._verified(
            item_id, self._read_after_write(item_id, layout, None), frozenset({DESCRIPTION})
        )

    def _verified(self, item_id: str, read: _Read, written: frozenset[str]) -> RemoteItem:
        since = self._markers.get(item_id, NO_MARKER)
        later = [entry for entry in read.history if entry.number > since]
        own = max(
            (entry for entry in later if self._is_skaldrs(entry, written)),
            key=lambda entry: entry.number,
            default=None,
        )
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
        return self._read(item_id) if repairs else read

    def _read(self, item_id: str, *, history_first: bool = False) -> _Read:
        history = tuple(self._client.changelog(item_id)) if history_first else ()
        if history_first:
            self._refuse_unseen_edits(item_id, history)
            stamp, layout = self._stamp(item_id), self._layout(item_id)
            issue = self._issue(item_id)
        else:
            issue = self._issue(item_id)
            stamp, layout = self._stamp(item_id), self._layout(item_id)
            history = tuple(self._client.changelog(item_id))
        if stamp is not None and stamp.archived:
            raise ItemNotFoundError(f"skaldr archived {item_id}, so it no longer publishes there")
        return _Read(self._remote(item_id, issue, layout, stamp, history), layout, stamp, history)

    def _issue(self, item_id: str) -> Issue:
        names = list(dict.fromkeys([SUMMARY, DESCRIPTION, *self._field_shapes.get(item_id, {})]))
        try:
            return self._client.get_issue(item_id, names)
        except ItemNotFoundError:
            self._client.myself()
            raise

    def _remote(
        self,
        item_id: str,
        issue: Issue,
        layout: Layout | None,
        stamp: StampValue | None,
        history: Sequence[Changelog],
    ) -> RemoteItem:
        sections = split_description(blocks_of(issue.fields.get(DESCRIPTION)), layout)
        raw = {key: section_text(blocks) for key, blocks in sections.items()}
        summary = issue.fields.get(SUMMARY)
        fields = {
            name: self._read_field(issue, name, self._shape(item_id, name), stamp)
            for name in self._field_shapes.get(item_id, {})
        }
        latest = max(self._owned_entries(item_id, history), key=lambda entry: entry.number, default=None)
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

    def _stamp(self, item_id: str) -> StampValue | None:
        found = self._client.get_property(item_id, STAMP_PROPERTY)
        if found is None:
            return None
        try:
            return StampValue.model_validate(found.value)
        except ValidationError:
            return None

    def _layout(self, item_id: str) -> Layout | None:
        found = self._client.get_property(item_id, LAYOUT_PROPERTY)
        if found is None:
            return None
        try:
            return Layout.model_validate(found.value)
        except ValidationError:
            return None

    def _status(self, issue: Issue) -> Status:
        try:
            return Status.model_validate(issue.fields.get("status"))
        except ValidationError as exc:
            raise ConnectorError(f"Jira did not say which status {issue.key} is in") from exc

    def _done_transition(self, item_id: str, status: Status) -> Transition:
        done = next((option for option in self._client.transitions(item_id) if option.to.is_done), None)
        if done is None:
            raise WriteRejectedError(
                f"{item_id} has no transition from '{status.name}' to a done status, so skaldr cannot "
                "archive it; close it in Jira, then publish again"
            )
        return done
