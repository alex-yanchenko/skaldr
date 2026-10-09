import re
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from skaldr.errors import ConnectorError, ItemNotFoundError, WriteRejectedError
from skaldr.export.notion import render_notion_regions
from skaldr.export.tree import LoweredDocument
from skaldr.models import Report
from skaldr.publish import ConnectorRegistry, ContentLimit
from skaldr.publish.connector import WriteGranularity
from skaldr.publish.content import FIELDS, ItemContent, Part, section_part
from skaldr.publish.drafts import Authored, authored_from
from skaldr.publish.transport import (
    AddSection,
    FieldsWrite,
    NewItem,
    RawSections,
    RemoteItem,
    RemoveSection,
    SectionWrite,
    Stamp,
)
from skaldr.publish_block import NotionTarget, TargetBase, notion_page_id
from skaldr.publish_block.target import JsonFields
from tests.factories.export_factory import API_BADGES, write_report
from tests.factories.report_factory import NOTION_PAGE_URL, make_report

DOC_ID = "garden-handbook"
OTHER_DOC_ID = "kitchen-rota"
TARGET_LABEL = "notion page 0123456789abcdef0123456789abcdef"
INTO_LABEL = f"{TARGET_LABEL} (written into)"
REFUSED_WRITE = "the service refused the write"
DROPPED_AFTER_WRITE = "the connection dropped after the service took the write"
LOST_WRITE = "the connection dropped before the service saw the write"
COMMENT_MARKER = re.compile(r'<span discussion-urls="[^"]*">(.*?)</span>')
INTRO_KEY = "block 2c7116fc"
NEW_INTRO_KEY = "block e976d1ce"


def make_garden_blocks(**changes: str) -> list[dict[str, Any]]:
    return [
        {"type": "text", "body": changes.get("intro", "Welcome to the garden.")},
        {
            "type": "section",
            "id": "tools",
            "title": changes.get("tools_title", "Tools"),
            "collapsed": False,
            "blocks": [
                {"type": "badge_row", "items": [{"key": "API"}]},
                {"type": "list", "items": [changes.get("tools", "Spade.")]},
            ],
        },
        {
            "type": "section",
            "id": "planting",
            "title": "Planting",
            "collapsed": False,
            "blocks": [{"type": "text", "body": changes.get("planting", "Sow in spring.")}],
        },
    ]


def make_notion_publish(**target: Any) -> dict[str, Any]:
    return {
        "doc_id": DOC_ID,
        "targets": [{"to": "notion", "where": {"parent_page": NOTION_PAGE_URL}, **target}],
    }


def make_garden_report(
    publish: dict[str, Any] | None = None, blocks: list[dict[str, Any]] | None = None, **overrides: Any
) -> dict[str, Any]:
    return make_report(
        **{
            "meta": {"title": "Garden handbook", "subtitle": ["For new members"], "toc": True},
            "badges": API_BADGES,
            "publish": publish if publish is not None else make_notion_publish(split=["tools"]),
            "blocks": blocks if blocks is not None else make_garden_blocks(),
            **overrides,
        }
    )


def authored_garden(**overrides: Any) -> Authored:
    return authored_from(make_garden_report(**overrides))


def write_garden_report(directory: Path, **overrides: Any) -> Path:
    return write_report(directory, make_garden_report(**overrides))


def _without_comment_markers(text: str) -> str:
    return COMMENT_MARKER.sub(r"\1", text)


@dataclass
class FakeItem:
    title: str
    raw_sections: dict[str, str]
    fields: JsonFields
    stamp: Stamp | None
    parent_id: str | None
    revision: int
    archived: bool = False
    children: tuple[str, ...] = ()

    @property
    def content(self) -> ItemContent:
        sections = {key: _without_comment_markers(text) for key, text in self.raw_sections.items()}
        return ItemContent(title=self.title, sections=sections, fields=self.fields)


@dataclass
class FakeTransport:
    reads_list_fields_reversed: bool = False
    strips_trailing_whitespace: bool = False
    items: dict[str, FakeItem] = field(default_factory=dict[str, FakeItem])
    calls: list[tuple[str, ...]] = field(default_factory=list[tuple[str, ...]])
    hand_edits: list[tuple[str, int, Part]] = field(default_factory=list[tuple[str, int, Part]])
    _revision: int = 0
    _items_made: int = 0
    _writes: int = 0
    _failing_write: int | None = None
    _dropping_after_write: int | None = None
    _losing_write: int | None = None
    _landing_one_section_of: int | None = None

    def lose_the_next_write(self) -> None:
        self._losing_write = self._writes + 1

    def land_only_the_first_section_of_the_next_content_write(self) -> None:
        self._landing_one_section_of = self._writes + 1

    def comparable_form(self, content: ItemContent, /) -> ItemContent:
        sections = {key: self._stored(text) for key, text in content.sections.items()}
        return content.model_copy(update={"sections": sections})

    def _stored(self, text: str) -> str:
        return text.rstrip() if self.strips_trailing_whitespace else text

    def seed(
        self,
        item_id: str,
        title: str,
        doc_id: str | None,
        sections: dict[str, str] | None = None,
        *,
        children: tuple[str, ...] = (),
        fields: JsonFields | None = None,
    ) -> None:
        stamp = None if doc_id is None else Stamp(doc_id, None)
        self._items_made += 1
        self.items[item_id] = FakeItem(
            title, dict(sections or {}), dict(fields or {}), stamp, None, self._bump(), children=children
        )

    def fail_on_write(self, count_from_now: int) -> None:
        self._failing_write = self._writes + count_from_now

    def drop_the_connection_after_write(self, count_from_now: int) -> None:
        self._dropping_after_write = self._writes + count_from_now

    def stop_failing(self) -> None:
        self._failing_write = None
        self._dropping_after_write = None
        self._losing_write = None
        self._landing_one_section_of = None

    def comment_on(self, item_id: str, key: str) -> None:
        item = self.items[item_id]
        first, _, rest = item.raw_sections[key].partition("\n")
        item.raw_sections[key] = f'<span discussion-urls="discussion://1">{first}</span>\n{rest}'

    def edit_section_by_hand(self, item_id: str, key: str, text: str) -> None:
        self.items[item_id].raw_sections[key] = text
        self.report_an_edit_without_changing_content(item_id, section_part(key))

    def delete_section_by_hand(self, item_id: str, key: str) -> None:
        del self.items[item_id].raw_sections[key]
        self.report_an_edit_without_changing_content(item_id, section_part(key))

    def delete_item_by_hand(self, item_id: str) -> None:
        del self.items[item_id]

    def edit_fields_by_hand(self, item_id: str, fields: JsonFields) -> None:
        self.items[item_id].fields = fields
        self.report_an_edit_without_changing_content(item_id, FIELDS)

    def report_an_edit_without_changing_content(self, item_id: str, part: Part) -> None:
        item = self.items[item_id]
        item.revision = self._bump()
        self.hand_edits.append((item_id, item.revision, part))

    def writes(self) -> list[tuple[str, ...]]:
        return [call for call in self.calls if call[0] not in ("read", "edits_since")]

    def forget_calls(self) -> None:
        self.calls.clear()

    def create_item(self, item: NewItem, /) -> RemoteItem:
        self._write(("create", item.content.title, item.parent_id or "", item.into_id or ""))
        if item.into_id is not None:
            self._refuse_a_stale_layout(item.into_id, item.into_raw_sections)
        item_id = item.into_id or self._new_item_id()
        content = self.comparable_form(item.content)
        self.items[item_id] = FakeItem(
            content.title,
            dict(content.sections),
            dict(content.fields),
            item.stamp,
            item.parent_id,
            self._bump(),
        )
        return self._after_write(item_id)

    def read_item(self, item_id: str, _published: ItemContent, /) -> RemoteItem:
        self.calls.append(("read", item_id))
        if item_id not in self.items or self.items[item_id].archived:
            raise ItemNotFoundError(f"{item_id} is not on the service")
        remote = self._remote(item_id)
        if not self.reads_list_fields_reversed:
            return remote
        comparable = remote.comparable
        reversed_fields: JsonFields = {
            name: list(reversed(value)) if isinstance(value, list) else value
            for name, value in comparable.fields.items()
        }
        return replace(remote, comparable=comparable.model_copy(update={"fields": reversed_fields}))

    def write_section(self, item_id: str, write: SectionWrite, raw_sections: RawSections, /) -> RemoteItem:
        self._write(("write_section", item_id, write.key))
        self._refuse_a_stale_layout(item_id, raw_sections)
        item = self.items[item_id]
        sections = dict(item.raw_sections)
        if not isinstance(write, AddSection):
            if sections.get(write.key) != write.raw_current:
                raise WriteRejectedError(f"no matches found for section {write.key}")
            del sections[write.key]
        if not isinstance(write, RemoveSection):
            pairs = list(sections.items())
            at = 0 if write.follows is None else list(sections).index(write.follows) + 1
            sections = dict([*pairs[:at], (write.key, self._stored(write.text)), *pairs[at:]])
        item.raw_sections = sections
        item.revision = self._bump()
        return self._after_write(item_id)

    def write_content(
        self, item_id: str, sections: Mapping[str, str], raw_sections: RawSections, /
    ) -> RemoteItem:
        self._write(("write_content", item_id))
        self._refuse_a_stale_layout(item_id, raw_sections)
        item = self.items[item_id]
        stored = {key: self._stored(text) for key, text in sections.items()}
        if self._writes == self._landing_one_section_of:
            changed = next(key for key, text in stored.items() if item.raw_sections.get(key) != text)
            item.raw_sections = {**item.raw_sections, changed: stored[changed]}
            item.revision = self._bump()
            raise ConnectorError(DROPPED_AFTER_WRITE)
        item.raw_sections = stored
        item.revision = self._bump()
        return self._after_write(item_id)

    def write_fields(self, item_id: str, write: FieldsWrite, /) -> RemoteItem:
        title = ("title",) if write.changes_the_title else ()
        changed = tuple(f"set {name}" for name in sorted(write.changed_fields))
        cleared = tuple(f"clear {name}" for name in sorted(write.cleared_fields))
        self._write(("write_fields", item_id, *title, *changed, *cleared))
        item = self.items[item_id]
        if item.stamp is None or item.stamp.doc_id != write.stamp.doc_id:
            raise ConnectorError(f"{item_id} is not stamped with {write.stamp.doc_id}")
        kept = {name: value for name, value in item.fields.items() if name not in write.cleared_fields}
        item.fields = {**kept, **write.changed_fields}
        item.title = write.title
        item.revision = self._bump()
        return self._after_write(item_id)

    def archive_item(self, item_id: str, /) -> None:
        self._write(("archive", item_id))
        self.items[item_id].archived = True
        self._drop_the_connection_if_asked()

    def release_item(self, item_id: str, raw_sections: RawSections, /) -> None:
        self._write(("release", item_id))
        self._refuse_a_stale_layout(item_id, raw_sections)
        item = self.items[item_id]
        item.raw_sections = {}
        item.fields = {}
        item.stamp = None
        item.revision = self._bump()
        self._drop_the_connection_if_asked()

    def remote_edits_since(self, item_id: str, marker: str | None, /) -> tuple[Part, ...]:
        self.calls.append(("edits_since", item_id))
        since = int(marker or "0")
        return tuple(
            part for edited, revision, part in self.hand_edits if edited == item_id and revision > since
        )

    def _refuse_a_stale_layout(self, item_id: str, raw_sections: RawSections) -> None:
        if list(raw_sections.items()) != list(self.items[item_id].raw_sections.items()):
            raise ConnectorError(f"the layout skaldr sent for {item_id} is not the one on the service")

    def _write(self, call: tuple[str, ...]) -> None:
        self._writes += 1
        if self._writes == self._failing_write:
            raise WriteRejectedError(REFUSED_WRITE)
        if self._writes == self._losing_write:
            raise ConnectorError(LOST_WRITE)
        self.calls.append(call)

    def _drop_the_connection_if_asked(self) -> None:
        if self._writes == self._dropping_after_write:
            raise ConnectorError(DROPPED_AFTER_WRITE)

    def _after_write(self, item_id: str) -> RemoteItem:
        self._drop_the_connection_if_asked()
        return self._remote(item_id)

    def _bump(self) -> int:
        self._revision += 1
        return self._revision

    def _new_item_id(self) -> str:
        self._items_made += 1
        return f"page-{self._items_made}"

    def _remote(self, item_id: str) -> RemoteItem:
        item = self.items[item_id]
        doc_id = None if item.stamp is None else item.stamp.doc_id
        return RemoteItem(
            item_id,
            item.content,
            dict(item.raw_sections),
            doc_id,
            str(item.revision),
            child_ids=item.children,
        )


@dataclass(frozen=True)
class FakeConnector:
    target_type: type[TargetBase]
    transport: FakeTransport = field(default_factory=FakeTransport)
    limits: tuple[ContentLimit, ...] = ()
    writes: WriteGranularity = "section"

    def render_regions(self, report: Report, page: LoweredDocument, /) -> tuple[str, ...]:
        return render_notion_regions(page, report.meta.notion_width)

    def existing_item_id(self, target: TargetBase, /) -> str | None:
        if isinstance(target, NotionTarget) and target.where.page is not None:
            return notion_page_id(target.where.page)
        return None

    def open_transport(self, _target: TargetBase, /) -> FakeTransport:
        return self.transport


def fake_registry(
    transport: FakeTransport,
    limits: tuple[ContentLimit, ...] = (),
    target_types: tuple[type[TargetBase], ...] = (NotionTarget,),
    writes: WriteGranularity = "section",
) -> ConnectorRegistry:
    return ConnectorRegistry(
        [FakeConnector(target_type, transport, limits, writes) for target_type in target_types]
    )
