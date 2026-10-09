import hashlib
import json
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Literal

from pydantic import Field, JsonValue

from skaldr.frozen_model import FrozenModel
from skaldr.publish_block.target import JsonFields

PartKind = Literal["title", "fields", "section"]


@dataclass(frozen=True)
class Part:
    kind: PartKind
    key: str = ""

    @property
    def label(self) -> str:
        return self.key if self.kind == "section" else self.kind


TITLE = Part("title")
FIELDS = Part("fields")


def section_part(key: str) -> Part:
    return Part("section", key)


class ItemContent(FrozenModel):
    title: str
    sections: dict[str, str] = Field(default_factory=dict[str, str])
    fields: JsonFields = Field(default_factory=JsonFields)


UNSET_VALUES: tuple[JsonValue, ...] = (None, "", [], {})


def is_unset(value: JsonValue) -> bool:
    return any(value == unset and type(value) is type(unset) for unset in UNSET_VALUES)


def set_fields(fields: Mapping[str, JsonValue]) -> JsonFields:
    return {name: value for name, value in fields.items() if not is_unset(value)}


def with_fields_named(content: ItemContent, names: Collection[str]) -> ItemContent:
    owned = {name: value for name, value in content.fields.items() if name in names}
    return content.model_copy(update={"fields": owned})


def _canonical_json(value: JsonValue) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def _is_scalar(value: JsonValue) -> bool:
    return not isinstance(value, (dict, list))


def comparable(value: JsonValue) -> JsonValue:
    if isinstance(value, dict):
        return {key: comparable(value[key]) for key in sorted(value)}
    if not isinstance(value, list):
        return value
    members = [comparable(member) for member in value]
    if not all(_is_scalar(member) for member in members):
        return members
    by_text = {_canonical_json(member): member for member in members}
    return [by_text[text] for text in sorted(by_text)]


def same_fields(published: Mapping[str, JsonValue], current: Mapping[str, JsonValue]) -> bool:
    return comparable(set_fields(published)) == comparable(set_fields(current))


def same_value(published: JsonValue, current: JsonValue) -> bool:
    if is_unset(published) or is_unset(current):
        return is_unset(published) and is_unset(current)
    return comparable(published) == comparable(current)


@dataclass(frozen=True)
class SectionChanges:
    written: tuple[str, ...]
    removed: tuple[str, ...]


def _keys_kept_in_place(old_keys: list[str], new_keys: list[str]) -> set[str]:
    matcher = SequenceMatcher(None, old_keys, new_keys, autojunk=False)
    return {
        key for block in matcher.get_matching_blocks() for key in old_keys[block.a : block.a + block.size]
    }


def section_changes(old: Mapping[str, str], new: Mapping[str, str]) -> SectionChanges:
    kept_in_place = _keys_kept_in_place(list(old), list(new))
    return SectionChanges(
        written=tuple(key for key in new if key not in kept_in_place or old[key] != new[key]),
        removed=tuple(key for key in old if key not in new),
    )


def placed_section(
    sections: Mapping[str, str], key: str, text: str | None, follows: str | None
) -> dict[str, str]:
    others = [(other, other_text) for other, other_text in sections.items() if other != key]
    if text is None:
        return dict(others)
    at = _place_after(follows, [other for other, _ in others])
    return dict([*others[:at], (key, text), *others[at:]])


def _place_after(follows: str | None, keys: list[str]) -> int:
    if follows is None:
        return 0
    if follows in keys:
        return keys.index(follows) + 1
    return len(keys)


def differing_parts(published: ItemContent, current: ItemContent) -> tuple[Part, ...]:
    changes = section_changes(published.sections, current.sections)
    return (
        *((TITLE,) if published.title != current.title else ()),
        *(() if same_fields(published.fields, current.fields) else (FIELDS,)),
        *(section_part(key) for key in (*changes.written, *changes.removed)),
    )


def content_digest(content: ItemContent) -> str:
    canonical = _canonical_json(
        {
            "title": content.title,
            "sections": [[key, text] for key, text in content.sections.items()],
            "fields": comparable(set_fields(content.fields)),
        }
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
