import re
from collections.abc import Sequence
from dataclasses import dataclass

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
)
from skaldr.export.tree import (
    Callout,
    CodeBlock,
    Columns,
    Diagram,
    Divider,
    Heading,
    Image,
    ListNode,
    Node,
    Paragraph,
    Quote,
    Table,
    TableCell,
    TableOfContents,
    Tabs,
    Toggle,
    ToneName,
)

NOTION_ESCAPED = frozenset("\\*~`$[]<>{}|^")
NOTION_WEB_DOMAIN_FILE = re.compile(r"(?<![\w/.-])([\w./-]*\w\.(?:md|py|sh)(?::\d+(?:-\d+)?)?)(?![\w`])")
TABLE_CELL_LIST_MARKER = re.compile(r"^([-+*]|\d+\.)(\s)")
BLOCK_COLOR: dict[str, str] = {
    "neutral": "gray",
    "muted": "gray",
    "info": "blue",
    "success": "green",
    "warning": "yellow",
    "danger": "red",
    "accent": "purple",
    "teal": "green",
    "sky": "blue",
}
CHIP_COLOR: dict[str, str] = {
    "slate": "gray",
    "blue": "blue",
    "green": "green",
    "amber": "yellow",
    "red": "red",
    "violet": "purple",
    "teal": "green",
    "sky": "blue",
}
CALLOUT_ICON: dict[str, str] = {
    "info": "💡",
    "success": "✅",
    "warning": "⚠️",
    "danger": "🛑",
    "accent": "📌",
    "neutral": "📝",
    "muted": "📝",
    "teal": "💡",
    "sky": "💡",
}
TAB_ICON: dict[str, str] = {"success": "✅", "info": "🔵", "warning": "⚠️", "danger": "🛑"}


def escape_notion_text(text: str) -> str:
    return "".join("\\" + character if character in NOTION_ESCAPED else character for character in text)


def _plain_text(text: str) -> str:
    pieces = NOTION_WEB_DOMAIN_FILE.split(text)
    return "".join(
        f"`{piece}`" if index % 2 else escape_notion_text(piece) for index, piece in enumerate(pieces)
    )


def _wrap(marker: str, inner: str) -> str:
    core = inner.strip()
    if not core:
        return inner
    lead = inner[: len(inner) - len(inner.lstrip())]
    trail = inner[len(inner.rstrip()) :]
    return f"{lead}{marker}{core}{marker}{trail}"


def notion_inline(runs: Rich) -> str:
    out: list[str] = []
    for run in runs:
        match run:
            case Plain():
                out.append(_plain_text(run.text))
            case Code():
                out.append(f"`{run.text}`")
            case Link():
                out.append(f"[{notion_inline(run.label)}]({run.url})")
            case AnchorLink():
                out.append(notion_inline(run.label))
            case Citation():
                label = escape_notion_text(f"[{run.number}]")
                out.append(f"[{label}]({run.url})" if run.url else label)
            case Placeholder():
                out.append(f'<span color="yellow_bg">{escape_notion_text("{{" + run.name + "}}")}</span>')
            case Chip():
                out.append(f'<span color="{CHIP_COLOR[run.color]}_bg">{escape_notion_text(run.label)}</span>')
            case Break():
                out.append("<br>")
            case Styled():
                marker = {"bold": "**", "italic": "*", "strike": "~~"}[run.style]
                out.append(_wrap(marker, notion_inline(run.runs)))
            case _:
                assert_never(run)
    return "".join(out)


def _table_cell_text(cell: TableCell) -> str:
    text = notion_inline(cell.text).replace("+", "\\+")
    return TABLE_CELL_LIST_MARKER.sub(lambda match: "\\" + match.group(1) + match.group(2), text)


def _color_attribute(tone: ToneName | None, suffix: str = "") -> str:
    return f' color="{BLOCK_COLOR[tone]}{suffix}"' if tone else ""


def _indent(lines: Sequence[str], depth: int) -> list[str]:
    return [("\t" * depth + line) if line else line for line in lines]


def _fence(content: str) -> str:
    longest = max((len(run) for run in re.findall(r"`+", content)), default=0)
    return "`" * max(3, longest + 1)


def _table_lines(table: Table) -> list[str]:
    attributes = ' fit-page-width="true" header-row="true"'
    if table.header_column:
        attributes += ' header-column="true"'
    lines = [f"<table{attributes}>", "\t<tr>"]
    lines += [f"\t\t<td>{_bold_cell(cell)}</td>" for cell in table.header]
    lines.append("\t</tr>")
    for row in table.rows:
        lines.append(f"\t<tr{_color_attribute(row.tone, '_bg')}>")
        for cell in row.cells:
            text = _table_cell_text(cell)
            if row.emphasis == "total" and text and not text.startswith("**"):
                text = f"**{text}**"
            lines.append(f"\t\t<td{_color_attribute(cell.tone, '_bg')}>{text}</td>")
        lines.append("\t</tr>")
    lines.append("</table>")
    return lines


def _bold_cell(cell: TableCell) -> str:
    text = _table_cell_text(cell)
    return f"**{text}**" if text and not text.startswith("**") else text


def notion_lines(node: Node) -> list[str]:
    match node:
        case Heading():
            return [f"{'#' * max(1, min(node.level, 4))} {notion_inline(node.text)}"]
        case Paragraph():
            text = notion_inline(node.text)
            return [text + (f' {{color="{BLOCK_COLOR[node.tone]}"}}' if node.tone else "")] if text else []
        case ListNode():
            lines: list[str] = []
            for index, entry in enumerate(node.entries, start=1):
                marker = {
                    "bullet": "-",
                    "number": f"{index}.",
                    "check": "- [x]" if entry.checked else "- [ ]",
                }[node.kind]
                lines.append(f"{marker} {notion_inline(entry.text)}")
                lines += _indent(notion_nodes(entry.children), 1)
            return lines
        case Table():
            return _table_lines(node)
        case CodeBlock():
            fence = _fence(node.content)
            return [f"{fence}{node.language}", *node.content.split("\n"), fence]
        case Callout():
            opening = f'<callout icon="{CALLOUT_ICON[node.tone]}" color="{BLOCK_COLOR[node.tone]}_bg">'
            return [opening, *_indent(notion_nodes(node.children), 1), "</callout>"]
        case Quote():
            body = "<br>".join(notion_inline(line) for line in node.lines)
            if node.cite:
                body += f"<br>*{notion_inline(node.cite)}*"
            return [f"> {body}"]
        case Divider():
            return ["---"]
        case Toggle():
            children = _indent(notion_nodes(node.children), 1)
            if node.heading_level is not None:
                return [
                    f'{"#" * node.heading_level} {notion_inline(node.title)} {{toggle="true"}}',
                    *children,
                ]
            return ["<details>", f"<summary>{notion_inline(node.title)}</summary>", *children, "</details>"]
        case Columns():
            lines = ["<columns>"]
            for column in node.columns:
                lines += [
                    f'\t<column ratio="{column.ratio}">',
                    *_indent(notion_nodes(column.children), 2),
                    "\t</column>",
                ]
            return [*lines, "</columns>"]
        case Tabs():
            lines = ["<tabs>"]
            for tab in node.tabs:
                icon = TAB_ICON.get(tab.tone or "")
                lines.append(f'\t<tab icon="{icon}">' if icon else "\t<tab>")
                lines += [
                    "\t\t" + notion_inline(tab.title),
                    *_indent(notion_nodes(tab.children), 2),
                    "\t</tab>",
                ]
            return [*lines, "</tabs>"]
        case Diagram():
            return ["```mermaid", *node.mermaid.split("\n"), "```", *notion_nodes(node.supplement)]
        case Image():
            return [f"![{notion_inline(node.caption)}]({node.url})"]
        case TableOfContents():
            return ["<table_of_contents/>"]
        case _:
            assert_never(node)


def notion_nodes(nodes: Sequence[Node]) -> list[str]:
    lines: list[str] = []
    for node in nodes:
        lines += notion_lines(node)
    return lines


def render_notion(nodes: Sequence[Node]) -> str:
    return "\n".join(notion_nodes(nodes)) + "\n"


def _starts_a_chunk(node: Node) -> bool:
    if isinstance(node, Heading):
        return node.level <= 2
    return isinstance(node, Toggle) and node.heading_level is not None and node.heading_level <= 2


@dataclass(frozen=True)
class NotionChunks:
    chunks: tuple[str, ...]
    oversized: tuple[str, ...]


def chunk_notion(nodes: Sequence[Node], limit: int) -> NotionChunks:
    sections: list[list[Node]] = [[]]
    for node in nodes:
        if _starts_a_chunk(node) and sections[-1]:
            sections.append([])
        sections[-1].append(node)
    chunks: list[str] = []
    oversized: list[str] = []
    current = ""
    for section in sections:
        text = render_notion(section)
        if len(text) > limit:
            oversized.append(text.split("\n", 1)[0])
        if current and len(current) + len(text) > limit:
            chunks.append(current)
            current = ""
        current += text
    if current:
        chunks.append(current)
    return NotionChunks(tuple(chunks), tuple(oversized))
