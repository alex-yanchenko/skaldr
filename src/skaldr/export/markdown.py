import unicodedata
from collections import Counter
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Literal

from typing_extensions import assert_never

from skaldr.errors import ExportInvariantError
from skaldr.export.glyphs import callout_icon, tab_icon
from skaldr.export.inline import plain
from skaldr.export.markup import (
    DIVIDER_LINE,
    ENTITY_LOOKALIKE,
    LARGEST_ORDERED_MARKER_NUMBER,
    CommonMarkRuns,
    code_block_lines,
    encode_url,
    escape_block_start,
    heading_line,
    indent_lines,
    joined,
    pipe_table_lines,
    quoted,
    spaced,
    styled,
    styled_in_tags,
)
from skaldr.export.mermaid import mermaid_fence_lines
from skaldr.export.runs import ExportRich, export_visible_text
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
    Media,
    Node,
    Paragraph,
    Quote,
    TableNode,
    TableOfContents,
    Tabs,
    Toggle,
    heading_of,
    nested_nodes,
)
from skaldr.models import MEDIA_KIND_LABELS, ToneLiteral
from skaldr.richtext import SCRIPT_HTML_TAG, Link, MarkerStyle, ScriptPosition

OTHER_ALPHABETIC_SYMBOL_RANGES: Final = (
    range(0x24D0, 0x24EA),
    range(0x1F130, 0x1F14A),
    range(0x1F150, 0x1F16A),
    range(0x1F170, 0x1F18A),
)
MARKDOWN_ESCAPES: Final = str.maketrans({character: "\\" + character for character in "\\*_`[]<>~$"})
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


class _MarkdownRuns(CommonMarkRuns):
    def __init__(self, heading_slugs: Mapping[str, str]) -> None:
        self.heading_slugs = heading_slugs

    def heading_slug(self, anchor: str, /) -> str | None:
        return self.heading_slugs.get(anchor)

    def unflanked_emphasis(self, style: MarkerStyle, inner: str, /) -> str:
        return styled_in_tags(style, inner)

    def require_a_tint_it_can_drop(
        self, tone: ToneLiteral | None, _background: ToneLiteral | None, /
    ) -> None:
        if tone is not None:
            raise ExportInvariantError(
                "GitHub Markdown cannot colour text; the export check should have refused it"
            )

    def require_links_to_its_own_headings(self) -> None:
        return

    def escape(self, text: str, /) -> str:
        return ENTITY_LOOKALIKE.sub(r"\\&", text.translate(MARKDOWN_ESCAPES))

    def document_link(self, label: str, doc_id: str, _section: str | None, /) -> str:
        return self.link(label, f"{doc_id}.md")

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


class _MarkdownWriter:
    def __init__(self, heading_slugs: Mapping[str, str]) -> None:
        self.runs = _MarkdownRuns(heading_slugs)

    def inline(self, runs: ExportRich) -> str:
        return self.runs.write(runs)

    def block_text(self, runs: ExportRich) -> str:
        return escape_block_start(self.inline(runs))

    def heading_line(self, level: HeadingLevel, runs: ExportRich) -> str:
        return heading_line(level, self.inline(runs))

    def table_lines(self, table: TableNode) -> list[str]:
        return pipe_table_lines(table, self.inline)

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
        return _Written.of([title, *spaced(body.lines)], body.tail)

    def callout_lines(self, node: Callout) -> list[str]:
        icon = callout_icon(node)
        body = self.blocks_after(node.children, None)
        lines = list(body.lines)
        if icon is None:
            return quoted(lines)
        if lines and body.opens_with_a_paragraph:
            lines[0] = f"{icon} {lines[0]}"
        else:
            lines = [icon, *spaced(lines)]
        return quoted(lines)

    def media_lines(self, node: Media) -> list[str]:
        if node.kind == "image":
            image = f"![{self.inline(node.description)}]({encode_url(node.url)})"
            caption = [styled("italic", self.inline(node.caption))] if node.caption else []
            return joined([[image], caption])
        label = self.inline(node.caption or plain(node.url))
        return [f"{MEDIA_KIND_LABELS[node.kind]}: {self.runs.link(label, node.url)}"]

    def quote_lines(self, node: Quote) -> list[str]:
        parts = [self.block_text(line) for line in node.lines]
        if node.cite:
            parts.append(styled("italic", self.inline(node.cite)))
        return quoted(joined([[part] for part in parts]))

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
        return _Written.of(joined(sections), tail)

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
            case Media():
                return _Written.of(self.media_lines(node))
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
                    [*mermaid_fence_lines(node.figure), *spaced(supplement.lines)], supplement.tail
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
        return _Written(tuple(joined(rendered)), tail, opens_with_a_paragraph)

    def blocks(self, nodes: Sequence[Node]) -> list[str]:
        return list(self.blocks_after(nodes, None).lines)


def render_markdown(nodes: Sequence[Node]) -> str:
    return "\n".join(_MarkdownWriter(github_heading_slugs(nodes)).blocks(nodes)) + "\n"


def _cover_link(cover: str | None) -> tuple[Paragraph, ...]:
    return (Paragraph((Link(plain("Cover image"), cover),)),) if cover else ()


def render_markdown_document(document: LoweredDocument) -> str:
    title = plain(f"{document.icon} {document.title}" if document.icon else document.title)
    return render_markdown((Heading(1, title), *_cover_link(document.cover), *document.body))
