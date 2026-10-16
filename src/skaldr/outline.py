import difflib
import functools
import math
import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml

from skaldr.compute import anchor_slugs
from skaldr.errors import IndexDocumentOutlineError, RegionOutsideFileError, ReportError, UnknownAnchorError
from skaldr.models import (
    AnyBlock,
    Heading,
    Section,
    load_report,
    located_child_blocks,
    walk_blocks,
)

_YAML_LINE_BREAKS = "".join(map(chr, (0x0D, 0x0A, 0x85, 0x2028, 0x2029)))
_YAML_LINE = re.compile(f".*?(?:\r\n|[{_YAML_LINE_BREAKS}])|.+\\Z", re.DOTALL)
_INCLUDE_TAG = "!include"
_NULL_TAG = "tag:yaml.org,2002:null"
_CHARACTERS_PER_TOKEN = 4
_CLOSEST_ANCHORS = 5
_COLUMNS = ("ANCHOR", "KIND", "LEVEL", "ID", "START", "END", "~TOKENS", "TITLE")


@dataclass(frozen=True)
class OutsideFile:
    reason: str


_NOT_WRITTEN_IN_PLACE = OutsideFile("is not written in place (it comes through a YAML alias or merge key)")

Origin = yaml.Node | OutsideFile
ItemNodes = tuple[yaml.Node, ...] | OutsideFile


@dataclass(frozen=True)
class Region:
    anchor: str
    kind: Literal["heading", "section"]
    level: int | None
    title: str
    author_set: bool
    lines: tuple[int, int] | OutsideFile
    tokens: int | None

    @property
    def start_line(self) -> int | None:
        return None if isinstance(self.lines, OutsideFile) else self.lines[0]

    @property
    def end_line(self) -> int | None:
        return None if isinstance(self.lines, OutsideFile) else self.lines[1]


@dataclass(frozen=True)
class Outline:
    source_lines: tuple[str, ...]
    regions: tuple[Region, ...]

    @property
    def tokens(self) -> int:
        return approximate_tokens("".join(self.source_lines))

    def text_of(self, lines: tuple[int, int]) -> str:
        start, end = lines
        return "".join(self.source_lines[start - 1 : end])


@dataclass(frozen=True)
class _Placed:
    items: ItemNodes
    siblings: Sequence[AnyBlock]
    position: int


def approximate_tokens(text: str) -> int:
    return math.ceil(len(text) / _CHARACTERS_PER_TOKEN)


def _unless_included(node: yaml.Node) -> Origin:
    if node.tag != _INCLUDE_TAG:
        return node
    target = str(node.value).strip()
    return OutsideFile(f"comes from `!include {target}` at line {node.start_mark.line + 1}")


def _child(origin: Origin, step: str) -> Origin:
    if isinstance(origin, OutsideFile):
        return origin
    found: yaml.Node | None = None
    if isinstance(origin, yaml.MappingNode):
        found = next((value for key, value in origin.value if key.value == step), None)
    elif isinstance(origin, yaml.SequenceNode) and step.isdigit() and int(step) < len(origin.value):
        found = origin.value[int(step)]
    return _NOT_WRITTEN_IN_PLACE if found is None else _unless_included(found)


def _item_nodes(sequence: Origin, count: int) -> ItemNodes:
    if isinstance(sequence, OutsideFile):
        return sequence
    if not isinstance(sequence, yaml.SequenceNode) or len(sequence.value) != count:
        return _NOT_WRITTEN_IN_PLACE
    return tuple(sequence.value)


def _origin_of(placed: _Placed) -> Origin:
    if isinstance(placed.items, OutsideFile):
        return placed.items
    return _unless_included(placed.items[placed.position])


def _child_lists(block: AnyBlock) -> dict[tuple[str, ...], list[AnyBlock]]:
    lists: dict[tuple[str, ...], list[AnyBlock]] = {}
    for path, inner in located_child_blocks(block):
        lists.setdefault(tuple(path.split("."))[:-1], []).append(inner)
    return lists


def _placements(blocks: Sequence[AnyBlock], sequence: Origin) -> Iterator[tuple[AnyBlock, _Placed]]:
    items = _item_nodes(sequence, len(blocks))
    for position, block in enumerate(blocks):
        placed = _Placed(items, blocks, position)
        yield block, placed
        for steps, children in _child_lists(block).items():
            yield from _placements(children, functools.reduce(_child, steps, _origin_of(placed)))


def _is_blank_plain_scalar(node: yaml.Node) -> bool:
    return isinstance(node, yaml.ScalarNode) and node.value == "" and not node.style


def _last_line(node: yaml.Node) -> int:
    if isinstance(node, yaml.MappingNode) and node.value and not node.flow_style:
        key, value = node.value[-1]
        return _last_line(key if _is_blank_plain_scalar(value) else value)
    if isinstance(node, yaml.SequenceNode) and node.value and not node.flow_style:
        return _last_line(node.value[-1])
    end = node.end_mark
    return end.line - 1 if end.column == 0 and end.line > node.start_mark.line else end.line


def _closes_a_heading_of(level: int, block: AnyBlock) -> bool:
    return isinstance(block, Heading) and block.level <= level


def _heading_last_line(heading: Heading, placed: _Placed, items: tuple[yaml.Node, ...]) -> int:
    following = range(placed.position + 1, len(placed.siblings))
    closing = next(
        (index for index in following if _closes_a_heading_of(heading.level, placed.siblings[index])), None
    )
    return _last_line(items[-1]) if closing is None else items[closing].start_mark.line - 1


def _without_trailing_blank_lines(source_lines: Sequence[str], start: int, end: int) -> int:
    end = min(end, len(source_lines) - 1)
    while end > start and not source_lines[end].strip():
        end -= 1
    return end


def _region_lines(
    block: Heading | Section, placed: _Placed, source_lines: Sequence[str]
) -> tuple[int, int] | OutsideFile:
    if isinstance(placed.items, OutsideFile):
        return placed.items
    origin = _origin_of(placed)
    if isinstance(origin, OutsideFile):
        return origin
    start = origin.start_mark.line
    last = (
        _heading_last_line(block, placed, placed.items) if isinstance(block, Heading) else _last_line(origin)
    )
    return start + 1, _without_trailing_blank_lines(source_lines, start, last) + 1


def _region(block: Heading | Section, anchor: str, placed: _Placed, source_lines: Sequence[str]) -> Region:
    lines = _region_lines(block, placed, source_lines)
    tokens = (
        None
        if isinstance(lines, OutsideFile)
        else approximate_tokens("".join(source_lines[lines[0] - 1 : lines[1]]))
    )
    if isinstance(block, Heading):
        return Region(anchor, "heading", block.level, block.text, block.id is not None, lines, tokens)
    return Region(anchor, "section", None, block.title, block.id is not None, lines, tokens)


def _composed(path: Path, text: str) -> Origin:
    try:
        root = yaml.SafeLoader(text).get_single_node()
    except yaml.YAMLError as err:
        raise ReportError(f"invalid YAML in {path}: {err}") from err
    return _NOT_WRITTEN_IN_PLACE if root is None else root


def _is_an_index_document(root: Origin) -> bool:
    index = _child(root, "index") if isinstance(root, yaml.MappingNode) else None
    return isinstance(index, yaml.Node) and index.tag != _NULL_TAG


def _text_with_its_own_line_breaks(path: Path) -> str:
    try:
        with path.open(encoding="utf-8", newline="") as source:
            return source.read()
    except (OSError, UnicodeDecodeError) as err:
        raise ReportError(f"could not read {path}: {err}") from err


def outline_file(path: Path) -> Outline:
    text = _text_with_its_own_line_breaks(path)
    root = _composed(path, text)
    if _is_an_index_document(root):
        raise IndexDocumentOutlineError(
            f"{path} is an index document; outline each file it lists under `index.parts` on its own"
        )
    report = load_report(path)
    slugs = anchor_slugs(report)
    placements = {id(block): placed for block, placed in _placements(report.blocks, _child(root, "blocks"))}
    source_lines = tuple(_YAML_LINE.findall(text))
    regions = tuple(
        _region(block, slugs[id(block)], placements[id(block)], source_lines)
        for block in walk_blocks(report.blocks)
        if isinstance(block, Heading | Section)
    )
    return Outline(source_lines, regions)


def _cell(value: int | None) -> str:
    return "-" if value is None else str(value)


def _table_row(region: Region) -> tuple[str, ...]:
    return (
        region.anchor,
        region.kind,
        "" if region.level is None else str(region.level),
        "set" if region.author_set else "derived",
        _cell(region.start_line),
        _cell(region.end_line),
        _cell(region.tokens),
        region.title,
    )


def outline_table(outline: Outline, file: str) -> str:
    rows = [_COLUMNS, *map(_table_row, outline.regions)]
    widths = [max(len(row[column]) for row in rows) for column in range(len(_COLUMNS) - 1)]
    lines = [
        "  ".join(
            [*(cell.ljust(width) for cell, width in zip(row[:-1], widths, strict=True)), row[-1]]
        ).rstrip()
        for row in rows
    ]
    return "\n".join([*lines, f"{file}: {len(outline.source_lines)} lines, ~{outline.tokens} tokens"])


def outline_json(outline: Outline, file: str) -> dict[str, object]:
    return {
        "file": file,
        "lines": len(outline.source_lines),
        "tokens": outline.tokens,
        "regions": [
            {
                "anchor": region.anchor,
                "kind": region.kind,
                "level": region.level,
                "title": region.title,
                "author_set": region.author_set,
                "start_line": region.start_line,
                "end_line": region.end_line,
                "tokens": region.tokens,
            }
            for region in outline.regions
        ],
    }


def _unknown_anchor_message(outline: Outline, file: str, anchor: str) -> str:
    anchors = [region.anchor for region in outline.regions]
    closest = difflib.get_close_matches(anchor, anchors, n=_CLOSEST_ANCHORS)
    if closest:
        return f"no anchor '{anchor}' in {file}; did you mean: {', '.join(closest)}"
    return f"no anchor '{anchor}' in {file}; `skaldr outline {file}` lists them"


def region_source(outline: Outline, file: str, anchor: str) -> str:
    region = next((region for region in outline.regions if region.anchor == anchor), None)
    if region is None:
        raise UnknownAnchorError(_unknown_anchor_message(outline, file, anchor))
    if isinstance(region.lines, OutsideFile):
        raise RegionOutsideFileError(
            f"{file}#{anchor} {region.lines.reason}, so {file} holds none of its lines"
        )
    return outline.text_of(region.lines)
