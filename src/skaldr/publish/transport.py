from dataclasses import dataclass
from typing import Protocol

from skaldr.publish.content import ItemContent, Part
from skaldr.publish_block.target import JsonFields, TargetBase


@dataclass(frozen=True)
class RemoteItem:
    item_id: str
    content: ItemContent
    doc_id: str | None
    marker: str | None = None
    edited_by: str | None = None
    edited_at: str | None = None


@dataclass(frozen=True)
class NewItem:
    target: TargetBase
    doc_id: str
    content: ItemContent
    parent_id: str | None = None
    into_id: str | None = None


@dataclass(frozen=True)
class SectionWrite:
    key: str
    current: str | None
    text: str | None
    follows: str | None


class Transport(Protocol):
    def create_item(self, item: NewItem, /) -> RemoteItem: ...

    def read_item(self, item_id: str, published: ItemContent, /) -> RemoteItem: ...

    def write_section(self, item_id: str, write: SectionWrite, /) -> RemoteItem: ...

    def write_fields(self, item_id: str, title: str, fields: JsonFields, /) -> RemoteItem: ...

    def archive_item(self, item_id: str, /) -> None: ...

    def remote_edits_since(self, item_id: str, marker: str | None, /) -> tuple[Part, ...]: ...
