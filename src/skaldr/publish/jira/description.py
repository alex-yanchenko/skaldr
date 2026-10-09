import hashlib
import json
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from difflib import SequenceMatcher
from typing import Final

from pydantic import BaseModel, ConfigDict, Field, JsonValue, TypeAdapter, ValidationError

from skaldr.errors import ConnectorError
from skaldr.export.adf import compact_adf_length

UNKEYED_SECTION: Final = "(description)"
BLOCK_DIGEST_LENGTH: Final = 16
ANY_NODE: Final = "*"
LEADING_GROUP: Final = -1
SAVED_ATTRS: Final[Mapping[tuple[str, str], tuple[JsonValue, ...] | None]] = {
    (ANY_NODE, "localId"): None,
    ("table", "displayMode"): None,
    ("table", "isNumberColumnEnabled"): (False,),
    ("table", "layout"): ("default", "center"),
    ("tableCell", "colspan"): (1,),
    ("tableCell", "rowspan"): (1,),
    ("tableHeader", "colspan"): (1,),
    ("tableHeader", "rowspan"): (1,),
    ("orderedList", "order"): (1,),
}

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


def section_text(blocks: Sequence[JsonValue]) -> str:
    if not blocks:
        return ""
    return json.dumps(list(blocks), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _not_blocks(text: str) -> ConnectorError:
    return ConnectorError(
        f"a Jira section holds a JSON list of ADF blocks, and this one does not: {text[:40]!r}"
    )


def section_blocks(text: str) -> Blocks:
    if not text.strip():
        return []
    try:
        return _BLOCKS.validate_json(text)
    except ValidationError as exc:
        raise _not_blocks(text) from exc


def as_blocks(blocks: object) -> Blocks:
    return _BLOCKS.validate_python(blocks)


def _canonical(node: JsonValue) -> str:
    return json.dumps(node, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _filled_in_by_jira(node_type: str, name: str, value: JsonValue) -> bool:
    for key in ((ANY_NODE, name), (node_type, name)):
        if key in SAVED_ATTRS:
            defaults = SAVED_ATTRS[key]
            if defaults is None:
                return True
            return any(value == default and type(value) is type(default) for default in defaults)
    return False


def _comparable_attrs(node_type: str, attrs: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
    return {
        name: comparable_node(value)
        for name, value in attrs.items()
        if value is not None and not _filled_in_by_jira(node_type, name, value)
    }


def comparable_node(node: JsonValue) -> JsonValue:
    if isinstance(node, list):
        return [comparable_node(member) for member in node]
    if not isinstance(node, dict):
        return node
    kept: dict[str, JsonValue] = {}
    for name, value in node.items():
        if name == "attrs" and isinstance(value, dict):
            node_type = node.get("type")
            attrs = _comparable_attrs(node_type if isinstance(node_type, str) else "", value)
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
        try:
            decoded, position = _DECODER.raw_decode(joined, position)
            blocks += _BLOCKS.validate_python(decoded)
        except (json.JSONDecodeError, ValidationError) as exc:
            raise _not_blocks(joined[position:]) from exc


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


def _matched_owners(remote: Sequence[str], sections: Sequence[LayoutSection]) -> list[str]:
    keys = [section.key for section in sections for _ in section.blocks]
    expected = [digest for section in sections for digest in section.blocks]
    owners: list[str] = []
    for tag, first, end, remote_first, remote_end in SequenceMatcher(
        None, expected, list(remote), autojunk=False
    ).get_opcodes():
        for position in range(remote_first, remote_end):
            if tag == "insert":
                owners.append(keys[max(first - 1, 0)])
            elif tag != "delete":
                owners.append(keys[min(first + position - remote_first, end - 1)])
    return owners


def _anchors(sections: Sequence[LayoutSection], remote: Sequence[str]) -> dict[int, int]:
    expected = Counter(digest for section in sections for digest in section.blocks)
    found = Counter(remote)
    return {
        index: remote.index(section.blocks[0])
        for index, section in enumerate(sections)
        if expected[section.blocks[0]] == 1 and found[section.blocks[0]] == 1
    }


def _anchored_groups(
    sections: Sequence[LayoutSection], anchors: Mapping[int, int]
) -> dict[int, list[LayoutSection]]:
    groups: dict[int, list[LayoutSection]] = {LEADING_GROUP: []}
    current = LEADING_GROUP
    for index, section in enumerate(sections):
        if index in anchors:
            current = index
            groups[current] = []
        groups[current].append(section)
    return groups


def _owners(blocks: Blocks, layout: Layout) -> list[str]:
    sections = [section for section in layout.sections if section.blocks]
    if not sections:
        return [UNKEYED_SECTION] * len(blocks)
    remote = [block_digest(block) for block in blocks]
    anchors = _anchors(sections, remote)
    groups = _anchored_groups(sections, anchors)
    starts = sorted((position, index) for index, position in anchors.items())
    leading = groups[LEADING_GROUP] or groups[starts[0][1]]
    bounds = [0, *(position for position, _ in starts), len(blocks)]
    chosen = [leading, *(groups[index] for _, index in starts)]
    owners: list[str] = []
    for begin, end, group in zip(bounds[:-1], bounds[1:], chosen, strict=True):
        owners += _matched_owners(remote[begin:end], group)
    return owners


def split_description(blocks: Blocks, layout: Layout | None) -> dict[str, Blocks]:
    sections: dict[str, Blocks] = {}
    for owner, block in zip(_owners(blocks, layout or Layout()), blocks, strict=True):
        sections.setdefault(owner, []).append(block)
    return sections
