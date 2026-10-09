import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Final, Literal

from skaldr.export.budget import json_string_bytes
from skaldr.export.notion import EMPTY_BLOCK, notion_fence_closer
from skaldr.patterns import SLUG_PATTERN
from skaldr.publish.transport import Stamp
from skaldr.publish_block import notion_page_id

UNKEYED_SECTION: Final = "content skaldr did not publish"
STAMP_WORDS: Final = "Published with skaldr from document"
STAMP_COLOR: Final = '{color="gray"}'
STAMP_PATTERN: Final = re.compile(
    rf"{STAMP_WORDS} ({SLUG_PATTERN})(?:, section ({SLUG_PATTERN}))?(?: {re.escape(STAMP_COLOR)})?"
)
CHILD_REFERENCE: Final = re.compile(r'<(page|database)\b[^>]*?\burl="([^"]*)"[^>]*>.*</\1>')
UNKNOWN_BLOCK: Final = re.compile(r"<unknown\b")
SPAN_TAG: Final = re.compile(r"<span\b([^>]*)>|</span>")
DISCUSSION_ATTRIBUTE: Final = re.compile(r'\s*discussion-urls="[^"]*"')
TABLE_OPENING: Final = re.compile(r"<table[\s>]")
TABLE_CLOSING: Final = "</table>"
BLOCK_CONTINUATION: Final = re.compile(r"</[a-z_]+>|<summary>.*</summary>")
INDENTATION: Final = (" ", "\t")

LineRole = Literal["published", "added", "child", "blank", "stamp", "below"]
KEPT_WHEN_RELEASED: Final[frozenset[LineRole]] = frozenset({"added", "child"})
REMOVED_WHEN_RELEASED: Final[frozenset[LineRole]] = frozenset({"published", "blank"})


def stamp_line(stamp: Stamp) -> str:
    section = "" if stamp.section_id is None else f", section {stamp.section_id}"
    return f"{STAMP_WORDS} {stamp.doc_id}{section} {STAMP_COLOR}\n"


def _parsed_stamp(line: str) -> Stamp | None:
    found = STAMP_PATTERN.fullmatch(line.strip())
    return None if found is None else Stamp(found.group(1), found.group(2))


@dataclass
class _SpanEdits:
    replacements: dict[int, tuple[int, str]] = field(default_factory=dict[int, tuple[int, str]])
    open_spans: list[int | None] = field(default_factory=list[int | None])

    def opening(self, match: re.Match[str]) -> None:
        attributes = match.group(1)
        if DISCUSSION_ATTRIBUTE.search(attributes) is None:
            self.open_spans.append(None)
            return
        others = DISCUSSION_ATTRIBUTE.sub("", attributes)
        if others.strip():
            self.replacements[match.start()] = (match.end(), f"<span{others}>")
            self.open_spans.append(None)
            return
        self.replacements[match.start()] = (match.end(), "")
        self.open_spans.append(match.start())

    def closing(self, match: re.Match[str]) -> None:
        if not self.open_spans:
            return
        marker_start = self.open_spans.pop()
        if marker_start is not None:
            self.replacements[match.start()] = (match.end(), "")

    def applied_to(self, text: str) -> str:
        unclosed = {start for start in self.open_spans if start is not None}
        pieces: list[str] = []
        position = 0
        for start in sorted(self.replacements):
            if start in unclosed:
                continue
            end, replacement = self.replacements[start]
            pieces += [text[position:start], replacement]
            position = end
        return "".join([*pieces, text[position:]])


def without_comment_markers(text: str) -> str:
    edits = _SpanEdits()
    for match in SPAN_TAG.finditer(text):
        if match.group(0) == "</span>":
            edits.closing(match)
        else:
            edits.opening(match)
    return edits.applied_to(text)


def holds_an_unknown_block(text: str) -> bool:
    return UNKNOWN_BLOCK.search(text) is not None


@dataclass
class _Normaliser:
    closer: str | None = None
    indented_fence: bool = False
    in_table: bool = False

    @property
    def at_block_level(self) -> bool:
        return self.closer is None and not self.in_table

    def line(self, line: str) -> str | None:
        stripped = line.strip()
        if self.closer is not None:
            if stripped == self.closer:
                self.closer = None
                return stripped if self.indented_fence else line
            return line.lstrip() if self.indented_fence else line
        if not stripped:
            return None
        if self.in_table or TABLE_OPENING.match(stripped):
            self.in_table = stripped != TABLE_CLOSING
            return stripped
        self.closer = notion_fence_closer(stripped)
        self.indented_fence = self.closer is not None and line.startswith(INDENTATION)
        return line


def _lines_of(text: str) -> list[str]:
    lines = text.split("\n")
    return lines[:-1] if lines[-1] == "" else lines


def _raw_lines(text: str) -> list[str]:
    pieces = text.split("\n")
    return [f"{piece}\n" for piece in pieces[:-1]] + ([pieces[-1]] if pieces[-1] else [])


def _is_empty_block(line: str) -> bool:
    return line.strip() == EMPTY_BLOCK


def comparable_text(text: str) -> str:
    normaliser = _Normaliser()
    kept = [line for line in map(normaliser.line, _lines_of(text)) if line is not None]
    while kept and _is_empty_block(kept[-1]):
        kept.pop()
    return "".join(f"{line}\n" for line in kept)


def joined(pieces: Sequence[str]) -> str:
    present = [piece for piece in pieces if piece]
    return "".join(
        piece if piece.endswith("\n") or position == len(present) - 1 else f"{piece}\n"
        for position, piece in enumerate(present)
    )


@dataclass(frozen=True)
class KeyedPage:
    raw_sections: dict[str, str]
    sections: dict[str, str]
    stamp: Stamp | None
    stamp_line: str | None
    child_ids: tuple[str, ...]


@dataclass(frozen=True)
class _PageLine:
    raw: str
    normalised: str | None
    at_top_level: bool

    @property
    def child_url(self) -> str | None:
        if not self.at_top_level or self.normalised is None:
            return None
        found = CHILD_REFERENCE.fullmatch(self.normalised.strip())
        return None if found is None else found.group(2)

    @property
    def stamp(self) -> Stamp | None:
        if not self.at_top_level or self.normalised is None:
            return None
        return _parsed_stamp(self.normalised)

    @property
    def aligns(self) -> bool:
        return self.normalised is not None and self.child_url is None

    @property
    def starts_a_block(self) -> bool:
        if not self.at_top_level or self.normalised is None:
            return False
        return BLOCK_CONTINUATION.fullmatch(self.normalised.strip()) is None

    @property
    def unaligned_role(self) -> LineRole:
        return "child" if self.child_url is not None else "blank"


def _page_lines(markdown: str) -> list[_PageLine]:
    normaliser = _Normaliser()
    lines: list[_PageLine] = []
    for raw in _raw_lines(markdown):
        bare = without_comment_markers(raw.removesuffix("\n"))
        at_block_level = normaliser.at_block_level
        normalised = normaliser.line(bare)
        lines.append(_PageLine(raw, normalised, at_block_level and not bare.startswith(INDENTATION)))
    return lines


def _last_stamp_at(lines: Sequence[_PageLine]) -> int | None:
    return next((index for index in reversed(range(len(lines))) if lines[index].stamp is not None), None)


@dataclass(frozen=True)
class _Layout:
    keys: list[str]
    lines: list[str]
    fallback: str

    @classmethod
    def of(cls, layout: Mapping[str, str]) -> "_Layout":
        keys: list[str] = []
        lines: list[str] = []
        for key, text in layout.items():
            expected = _lines_of(comparable_text(without_comment_markers(text)))
            keys += [key] * len(expected)
            lines += expected
        return cls(keys, lines, next(iter(layout), UNKEYED_SECTION))

    def key_of_inserted(self, position: int) -> str:
        if not self.keys:
            return self.fallback
        opens_a_section = position < len(self.keys) and (
            position == 0 or self.keys[position] != self.keys[position - 1]
        )
        return self.keys[position] if opens_a_section else self.keys[position - 1]

    def placed(self, actual: Sequence[str]) -> list[tuple[str, LineRole]]:
        placed: list[tuple[str, LineRole]] = [(self.fallback, "added")] * len(actual)
        matcher = SequenceMatcher(None, self.lines, actual, autojunk=False)
        for tag, start, end, actual_start, actual_end in matcher.get_opcodes():
            for offset, index in enumerate(range(actual_start, actual_end)):
                if tag == "equal":
                    placed[index] = (self.keys[start + offset], "published")
                elif tag == "replace":
                    position = start + offset * (end - start) // (actual_end - actual_start)
                    placed[index] = (self.keys[position], "added")
                else:
                    placed[index] = (self.key_of_inserted(start), "added")
        return placed


@dataclass(frozen=True)
class _Placed:
    line: _PageLine
    key: str | None
    role: LineRole
    block: int


def _placed_lines(markdown: str, layout: Mapping[str, str]) -> list[_Placed]:
    lines = _page_lines(markdown)
    stamp_at = _last_stamp_at(lines)
    content_end = len(lines) if stamp_at is None else stamp_at
    shape = _Layout.of(layout)
    aligned = [index for index in range(content_end) if lines[index].aligns]
    found = dict(
        zip(aligned, shape.placed([lines[index].normalised or "" for index in aligned]), strict=True)
    )
    first_key = found[aligned[0]][0] if aligned else shape.fallback
    placed: list[_Placed] = []
    current = first_key
    block = 0
    for index, line in enumerate(lines):
        block += 1 if line.starts_a_block or index == stamp_at else 0
        if index >= content_end:
            placed.append(_Placed(line, None, "stamp" if index == stamp_at else "below", block))
            continue
        key, role = found.get(index, (current, line.unaligned_role))
        current = key
        placed.append(_Placed(line, key, role, block))
    return placed


def keyed_page(markdown: str, layout: Mapping[str, str]) -> KeyedPage:
    placed = _placed_lines(markdown, layout)
    raw: dict[str, list[str]] = {}
    shown: dict[str, list[str]] = {}
    for line in placed:
        if line.key is None:
            continue
        raw.setdefault(line.key, []).append(line.line.raw)
        shown.setdefault(line.key, []).extend([] if line.role == "child" else [line.line.raw])
    stamp = next((line.line for line in placed if line.role == "stamp"), None)
    return KeyedPage(
        raw_sections={key: "".join(lines) for key, lines in raw.items()},
        sections={
            key: text
            for key, lines in shown.items()
            if (text := comparable_text(without_comment_markers("".join(lines))))
        },
        stamp=None if stamp is None else stamp.stamp,
        stamp_line=None if stamp is None else stamp.raw,
        child_ids=tuple(
            notion_page_id(url) or url for line in placed if (url := line.line.child_url) is not None
        ),
    )


def carried_into(raw: str, text: str) -> str:
    children: list[tuple[int, str]] = []
    lines_before = 0
    for line in _page_lines(raw):
        if line.child_url is not None:
            children.append((lines_before, line.raw if line.raw.endswith("\n") else f"{line.raw}\n"))
        elif line.normalised is not None:
            lines_before += 1
    if not children:
        return text
    new_lines = _raw_lines(text)
    normaliser = _Normaliser()
    pieces: list[str] = []
    for index in range(len(new_lines) + 1):
        at_a_boundary = index == len(new_lines) or (
            normaliser.at_block_level and not new_lines[index].startswith(INDENTATION)
        )
        if at_a_boundary:
            due = [child for position, child in children if min(position, len(new_lines)) <= index]
            pieces += due
            children = children[len(due) :]
        if index < len(new_lines):
            pieces.append(new_lines[index])
            normaliser.line(new_lines[index].removesuffix("\n"))
    return joined(pieces)


@dataclass(frozen=True)
class Replacement:
    old_str: str
    new_str: str
    quoted: tuple[str, ...] = ()

    @property
    def changes_nothing(self) -> bool:
        return self.old_str == self.new_str


NO_REPLACEMENT: Final = Replacement("", "")


def _released_runs(placed: Sequence[_Placed]) -> list[tuple[int, int]]:
    kept_blocks = {line.block for line in placed if line.role in KEPT_WHEN_RELEASED}
    removed = [
        line.role == "stamp" or (line.role in REMOVED_WHEN_RELEASED and line.block not in kept_blocks)
        for line in placed
    ]
    runs: list[tuple[int, int]] = []
    for index, gone in enumerate(removed):
        if not gone:
            continue
        if runs and runs[-1][1] == index:
            runs[-1] = (runs[-1][0], index + 1)
        else:
            runs.append((index, index + 1))
    return runs


def _chunks_of_whole_blocks(
    placed: Sequence[_Placed], run: tuple[int, int], most_bytes: int
) -> list[tuple[int, int]]:
    blocks: dict[int, int] = {}
    for line in placed[run[0] : run[1]]:
        blocks[line.block] = blocks.get(line.block, 0) + json_string_bytes(line.line.raw)
    chunks: list[tuple[int, int]] = []
    start, size = run[0], 0
    for index in range(run[0], run[1]):
        block = placed[index].block
        opens_a_block = index == run[0] or block != placed[index - 1].block
        if opens_a_block and size and size + blocks[block] > most_bytes:
            chunks.append((start, index))
            start, size = index, 0
        size += blocks[block] if opens_a_block else 0
    chunks.append((start, run[1]))
    return chunks


def _raw(placed: Sequence[_Placed]) -> str:
    return "".join(line.line.raw for line in placed)


def _unique_removal(
    placed: Sequence[_Placed], chunk: tuple[int, int], page: str, gone: set[int]
) -> Replacement:
    start, end = chunk
    removed = placed[start:end]
    before: list[_Placed] = []
    after: list[_Placed] = []

    def may_quote(index: int) -> bool:
        return index not in gone and _quotable(placed[index].line.raw, with_markers=True)

    while page.count(_raw([*before, *removed, *after])) != 1:
        if start > 0 and may_quote(start - 1):
            start -= 1
            before.insert(0, placed[start])
        elif end < len(placed) and may_quote(end):
            after.append(placed[end])
            end += 1
        else:
            break
    quoted = tuple(dict.fromkeys(line.key for line in removed if line.key is not None))
    return Replacement(_raw([*before, *removed, *after]), _raw([*before, *after]), quoted)


def release_replacements(markdown: str, layout: Mapping[str, str], most_bytes: int) -> list[Replacement]:
    placed = [line for line in _placed_lines(markdown, layout) if line.role != "below"]
    page = markdown
    gone: set[int] = set()
    replacements: list[Replacement] = []
    for run in _released_runs(placed):
        for chunk in _chunks_of_whole_blocks(placed, run, most_bytes):
            replacement = _unique_removal(placed, chunk, page, gone)
            page = page.replace(replacement.old_str, replacement.new_str, 1)
            gone |= set(range(*chunk))
            replacements.append(replacement)
    return replacements


def _common_prefix(before: Sequence[tuple[str, str]], after: Sequence[tuple[str, str]]) -> int:
    count = 0
    while count < min(len(before), len(after)) and before[count] == after[count]:
        count += 1
    return count


def _common_suffix(before: Sequence[tuple[str, str]], after: Sequence[tuple[str, str]], prefix: int) -> int:
    count = 0
    room = min(len(before), len(after)) - prefix
    while count < room and before[-1 - count] == after[-1 - count]:
        count += 1
    return count


def _texts(pairs: Sequence[tuple[str, str]]) -> list[str]:
    return [text for _, text in pairs]


def _keys(pairs: Sequence[tuple[str, str]]) -> tuple[str, ...]:
    return tuple(key for key, _ in pairs)


def _quotable(line: str, with_markers: bool) -> bool:
    return not holds_an_unknown_block(line) and (with_markers or DISCUSSION_ATTRIBUTE.search(line) is None)


def _offset_of(current: Sequence[tuple[str, str]], index: int) -> int:
    return len(joined([*_texts(current[:index]), "\0"])) - 1


def _found_once_at(page: str, text: str, offset: int) -> bool:
    return page.count(text) == 1 and page.find(text) == offset


def _unique_edge(
    section: tuple[str, str], offset: int, page: str, *, from_the_end: bool, with_markers: bool
) -> str | None:
    text = section[1]
    lines = _raw_lines(text)
    ordered = list(reversed(lines)) if from_the_end else lines
    taken: list[str] = []
    for line in ordered:
        if not _quotable(line, with_markers):
            return None
        taken.append(line)
        edge = "".join(reversed(taken)) if from_the_end else "".join(taken)
        at = offset + len(text) - len(edge) if from_the_end else offset
        if edge.strip() and _found_once_at(page, edge, at):
            return edge
    return None


def _anchored_insertion(
    current: Sequence[tuple[str, str]], at: int, inserted: str, page: str, stamp: str | None
) -> Replacement | None:
    before = current[at - 1] if at > 0 else None
    after = current[at] if at < len(current) else None
    for with_markers in (False, True):
        if before is not None:
            offset = _offset_of(current, at - 1)
            tail = _unique_edge(before, offset, page, from_the_end=True, with_markers=with_markers)
            if tail is not None:
                return Replacement(tail, joined([tail, inserted]), (before[0],))
        if after is not None:
            offset = _offset_of(current, at)
            head = _unique_edge(after, offset, page, from_the_end=False, with_markers=with_markers)
            if head is not None:
                return Replacement(head, joined([inserted, head]), (after[0],))
        if after is None and stamp is not None:
            return Replacement(stamp, joined([inserted, stamp]))
    return None


def section_replacement(
    current: Sequence[tuple[str, str]], after: Sequence[tuple[str, str]], page: str, stamp: str | None
) -> Replacement | None:
    start = _common_prefix(current, after)
    suffix = _common_suffix(current, after, start)
    end_before, end_after = len(current) - suffix, len(after) - suffix
    if start == end_before and start == end_after:
        return NO_REPLACEMENT
    if start == end_before:
        anchored = _anchored_insertion(current, start, joined(_texts(after[start:end_after])), page, stamp)
        if anchored is not None:
            return anchored
    while True:
        old = joined(_texts(current[start:end_before]))
        if old and _found_once_at(page, old, _offset_of(current, start)):
            return Replacement(old, joined(_texts(after[start:end_after])), _keys(current[start:end_before]))
        if start > 0:
            start -= 1
        elif end_before < len(current):
            end_before += 1
            end_after += 1
        else:
            return None
