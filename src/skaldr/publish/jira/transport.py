from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, JsonValue, ValidationError

from skaldr.errors import ConnectorError, ItemNotFoundError, WriteRejectedError
from skaldr.export.adf import JIRA_DESCRIPTION_LIMIT, compact_adf_length
from skaldr.publish.content import FIELDS, TITLE, ItemContent, Part, is_unset, placed_section, section_part
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
NOTHING_TO_RELEASE = (
    "Jira has nothing to release: skaldr writes only into issues it created, and archives those"
)
SPLIT_ADVICE = "split the document further with `split`, or shorten it"


class StampValue(BaseModel):
    model_config = ConfigDict(frozen=True)

    doc_id: str | None
    section_id: str | None = None
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


@dataclass(frozen=True)
class _Read:
    remote: RemoteItem
    layout: Layout | None
    stamp: StampValue | None


class JiraTransport:
    def __init__(self, client: JiraClient) -> None:
        self._client = client
        self._field_shapes: dict[str, JsonFields] = {}

    def comparable_form(self, content: ItemContent, /) -> ItemContent:
        sections = {key: comparable_section(text) for key, text in content.sections.items()}
        return content.model_copy(update={"sections": {key: text for key, text in sections.items() if text}})

    def read_item(self, item_id: str, keyed_like: ItemContent, /) -> RemoteItem:
        self._remember_shapes(item_id, keyed_like.fields)
        return self._read(item_id).remote

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
        return self._read_after_write(created.key, layout, stamp)

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
        changes: dict[str, JsonValue] = {SUMMARY: request.title} if request.changes_the_title else {}
        for name, value in request.changed_fields.items():
            changes[name] = _with_doc_label(value, request.stamp.doc_id) if name == LABELS else value
        for name in request.cleared_fields:
            changes[name] = [doc_label(request.stamp.doc_id)] if name == LABELS else None
        if changes:
            self._client.edit_issue(item_id, changes)
        return self._read(item_id).remote

    def archive_item(self, item_id: str, /) -> None:
        stamp = self._stamp(item_id)
        if stamp is not None and stamp.archived:
            return
        status = self._status(self._client.get_issue(item_id, ["status"]))
        if not status.is_done:
            self._client.transition(item_id, self._done_transition(item_id, status).id)
            self._client.add_comment(item_id, _archive_comment(stamp))
        archived = (stamp or StampValue(doc_id=None)).model_copy(update={"archived": True})
        self._client.put_property(item_id, STAMP_PROPERTY, archived.model_dump(mode="json"))

    def release_item(self, _item_id: str, _request: Release, /) -> None:
        raise ConnectorError(NOTHING_TO_RELEASE)

    def parts_edited_after(
        self, item_id: str, marker: str | None, keyed_like: ItemContent, /
    ) -> tuple[Part, ...]:
        self._remember_shapes(item_id, keyed_like.fields)
        since = int(marker) if marker is not None and marker.isdigit() else -1
        touched = {
            name
            for entry in self._client.changelog(item_id)
            if entry.number > since
            for item in entry.items
            for name in item.names
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
        current = dict(self._read(item_id).remote.raw_sections)
        if list(current.items()) != list(raw_sections.items()):
            raise WriteRejectedError(
                f"{item_id} changed in Jira after skaldr read it, so skaldr did not write its description; "
                "publish again to see the change"
            )
        return current

    def _write_description(self, item_id: str, sections: Mapping[str, str]) -> RemoteItem:
        blocks = {key: section_blocks(text) for key, text in sections.items()}
        description = self._description(blocks, item_id)
        layout = layout_of(blocks)
        self._client.edit_issue(item_id, {DESCRIPTION: description}, [_property(LAYOUT_PROPERTY, layout)])
        return self._read_after_write(item_id, layout, None)

    def _read_after_write(self, item_id: str, layout: Layout, stamp: StampValue | None) -> RemoteItem:
        read = self._read(item_id)
        repairs = [
            *([_property(LAYOUT_PROPERTY, layout)] if read.layout != layout else []),
            *([_property(STAMP_PROPERTY, stamp)] if stamp is not None and read.stamp != stamp else []),
        ]
        for repair in repairs:
            self._client.put_property(item_id, repair.key, repair.value)
        return self._read(item_id).remote if repairs else read.remote

    def _read(self, item_id: str) -> _Read:
        shapes = self._field_shapes.get(item_id, {})
        names = list(dict.fromkeys([SUMMARY, DESCRIPTION, *shapes]))
        try:
            issue = self._client.get_issue(item_id, names)
        except ItemNotFoundError:
            self._client.myself()
            raise
        stamp = self._stamp(item_id)
        if stamp is not None and stamp.archived:
            raise ItemNotFoundError(f"skaldr archived {item_id}, so it no longer publishes there")
        layout = self._layout(item_id)
        history = self._client.changelog(item_id)
        return _Read(self._remote(item_id, issue, layout, stamp, history), layout, stamp)

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
        shapes = self._field_shapes.get(item_id, {})
        fields = {name: self._read_field(issue, name, shape, stamp) for name, shape in shapes.items()}
        latest = self._latest_edit(history, {SUMMARY, DESCRIPTION, *shapes})
        return RemoteItem(
            item_id,
            ItemContent(
                title=summary if isinstance(summary, str) else "",
                sections={key: comparable_section(text) for key, text in raw.items()},
                fields=fields,
            ),
            raw,
            None if stamp is None else stamp.stamp,
            str(max(entry.number for entry in history)) if history else None,
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

    def _latest_edit(self, history: Iterable[Changelog], owned: set[str]) -> Changelog | None:
        touching = [entry for entry in history if any(item.names & owned for item in entry.items)]
        return max(touching, key=lambda entry: entry.number, default=None)

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
