import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Final

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
SPAN_TAG: Final = re.compile(r"<span\b([^>]*)>|</span>")
DISCUSSION_ATTRIBUTE: Final = re.compile(r'\s*discussion-urls="[^"]*"')
TABLE_OPENING: Final = re.compile(r"<table[\s>]")
TABLE_CLOSING: Final = "</table>"
INDENTATION: Final = (" ", "\t")


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
    def ignorable_at_the_end(self) -> bool:
        return self.normalised is None or _is_empty_block(self.normalised) or self.child_url is not None

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


def _trailing_after(lines: Sequence[_PageLine], stamp_at: int | None) -> set[int]:
    if stamp_at is None:
        return set()
    trailing: set[int] = set()
    for index in reversed(range(stamp_at + 1, len(lines))):
        if not lines[index].ignorable_at_the_end:
            break
        trailing.add(index)
    return trailing


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

    def key_before(self, position: int) -> str:
        if position > 0:
            return self.keys[position - 1]
        return self.keys[0] if self.keys else self.fallback

    def keys_of(self, actual: Sequence[str]) -> list[str]:
        keys = [self.fallback] * len(actual)
        matcher = SequenceMatcher(None, self.lines, actual, autojunk=False)
        for tag, start, end, actual_start, actual_end in matcher.get_opcodes():
            for offset, index in enumerate(range(actual_start, actual_end)):
                if tag == "equal":
                    keys[index] = self.keys[start + offset]
                elif tag == "replace":
                    keys[index] = self.keys[start + offset * (end - start) // (actual_end - actual_start)]
                else:
                    keys[index] = self.key_before(start)
        return keys


def _keys_of_lines(lines: Sequence[_PageLine], content: Sequence[int], layout: _Layout) -> dict[int, str]:
    aligned = [index for index in content if lines[index].normalised is not None]
    aligned_keys = layout.keys_of([lines[index].normalised or "" for index in aligned])
    found: dict[int, str] = dict(zip(aligned, aligned_keys, strict=True))
    keys: dict[int, str] = {}
    waiting: list[int] = []
    current: str | None = None
    for index in content:
        if index in found:
            current = found[index]
        if current is None:
            waiting.append(index)
            continue
        keys |= dict.fromkeys([*waiting, index], current)
        waiting = []
    return keys | dict.fromkeys(waiting, layout.fallback)


def keyed_page(markdown: str, layout: Mapping[str, str]) -> KeyedPage:
    lines = _page_lines(markdown)
    stamp_at = _last_stamp_at(lines)
    children = {index for index, line in enumerate(lines) if line.child_url is not None}
    left_out = {*children, *_trailing_after(lines, stamp_at), *([] if stamp_at is None else [stamp_at])}
    content = [index for index in range(len(lines)) if index not in left_out]
    raw: dict[str, list[str]] = {}
    for index, key in sorted(_keys_of_lines(lines, content, _Layout.of(layout)).items()):
        raw.setdefault(key, []).append(lines[index].raw)
    raw_sections = {key: "".join(section) for key, section in raw.items()}
    return KeyedPage(
        raw_sections=raw_sections,
        sections={key: comparable_text(without_comment_markers(text)) for key, text in raw_sections.items()},
        stamp=None if stamp_at is None else lines[stamp_at].stamp,
        stamp_line=None if stamp_at is None else lines[stamp_at].raw,
        child_ids=tuple(
            notion_page_id(url) or url for index in sorted(children) if (url := lines[index].child_url)
        ),
    )


@dataclass(frozen=True)
class Replacement:
    old_str: str
    new_str: str


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


def section_replacement(
    current: Sequence[tuple[str, str]], after: Sequence[tuple[str, str]], stamp: str | None
) -> Replacement | None:
    start = _common_prefix(current, after)
    suffix = _common_suffix(current, after, start)
    end_before, end_after = len(current) - suffix, len(after) - suffix
    if start == end_before and start == end_after:
        return None
    page = joined([*_texts(current), stamp or ""])
    while True:
        old = joined(_texts(current[start:end_before]))
        if old and page.count(old) == 1:
            return Replacement(old, joined(_texts(after[start:end_after])))
        if start > 0:
            start -= 1
        elif end_before < len(current):
            end_before += 1
            end_after += 1
        else:
            break
    if stamp is None:
        return None
    return Replacement(stamp, joined([*_texts(after), stamp]))
