from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Protocol, runtime_checkable

from skaldr.frozen_model import FrozenModel
from skaldr.publish.content import ItemContent, Part, is_unset, same_value

__all__ = [
    "NO_PUBLISHED",
    "NO_SECTIONS",
    "AddSection",
    "ContentWrite",
    "FieldsWrite",
    "FillsAPageLeftEmpty",
    "ItemLink",
    "LinkedItem",
    "LinksWrite",
    "NewItem",
    "PlacesItsCreates",
    "PublishedSections",
    "RawSections",
    "RefusesFieldsAnItemCannotHold",
    "Release",
    "RemoteItem",
    "RemoveSection",
    "ReplaceSection",
    "SectionRequest",
    "SectionWrite",
    "ShownLink",
    "Stamp",
    "Transport",
    "is_unset",
]
from skaldr.publish_block.target import JsonFields, TargetBase
from skaldr.services import Service

RawSections = Mapping[str, str]
NO_SECTIONS: RawSections = MappingProxyType({})


@dataclass(frozen=True)
class PublishedSections:
    rendered: RawSections
    saved_remote: RawSections


NO_PUBLISHED = PublishedSections(NO_SECTIONS, NO_SECTIONS)


@dataclass(frozen=True)
class Stamp:
    doc_id: str
    section_id: str | None

    @property
    def named(self) -> str:
        section = "" if self.section_id is None else f", section '{self.section_id}'"
        return f"doc_id '{self.doc_id}'{section}"


LinkedItem = tuple[Service, str]


class ShownLink(FrozenModel):
    service: Service
    item_id: str
    url: str
    title: str

    @property
    def linked_item(self) -> LinkedItem:
        return (self.service, self.item_id)


@dataclass(frozen=True)
class ItemLink:
    url: str
    title: str


@dataclass(frozen=True)
class LinksWrite:
    stamp: Stamp
    links: tuple[ShownLink, ...]
    current: tuple[ShownLink, ...] = ()
    published: PublishedSections = NO_PUBLISHED

    @property
    def sent(self) -> tuple[ShownLink, ...]:
        held = {link.linked_item: link for link in self.current}
        return tuple(link for link in self.links if held.get(link.linked_item) != link)

    @property
    def dropped(self) -> tuple[ShownLink, ...]:
        kept = {link.linked_item for link in self.links}
        return tuple(link for link in self.current if link.linked_item not in kept)

    @property
    def changes_nothing(self) -> bool:
        return not self.sent and not self.dropped


@dataclass(frozen=True)
class RemoteItem:
    item_id: str
    comparable: ItemContent
    raw_sections: RawSections
    stamp: Stamp | None
    marker: str | None = None
    edited_by: str | None = None
    edited_at: str | None = None
    child_ids: tuple[str, ...] = ()
    set_properties: tuple[str, ...] = ()
    links: tuple[ShownLink, ...] | None = None

    @property
    def doc_id(self) -> str | None:
        return None if self.stamp is None else self.stamp.doc_id


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
class SectionRequest:
    change: SectionWrite
    raw_sections: RawSections
    stamp: Stamp
    published: PublishedSections = NO_PUBLISHED


@dataclass(frozen=True)
class ContentWrite:
    sections: Mapping[str, str]
    raw_sections: RawSections
    stamp: Stamp


@dataclass(frozen=True)
class Release:
    raw_sections: RawSections
    field_names: tuple[str, ...]
    clears_icon: bool = False
    clears_cover: bool = False


@dataclass(frozen=True)
class FieldsWrite:
    title: str
    fields: JsonFields
    previous_title: str
    previous_fields: JsonFields
    stamp: Stamp
    icon: str | None = None
    cover: str | None = None
    previous_icon: str | None = None
    previous_cover: str | None = None
    published: PublishedSections = NO_PUBLISHED

    @property
    def changes_the_icon(self) -> bool:
        return self.icon != self.previous_icon

    @property
    def changes_the_cover(self) -> bool:
        return self.cover != self.previous_cover

    @property
    def changed_fields(self) -> JsonFields:
        return {
            name: value
            for name, value in self.fields.items()
            if not same_value(self.previous_fields.get(name), value)
        }

    @property
    def cleared_fields(self) -> tuple[str, ...]:
        return tuple(
            name
            for name, value in self.previous_fields.items()
            if name not in self.fields and not is_unset(value)
        )

    @property
    def changes_the_title(self) -> bool:
        return self.title != self.previous_title


@runtime_checkable
class FillsAPageLeftEmpty(Protocol):
    def fill_a_page_left_empty(self, item_id: str, request: NewItem, /) -> RemoteItem: ...


@runtime_checkable
class PlacesItsCreates(Protocol):
    def where_it_creates(self, request: NewItem, /) -> str | None: ...


@runtime_checkable
class RefusesFieldsAnItemCannotHold(Protocol):
    def refuse_fields_the_item_cannot_hold(self, item_id: str, names: Sequence[str], /) -> None: ...


class Transport(Protocol):
    def read_item(self, item_id: str, keyed_like: ItemContent, /) -> RemoteItem: ...

    def comparable_form(self, content: ItemContent, /) -> ItemContent: ...

    def comparable_draft(self, content: ItemContent, /) -> ItemContent: ...

    def create_item(self, request: NewItem, /) -> RemoteItem: ...

    def write_section(self, item_id: str, request: SectionRequest, /) -> RemoteItem: ...

    def write_content(self, item_id: str, request: ContentWrite, /) -> RemoteItem: ...

    def write_fields(self, item_id: str, request: FieldsWrite, /) -> RemoteItem: ...

    def archive_item(self, item_id: str, /) -> None: ...

    def release_item(self, item_id: str, request: Release, /) -> None: ...

    def parts_edited_after(
        self, item_id: str, marker: str | None, keyed_like: ItemContent, /
    ) -> tuple[Part, ...]: ...

    def editor_name(self, user_id: str, /) -> str: ...

    def item_link(self, item_id: str, title: str, /) -> ItemLink: ...

    def read_links(self, item_id: str, stamp: Stamp, /) -> tuple[ShownLink, ...]: ...

    def write_links(self, item_id: str, request: LinksWrite, /) -> tuple[ShownLink, ...]: ...

    def close(self) -> None: ...
