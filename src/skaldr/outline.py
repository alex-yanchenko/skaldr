import difflib
import functools
import math
import re
from collections import defaultdict
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from typing_extensions import TypedDict

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
_BLOCK_SCALAR_HEADER = re.compile(r"(?:[&!]\S*[ \t]+)*[|>][1-9+-]*")
_INDENTATION_AND_DASHES = re.compile(r"[ \t]*(?:-[ \t]+)*")
_A_LONE_DASH = re.compile(r"[ \t]*-(?:[ \t]+-)*[ \t]*")
_COMMA_OR_COMMENT = re.compile(r"[ \t]*,?[ \t]*(?:#.*)?")
_INCLUDE_TAG = "!include"
_ALIAS_TAG = "!alias"
_NULL_TAG = "tag:yaml.org,2002:null"
_CHARACTERS_PER_TOKEN = 4
_CLOSEST_ANCHORS = 5
_COLUMNS = ("ANCHOR", "KIND", "LEVEL", "ID", "START", "END", "~TOKENS", "TITLE")


@dataclass(frozen=True)
class OutsideFile:
    reason: str


_NOT_WRITTEN_IN_PLACE = OutsideFile("is not written in place (it comes through a YAML alias or merge key)")
_SHARES_WITH_THE_NEXT_BLOCK = OutsideFile("shares its lines with the next block")
_SHARES_WITH_THE_BLOCK_BEFORE = OutsideFile("shares its lines with the block before it")
_SHARES_WITH_THE_LIST_AROUND = OutsideFile("shares its lines with the list around it")

Origin = yaml.Node | OutsideFile
_Position = tuple[int, int | None]


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


class OutlineRegionJson(TypedDict):
    anchor: str
    kind: Literal["heading", "section"]
    level: int | None
    title: str
    author_set: bool
    start_line: int | None
    end_line: int | None
    tokens: int | None


class OutlineJson(TypedDict):
    file: str
    lines: int
    tokens: int
    regions: list[OutlineRegionJson]


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
    items: tuple[Origin, ...]
    siblings: Sequence[AnyBlock]
    position: int


def approximate_tokens(text: str) -> int:
    return math.ceil(len(text) / _CHARACTERS_PER_TOKEN)


class _AliasNode(yaml.ScalarNode):
    pass


class _AliasKeepingLoader(yaml.SafeLoader):
    def compose_node(self, parent: yaml.Node | None, index: int) -> yaml.Node | None:
        event: object = self.peek_event()  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        if not isinstance(event, yaml.AliasEvent):
            return super().compose_node(parent, index)
        self.get_event()  # pyright: ignore[reportUnknownMemberType]
        return _AliasNode(_ALIAS_TAG, event.anchor, event.start_mark, event.end_mark)


def _unless_included(node: yaml.Node) -> Origin:
    if node.tag != _INCLUDE_TAG:
        return node
    target = str(node.value).strip()
    return OutsideFile(f"comes from `!include {target}` at line {node.start_mark.line + 1}")


def _block_origin(item: Origin) -> Origin:
    if isinstance(item, _AliasNode):
        return _NOT_WRITTEN_IN_PLACE
    return item if isinstance(item, OutsideFile) else _unless_included(item)


def _value_of(mapping: yaml.MappingNode, key: str) -> yaml.Node | None:
    return next((value for name, value in reversed(mapping.value) if name.value == key), None)


def _child(origin: Origin, step: str) -> Origin:
    if isinstance(origin, OutsideFile):
        return origin
    found: yaml.Node | None = None
    if isinstance(origin, yaml.MappingNode):
        found = _value_of(origin, step)
    elif isinstance(origin, yaml.SequenceNode) and step.isdigit() and int(step) < len(origin.value):
        found = origin.value[int(step)]
    return _NOT_WRITTEN_IN_PLACE if found is None else _block_origin(found)


def _item_origins(sequence: Origin, count: int) -> tuple[Origin, ...]:
    if isinstance(sequence, OutsideFile):
        return (sequence,) * count
    if not isinstance(sequence, yaml.SequenceNode) or len(sequence.value) != count:
        return (_NOT_WRITTEN_IN_PLACE,) * count
    return tuple(sequence.value)


def _origin_of(placed: _Placed) -> Origin:
    return _block_origin(placed.items[placed.position])


def _child_lists(block: AnyBlock) -> dict[tuple[str, ...], list[AnyBlock]]:
    lists: defaultdict[tuple[str, ...], list[AnyBlock]] = defaultdict(list)
    for path, inner in located_child_blocks(block):
        lists[tuple(path.split("."))[:-1]].append(inner)
    return lists


def _placements(blocks: Sequence[AnyBlock], sequence: Origin) -> Iterator[tuple[AnyBlock, _Placed]]:
    items = _item_origins(sequence, len(blocks))
    for position, block in enumerate(blocks):
        placed = _Placed(items, blocks, position)
        yield block, placed
        for steps, children in _child_lists(block).items():
            yield from _placements(children, functools.reduce(_child, steps, _origin_of(placed)))


def _is_blank_plain_scalar(node: yaml.Node) -> bool:
    return isinstance(node, yaml.ScalarNode) and node.value == "" and not node.style


def _keeps_trailing_blank_lines(scalar: yaml.ScalarNode, source_lines: Sequence[str]) -> bool:
    mark = scalar.start_mark
    header = _BLOCK_SCALAR_HEADER.match(source_lines[mark.line], mark.column)
    return header is not None and "+" in header.group()


def _end_position(node: yaml.Node) -> _Position:
    end = node.end_mark
    if end.column == 0 and end.line > node.start_mark.line:
        return end.line - 1, None
    return end.line, end.column


def _block_scalar_last_line(scalar: yaml.ScalarNode, source_lines: Sequence[str]) -> int:
    start = scalar.start_mark.line
    last = min(_end_position(scalar)[0], len(source_lines) - 1)
    if not _keeps_trailing_blank_lines(scalar, source_lines):
        while last > start and not source_lines[last].strip():
            last -= 1
    return last


def _whole_line(line: int) -> _Position:
    return line, None


def _last_position(node: yaml.Node, source_lines: Sequence[str]) -> _Position:
    if isinstance(node, yaml.MappingNode) and node.value and not node.flow_style:
        key, value = node.value[-1]
        if _is_blank_plain_scalar(value):
            return _whole_line(_last_line(key, source_lines))
        return _last_position(value, source_lines)
    if isinstance(node, yaml.SequenceNode) and node.value and not node.flow_style:
        return _last_position(node.value[-1], source_lines)
    if isinstance(node, yaml.ScalarNode) and node.style in ("|", ">"):
        return _whole_line(_block_scalar_last_line(node, source_lines))
    return _end_position(node)


def _last_line(node: yaml.Node, source_lines: Sequence[str]) -> int:
    return _last_position(node, source_lines)[0]


def _first_line(item: yaml.Node, source_lines: Sequence[str]) -> int:
    start = item.start_mark
    dash_line = source_lines[start.line - 1].rstrip(_YAML_LINE_BREAKS) if start.line else ""
    starts_its_line = not source_lines[start.line][: start.column].strip()
    return start.line - 1 if starts_its_line and _A_LONE_DASH.fullmatch(dash_line) else start.line


def _shares_a_line_with_the_list_around(
    start: yaml.Mark, end: _Position, source_lines: Sequence[str]
) -> bool:
    before = source_lines[start.line][: start.column]
    end_line, end_column = end
    after = "" if end_column is None else source_lines[end_line][end_column:].rstrip(_YAML_LINE_BREAKS)
    return not (_INDENTATION_AND_DASHES.fullmatch(before) and _COMMA_OR_COMMENT.fullmatch(after))


def _closes_a_heading_of(level: int, block: AnyBlock) -> bool:
    return isinstance(block, Heading) and block.level <= level


def _first_sibling_after_region(block: Heading | Section, placed: _Placed) -> int:
    if isinstance(block, Section):
        return placed.position + 1
    following = range(placed.position + 1, len(placed.siblings))
    return next(
        (index for index in following if _closes_a_heading_of(block.level, placed.siblings[index])),
        len(placed.siblings),
    )


def _region_lines(
    block: Heading | Section, placed: _Placed, source_lines: Sequence[str]
) -> tuple[int, int] | OutsideFile:
    origin = _origin_of(placed)
    if isinstance(origin, OutsideFile):
        return origin
    start = _first_line(origin, source_lines)
    after = _first_sibling_after_region(block, placed)
    covered = [item for item in placed.items[placed.position : after] if isinstance(item, yaml.Node)]
    end_position = _last_position(covered[-1], source_lines)
    end = end_position[0]
    previous = placed.items[placed.position - 1] if placed.position else None
    if isinstance(previous, yaml.Node) and _last_line(previous, source_lines) >= start:
        return _SHARES_WITH_THE_BLOCK_BEFORE
    following = placed.items[after] if after < len(placed.items) else None
    if isinstance(following, yaml.Node) and following.start_mark.line <= end:
        return _SHARES_WITH_THE_NEXT_BLOCK
    if _shares_a_line_with_the_list_around(origin.start_mark, end_position, source_lines):
        return _SHARES_WITH_THE_LIST_AROUND
    return start + 1, end + 1


def _region(block: Heading | Section, anchor: str, placed: _Placed, source_lines: Sequence[str]) -> Region:
    lines = _region_lines(block, placed, source_lines)
    tokens = (
        None
        if isinstance(lines, OutsideFile)
        else approximate_tokens("".join(source_lines[lines[0] - 1 : lines[1]]))
    )
    kind: Literal["heading", "section"] = "heading" if isinstance(block, Heading) else "section"
    level = block.level if isinstance(block, Heading) else None
    title = block.text if isinstance(block, Heading) else block.title
    return Region(
        anchor=anchor,
        kind=kind,
        level=level,
        title=title,
        author_set=block.id is not None,
        lines=lines,
        tokens=tokens,
    )


def _text_with_its_own_line_breaks(path: Path) -> str:
    if not path.exists():
        raise ReportError(f"file not found: {path}")
    try:
        with path.open(encoding="utf-8", newline="") as source:
            return source.read()
    except (OSError, UnicodeDecodeError) as err:
        raise ReportError(f"could not read {path}: {err}") from err


def _composed(path: Path, text: str) -> Origin:
    try:
        root = _AliasKeepingLoader(text).get_single_node()
    except yaml.YAMLError as err:
        raise ReportError(f"invalid YAML in {path}: {err}") from err
    return _NOT_WRITTEN_IN_PLACE if root is None else root


def _is_an_index_document(root: Origin) -> bool:
    index = _value_of(root, "index") if isinstance(root, yaml.MappingNode) else None
    return index is not None and index.tag != _NULL_TAG


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
    widths = [max(map(len, column)) for column in zip(*(row[:-1] for row in rows), strict=True)]
    lines = [
        "  ".join(
            [*(cell.ljust(width) for cell, width in zip(row[:-1], widths, strict=True)), row[-1]]
        ).rstrip()
        for row in rows
    ]
    return "\n".join([*lines, f"{file}: {len(outline.source_lines)} lines, ~{outline.tokens} tokens"])


def outline_json(outline: Outline, file: str) -> OutlineJson:
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
