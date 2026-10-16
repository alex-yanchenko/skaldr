import html
import unicodedata
from collections import Counter
from collections.abc import Generator, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from typing import Final, Literal, NoReturn

from typing_extensions import assert_never

from skaldr.errors import ExportInvariantError
from skaldr.export.folds import folded, folded_except
from skaldr.export.github_html import HtmlRuns, date_tag, details_lines
from skaldr.export.glyphs import callout_icon, tab_title_led_by_its_icon
from skaldr.export.inline import one_line, plain
from skaldr.export.lower.context import joined_by_breaks, toned
from skaldr.export.markup import (
    DIVIDER_LINE,
    ENTITY_LOOKALIKE,
    HTML_LINE_BREAK,
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
    wrap_around_core,
)
from skaldr.export.mermaid import mermaid_fence_lines
from skaldr.export.runs import Chip, ExportRich, export_visible_text
from skaldr.export.swaps import data_table_swapped_in, figure_mermaid_draws, swaps_the_figure, web_address_of
from skaldr.export.tree import (
    Callout,
    Card,
    Cards,
    CodeBlock,
    Columns,
    DefinitionList,
    Diagram,
    DisplayMath,
    Divider,
    FactStrip,
    GridColumn,
    Heading,
    HeadingLevel,
    KeyValueList,
    LinkCard,
    ListEntry,
    ListKind,
    ListNode,
    LoweredDocument,
    Media,
    Node,
    Paragraph,
    Quote,
    ReferenceEntry,
    References,
    TableCell,
    TableNode,
    TableOfContents,
    TableRow,
    Tabs,
    TextNumbering,
    Timeline,
    Toggle,
    ToneName,
    heading_of,
    nested_nodes,
)
from skaldr.models import MEDIA_KIND_LABELS
from skaldr.richtext import SCRIPT_HTML_TAG, Citation, MarkerStyle, ScriptPosition

OTHER_ALPHABETIC_SYMBOL_RANGES: Final = (
    range(0x24D0, 0x24EA),
    range(0x1F130, 0x1F14A),
    range(0x1F150, 0x1F16A),
    range(0x1F170, 0x1F18A),
)
MARKDOWN_ESCAPES: Final = str.maketrans({character: "\\" + character for character in "\\*_`[]<>~$"})
GITHUB_ALERT_TYPE: Final[Mapping[ToneName, str]] = {
    "info": "NOTE",
    "sky": "NOTE",
    "neutral": "NOTE",
    "muted": "NOTE",
    "success": "TIP",
    "teal": "TIP",
    "warning": "WARNING",
    "danger": "CAUTION",
    "accent": "IMPORTANT",
}
ORDERED_LIST_TYPE: Final[Mapping[TextNumbering, str]] = {"letters": "a", "roman": "i"}
MOST_COLUMNS_THAT_KEEP_THEIR_WIDTH: Final = 3
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


def _refuse_a_block_a_cell_cannot_hold(node: Node) -> NoReturn:
    raise ExportInvariantError(
        "a table cell holds only paragraphs and lists, "
        f"not a {type(node).__name__}; the lowering should not have put one there"
    )


class _MarkdownRuns(CommonMarkRuns):
    def __init__(self, heading_slugs: Mapping[str, str], footnotes: frozenset[int]) -> None:
        self.heading_slugs = heading_slugs
        self.footnotes = footnotes
        self.cited: set[int] = set()

    def heading_slug(self, anchor: str, /) -> str | None:
        return self.heading_slugs.get(anchor)

    def citation(self, run: Citation, /) -> str:
        self.cited.add(run.number)
        if run.number in self.footnotes:
            return f"[^{run.number}]"
        return super().citation(run)

    def unflanked_emphasis(self, style: MarkerStyle, inner: str, /) -> str:
        return styled_in_tags(style, inner)

    def refuse_a_tint(self) -> NoReturn:
        raise ExportInvariantError(
            "GitHub Markdown cannot colour or highlight text; the export check should have refused it"
        )

    def require_links_to_its_own_headings(self) -> None:
        return

    def highlighted(self, inner: str, /) -> str | None:
        return wrap_around_core(inner, "<mark>", "</mark>")

    def escape(self, text: str, /) -> str:
        return ENTITY_LOOKALIKE.sub(r"\\&", text.translate(MARKDOWN_ESCAPES))

    def date_mention(self, label: str, start: date, end: date | None, /) -> str:
        return date_tag(label, start, end)

    def document_link(self, label: str, doc_id: str, _section: str | None, /) -> str:
        return self.link(label, f"{doc_id}.md")

    def write_cell(self, tones: Sequence[ToneName], cell: TableCell) -> str:
        if not cell.blocks:
            return super().write_cell(tones, cell)
        dots = self.tone_dots(tones, ())
        parts = [part for part in self._cell_parts(cell.blocks, tones) if part]
        content = HTML_LINE_BREAK.join(parts)
        return " ".join([*dots, content] if content else dots)

    def _cell_parts(self, blocks: Sequence[Node], tones: Sequence[ToneName]) -> Iterator[str]:
        for node in folded(blocks):
            match node:
                case Paragraph():
                    yield self.write_struck_if_muted(tones, node.text)
                case ListNode():
                    yield self._html_list(node, tones)
                case _:
                    _refuse_a_block_a_cell_cannot_hold(node)

    def _html_list(self, node: ListNode, tones: Sequence[ToneName]) -> str:
        tag = "ol" if node.kind == "number" else "ul"
        start = f' start="{node.start}"' if node.kind == "number" and node.start != 1 else ""
        items = "".join(f"<li>{self._html_item(entry, tones)}</li>" for entry in node.entries)
        return f"<{tag}{start}>{items}</{tag}>"

    def _html_item(self, entry: ListEntry, tones: Sequence[ToneName]) -> str:
        content = self.write_struck_if_muted(tones, entry.text)
        for child in folded(entry.children):
            match child:
                case ListNode():
                    content += self._html_list(child, tones)
                case Paragraph():
                    content += HTML_LINE_BREAK + self.write_struck_if_muted(tones, child.text)
                case _:
                    _refuse_a_block_a_cell_cannot_hold(child)
        return content

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


def _is_written_natively(node: Node) -> bool:
    match node:
        case Toggle():
            return node.open
        case ListNode():
            return node.numbering is not None
        case FactStrip() | Cards() | DefinitionList() | References():
            return True
        case _:
            return False


def _holds_a_table_or_a_tone(column: GridColumn) -> bool:
    return any(
        isinstance(child, TableNode) or (isinstance(child, Callout) and child.authored_as == "grid cell")
        for child in column.children
    )


def _cell_widths(node: Columns) -> list[int | None]:
    sized = len(node.columns) <= MOST_COLUMNS_THAT_KEEP_THEIR_WIDTH and not any(
        map(_holds_a_table_or_a_tone, node.columns)
    )
    return [column.ratio if sized else None for column in node.columns]


def _label_text(label: str | None) -> str:
    return one_line(label or "").removesuffix(":").rstrip()


def _card_header(card: Card) -> ExportRich:
    if card.badge is not None:
        return (Chip.on_one_line(card.label or "", card.badge),)
    return toned(card.tone, plain(_label_text(card.label)))


def _card_value(card: Card) -> ExportRich:
    return joined_by_breaks([card.value, plain(card.note)])


def _is_a_markdown_list(node: Node) -> bool:
    return (isinstance(node, ListNode) and node.numbering is None) or isinstance(node, References)


def _marker_family(node: Node) -> MarkerFamily | None:
    if isinstance(node, ListNode):
        return MARKER_FAMILY[node.kind]
    return "dash" if isinstance(node, TableOfContents) else None


def _must_alternate_markers(family: MarkerFamily | None, after: _ListTail | None) -> bool:
    return family is not None and after is not None and after.family == family and not after.alternated


class _MarkdownWriter:
    def __init__(self, heading_slugs: Mapping[str, str], footnotes: frozenset[int]) -> None:
        self.runs = _MarkdownRuns(heading_slugs, footnotes)
        self.html = HtmlRuns(heading_slugs)
        self.container_depth = 0
        self.html_block_depth = 0
        self.defined_footnotes: set[int] = set()

    def inline(self, runs: ExportRich) -> str:
        return self.runs.write(runs)

    def block_text(self, runs: ExportRich) -> str:
        return escape_block_start(self.inline(runs))

    def heading_line(self, level: HeadingLevel, runs: ExportRich) -> str:
        return heading_line(level, self.inline(runs))

    def table_lines(self, table: TableNode) -> list[str]:
        return pipe_table_lines(table, self.runs)

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
        nodes = folded_except(entry.children, _is_written_natively)
        with self.inside_a_container():
            children = self.blocks(nodes)
        if not children:
            return []
        gap = [] if after_a_bare_marker or _is_a_markdown_list(nodes[0]) else [""]
        return gap + indent_lines(children, " " * width)

    def titled(self, title: str, children: Sequence[Node], after: _ListTail | None) -> _Written:
        if not title:
            return self.blocks_after(children, after)
        body = self.blocks_after(children, None)
        return _Written.of([title, *spaced(body.lines)], body.tail)

    @contextmanager
    def inside_a_container(self) -> Generator[None]:
        self.container_depth += 1
        try:
            yield
        finally:
            self.container_depth -= 1

    @contextmanager
    def inside_an_html_block(self) -> Generator[None]:
        self.html_block_depth += 1
        try:
            yield
        finally:
            self.html_block_depth -= 1

    def is_at_the_top_level(self) -> bool:
        return self.container_depth == 0 and self.html_block_depth == 0

    def is_an_alert(self, node: Callout) -> bool:
        return node.shows_icon and node.authored_as != "grid cell" and self.container_depth == 0

    def callout_lines(self, node: Callout) -> list[str]:
        alert = self.is_an_alert(node)
        icon = node.icon if alert else callout_icon(node)
        with self.inside_a_container():
            body = self.blocks_after(node.children, None)
        lines = list(body.lines)
        if icon is not None:
            if lines and body.opens_with_a_paragraph:
                lines[0] = f"{icon} {lines[0]}"
            else:
                lines = [icon, *spaced(lines)]
        if alert:
            opens_with_a_paragraph = icon is not None or body.opens_with_a_paragraph
            lines = [
                f"[!{GITHUB_ALERT_TYPE[node.tone]}]",
                *(lines if opens_with_a_paragraph else spaced(lines)),
            ]
        return quoted(lines)

    def media_lines(self, node: Media) -> list[str]:
        url = web_address_of(node, "markdown")
        if node.kind == "image":
            image = f"![{self.inline(node.description)}]({encode_url(url)})"
            caption = [styled("italic", self.inline(node.caption))] if node.caption else []
            return joined([[image], caption])
        label = self.inline(node.caption or plain(url))
        return [f"{MEDIA_KIND_LABELS[node.kind]}: {self.runs.link(label, url)}"]

    def quote_lines(self, node: Quote) -> list[str]:
        with self.inside_a_container():
            body = self.blocks(node.body)
        cite = [styled("italic", self.inline(node.cite))] if node.cite else []
        return quoted(joined([body, cite]))

    def columns_lines(self, node: Columns) -> list[str]:
        cells: list[list[str]] = []
        for column in node.columns:
            with self.inside_a_container(), self.inside_an_html_block():
                cells.append(self.blocks(column.children))
        if not any(cells):
            return []
        sizes = _cell_widths(node)
        lines = ["<table>", "<tr>"]
        for width, body in zip(sizes, cells, strict=True):
            opening = f'<td width="{width}%">' if width is not None else "<td>"
            lines += [opening, "", *body, "", "</td>"] if body else [f"{opening}</td>"]
        return [*lines, "</tr>", "</table>"]

    def fact_strip_lines(self, node: FactStrip) -> list[str]:
        header = tuple(TableCell(plain(_label_text(fact.label))) for fact in node.facts)
        row = TableRow(tuple(TableCell(fact.value) for fact in node.facts))
        return self.table_lines(TableNode(header, (row,))) if node.facts else []

    def cards_lines(self, node: Cards) -> list[str]:
        header = tuple(TableCell(_card_header(card)) for card in node.cards)
        row = TableRow(tuple(TableCell(_card_value(card)) for card in node.cards))
        return self.table_lines(TableNode(header, (row,))) if node.cards else []

    def definition_list_lines(self, node: DefinitionList) -> list[str]:
        lines = ["<dl>"]
        for definition in node.definitions:
            lines.append(f"<dt>{html.escape(_label_text(definition.term), quote=False)}</dt>")
            with self.inside_a_container(), self.inside_an_html_block():
                body = self.blocks(definition.body)
            lines += ["<dd>", "", *body, "", "</dd>"] if body else ["<dd></dd>"]
        return [*lines, "</dl>"]

    def ordered_html_lines(self, node: ListNode, numbering: TextNumbering) -> list[str]:
        start = f' start="{node.start}"' if node.start != 1 else ""
        lines = [f'<ol type="{ORDERED_LIST_TYPE[numbering]}"{start}>']
        for entry in node.entries:
            text = self.block_text(entry.text)
            with self.inside_a_container(), self.inside_an_html_block():
                children = self.blocks(entry.children)
            content = joined([[text] if text else [], children])
            lines += ["<li>", "", *content, "", "</li>"] if content else ["<li></li>"]
        return [*lines, "</ol>"]

    def details_written(
        self, title: ExportRich, children: Sequence[Node], after: _ListTail | None, *, opened: bool
    ) -> _Written:
        summary = self.html.write(title)
        if not summary.strip():
            return self.blocks_after(children, after)
        with self.inside_an_html_block():
            body = self.blocks_after(children, None)
        return _Written.of(details_lines(summary, body.lines, opened=opened))

    def references_written(self, node: References, after: _ListTail | None) -> _Written:
        if not self.is_at_the_top_level():
            return self.written(folded((node,))[0], after)
        self.defined_footnotes.update(entry.number for entry in node.entries)
        cited = [entry for entry in node.entries if entry.number in self.runs.footnotes]
        uncited = References(tuple(entry for entry in node.entries if entry not in cited))
        definitions = [f"[^{entry.number}]: {self.reference_text(entry)}" for entry in cited]
        if not uncited.entries:
            return _Written.of(definitions)
        bullets = self.written(folded((uncited,))[0], after)
        return _Written.of(joined([definitions, bullets.lines]), bullets.tail)

    def reference_text(self, entry: ReferenceEntry) -> str:
        source = [self.runs.link("source", entry.url)] if entry.url else []
        return " ".join([self.inline(entry.text), *source])

    def tabs_written(self, node: Tabs, after: _ListTail | None) -> _Written:
        sections: list[Sequence[str]] = []
        tail = after
        for index, tab in enumerate(node.tabs):
            section = self.details_written(
                tab_title_led_by_its_icon(tab), tab.children, tail, opened=index == 0
            )
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
            case ListNode() if node.numbering is not None:
                return _Written.of(self.ordered_html_lines(node, node.numbering))
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
                return self.details_written(node.title, node.children, after, opened=node.open)
            case Columns():
                return _Written.of(self.columns_lines(node))
            case Tabs():
                return self.tabs_written(node, after)
            case Diagram() if swaps_the_figure(node, "markdown"):
                table = self.blocks_after(data_table_swapped_in(node, "markdown"), after)
                return _Written.of(table.lines, table.tail)
            case Diagram():
                supplement = self.blocks_after(node.supplement, None)
                return _Written.of(
                    [*mermaid_fence_lines(figure_mermaid_draws(node, "markdown")), *spaced(supplement.lines)],
                    supplement.tail,
                )
            case TableOfContents():
                return _Written.of(self.toc_lines(node, alternate), _ListTail("dash", alternate))
            case FactStrip():
                return _Written.of(self.fact_strip_lines(node))
            case Cards():
                return _Written.of(self.cards_lines(node))
            case DefinitionList():
                return _Written.of(self.definition_list_lines(node))
            case References():
                return self.references_written(node, after)
            case KeyValueList() | Timeline() | LinkCard():
                raise ExportInvariantError(
                    f"the GitHub writer folds a {type(node).__name__} before it writes it"
                )
            case _:
                assert_never(node)

    def blocks_after(self, nodes: Sequence[Node], after: _ListTail | None) -> _Written:
        rendered: list[Sequence[str]] = []
        tail = after
        opens_with_a_paragraph = False
        for node in folded_except(nodes, _is_written_natively):
            written = self.written(node, tail)
            if written.lines:
                opens_with_a_paragraph = opens_with_a_paragraph if rendered else isinstance(node, Paragraph)
                rendered.append(written.lines)
                tail = written.tail
        return _Written(tuple(joined(rendered)), tail, opens_with_a_paragraph)

    def blocks(self, nodes: Sequence[Node]) -> list[str]:
        return list(self.blocks_after(nodes, None).lines)


def render_markdown(nodes: Sequence[Node]) -> str:
    slugs = github_heading_slugs(nodes)
    survey = _MarkdownWriter(slugs, frozenset())
    lines = survey.blocks(nodes)
    footnotes = survey.defined_footnotes & survey.runs.cited
    if footnotes:
        lines = _MarkdownWriter(slugs, frozenset(footnotes)).blocks(nodes)
    return "\n".join(lines) + "\n"


def _cover_image(cover: str | None) -> tuple[Media, ...]:
    return (Media("image", cover, plain("Cover")),) if cover else ()


def render_markdown_document(document: LoweredDocument) -> str:
    title = plain(f"{document.icon} {document.title}" if document.icon else document.title)
    return render_markdown((Heading(1, title), *_cover_image(document.cover), *document.body))
