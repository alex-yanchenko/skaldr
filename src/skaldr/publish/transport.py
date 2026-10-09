from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Protocol

from skaldr.publish.content import ItemContent, Part, comparable
from skaldr.publish_block.target import JsonFields, TargetBase

RawSections = Mapping[str, str]
NO_SECTIONS: RawSections = MappingProxyType({})


@dataclass(frozen=True)
class Stamp:
    doc_id: str
    section_id: str | None


@dataclass(frozen=True)
class RemoteItem:
    item_id: str
    comparable: ItemContent
    raw_sections: RawSections
    doc_id: str | None
    marker: str | None = None
    edited_by: str | None = None
    edited_at: str | None = None
    child_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class NewItem:
    target: TargetBase
    stamp: Stamp
    content: ItemContent
    parent_id: str | None = None
    into_id: str | None = None
    into_raw_sections: RawSections = field(default=NO_SECTIONS)


@dataclass(frozen=True)
class AddSection:
    key: str
    text: str
    follows: str | None


@dataclass(frozen=True)
class ReplaceSection:
    key: str
    raw_current: str
    text: str
    follows: str | None

    def moves_within(self, raw_sections: RawSections) -> bool:
        keys = list(raw_sections)
        position = keys.index(self.key)
        sits_after = keys[position - 1] if position > 0 else None
        return sits_after != self.follows


@dataclass(frozen=True)
class RemoveSection:
    key: str
    raw_current: str


SectionWrite = AddSection | ReplaceSection | RemoveSection


@dataclass(frozen=True)
class FieldsWrite:
    title: str
    fields: JsonFields
    previous_title: str
    previous_fields: JsonFields
    stamp: Stamp

    @property
    def changed_fields(self) -> JsonFields:
        return {
            name: value
            for name, value in self.fields.items()
            if name not in self.previous_fields or comparable(self.previous_fields[name]) != comparable(value)
        }

    @property
    def cleared_fields(self) -> tuple[str, ...]:
        return tuple(name for name in self.previous_fields if name not in self.fields)

    @property
    def changes_the_title(self) -> bool:
        return self.title != self.previous_title


class Transport(Protocol):
    def create_item(self, item: NewItem, /) -> RemoteItem: ...

    def read_item(self, item_id: str, published: ItemContent, /) -> RemoteItem: ...

    def comparable_form(self, content: ItemContent, /) -> ItemContent: ...

    def write_section(
        self, item_id: str, write: SectionWrite, raw_sections: RawSections, /
    ) -> RemoteItem: ...

    def write_content(
        self, item_id: str, sections: Mapping[str, str], raw_sections: RawSections, /
    ) -> RemoteItem: ...

    def write_fields(self, item_id: str, write: FieldsWrite, /) -> RemoteItem: ...

    def archive_item(self, item_id: str, /) -> None: ...

    def release_item(self, item_id: str, raw_sections: RawSections, /) -> None: ...

    def remote_edits_since(self, item_id: str, marker: str | None, /) -> tuple[Part, ...]: ...
