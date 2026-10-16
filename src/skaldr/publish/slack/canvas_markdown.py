import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final, Literal

from skaldr.export.slack import CANVAS_ESCAPES, CANVAS_FENCE, LIST_SEPARATOR
from skaldr.publish.keyed import UNKEYED_SECTION, SectionLayout
from skaldr.publish.stamp_text import parsed_stamp, parsed_stamp_links, stamp_pattern, stamp_text
from skaldr.publish.transport import ShownLink, Stamp

TITLE_HEADING: Final = "# "
STAMP_PATTERN: Final = stamp_pattern("")
ARCHIVED_TITLE_MARKER: Final = " (archived by skaldr)"
ARCHIVED_WORDS: Final = "skaldr archived this canvas:"
ARCHIVED_PATTERN: Final = re.compile(
    rf"{re.escape(ARCHIVED_WORDS)} the document (?:\S+ )?no longer publishes here\."
)
FENCE_OPENING: Final = re.compile(r"(`{3,}|~{3,})")
CONTAINER_OPENING: Final = re.compile(rf"{CANVAS_FENCE}\s*\{{")
BULLET: Final = re.compile(r"^(\s*)[-+] ")
LIST_ITEM: Final = re.compile(r"\s*(?:[-+*]|\d+[.)]) ")
ITEM_LINE: Final = re.compile(r"(\s*(?:[-+*]|\d+[.)]) (?:\[[ xX]\] )?)(.*)", re.DOTALL)
NUMBER_MARKER_TEXT: Final = re.compile(r"(\d+)([.)] )")
BULLET_MARKER_TEXT: Final = re.compile(r"[-+*] ")
ESCAPED_NUMBER_MARKER_TEXT: Final = re.compile(r"(\d+)\\([.)] )")
ESCAPED_BULLET_MARKER_TEXT: Final = re.compile(r"\\([-+*] )")
COMPARABLE_INDENT: Final = "  "
HARD_BREAK: Final = re.compile(r"(?<!\\)\\$")
MENTION: Final = re.compile(r"!\[\]\(([@#][A-Z0-9]+)\)")
UNESCAPED_PIPE: Final = re.compile(r"(?<!\\)\|")
TABLE_SEPARATOR_CELL: Final = re.compile(r":?-{3,}:?")
SEPARATOR_TEXTS: Final = frozenset({"", LIST_SEPARATOR})
TABLE_EDGE: Final = "|"
TABLE_SEPARATOR: Final = "---"

BlockRole = Literal["title", "published", "added", "blank", "stamp", "below"]


def is_a_list(block: str) -> bool:
    return LIST_ITEM.match(block) is not None


def archived_line(doc_id: str | None) -> str:
    document = "the document" if doc_id is None else f"the document {doc_id}"
    return f"{ARCHIVED_WORDS} {document} no longer publishes here."


def canvas_stamp_line(stamp: Stamp, links: Sequence[ShownLink] = ()) -> str:
    return stamp_text(stamp, links, CANVAS_ESCAPES)


@dataclass
class _Fences:
    closer: str | None = None
    depth: int = 0

    def read(self, line: str) -> bool:
        stripped = line.strip()
        if self.closer is not None:
            if stripped.startswith(self.closer) and not stripped.strip(self.closer[0]):
                self.closer = None
            return True
        opening = FENCE_OPENING.match(stripped)
        if opening is not None:
            self.closer = opening.group(1)
            return True
        if CONTAINER_OPENING.match(stripped):
            self.depth += 1
        elif stripped == CANVAS_FENCE and self.depth:
            self.depth -= 1
        return False

    @property
    def at_the_top(self) -> bool:
        return self.closer is None and self.depth == 0


def canvas_blocks(markdown: str) -> list[str]:
    blocks: list[str] = []
    current: list[str] = []
    fences = _Fences()
    for line in markdown.split("\n"):
        if fences.at_the_top and line == "":
            if current:
                blocks.append("\n".join(current))
            current = []
            continue
        fences.read(line)
        current.append(line)
    if current:
        blocks.append("\n".join(current))
    return blocks


def _table_row(line: str) -> str:
    cells = [cell.strip() for cell in UNESCAPED_PIPE.split(line.strip())[1:-1]]
    if cells and all(TABLE_SEPARATOR_CELL.fullmatch(cell) for cell in cells):
        cells = [TABLE_SEPARATOR] * len(cells)
    return f"{TABLE_EDGE}{TABLE_EDGE.join(cells)}{TABLE_EDGE}"


def _comparable_line(line: str) -> str:
    stripped = HARD_BREAK.sub("", line.rstrip()).rstrip()
    if stripped.lstrip().startswith(TABLE_EDGE) and stripped.endswith(TABLE_EDGE):
        return _table_row(stripped)
    return MENTION.sub(r"<\1>", BULLET.sub(r"\1* ", stripped))


def _item_text_with_its_marker_unescaped(text: str) -> str:
    if ESCAPED_NUMBER_MARKER_TEXT.match(text):
        return ESCAPED_NUMBER_MARKER_TEXT.sub(r"\1\2", text, count=1)
    if ESCAPED_BULLET_MARKER_TEXT.match(text):
        return text.removeprefix("\\")
    return text


def _holds_a_fence(block: str) -> bool:
    return any(FENCE_OPENING.match(line.strip()) for line in block.split("\n"))


def _comparable_list(block: str) -> str:
    indents: list[int] = []
    lines: list[str] = []
    for line in block.split("\n"):
        comparable = _comparable_line(line)
        if not comparable.strip():
            continue
        item = ITEM_LINE.fullmatch(comparable)
        if item is None:
            lines.append(COMPARABLE_INDENT * len(indents) + comparable.strip())
            continue
        indent = len(comparable) - len(comparable.lstrip())
        while indents and indents[-1] >= indent:
            indents.pop()
        marker, text = item.group(1).strip(), _item_text_with_its_marker_unescaped(item.group(2))
        lines.append(f"{COMPARABLE_INDENT * len(indents)}{marker} {text}")
        indents.append(indent)
    return "\n".join(lines)


def comparable_block(block: str) -> str:
    if block.strip() in SEPARATOR_TEXTS:
        return ""
    if is_a_list(block) and not _holds_a_fence(block):
        return _comparable_list(block)
    fences = _Fences()
    lines: list[str] = []
    for line in block.split("\n"):
        in_code = fences.closer is not None
        opens_or_closes_code = fences.read(line)
        inside_the_code = in_code and fences.closer is not None
        if in_code or opens_or_closes_code:
            lines.append(line if inside_the_code else line.rstrip())
            continue
        comparable = _comparable_line(line)
        if comparable.strip():
            lines.append(comparable)
    return "\n".join(lines)


def _blocks_text(blocks: Sequence[str]) -> str:
    return "\n".join(f"{block}\n" for block in blocks)


def _comparable_blocks(text: str) -> list[str]:
    return [comparable for block in canvas_blocks(text) if (comparable := comparable_block(block))]


def comparable_text(text: str) -> str:
    return _blocks_text(_comparable_blocks(text))


def canvas_markdown_of(texts: Sequence[str]) -> str:
    return _blocks_text([text.strip("\n") for text in texts if text.strip("\n")])


@dataclass(frozen=True)
class CanvasBlock:
    raw: str
    key: str | None
    role: BlockRole


@dataclass(frozen=True)
class KeyedCanvas:
    title: str
    blocks: tuple[CanvasBlock, ...]
    stamp: Stamp | None
    links: tuple[ShownLink, ...]
    content_start: int
    stamp_at: int | None

    @property
    def content_end(self) -> int:
        return len(self.blocks) if self.stamp_at is None else self.stamp_at

    @property
    def content(self) -> tuple[CanvasBlock, ...]:
        return self.blocks[self.content_start : self.content_end]

    @property
    def body(self) -> list[str]:
        return [block.raw for block in self.blocks[self.content_start :]]

    @property
    def below_the_stamp(self) -> list[str]:
        return [] if self.stamp_at is None else [block.raw for block in self.blocks[self.stamp_at + 1 :]]

    @property
    def raw_sections(self) -> dict[str, str]:
        grouped: defaultdict[str, list[str]] = defaultdict(list[str])
        for block in self.content:
            grouped[block.key or UNKEYED_SECTION].append(block.raw)
        return {key: _blocks_text(raws) for key, raws in grouped.items()}

    @property
    def sections(self) -> dict[str, str]:
        texts = {key: comparable_text(text) for key, text in self.raw_sections.items()}
        return {key: text for key, text in texts.items() if text}

    @property
    def opens_with_the_archived_line(self) -> bool:
        return bool(self.content) and ARCHIVED_PATTERN.fullmatch(self.content[0].raw.strip()) is not None

    @property
    def archived(self) -> bool:
        return self.title.endswith(ARCHIVED_TITLE_MARKER)

    def positions_of(self, key: str) -> list[int]:
        return [
            index for index in range(self.content_start, self.content_end) if self.blocks[index].key == key
        ]

    def position_after(self, keys: Sequence[str]) -> int:
        for key in reversed(keys):
            held = self.positions_of(key)
            if held:
                return held[-1] + 1
        return self.content_start


def _is_title(raw: str) -> bool:
    return raw.startswith(TITLE_HEADING) and "\n" not in raw


def _last_stamp_at(raws: Sequence[str], start: int) -> int | None:
    return next(
        (
            index
            for index in reversed(range(start, len(raws)))
            if "\n" not in raws[index] and parsed_stamp(raws[index], STAMP_PATTERN) is not None
        ),
        None,
    )


@dataclass
class _Keying:
    layout: SectionLayout
    blocks: list[CanvasBlock] = field(default_factory=list[CanvasBlock])

    def content(self, raws: Sequence[str]) -> None:
        comparables = [comparable_block(raw) for raw in raws]
        aligned = [index for index, comparable in enumerate(comparables) if comparable]
        found: dict[int, tuple[str, BlockRole]] = dict(
            zip(aligned, self.layout.placed([comparables[index] for index in aligned]), strict=True)
        )
        current = found[aligned[0]][0] if aligned else self.layout.fallback
        for index, raw in enumerate(raws):
            key, role = found.get(index, (current, "blank"))
            current = key
            self.blocks.append(CanvasBlock(raw, key, role))


def keyed_canvas(markdown: str, layout: Mapping[str, str]) -> KeyedCanvas:
    raws = canvas_blocks(markdown)
    titled = bool(raws) and _is_title(raws[0])
    start = 1 if titled else 0
    stamp_at = _last_stamp_at(raws, start)
    end = len(raws) if stamp_at is None else stamp_at
    keying = _Keying(SectionLayout.of(layout, _comparable_blocks))
    if titled:
        keying.blocks.append(CanvasBlock(raws[0], None, "title"))
    keying.content(raws[start:end])
    if stamp_at is not None:
        keying.blocks.append(CanvasBlock(raws[stamp_at], None, "stamp"))
        keying.blocks += [CanvasBlock(raw, None, "below") for raw in raws[stamp_at + 1 :]]
    stamp_line = None if stamp_at is None else raws[stamp_at]
    return KeyedCanvas(
        title=raws[0].removeprefix(TITLE_HEADING).strip() if titled else "",
        blocks=tuple(keying.blocks),
        stamp=None if stamp_line is None else parsed_stamp(stamp_line, STAMP_PATTERN),
        links=() if stamp_line is None else parsed_stamp_links(stamp_line, STAMP_PATTERN),
        content_start=start,
        stamp_at=stamp_at,
    )


def _blank_as_a_list_separator(raw: str) -> str:
    return LIST_SEPARATOR if comparable_block(raw) == "" else raw


def _item_text_that_cannot_start_a_list(text: str) -> str:
    if NUMBER_MARKER_TEXT.match(text):
        return NUMBER_MARKER_TEXT.sub(r"\1\\\2", text, count=1)
    if BULLET_MARKER_TEXT.match(text):
        return "\\" + text
    return text


def _item_line_as_slack_takes_it_back(line: str) -> str:
    item = ITEM_LINE.fullmatch(line)
    if item is None:
        return line
    return item.group(1) + _item_text_that_cannot_start_a_list(item.group(2))


def _as_slack_takes_it_back(raw: str) -> str:
    raw = _blank_as_a_list_separator(raw)
    if not is_a_list(raw):
        return raw
    return "\n".join(map(_item_line_as_slack_takes_it_back, raw.split("\n")))


def canvas_body(raws: Sequence[str]) -> str:
    spaced: list[str] = []
    for raw in map(_as_slack_takes_it_back, raws):
        if spaced and is_a_list(spaced[-1]) and is_a_list(raw):
            spaced.append(LIST_SEPARATOR)
        spaced.append(raw)
    return _blocks_text(spaced or [LIST_SEPARATOR])


def body_with_content_swapped(keyed: KeyedCanvas, old: Sequence[int], at: int, markdown: str) -> list[str]:
    removed = frozenset(old)
    kept = [
        block.raw
        for position, block in enumerate(keyed.blocks)
        if position >= keyed.content_start and position not in removed
    ]
    insertion = at - keyed.content_start - sum(position < at for position in removed)
    kept[insertion:insertion] = canvas_blocks(markdown)
    return kept


def with_the_stamp_line(keyed: KeyedCanvas, raws: Sequence[str], stamp: Stamp) -> list[str]:
    return [*raws, canvas_stamp_line(stamp)] if keyed.stamp is None else list(raws)
