import re
from collections.abc import Iterator, Sequence

from typing_extensions import assert_never

from skaldr.export.inline import (
    AnchorLink,
    Break,
    Chip,
    Citation,
    Code,
    Link,
    Placeholder,
    Plain,
    Rich,
    Styled,
    visible_text,
)
from skaldr.export.markup import CALLOUT_ICON, STYLE_MARKER, TAB_ICON, code_fence, indent_lines, wrap_marker
from skaldr.export.tree import (
    Callout,
    CodeBlock,
    Columns,
    Diagram,
    Divider,
    Heading,
    Image,
    ListEntry,
    ListNode,
    Node,
    Paragraph,
    Quote,
    Table,
    TableCell,
    TableOfContents,
    Tabs,
    Toggle,
)

MARKDOWN_ESCAPED = frozenset("\\*_`[]<>~")
BLOCK_START_MARKER = re.compile(r"^(#{1,6}|[-+]+|=+)(?=\s|$)")
ORDERED_START_MARKER = re.compile(r"^(\d{1,9})([.)])(?=\s|$)")
HEADING_CLOSING_RUN = re.compile(r"(?<=\s)(#+\s*)$")
URL_NEEDING_BRACKETS = re.compile(r"[\s()]")
GITHUB_SLUG_DROPPED = re.compile(r"[^\w\- ]")
TOC_DEEPEST_LEVEL = 3


def escape_markdown_text(text: str) -> str:
    return "".join("\\" + character if character in MARKDOWN_ESCAPED else character for character in text)


def code_span(text: str) -> str:
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    ticks = "`" * (longest + 1)
    padding = " " if text.startswith("`") or text.endswith("`") else ""
    return f"{ticks}{padding}{text}{padding}{ticks}"


def _link_target(url: str) -> str:
    return f"<{url}>" if URL_NEEDING_BRACKETS.search(url) else url


def markdown_inline(runs: Rich) -> str:
    out: list[str] = []
    for run in runs:
        match run:
            case Plain():
                out.append(escape_markdown_text(run.text))
            case Code():
                out.append(code_span(run.text))
            case Link():
                out.append(f"[{markdown_inline(run.label)}]({_link_target(run.url)})")
            case AnchorLink():
                out.append(markdown_inline(run.label))
            case Citation():
                label = escape_markdown_text(f"[{run.number}]")
                out.append(f"[{label}]({_link_target(run.url)})" if run.url else label)
            case Placeholder():
                out.append(code_span("{{" + run.name + "}}"))
            case Chip():
                out.append(wrap_marker(STYLE_MARKER["bold"], escape_markdown_text(run.label)))
            case Break():
                out.append("<br>")
            case Styled():
                out.append(wrap_marker(STYLE_MARKER[run.style], markdown_inline(run.runs)))
            case _:
                assert_never(run)
    return "".join(out)


def _block_text(runs: Rich) -> str:
    text = markdown_inline(runs)
    text = BLOCK_START_MARKER.sub(lambda match: "\\" + match.group(1), text)
    return ORDERED_START_MARKER.sub(lambda match: match.group(1) + "\\" + match.group(2), text)


def _heading_line(level: int, runs: Rich) -> str:
    text = HEADING_CLOSING_RUN.sub(lambda match: "\\" + match.group(1), markdown_inline(runs))
    return f"{'#' * max(1, min(level, 6))} {text}"


def _cell_text(cell: TableCell) -> str:
    return markdown_inline(cell.text).replace("|", "\\|")


def _table_row(cells: Sequence[str]) -> str:
    return "| " + " | ".join(cells) + " |"


def _table_lines(table: Table) -> list[str]:
    width = max([len(table.header), *(len(row.cells) for row in table.rows)])
    header = [_cell_text(cell) for cell in table.header]
    lines = [_table_row(header + [""] * (width - len(header))), _table_row(["---"] * width)]
    for row in table.rows:
        cells = [_cell_text(cell) for cell in row.cells]
        if row.emphasis == "total":
            cells = [
                wrap_marker(STYLE_MARKER["bold"], text) if not text.startswith("**") else text
                for text in cells
            ]
        lines.append(_table_row(cells + [""] * (width - len(cells))))
    return lines


def _list_lines(node: ListNode, alternate: bool) -> list[str]:
    bullet = "*" if alternate else "-"
    lines: list[str] = []
    for index, entry in enumerate(node.entries, start=1):
        match node.kind:
            case "bullet":
                marker, width = bullet, len(bullet) + 1
            case "number":
                marker = f"{index}{')' if alternate else '.'}"
                width = len(marker) + 1
            case "check":
                marker, width = f"{bullet} [{'x' if entry.checked else ' '}]", len(bullet) + 1
            case _:
                assert_never(node.kind)
        lines.append(f"{marker} {_block_text(entry.text)}".rstrip())
        lines += _entry_children(entry, width)
    return lines


def _entry_children(entry: ListEntry, width: int) -> list[str]:
    children = markdown_blocks(entry.children)
    if not children:
        return []
    gap = [] if isinstance(entry.children[0], ListNode) else [""]
    return gap + indent_lines(children, " " * width)


def _quoted(lines: Sequence[str]) -> list[str]:
    return [f"> {line}" if line else ">" for line in lines]


def _callout_lines(node: Callout) -> list[str]:
    icon = CALLOUT_ICON[node.tone]
    lines = markdown_blocks(node.children)
    if lines and isinstance(node.children[0], Paragraph):
        lines[0] = f"{icon} {lines[0]}"
    else:
        lines = [icon, "", *lines] if lines else [icon]
    return _quoted(lines)


def _titled(title: str, children: Sequence[Node]) -> list[str]:
    body = markdown_blocks(children)
    return [title, "", *body] if body else [title]


def markdown_lines(node: Node, alternate: bool = False) -> list[str]:
    match node:
        case Heading():
            return [_heading_line(node.level, node.text)]
        case Paragraph():
            text = _block_text(node.text)
            return [text] if text else []
        case ListNode():
            return _list_lines(node, alternate)
        case Table():
            return _table_lines(node)
        case CodeBlock():
            fence = code_fence(node.content)
            return [f"{fence}{node.language}", *node.content.split("\n"), fence]
        case Callout():
            return _callout_lines(node)
        case Quote():
            lines: list[str] = []
            for line in node.lines:
                lines += ["", markdown_inline(line)] if lines else [markdown_inline(line)]
            if node.cite:
                lines += ["", wrap_marker(STYLE_MARKER["italic"], markdown_inline(node.cite))]
            return _quoted(lines)
        case Divider():
            return ["---"]
        case Toggle():
            if node.heading_level is not None:
                return _titled(_heading_line(node.heading_level, node.title), node.children)
            return _titled(wrap_marker(STYLE_MARKER["bold"], markdown_inline(node.title)), node.children)
        case Columns():
            return markdown_blocks([child for column in node.columns for child in column.children])
        case Tabs():
            lines = []
            for tab in node.tabs:
                icon = TAB_ICON.get(tab.tone or "")
                title = markdown_inline(tab.title)
                heading = wrap_marker(STYLE_MARKER["bold"], f"{icon} {title}" if icon else title)
                lines += ["", *_titled(heading, tab.children)] if lines else _titled(heading, tab.children)
            return lines
        case Diagram():
            return [
                "```mermaid",
                *node.mermaid.split("\n"),
                "```",
                *_spaced(markdown_blocks(node.supplement)),
            ]
        case Image():
            alt = escape_markdown_text(visible_text(node.caption))
            caption = markdown_inline(node.caption)
            return [
                f"![{alt}]({_link_target(node.url)})",
                *_spaced([wrap_marker("*", caption)] if caption else []),
            ]
        case TableOfContents():
            return []
        case _:
            assert_never(node)


def _spaced(lines: list[str]) -> list[str]:
    return ["", *lines] if lines else []


def markdown_blocks(nodes: Sequence[Node]) -> list[str]:
    out: list[str] = []
    previous: Node | None = None
    alternate = False
    for node in nodes:
        if isinstance(node, ListNode):
            alternate = (
                (not alternate) if isinstance(previous, ListNode) and previous.kind == node.kind else False
            )
        lines = markdown_lines(node, alternate)
        previous = node
        if not lines:
            continue
        if out:
            out.append("")
        out += lines
    return out


def _headings(nodes: Sequence[Node]) -> Iterator[tuple[int, Rich]]:
    for node in nodes:
        match node:
            case Heading():
                yield node.level, node.text
            case Toggle():
                if node.heading_level is not None:
                    yield node.heading_level, node.title
                yield from _headings(node.children)
            case Callout():
                yield from _headings(node.children)
            case ListNode():
                yield from _headings([child for entry in node.entries for child in entry.children])
            case Columns():
                yield from _headings([child for column in node.columns for child in column.children])
            case Tabs():
                yield from _headings([child for tab in node.tabs for child in tab.children])
            case _:
                pass


def github_slug(text: str) -> str:
    return GITHUB_SLUG_DROPPED.sub("", text.lower()).replace(" ", "-")


def _toc_link(text: Rich, slug: str) -> ListEntry:
    label = tuple(run for run in text if isinstance(run, (Plain, Code)))
    return ListEntry((Link(label, f"#{slug}"),))


def _table_of_contents(nodes: Sequence[Node]) -> ListNode:
    seen: dict[str, int] = {}
    linked: list[tuple[int, ListEntry]] = []
    for level, text in _headings(nodes):
        base = github_slug(visible_text(text))
        count = seen.get(base, 0)
        seen[base] = count + 1
        if 1 < level <= TOC_DEEPEST_LEVEL:
            linked.append((level, _toc_link(text, f"{base}-{count}" if count else base)))
    shallowest = min((level for level, _ in linked), default=0)
    tops: list[tuple[ListEntry, list[ListEntry]]] = []
    for level, entry in linked:
        if level == shallowest or not tops:
            tops.append((entry, []))
        else:
            tops[-1][1].append(entry)
    return ListNode(
        "bullet",
        tuple(
            ListEntry(top.text, children=(ListNode("bullet", tuple(nested)),) if nested else ())
            for top, nested in tops
        ),
    )


def _with_table_of_contents(nodes: Sequence[Node]) -> list[Node]:
    toc = _table_of_contents(nodes)
    placed: list[Node] = []
    for node in nodes:
        if not isinstance(node, TableOfContents):
            placed.append(node)
        elif toc.entries:
            placed.append(toc)
    return placed


def render_markdown(nodes: Sequence[Node]) -> str:
    return "\n".join(markdown_blocks(_with_table_of_contents(nodes))) + "\n"
