import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Final, Literal

from markdown_it import MarkdownIt
from markdown_it.token import Token
from typing_extensions import override

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
HARD_BREAK: Final = re.compile(r"(?<!\\)\\$")
MENTION: Final = re.compile(r"!\[\]\(([@#][A-Z0-9]+)\)")
UNESCAPED_PIPE: Final = re.compile(r"(?<!\\)\|")
TABLE_SEPARATOR_CELL: Final = re.compile(r":?-{3,}:?")
SEPARATOR_TEXTS: Final = frozenset({"", LIST_SEPARATOR})
TABLE_EDGE: Final = "|"
TABLE_SEPARATOR: Final = "---"
VOID_ELEMENTS: Final = frozenset(
    {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
)
DOCUMENT_ELEMENTS: Final = frozenset({"html", "body"})
HEAD_ELEMENT: Final = "head"
WORD: Final = re.compile(r"\w+")
SLACK_ONLY_MARKUP: Final = re.compile(r"<[@#!][^>]*>|:[a-z0-9_+-]+:|\[[ xX]\]")
CODE_TOKENS: Final = frozenset({"fence", "code_block"})
TEXT: Final = "text"
CODE_INLINE: Final = "code_inline"
BLOCK_MARKDOWN: Final = MarkdownIt("commonmark").enable("table")

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


def comparable_block(block: str) -> str:
    if block.strip() in SEPARATOR_TEXTS:
        return ""
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


def left_by_a_split_canvas_write(current: str | None, published: str | None, expected: str | None) -> bool:
    now = _comparable_blocks(current or "")
    old = _comparable_blocks(published or "")
    new = _comparable_blocks(expected or "")
    inserted_first = [[*new, *old[:kept]] for kept in range(len(old) + 1)]
    deleted_first = [old[:kept] for kept in range(len(old) + 1)]
    return now in [*inserted_first, *deleted_first]


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


def _words(text: str) -> tuple[str, ...]:
    return tuple(word.casefold() for word in WORD.findall(text))


def _shown_text(token: Token) -> str:
    if token.type in CODE_TOKENS:
        return token.content
    return " ".join(
        child.content if child.type == CODE_INLINE else SLACK_ONLY_MARKUP.sub(" ", child.content)
        for child in token.children or []
        if child.type in (TEXT, CODE_INLINE)
    )


def _block_words(block: str) -> tuple[str, ...]:
    kept = "\n".join(line for line in block.split("\n") if not line.strip().startswith(CANVAS_FENCE))
    return _words(" ".join(_shown_text(token) for token in BLOCK_MARKDOWN.parse(kept)))


@dataclass(frozen=True)
class HtmlSection:
    section_id: str | None
    words: tuple[str, ...]

    def shows(self, block: str) -> bool:
        shown = iter(self.words)
        return all(word in shown for word in _block_words(block))


@dataclass
class _OpenSection:
    section_id: str | None
    text: list[str] = field(default_factory=list[str])


class _TopLevelSections(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.sections: list[_OpenSection] = []
        self.collecting = False

    @override
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in DOCUMENT_ELEMENTS:
            return
        if self.depth == 0 and tag != HEAD_ELEMENT:
            self.sections.append(_OpenSection(dict(attrs).get("id")))
            self.collecting = tag not in VOID_ELEMENTS
        if tag not in VOID_ELEMENTS:
            self.depth += 1

    @override
    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in DOCUMENT_ELEMENTS and self.depth == 0:
            self.sections.append(_OpenSection(dict(attrs).get("id")))

    @override
    def handle_endtag(self, tag: str) -> None:
        if tag not in DOCUMENT_ELEMENTS and tag not in VOID_ELEMENTS:
            self.depth = max(0, self.depth - 1)
            self.collecting = self.collecting and self.depth > 0

    @override
    def handle_data(self, data: str) -> None:
        if self.collecting:
            self.sections[-1].text.append(data)


def html_sections(html: str) -> tuple[HtmlSection, ...]:
    parser = _TopLevelSections()
    parser.feed(html)
    parser.close()
    return tuple(
        HtmlSection(section.section_id, _words(" ".join(section.text))) for section in parser.sections
    )
