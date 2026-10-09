import hashlib
import json
from collections.abc import Mapping
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


def _canonical_json(value: JsonValue) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def comparable(value: JsonValue) -> JsonValue:
    if isinstance(value, dict):
        return {key: comparable(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        members = {_canonical_json(member): member for member in map(comparable, value)}
        return [members[key] for key in sorted(members)]
    return value


def same_fields(published: Mapping[str, JsonValue], current: Mapping[str, JsonValue]) -> bool:
    return comparable(dict(published)) == comparable(dict(current))


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
    keys = [other for other, _ in others]
    at = keys.index(follows) + 1 if follows in keys else 0 if follows is None else len(others)
    return dict([*others[:at], (key, text), *others[at:]])


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
            "fields": comparable(dict(content.fields)),
        }
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
