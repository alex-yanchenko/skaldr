import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from difflib import SequenceMatcher
from typing import Final

from pydantic import BaseModel, ConfigDict, Field, JsonValue, TypeAdapter, ValidationError

from skaldr.errors import ConnectorError
from skaldr.export.adf import compact_adf_length

UNKEYED_SECTION: Final = "description"
IGNORED_ATTRS: Final = frozenset({"localId"})
BLOCK_DIGEST_LENGTH: Final = 16

Blocks = list[JsonValue]
_BLOCKS: Final = TypeAdapter(Blocks)
_DECODER: Final = json.JSONDecoder()


class LayoutSection(BaseModel):
    model_config = ConfigDict(frozen=True)

    key: str
    blocks: list[str] = Field(default_factory=list[str])


class Layout(BaseModel):
    model_config = ConfigDict(frozen=True)

    sections: list[LayoutSection] = Field(default_factory=list[LayoutSection])


def section_text(blocks: Sequence[object]) -> str:
    if not blocks:
        return ""
    return json.dumps(list(blocks), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def section_blocks(text: str) -> Blocks:
    if not text.strip():
        return []
    try:
        return _BLOCKS.validate_json(text)
    except ValidationError as exc:
        raise ConnectorError(
            f"a Jira section holds a JSON list of ADF blocks, and this one does not: {text[:40]!r}"
        ) from exc


def _canonical(node: JsonValue) -> str:
    return json.dumps(node, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _comparable_attrs(attrs: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
    return {
        name: comparable_node(value)
        for name, value in attrs.items()
        if name not in IGNORED_ATTRS and value is not None
    }


def comparable_node(node: JsonValue) -> JsonValue:
    if isinstance(node, list):
        return [comparable_node(member) for member in node]
    if not isinstance(node, dict):
        return node
    kept: dict[str, JsonValue] = {}
    for name, value in node.items():
        if name == "attrs" and isinstance(value, dict):
            attrs = _comparable_attrs(value)
            if attrs:
                kept[name] = attrs
        elif name == "marks" and isinstance(value, list):
            marks = sorted((comparable_node(mark) for mark in value), key=_canonical)
            if marks:
                kept[name] = marks
        elif name != "content" or value != []:
            kept[name] = comparable_node(value)
    return kept


def comparable_section(text: str) -> str:
    return section_text([comparable_node(block) for block in section_blocks(text)])


def block_digest(block: JsonValue) -> str:
    digest = hashlib.sha256(_canonical(comparable_node(block)).encode("utf-8")).hexdigest()
    return digest[:BLOCK_DIGEST_LENGTH]


def description_doc(blocks: Blocks) -> JsonValue:
    if not blocks:
        return None
    return {"version": 1, "type": "doc", "content": list(blocks)}


def blocks_of(description: JsonValue) -> Blocks:
    if description is None:
        return []
    if not isinstance(description, dict):
        raise ConnectorError("the description Jira returned is not an ADF document")
    content = description.get("content")
    if content is None:
        return []
    if not isinstance(content, list):
        raise ConnectorError("the description Jira returned is not an ADF document")
    return list(content)


def _joined_blocks(joined: str) -> Blocks:
    blocks: Blocks = []
    position = 0
    while True:
        rest = joined[position:]
        position += len(rest) - len(rest.lstrip())
        if position >= len(joined):
            return blocks
        decoded, position = _DECODER.raw_decode(joined, position)
        blocks += _BLOCKS.validate_python(decoded)


def description_length(joined: str) -> int:
    document = description_doc(_joined_blocks(joined))
    return compact_adf_length(document) if isinstance(document, dict) else 0


def layout_of(sections: Mapping[str, Iterable[JsonValue]]) -> Layout:
    return Layout(
        sections=[
            LayoutSection(key=key, blocks=[block_digest(block) for block in blocks])
            for key, blocks in sections.items()
            if blocks
        ]
    )


def _owners(blocks: Blocks, layout: Layout) -> list[str]:
    keys = [section.key for section in layout.sections for _ in section.blocks]
    if not keys:
        return [UNKEYED_SECTION] * len(blocks)
    expected = [digest for section in layout.sections for digest in section.blocks]
    remote = [block_digest(block) for block in blocks]
    owners: list[str] = []
    for tag, first, end, remote_first, remote_end in SequenceMatcher(
        None, expected, remote, autojunk=False
    ).get_opcodes():
        for position in range(remote_first, remote_end):
            if tag == "insert":
                owners.append(keys[max(first - 1, 0)])
            elif tag != "delete":
                owners.append(keys[min(first + position - remote_first, end - 1)])
    return owners


def split_description(blocks: Blocks, layout: Layout | None) -> dict[str, Blocks]:
    sections: dict[str, Blocks] = {}
    for owner, block in zip(_owners(blocks, layout or Layout()), blocks, strict=True):
        sections.setdefault(owner, []).append(block)
    return sections
