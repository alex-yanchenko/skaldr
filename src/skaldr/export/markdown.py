import re
import unicodedata
from collections import Counter
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Literal

from typing_extensions import assert_never

from skaldr.export.flanking import EMPHASIS_OPENER_STAND_IN, LINE_EDGE, NO_CHARACTER, written_emphasis
from skaldr.export.glyphs import CALLOUT_ICON, tab_icon
from skaldr.export.inline import plain
from skaldr.export.markup import (
    DIVIDER_LINE,
    STYLE_MARKER,
    MarkupRuns,
    body_cell_texts,
    code_block_lines,
    code_span,
    escape_block_start,
    indent_lines,
    styled,
    styled_in_tags,
)
from skaldr.export.mermaid import mermaid_fence_lines
from skaldr.export.runs import Chip, ExportRich, export_visible_text, write_export_run
from skaldr.export.tree import (
    Callout,
    CodeBlock,
    Columns,
    Diagram,
    DisplayMath,
    Divider,
    Heading,
    HeadingLevel,
    ListEntry,
    ListKind,
    ListNode,
    LoweredDocument,
    Node,
    Paragraph,
    Quote,
    TableCell,
    TableNode,
    TableOfContents,
    Tabs,
    Toggle,
    heading_of,
    nested_nodes,
)
from skaldr.richtext import (
    SCRIPT_HTML_TAG,
    AnchorLink,
    Link,
    MarkerStyle,
    ScriptPosition,
    Styled,
    StyleName,
    Tinted,
)

OTHER_ALPHABETIC_SYMBOL_RANGES: Final = (
    range(0x24D0, 0x24EA),
    range(0x1F130, 0x1F14A),
    range(0x1F150, 0x1F16A),
    range(0x1F170, 0x1F18A),
)
MARKDOWN_ESCAPES: Final = str.maketrans({character: "\\" + character for character in "\\*_`[]<>~$"})
ENTITY_LOOKALIKE = re.compile(r"&(?=#?\w+;)")
HEADING_CLOSING_RUN = re.compile(r"(?:(?<=\s)|^)(#+\s*)$")
LARGEST_ORDERED_MARKER_NUMBER: Final = 999_999_999
MarkerFamily = Literal["dash", "ordinal"]
MARKER_FAMILY: Final[Mapping[ListKind, MarkerFamily]] = {
    "bullet": "dash",
    "check": "dash",
    "number": "ordinal",
}


def _dash(use_alternate_markers: bool) -> str:
    return "*" if use_alternate_markers else "-"


def _is_a_circled_or_squared_letter(character: str) -> bool:
    return any(ord(character) in symbols for symbols in OTHER_ALPHABETIC_SYMBOL_RANGES)


def _kept_in_a_github_slug(character: str) -> bool:
    category = unicodedata.category(character)
    return (
        character in " -"
        or category[0] in "LM"
        or category in ("Nd", "Nl", "Pc")
        or _is_a_circled_or_squared_letter(character)
    )


def github_slug(text: str) -> str:
    return "".join(filter(_kept_in_a_github_slug, text.lower())).replace(" ", "-")


@dataclass(frozen=True)
class _Emphasis:
    style: MarkerStyle
    inner: str


_Piece = str | _Emphasis


def _marker_style(style: StyleName) -> MarkerStyle | None:
    match style:
        case "bold" | "italic" | "strike":
            return style
        case "underline":
            return None
        case _:
            assert_never(style)


def _first_character(pieces: Sequence[_Piece]) -> str:
    for piece in pieces:
        if isinstance(piece, str):
            written = piece
        else:
            written = piece.inner if not piece.inner.strip() else EMPHASIS_OPENER_STAND_IN
        if written:
            return written[0]
    return NO_CHARACTER


class _MarkdownRuns(MarkupRuns):
    def __init__(self, heading_slugs: Mapping[str, str]) -> None:
        self.heading_slugs = heading_slugs

    def write(self, runs: ExportRich) -> str:
        pieces = self._pieces(runs)
        written = ""
        open_marker_character = NO_CHARACTER
        for index, piece in enumerate(pieces):
            if isinstance(piece, str):
                written += piece
                open_marker_character = NO_CHARACTER
                continue
            marker = STYLE_MARKER[piece.style]
            runs_into_the_previous_marker = (
                marker[0] == open_marker_character and piece.inner == piece.inner.lstrip()
            )
            if runs_into_the_previous_marker:
                emphasis = styled_in_tags(piece.style, piece.inner)
            else:
                following = _first_character(pieces[index + 1 :]) or LINE_EDGE
                emphasis = written_emphasis(piece.style, piece.inner, written[-1:] or LINE_EDGE, following)
            written += emphasis
            open_marker_character = marker[0] if emphasis.endswith(marker) else NO_CHARACTER
        return written

    def _pieces(self, runs: ExportRich) -> list[_Piece]:
        pieces: list[_Piece] = []
        for run in runs:
            match run:
                case Styled():
                    inner = self.write(run.runs)
                    marker_style = _marker_style(run.style)
                    pieces.append(
                        self.underline(inner) if marker_style is None else _Emphasis(marker_style, inner)
                    )
                case Tinted():
                    pieces += self._pieces(run.runs)
                case Link():
                    pieces.append(self.link(self.write(run.label), run.url))
                case AnchorLink() if run.anchor not in self.heading_slugs:
                    pieces += self._pieces(run.label)
                case AnchorLink():
                    pieces.append(self.anchor_link(self.write(run.label), run.anchor))
                case Chip():
                    pieces.append(_Emphasis("bold", self.escape(run.label)))
                case _:
                    pieces.append(write_export_run(run, self))
        return pieces

    def escape(self, text: str, /) -> str:
        return ENTITY_LOOKALIKE.sub(r"\\&", text.translate(MARKDOWN_ESCAPES))

    def code(self, text: str, /) -> str:
        return code_span(text)

    def anchor_link(self, label: str, anchor: str, /) -> str:
        slug = self.heading_slugs.get(anchor)
        return f"[{label}](#{slug})" if slug else label

    def placeholder(self, name: str, /) -> str:
        return code_span("{{" + name + "}}")

    def chip(self, run: Chip, /) -> str:
        return self.write((run,))

    def underline(self, inner: str, /) -> str:
        return f"<ins>{inner}</ins>"

    def script(self, position: ScriptPosition, text: str, /) -> str:
        tag = SCRIPT_HTML_TAG[position]
        return f"<{tag}>{self.escape(text)}</{tag}>"


def _headings(nodes: Sequence[Node]) -> Iterator[tuple[str | None, ExportRich]]:
    for node in nodes:
        heading = heading_of(node)
        if heading is not None:
            yield heading.anchor, heading.text
        yield from _headings(nested_nodes(node))


def github_heading_slugs(nodes: Sequence[Node]) -> dict[str, str]:
    repeats: Counter[str] = Counter()
    taken: set[str] = set()
    slugs: dict[str, str] = {}
    for anchor, text in _headings(nodes):
        base = slug = github_slug(export_visible_text(text))
        while slug in taken:
            repeats[base] += 1
            slug = f"{base}-{repeats[base]}"
        taken.add(slug)
        if anchor is not None:
            slugs[anchor] = slug
    return slugs


@dataclass(frozen=True)
class _ListTail:
    family: MarkerFamily
    alternated: bool


@dataclass(frozen=True)
class _Written:
    lines: tuple[str, ...]
    tail: _ListTail | None = None
    opens_with_a_paragraph: bool = False

    @classmethod
    def of(cls, lines: Sequence[str], tail: _ListTail | None = None) -> "_Written":
        return cls(tuple(lines), tail)


def _marker_family(node: Node) -> MarkerFamily | None:
    if isinstance(node, ListNode):
        return MARKER_FAMILY[node.kind]
    return "dash" if isinstance(node, TableOfContents) else None


def _must_alternate_markers(family: MarkerFamily | None, after: _ListTail | None) -> bool:
    return family is not None and after is not None and after.family == family and not after.alternated


def _spaced(lines: Sequence[str]) -> list[str]:
    return ["", *lines] if lines else []


def _quoted(lines: Sequence[str]) -> list[str]:
    return [f"> {line}" if line else ">" for line in lines]


def _pad(cells: Sequence[str], width: int) -> list[str]:
    return [*cells, *[""] * (width - len(cells))]


def _table_row(cells: Sequence[str]) -> str:
    return "| " + " | ".join(cells) + " |"


def _joined(sections: Sequence[Sequence[str]]) -> list[str]:
    out: list[str] = []
    for lines in sections:
        if lines:
            out += ["", *lines] if out else lines
    return out


class _MarkdownWriter:
    def __init__(self, heading_slugs: Mapping[str, str]) -> None:
        self.runs = _MarkdownRuns(heading_slugs)

    def inline(self, runs: ExportRich) -> str:
        return self.runs.write(runs)

    def block_text(self, runs: ExportRich) -> str:
        return escape_block_start(self.inline(runs))

    def heading_line(self, level: HeadingLevel, runs: ExportRich) -> str:
        text = HEADING_CLOSING_RUN.sub(lambda match: "\\" + match.group(1), self.inline(runs))
        return f"{'#' * level} {text}"

    def cell_text(self, cell: TableCell) -> str:
        return self.inline(cell.text).replace("|", "\\|")

    def table_lines(self, table: TableNode) -> list[str]:
        width = max(len(cells) for cells in (table.header, *(row.cells for row in table.rows)))
        lines = [
            _table_row(_pad([self.cell_text(cell) for cell in table.header], width)),
            _table_row(["---"] * width),
        ]
        for row in table.rows:
            texts = body_cell_texts(table, row, [self.cell_text(cell) for cell in row.cells])
            lines.append(_table_row(_pad(texts, width)))
        return lines

    def list_lines(self, node: ListNode, use_alternate_markers: bool) -> list[str]:
        dash = _dash(use_alternate_markers)
        lines: list[str] = []
        for index, entry in enumerate(node.entries, start=node.start):
            match node.kind:
                case "bullet":
                    marker, width = dash, len(dash) + 1
                case "number":
                    number = min(index, LARGEST_ORDERED_MARKER_NUMBER)
                    marker = f"{number}{')' if use_alternate_markers else '.'}"
                    width = len(marker) + 1
                case "check":
                    marker, width = f"{dash} [{'x' if entry.checked else ' '}]", len(dash) + 1
                case _:
                    assert_never(node.kind)
            line = f"{marker} {self.block_text(entry.text)}".rstrip()
            lines.append(line)
            lines += self.entry_children(entry, width, after_a_bare_marker=line == marker)
        return lines

    def entry_children(self, entry: ListEntry, width: int, after_a_bare_marker: bool) -> list[str]:
        children = self.blocks(entry.children)
        if not children:
            return []
        gap = [] if after_a_bare_marker or isinstance(entry.children[0], ListNode) else [""]
        return gap + indent_lines(children, " " * width)

    def titled(self, title: str, children: Sequence[Node], after: _ListTail | None) -> _Written:
        if not title:
            return self.blocks_after(children, after)
        body = self.blocks_after(children, None)
        return _Written.of([title, *_spaced(body.lines)], body.tail)

    def callout_lines(self, node: Callout) -> list[str]:
        icon = node.icon or CALLOUT_ICON[node.tone]
        body = self.blocks_after(node.children, None)
        lines = list(body.lines)
        if lines and body.opens_with_a_paragraph:
            lines[0] = f"{icon} {lines[0]}"
        else:
            lines = [icon, *_spaced(lines)]
        return _quoted(lines)

    def quote_lines(self, node: Quote) -> list[str]:
        parts = [self.block_text(line) for line in node.lines]
        if node.cite:
            parts.append(styled("italic", self.inline(node.cite)))
        return _quoted(_joined([[part] for part in parts]))

    def tabs_written(self, node: Tabs, after: _ListTail | None) -> _Written:
        sections: list[Sequence[str]] = []
        tail = after
        for tab in node.tabs:
            icon = tab_icon(tab.tone)
            title = self.inline(tab.title)
            section = self.titled(styled("bold", f"{icon} {title}" if icon else title), tab.children, tail)
            if section.lines:
                sections.append(section.lines)
                tail = section.tail
        return _Written.of(_joined(sections), tail)

    def toc_lines(self, node: TableOfContents, use_alternate_markers: bool) -> list[str]:
        dash = _dash(use_alternate_markers)
        entries = [
            (self.runs.heading_slugs.get(entry.anchor), self.inline(entry.title)) for entry in node.entries
        ]
        return [f"{dash} [{title}](#{slug})" if slug else f"{dash} {title}" for slug, title in entries]

    def written(self, node: Node, after: _ListTail | None) -> _Written:
        alternate = _must_alternate_markers(_marker_family(node), after)
        match node:
            case Heading():
                return _Written.of([self.heading_line(node.level, node.text)])
            case Paragraph():
                text = self.block_text(node.text)
                return _Written.of([text] if text else [])
            case ListNode():
                family = MARKER_FAMILY[node.kind]
                return _Written.of(self.list_lines(node, alternate), _ListTail(family, alternate))
            case TableNode():
                return _Written.of(self.table_lines(node))
            case CodeBlock():
                return _Written.of(code_block_lines(node))
            case DisplayMath():
                return _Written.of(code_block_lines(CodeBlock(node.expression, "math")))
            case Callout():
                return _Written.of(self.callout_lines(node))
            case Quote():
                return _Written.of(self.quote_lines(node))
            case Divider():
                return _Written.of([DIVIDER_LINE])
            case Toggle():
                if node.heading_level is not None:
                    return self.titled(
                        self.heading_line(node.heading_level, node.title), node.children, after
                    )
                return self.titled(styled("bold", self.inline(node.title)), node.children, after)
            case Columns():
                columns = self.blocks_after(nested_nodes(node), after)
                return _Written.of(columns.lines, columns.tail)
            case Tabs():
                return self.tabs_written(node, after)
            case Diagram():
                supplement = self.blocks_after(node.supplement, None)
                return _Written.of(
                    [*mermaid_fence_lines(node.figure), *_spaced(supplement.lines)], supplement.tail
                )
            case TableOfContents():
                return _Written.of(self.toc_lines(node, alternate), _ListTail("dash", alternate))
            case _:
                assert_never(node)

    def blocks_after(self, nodes: Sequence[Node], after: _ListTail | None) -> _Written:
        rendered: list[Sequence[str]] = []
        tail = after
        opens_with_a_paragraph = False
        for node in nodes:
            written = self.written(node, tail)
            if written.lines:
                opens_with_a_paragraph = opens_with_a_paragraph if rendered else isinstance(node, Paragraph)
                rendered.append(written.lines)
                tail = written.tail
        return _Written(tuple(_joined(rendered)), tail, opens_with_a_paragraph)

    def blocks(self, nodes: Sequence[Node]) -> list[str]:
        return list(self.blocks_after(nodes, None).lines)


def render_markdown(nodes: Sequence[Node]) -> str:
    return "\n".join(_MarkdownWriter(github_heading_slugs(nodes)).blocks(nodes)) + "\n"


def _cover_link(cover: str | None) -> tuple[Paragraph, ...]:
    return (Paragraph((Link(plain("Cover image"), cover),)),) if cover else ()


def render_markdown_document(document: LoweredDocument) -> str:
    title = plain(f"{document.icon} {document.title}" if document.icon else document.title)
    return render_markdown((Heading(1, title), *_cover_link(document.cover), *document.body))
