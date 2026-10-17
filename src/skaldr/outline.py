import difflib
import functools
import math
import re
from collections import defaultdict
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypeAlias

import yaml
from typing_extensions import TypedDict
from yaml.composer import Composer
from yaml.resolver import Resolver

from skaldr.compute import anchor_slugs
from skaldr.errors import IndexDocumentOutlineError, RegionOutsideFileError, ReportError, UnknownAnchorError
from skaldr.models import (
    AnyBlock,
    Heading,
    Section,
    document_data,
    located_child_blocks,
    names_an_index,
    parse_report,
    walk_blocks,
)

_YAML_LINE_BREAKS = "".join(map(chr, (0x0D, 0x0A, 0x85, 0x2028, 0x2029)))
_YAML_LINE = re.compile(f".*?(?:\r\n|[{_YAML_LINE_BREAKS}])|.+\\Z", re.DOTALL)
_BLOCK_SCALAR_HEADER = re.compile(f"(?:[&!]\\S*|#[^{_YAML_LINE_BREAKS}]*|\\s)*([|>][1-9+-]*)")
_INDENTATION_AND_A_DASH = re.compile(r"[ \t]*(?:-[ \t]+)?")
_A_LONE_DASH = re.compile(r"[ \t]*-(?:[ \t]+#.*|[ \t]*)")
_BLANK_OR_A_COMMENT = re.compile(r"[ \t]*(?:#.*)?")
_COMMA_OR_COMMENT = re.compile(r"[ \t]*,?[ \t]*(?:#.*)?")
_INCLUDE_TAG = "!include"
_ALIAS_TAG = "!alias"
_MERGE_TAG = "tag:yaml.org,2002:merge"
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
_COULD_NOT_BE_CHECKED = OutsideFile("could not be checked against the file")

Origin: TypeAlias = yaml.Node | OutsideFile
_Position: TypeAlias = tuple[int, int | None]
_Span: TypeAlias = tuple[int, int]


@dataclass(frozen=True)
class Region:
    anchor: str
    kind: Literal["heading", "section"]
    level: int | None
    title: str
    author_set: bool
    lines: _Span | OutsideFile
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


def _text_between(source_lines: Sequence[str], span: _Span) -> str:
    start, end = span
    return "".join(source_lines[start - 1 : end])


@dataclass(frozen=True)
class Outline:
    source_lines: tuple[str, ...]
    regions: tuple[Region, ...]

    @property
    def tokens(self) -> int:
        return approximate_tokens("".join(self.source_lines))

    def text_of(self, span: _Span) -> str:
        return _text_between(self.source_lines, span)


@dataclass(frozen=True)
class _Placed:
    items: tuple[yaml.Node, ...]
    origins: tuple[Origin, ...]
    siblings: Sequence[AnyBlock]
    position: int
    in_flow: bool

    @property
    def origin(self) -> Origin:
        return self.origins[self.position]


def approximate_tokens(text: str) -> int:
    return math.ceil(len(text) / _CHARACTERS_PER_TOKEN)


class _AliasNode(yaml.ScalarNode):
    pass


class _AliasKeepingComposer(Composer):
    def compose_node(self, parent: yaml.Node | None, index: int) -> yaml.Node | None:
        event = self.peek_event()  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType, reportUnknownVariableType]
        if not isinstance(event, yaml.AliasEvent):
            return super().compose_node(parent, index)
        self.get_event()  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]
        return _AliasNode(_ALIAS_TAG, event.anchor, event.start_mark, event.end_mark)


class _AliasKeepingLoader(_AliasKeepingComposer, yaml.SafeLoader):
    pass


@functools.cache
def _read_back_loader() -> Callable[[str], _AliasKeepingComposer]:
    if not yaml.__with_libyaml__:
        return _AliasKeepingLoader
    from yaml._yaml import CParser

    class _LibyamlAliasKeepingLoader(_AliasKeepingComposer, CParser, Resolver):
        def __init__(self, stream: str) -> None:
            CParser.__init__(self, stream)
            Composer.__init__(self)
            Resolver.__init__(self)

    return _LibyamlAliasKeepingLoader


def _classified(node: yaml.Node) -> Origin:
    if isinstance(node, _AliasNode):
        return _NOT_WRITTEN_IN_PLACE
    if node.tag == _INCLUDE_TAG:
        return OutsideFile(
            f"comes from `!include {str(node.value).strip()}` at line {node.start_mark.line + 1}"
        )
    return node


def _value_of(mapping: yaml.MappingNode, key: str) -> yaml.Node | None:
    return next(
        (
            value
            for name, value in reversed(mapping.value)
            if not isinstance(name, _AliasNode) and name.value == key
        ),
        None,
    )


def _has_a_merge_key(mapping: yaml.MappingNode) -> bool:
    return any(name.tag == _MERGE_TAG for name, _ in mapping.value)


def _pairs_with(item: yaml.Node, block: AnyBlock) -> bool:
    if not isinstance(item, yaml.MappingNode) or _has_a_merge_key(item):
        return False
    written_type = _value_of(item, "type")
    return (
        isinstance(written_type, yaml.ScalarNode)
        and not isinstance(written_type, _AliasNode)
        and written_type.value == block.type
    )


def _item_origin(item: yaml.Node, block: AnyBlock) -> Origin:
    classified = _classified(item)
    if isinstance(classified, OutsideFile) or _pairs_with(item, block):
        return classified
    return _NOT_WRITTEN_IN_PLACE


def _child(origin: Origin, step: str) -> Origin:
    if isinstance(origin, yaml.MappingNode):
        found = _value_of(origin, step)
        return _NOT_WRITTEN_IN_PLACE if found is None else _classified(found)
    if isinstance(origin, yaml.SequenceNode):
        return _classified(origin.value[int(step)])
    return origin


def _child_lists(block: AnyBlock) -> dict[tuple[str, ...], list[AnyBlock]]:
    lists: defaultdict[tuple[str, ...], list[AnyBlock]] = defaultdict(list)
    for path, inner in located_child_blocks(block):
        lists[tuple(path.split("."))[:-1]].append(inner)
    return lists


def _placed_list(
    blocks: Sequence[AnyBlock], sequence: Origin
) -> tuple[tuple[yaml.Node, ...], tuple[Origin, ...]]:
    if not isinstance(sequence, yaml.SequenceNode):
        unplaced = sequence if isinstance(sequence, OutsideFile) else _NOT_WRITTEN_IN_PLACE
        return (), (unplaced,) * len(blocks)
    items = tuple(sequence.value)
    return items, tuple(_item_origin(item, block) for item, block in zip(items, blocks, strict=True))


def _placements(blocks: Sequence[AnyBlock], sequence: Origin) -> Iterator[tuple[AnyBlock, _Placed]]:
    items, origins = _placed_list(blocks, sequence)
    in_flow = isinstance(sequence, yaml.SequenceNode) and bool(sequence.flow_style)
    for position, block in enumerate(blocks):
        placed = _Placed(items, origins, blocks, position, in_flow)
        yield block, placed
        for steps, children in _child_lists(block).items():
            yield from _placements(children, functools.reduce(_child, steps, placed.origin))


def _without_line_break(line: str) -> str:
    return line.rstrip(_YAML_LINE_BREAKS)


def _keeps_trailing_blank_lines(scalar: yaml.ScalarNode, source_lines: Sequence[str]) -> bool:
    start, end = scalar.start_mark, scalar.end_mark
    written = "".join(source_lines[start.line : end.line + 1])
    header = _BLOCK_SCALAR_HEADER.match(written, start.column)
    return header is not None and "+" in header.group(1)


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


def _last_position(node: yaml.Node, source_lines: Sequence[str]) -> _Position:
    if isinstance(node, yaml.MappingNode) and node.value and not node.flow_style:
        return _last_position(node.value[-1][1], source_lines)
    if isinstance(node, yaml.SequenceNode) and node.value and not node.flow_style:
        return _last_position(node.value[-1], source_lines)
    if isinstance(node, yaml.ScalarNode) and node.style in ("|", ">"):
        return _block_scalar_last_line(node, source_lines), None
    return _end_position(node)


def _first_line(item: yaml.Node, source_lines: Sequence[str]) -> int:
    start = item.start_mark
    if source_lines[start.line][: start.column].strip():
        return start.line
    line = start.line - 1
    while line >= 0 and _BLANK_OR_A_COMMENT.fullmatch(_without_line_break(source_lines[line])):
        line -= 1
    if line >= 0 and _A_LONE_DASH.fullmatch(_without_line_break(source_lines[line])):
        return line
    return start.line


def _shares_a_line_with_the_list_around(
    start: yaml.Mark, end: _Position, source_lines: Sequence[str]
) -> bool:
    before = source_lines[start.line][: start.column]
    end_line, end_column = end
    after = "" if end_column is None else _without_line_break(source_lines[end_line][end_column:])
    return not (_INDENTATION_AND_A_DASH.fullmatch(before) and _COMMA_OR_COMMENT.fullmatch(after))


def _value_tree(node: yaml.Node) -> object:
    if isinstance(node, yaml.MappingNode):
        return node.tag, [(_value_tree(key), _value_tree(value)) for key, value in node.value]
    if isinstance(node, yaml.SequenceNode):
        return node.tag, [_value_tree(item) for item in node.value]
    return node.tag, node.value


def _reads_back_as(text: str, items: Sequence[yaml.Node], *, in_flow: bool) -> bool:
    try:
        read_back = _read_back_loader()(f"[\n{text}\n]" if in_flow else text).get_single_node()
    except yaml.YAMLError:
        return False
    return isinstance(read_back, yaml.SequenceNode) and list(map(_value_tree, read_back.value)) == list(
        map(_value_tree, items)
    )


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
) -> _Span | OutsideFile:
    origin = placed.origin
    if isinstance(origin, OutsideFile):
        return origin
    start = _first_line(origin, source_lines)
    after = _first_sibling_after_region(block, placed)
    covered = placed.items[placed.position : after]
    end_position = _last_position(covered[-1], source_lines)
    end = end_position[0]
    if placed.position and _last_position(placed.items[placed.position - 1], source_lines)[0] >= start:
        return _SHARES_WITH_THE_BLOCK_BEFORE
    if after < len(placed.items) and placed.items[after].start_mark.line <= end:
        return _SHARES_WITH_THE_NEXT_BLOCK
    if _shares_a_line_with_the_list_around(origin.start_mark, end_position, source_lines):
        return _SHARES_WITH_THE_LIST_AROUND
    span = (start + 1, end + 1)
    if not _reads_back_as(_text_between(source_lines, span), covered, in_flow=placed.in_flow):
        return _COULD_NOT_BE_CHECKED
    return span


def _region(block: Heading | Section, anchor: str, placed: _Placed, source_lines: Sequence[str]) -> Region:
    lines = _region_lines(block, placed, source_lines)
    tokens = (
        None if isinstance(lines, OutsideFile) else approximate_tokens(_text_between(source_lines, lines))
    )
    kind: Literal["heading", "section"] = "heading" if isinstance(block, Heading) else "section"
    return Region(
        anchor=anchor,
        kind=kind,
        level=block.level if isinstance(block, Heading) else None,
        title=block.text if isinstance(block, Heading) else block.title,
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


@dataclass(frozen=True)
class _Anchored:
    block: Heading | Section
    anchor: str
    placed: _Placed


@dataclass(frozen=True)
class _ReadDocument:
    source_lines: tuple[str, ...]
    anchored: tuple[_Anchored, ...]


def _read_document(path: Path) -> _ReadDocument:
    text = _text_with_its_own_line_breaks(path)
    root = _composed(path, text)
    data = document_data(path, text)
    if names_an_index(data):
        raise IndexDocumentOutlineError(
            f"{path} is an index document; outline each file it lists under `index.parts` on its own"
        )
    report = parse_report(data)
    slugs = anchor_slugs(report)
    placements = {id(block): placed for block, placed in _placements(report.blocks, _child(root, "blocks"))}
    anchored = tuple(
        _Anchored(block, slugs[id(block)], placements[id(block)])
        for block in walk_blocks(report.blocks)
        if isinstance(block, Heading | Section)
    )
    return _ReadDocument(tuple(_YAML_LINE.findall(text)), anchored)


def outline_file(path: Path) -> Outline:
    document = _read_document(path)
    regions = tuple(
        _region(anchored.block, anchored.anchor, anchored.placed, document.source_lines)
        for anchored in document.anchored
    )
    return Outline(document.source_lines, regions)


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


def _unknown_anchor_message(anchors: Sequence[str], file: str, anchor: str) -> str:
    closest = difflib.get_close_matches(anchor, anchors, n=_CLOSEST_ANCHORS)
    if closest:
        return f"no anchor '{anchor}' in {file}; did you mean: {', '.join(closest)}"
    return f"no anchor '{anchor}' in {file}; `skaldr outline {file}` lists them"


def region_source(path: Path, file: str, anchor: str) -> str:
    document = _read_document(path)
    found = next((anchored for anchored in document.anchored if anchored.anchor == anchor), None)
    if found is None:
        anchors = [anchored.anchor for anchored in document.anchored]
        raise UnknownAnchorError(_unknown_anchor_message(anchors, file, anchor))
    lines = _region_lines(found.block, found.placed, document.source_lines)
    if isinstance(lines, OutsideFile):
        raise RegionOutsideFileError(f"{file}#{anchor} {lines.reason}, so {file} holds none of its lines")
    return _text_between(document.source_lines, lines)
