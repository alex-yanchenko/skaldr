from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from skaldr.errors import ConnectorError
from skaldr.export.notion import render_notion_regions
from skaldr.export.tree import LoweredDocument
from skaldr.models import Report, parse_report
from skaldr.publish import ConnectorRegistry, ContentLimit
from skaldr.publish.content import FIELDS, TITLE, ItemContent, Part, section_part
from skaldr.publish.transport import NewItem, RemoteItem, SectionWrite
from skaldr.publish_block import NotionTarget, TargetBase, notion_page_id
from skaldr.publish_block.target import JsonFields
from tests.factories.export_factory import API_BADGES, write_report
from tests.factories.report_factory import NOTION_PAGE_URL, make_report

DOC_ID = "garden-handbook"
OTHER_DOC_ID = "kitchen-rota"
TARGET_LABEL = "notion page 0123456789abcdef0123456789abcdef"
REFUSED_WRITE = "the service refused the write"


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
        meta={"title": "Garden handbook", "subtitle": ["For new members"], "toc": True},
        badges=API_BADGES,
        publish=publish if publish is not None else make_notion_publish(split=["tools"]),
        blocks=blocks if blocks is not None else make_garden_blocks(),
        **overrides,
    )


def parse_garden_report(**overrides: Any) -> Report:
    return parse_report(make_garden_report(**overrides))


def write_garden_report(directory: Path, **overrides: Any) -> Path:
    return write_report(directory, make_garden_report(**overrides))


@dataclass
class FakeItem:
    content: ItemContent
    doc_id: str | None
    parent_id: str | None
    revision: int
    archived: bool = False


@dataclass
class FakeTransport:
    fail_at_write: int | None = None
    items: dict[str, FakeItem] = field(default_factory=dict[str, FakeItem])
    calls: list[tuple[str, ...]] = field(default_factory=list[tuple[str, ...]])
    hand_edits: list[tuple[str, int, Part]] = field(default_factory=list[tuple[str, int, Part]])
    _revision: int = 0
    _writes: int = 0

    def seed(self, item_id: str, content: ItemContent, doc_id: str | None) -> None:
        self.items[item_id] = FakeItem(content, doc_id, None, self._bump())

    def edit_by_hand(
        self,
        item_id: str,
        *,
        section: str | None = None,
        text: str | None = None,
        title: str | None = None,
        fields: JsonFields | None = None,
    ) -> None:
        item = self.items[item_id]
        content = item.content
        part = TITLE
        if section is not None:
            sections = {**content.sections, section: text or ""}
            content = content.model_copy(update={"sections": sections})
            part = section_part(section)
        if title is not None:
            content = content.model_copy(update={"title": title})
        if fields is not None:
            content = content.model_copy(update={"fields": fields})
            part = FIELDS
        item.content = content
        item.revision = self._bump()
        self.hand_edits.append((item_id, item.revision, part))

    def report_an_edit_without_changing_content(self, item_id: str, part: Part) -> None:
        item = self.items[item_id]
        item.revision = self._bump()
        self.hand_edits.append((item_id, item.revision, part))

    def writes(self) -> list[tuple[str, ...]]:
        return [call for call in self.calls if call[0] not in ("read", "edits_since")]

    def create_item(self, item: NewItem, /) -> RemoteItem:
        self._write(("create", item.content.title, item.parent_id or "", item.into_id or ""))
        item_id = item.into_id or f"page-{len(self.items) + 1}"
        self.items[item_id] = FakeItem(item.content, item.doc_id, item.parent_id, self._bump())
        return self._remote(item_id)

    def read_item(self, item_id: str, _published: ItemContent, /) -> RemoteItem:
        self.calls.append(("read", item_id))
        return self._remote(item_id)

    def write_section(self, item_id: str, write: SectionWrite, /) -> RemoteItem:
        self._write(("write_section", item_id, write.key))
        item = self.items[item_id]
        sections = dict(item.content.sections)
        if write.current is not None:
            if sections.get(write.key) != write.current:
                raise ConnectorError(f"no matches found for section {write.key}")
            del sections[write.key]
        if write.text is not None:
            order = list(sections)
            at = 0 if write.follows is None else order.index(write.follows) + 1
            pairs = list(sections.items())
            sections = dict([*pairs[:at], (write.key, write.text), *pairs[at:]])
        item.content = item.content.model_copy(update={"sections": sections})
        item.revision = self._bump()
        return self._remote(item_id)

    def write_fields(self, item_id: str, title: str, fields: JsonFields, /) -> RemoteItem:
        self._write(("write_fields", item_id))
        item = self.items[item_id]
        item.content = item.content.model_copy(update={"title": title, "fields": fields})
        item.revision = self._bump()
        return self._remote(item_id)

    def archive_item(self, item_id: str, /) -> None:
        self._write(("archive", item_id))
        self.items[item_id].archived = True

    def remote_edits_since(self, item_id: str, marker: str | None, /) -> tuple[Part, ...]:
        self.calls.append(("edits_since", item_id))
        since = int(marker or "0")
        return tuple(
            part for edited, revision, part in self.hand_edits if edited == item_id and revision > since
        )

    def _write(self, call: tuple[str, ...]) -> None:
        self._writes += 1
        if self._writes == self.fail_at_write:
            raise ConnectorError(REFUSED_WRITE)
        self.calls.append(call)

    def _bump(self) -> int:
        self._revision += 1
        return self._revision

    def _remote(self, item_id: str) -> RemoteItem:
        item = self.items[item_id]
        return RemoteItem(item_id, item.content, item.doc_id, str(item.revision))


@dataclass(frozen=True)
class FakeConnector:
    target_type: type[TargetBase]
    transport: FakeTransport = field(default_factory=FakeTransport)
    limits: tuple[ContentLimit, ...] = ()

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
) -> ConnectorRegistry:
    return ConnectorRegistry([FakeConnector(target_type, transport, limits) for target_type in target_types])
