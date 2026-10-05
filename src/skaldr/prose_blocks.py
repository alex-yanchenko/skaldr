from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from markdown_it import MarkdownIt
from markdown_it.token import Token

FEWEST_LIST_ITEMS: Final = 2
PARAGRAPH_OPEN: Final = "paragraph_open"
LIST_CLOSE_OF_OPEN: Final = {
    "bullet_list_open": "bullet_list_close",
    "ordered_list_open": "ordered_list_close",
}
ITEM_CLOSE: Final = "list_item_close"
LIST_READER: Final = MarkdownIt("zero").enable("list")


@dataclass(frozen=True)
class ProseItem:
    text: str
    blocks: "tuple[ProseBlock, ...]" = ()


@dataclass(frozen=True)
class ProseList:
    items: tuple[ProseItem, ...]
    start: int | None = None


ProseBlock = str | ProseList


@dataclass(frozen=True)
class _Placed:
    block: ProseBlock
    first_line: int
    end_line: int


@dataclass(frozen=True)
class _TextSpan:
    first: int
    end: int


def _line_span(token: Token) -> tuple[int, int]:
    if token.map is None:
        return 0, 0
    first, end = token.map
    return first, end


def _read_list(tokens: Sequence[Token], index: int) -> tuple[ProseList, int]:
    opening = tokens[index]
    closing = LIST_CLOSE_OF_OPEN[opening.type]
    start = int(opening.attrs.get("start", 1)) if opening.type == "ordered_list_open" else None
    items: list[ProseItem] = []
    index += 1
    while tokens[index].type != closing:
        placed, index = _read_blocks(tokens, index + 1, ITEM_CLOSE)
        blocks = [entry.block for entry in placed]
        if blocks and isinstance(blocks[0], str):
            items.append(ProseItem(blocks[0], tuple(blocks[1:])))
        else:
            items.append(ProseItem("", tuple(blocks)))
    return ProseList(tuple(items), start), index + 1


def _read_blocks(tokens: Sequence[Token], index: int, closing: str | None) -> tuple[list[_Placed], int]:
    placed: list[_Placed] = []
    while index < len(tokens) and tokens[index].type != closing:
        token = tokens[index]
        first, end = _line_span(token)
        if token.type == PARAGRAPH_OPEN:
            placed.append(_Placed(tokens[index + 1].content, first, end))
            index += 3
        elif token.type in LIST_CLOSE_OF_OPEN:
            block, index = _read_list(tokens, index)
            placed.append(_Placed(block, first, end))
        else:
            index += 1
    return placed, index + 1


def _last_written_line(lines: Sequence[str], first: int, end: int) -> int:
    while end > first and not lines[end - 1].strip():
        end -= 1
    return end


def _segments(placed: Sequence[_Placed], lines: Sequence[str]) -> list[ProseList | _TextSpan]:
    segments: list[ProseList | _TextSpan] = []
    for entry in placed:
        end = _last_written_line(lines, entry.first_line, entry.end_line)
        previous = segments[-1] if segments else None
        if isinstance(entry.block, ProseList) and len(entry.block.items) >= FEWEST_LIST_ITEMS:
            segments.append(entry.block)
        elif isinstance(previous, _TextSpan) and previous.end == entry.first_line:
            segments[-1] = _TextSpan(previous.first, end)
        else:
            segments.append(_TextSpan(entry.first_line, end))
    return segments


def _with_short_lists_as_text(placed: Sequence[_Placed], lines: Sequence[str]) -> list[ProseBlock]:
    return [
        "\n".join(lines[segment.first : segment.end]).strip() if isinstance(segment, _TextSpan) else segment
        for segment in _segments(placed, lines)
    ]


def prose_blocks(text: str) -> list[ProseBlock]:
    source = text.replace("\r\n", "\n").replace("\r", "\n")
    placed, _ = _read_blocks(LIST_READER.parse(source), 0, None)
    return _with_short_lists_as_text(placed, source.split("\n"))


def _block_strings(block: ProseBlock) -> list[str]:
    if isinstance(block, str):
        return [block]
    strings: list[str] = []
    for item in block.items:
        strings.append(item.text)
        for child in item.blocks:
            strings.extend(_block_strings(child))
    return strings


def rendered_strings(text: str) -> list[str]:
    return [string for block in prose_blocks(text) for string in _block_strings(block)]
