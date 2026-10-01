import re
from collections import Counter
from collections.abc import Iterator, Mapping, Sequence
from typing import Literal

from typing_extensions import assert_never

from skaldr.export.inline import plain
from skaldr.export.markup import (
    CALLOUT_ICON,
    MarkupRuns,
    code_block_lines,
    code_span,
    escape_block_start,
    indent_lines,
    styled,
)
from skaldr.export.tree import (
    Callout,
    CodeBlock,
    Heading,
    ListEntry,
    ListKind,
    ListNode,
    LoweredDocument,
    Node,
    Paragraph,
    Quote,
    TableOfContents,
    Toggle,
    nested_nodes,
)
from skaldr.richtext import Rich, visible_text, write_runs

MARKDOWN_ESCAPED = frozenset("\\*_`[]<>~")
ENTITY_LOOKALIKE = re.compile(r"&(?=#?\w+;)")
HEADING_CLOSING_RUN = re.compile(r"(?:(?<=\s)|^)(#+\s*)$")
GITHUB_SLUG_DROPPED = re.compile(r"[^\w\- ]")
MarkerFamily = Literal["dash", "ordinal"]
MARKER_FAMILY: dict[ListKind, MarkerFamily] = {"bullet": "dash", "check": "dash", "number": "ordinal"}


def _escape(text: str) -> str:
    escaped = "".join("\\" + character if character in MARKDOWN_ESCAPED else character for character in text)
    return ENTITY_LOOKALIKE.sub(r"\\&", escaped)


def github_slug(text: str) -> str:
    return GITHUB_SLUG_DROPPED.sub("", text.lower()).replace(" ", "-")


class _MarkdownRuns(MarkupRuns):
    def __init__(self, heading_slugs: Mapping[str, str]) -> None:
        super().__init__(_escape)
        self.heading_slugs = heading_slugs

    def code(self, text: str, /) -> str:
        return code_span(text)

    def anchor_link(self, label: str, anchor: str, /) -> str:
        slug = self.heading_slugs.get(anchor)
        return f"[{label}](#{slug})" if slug else label

    def placeholder(self, name: str, /) -> str:
        return code_span("{{" + name + "}}")


def _headings(nodes: Sequence[Node]) -> Iterator[tuple[str | None, Rich]]:
    for node in nodes:
        if isinstance(node, Heading):
            yield node.anchor, node.text
        elif isinstance(node, Toggle) and node.heading_level is not None:
            yield node.anchor, node.title
        yield from _headings(nested_nodes(node))


def github_heading_slugs(nodes: Sequence[Node]) -> dict[str, str]:
    repeats: Counter[str] = Counter()
    taken: set[str] = set()
    slugs: dict[str, str] = {}
    for anchor, text in _headings(nodes):
        base = slug = github_slug(visible_text(text))
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


def _joined(sections: Sequence[Sequence[str]]) -> list[str]:
    out: list[str] = []
    for lines in sections:
        if lines:
            out += ["", *lines] if out else lines
    return out


class _MarkdownWriter:
    def __init__(self, heading_slugs: Mapping[str, str]) -> None:
        self.runs = _MarkdownRuns(heading_slugs)

    def inline(self, runs: Rich) -> str:
        return write_runs(runs, self.runs)

    def block_text(self, runs: Rich) -> str:
        return escape_block_start(self.inline(runs))

    def heading_line(self, level: int, runs: Rich) -> str:
        text = HEADING_CLOSING_RUN.sub(lambda match: "\\" + match.group(1), self.inline(runs))
        return f"{'#' * level} {text}"

    def list_lines(self, node: ListNode, use_alternate_markers: bool) -> list[str]:
        dash = "*" if use_alternate_markers else "-"
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
            lines.append(f"{marker} {self.block_text(entry.text)}".rstrip())
            lines += self.entry_children(entry, width)
        return lines

    def entry_children(self, entry: ListEntry, width: int) -> list[str]:
        children = self.blocks(entry.children)
        if not children:
            return []
        gap = [] if isinstance(entry.children[0], ListNode) else [""]
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

    def toc_lines(self, node: TableOfContents, use_alternate_markers: bool) -> list[str]:
        dash = "*" if use_alternate_markers else "-"
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
