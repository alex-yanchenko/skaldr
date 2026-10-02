import re
import unicodedata
from collections import Counter
from collections.abc import Iterator, Mapping, Sequence
from typing import Final, Literal

from typing_extensions import assert_never

from skaldr.export.inline import plain
from skaldr.export.markup import (
    CALLOUT_ICON,
    MarkupRuns,
    body_cell_texts,
    code_block_lines,
    code_span,
    escape_block_start,
    indent_lines,
    styled,
    tab_icon,
)
from skaldr.export.mermaid import mermaid_fence_lines
from skaldr.export.runs import Chip, ExportRich, export_visible_text, write_export_runs
from skaldr.export.tree import (
    Callout,
    CodeBlock,
    Columns,
    Diagram,
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
from skaldr.models import ToneLiteral
from skaldr.richtext import SCRIPT_HTML_TAG, ScriptPosition

MARKDOWN_ESCAPES: Final = str.maketrans({character: "\\" + character for character in "\\*_`[]<>~$"})
ENTITY_LOOKALIKE = re.compile(r"&(?=#?\w+;)")
HEADING_CLOSING_RUN = re.compile(r"(?:(?<=\s)|^)(#+\s*)$")
MarkerFamily = Literal["dash", "ordinal"]
MARKER_FAMILY: Final[Mapping[ListKind, MarkerFamily]] = {
    "bullet": "dash",
    "check": "dash",
    "number": "ordinal",
}


def _dash(use_alternate_markers: bool) -> str:
    return "*" if use_alternate_markers else "-"


def _kept_in_a_github_slug(character: str) -> bool:
    category = unicodedata.category(character)
    return character in " -" or category[0] in "LMN" or category == "Pc"


def github_slug(text: str) -> str:
    return "".join(filter(_kept_in_a_github_slug, text.lower())).replace(" ", "-")


class _MarkdownRuns(MarkupRuns):
    def __init__(self, heading_slugs: Mapping[str, str]) -> None:
        self.heading_slugs = heading_slugs

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
        return styled("bold", self.escape(run.label))

    def underline(self, inner: str, /) -> str:
        return f"<ins>{inner}</ins>"

    def script(self, position: ScriptPosition, text: str, /) -> str:
        tag = SCRIPT_HTML_TAG[position]
        return f"<{tag}>{self.escape(text)}</{tag}>"

    def tinted(self, _tone: ToneLiteral | None, _background: ToneLiteral | None, inner: str, /) -> str:
        return inner


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


def _marker_family(node: Node) -> MarkerFamily | None:
    if isinstance(node, ListNode):
        return MARKER_FAMILY[node.kind]
    return "dash" if isinstance(node, TableOfContents) else None


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
        return write_export_runs(runs, self.runs)

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
        for index, entry in enumerate(node.entries, start=1):
            match node.kind:
                case "bullet":
                    marker, width = dash, len(dash) + 1
                case "number":
                    marker = f"{index}{')' if use_alternate_markers else '.'}"
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

    def titled(self, title: str, children: Sequence[Node]) -> list[str]:
        return [title, *_spaced(self.blocks(children))]

    def callout_lines(self, node: Callout) -> list[str]:
        icon = CALLOUT_ICON[node.tone]
        lines = self.blocks(node.children)
        if lines and isinstance(node.children[0], Paragraph):
            lines[0] = f"{icon} {lines[0]}"
        else:
            lines = [icon, *_spaced(lines)]
        return _quoted(lines)

    def quote_lines(self, node: Quote) -> list[str]:
        parts = [self.block_text(line) for line in node.lines]
        if node.cite:
            parts.append(styled("italic", self.inline(node.cite)))
        return _quoted(_joined([[part] for part in parts]))

    def tabs_lines(self, node: Tabs) -> list[str]:
        sections: list[list[str]] = []
        for tab in node.tabs:
            icon = tab_icon(tab.tone)
            title = self.inline(tab.title)
            sections.append(self.titled(styled("bold", f"{icon} {title}" if icon else title), tab.children))
        return _joined(sections)

    def toc_lines(self, node: TableOfContents, use_alternate_markers: bool) -> list[str]:
        dash = _dash(use_alternate_markers)
        entries = [
            (self.runs.heading_slugs.get(entry.anchor), self.inline(entry.title)) for entry in node.entries
        ]
        return [f"{dash} [{title}](#{slug})" if slug else f"{dash} {title}" for slug, title in entries]

    def lines(self, node: Node, use_alternate_markers: bool = False) -> list[str]:
        match node:
            case Heading():
                return [self.heading_line(node.level, node.text)]
            case Paragraph():
                text = self.block_text(node.text)
                return [text] if text else []
            case ListNode():
                return self.list_lines(node, use_alternate_markers)
            case TableNode():
                return self.table_lines(node)
            case CodeBlock():
                return code_block_lines(node)
            case Callout():
                return self.callout_lines(node)
            case Quote():
                return self.quote_lines(node)
            case Toggle():
                if node.heading_level is not None:
                    return self.titled(self.heading_line(node.heading_level, node.title), node.children)
                return self.titled(styled("bold", self.inline(node.title)), node.children)
            case Columns():
                return self.blocks(nested_nodes(node))
            case Tabs():
                return self.tabs_lines(node)
            case Diagram():
                return [*mermaid_fence_lines(node.figure), *_spaced(self.blocks(node.supplement))]
            case TableOfContents():
                return self.toc_lines(node, use_alternate_markers)
            case _:
                assert_never(node)

    def blocks(self, nodes: Sequence[Node]) -> list[str]:
        rendered: list[list[str]] = []
        previous_family: MarkerFamily | None = None
        use_alternate_markers = False
        for node in nodes:
            family = _marker_family(node)
            alternate = family is not None and family == previous_family and not use_alternate_markers
            lines = self.lines(node, alternate)
            if lines:
                rendered.append(lines)
                previous_family, use_alternate_markers = family, alternate
        return _joined(rendered)


def render_markdown(nodes: Sequence[Node]) -> str:
    return "\n".join(_MarkdownWriter(github_heading_slugs(nodes)).blocks(nodes)) + "\n"


def render_markdown_document(document: LoweredDocument) -> str:
    return render_markdown((Heading(1, plain(document.title)), *document.body))
