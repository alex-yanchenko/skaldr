import re
from collections.abc import Sequence
from dataclasses import dataclass

from typing_extensions import assert_never

from skaldr.export.markup import (
    CALLOUT_ICON,
    MarkupRuns,
    code_block_lines,
    escape_block_start,
    indent_lines,
    styled,
)
from skaldr.export.tree import (
    Callout,
    CodeBlock,
    Heading,
    ListNode,
    Node,
    Paragraph,
    Quote,
    TableOfContents,
    Toggle,
    ToneName,
)
from skaldr.richtext import Rich, write_runs

NOTION_ESCAPED = frozenset("\\*~`$[]<>{}|^")
FILE_NAME_NOTION_LINKIFIES = re.compile(r"(?<![\w/.-])([\w./-]*\w\.(?:md|py|sh)(?::\d+(?:-\d+)?)?)(?![\w`])")
CHUNK_BOUNDARY_LEVEL = 2
OPENING_SECTION_LABEL = "the opening section, before the first heading"
BLOCK_COLOR: dict[ToneName, str] = {
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


def _escape(text: str) -> str:
    return "".join("\\" + character if character in NOTION_ESCAPED else character for character in text)


class _NotionRuns(MarkupRuns):
    def __init__(self) -> None:
        super().__init__(_escape)

    def text(self, text: str, /) -> str:
        pieces = FILE_NAME_NOTION_LINKIFIES.split(text)
        return "".join(
            self.code(piece) if index % 2 else _escape(piece) for index, piece in enumerate(pieces)
        )

    def bang_before_link(self) -> str:
        return "\\!"

    def code(self, text: str, /) -> str:
        return _escape(text) if "`" in text else f"`{text}`"

    def anchor_link(self, label: str, _anchor: str, /) -> str:
        return label

    def placeholder(self, name: str, /) -> str:
        return f'<span color="yellow_bg">{_escape("{{" + name + "}}")}</span>'


def notion_inline(runs: Rich) -> str:
    return write_runs(runs, _NotionRuns())


def _block_text(runs: Rich) -> str:
    return escape_block_start(notion_inline(runs))


def _color_attribute(tone: ToneName | None, suffix: str = "") -> str:
    return f' color="{BLOCK_COLOR[tone]}{suffix}"' if tone else ""


def _trailing_color(tone: ToneName | None) -> str:
    return f' {{color="{BLOCK_COLOR[tone]}"}}' if tone else ""


def _indent(lines: Sequence[str], depth: int = 1) -> list[str]:
    return indent_lines(lines, "\t" * depth)


def _list_lines(node: ListNode) -> list[str]:
    lines: list[str] = []
    for index, entry in enumerate(node.entries, start=1):
        match node.kind:
            case "bullet":
                marker = "-"
            case "number":
                marker = f"{index}."
            case "check":
                marker = "- [x]" if entry.checked else "- [ ]"
            case _:
                assert_never(node.kind)
        lines.append(f"{marker} {_block_text(entry.text)}{_trailing_color(entry.tone)}")
        lines += _indent(_notion_blocks(entry.children))
    return lines


def _quote_line(node: Quote) -> str:
    body = "<br>".join(_block_text(line) for line in node.lines)
    if node.cite:
        body += "<br>" + styled("italic", notion_inline(node.cite))
    return f"> {body}"


def _toggle_lines(node: Toggle) -> list[str]:
    children = _indent(_notion_blocks(node.children))
    if node.heading_level is not None:
        return [f'{"#" * node.heading_level} {notion_inline(node.title)} {{toggle="true"}}', *children]
    return ["<details>", f"<summary>{notion_inline(node.title)}</summary>", *children, "</details>"]


def _notion_lines(node: Node) -> list[str]:
    match node:
        case Heading():
            return [f"{'#' * node.level} {notion_inline(node.text)}"]
        case Paragraph():
            text = _block_text(node.text)
            return [text + _trailing_color(node.tone)] if text else []
        case ListNode():
            return _list_lines(node)
        case CodeBlock():
            return code_block_lines(node)
        case Callout():
            opening = f'<callout icon="{CALLOUT_ICON[node.tone]}"{_color_attribute(node.tone, "_bg")}>'
            return [opening, *_indent(_notion_blocks(node.children)), "</callout>"]
        case Quote():
            return [_quote_line(node)]
        case Toggle():
            return _toggle_lines(node)
        case TableOfContents():
            return ["<table_of_contents/>"]
        case _:
            assert_never(node)


def _notion_blocks(nodes: Sequence[Node]) -> list[str]:
    return [line for node in nodes for line in _notion_lines(node)]


def render_notion(nodes: Sequence[Node]) -> str:
    return "\n".join(_notion_blocks(nodes)) + "\n"


def _starts_a_chunk(node: Node) -> bool:
    if isinstance(node, Heading):
        return node.level <= CHUNK_BOUNDARY_LEVEL
    return (
        isinstance(node, Toggle)
        and node.heading_level is not None
        and node.heading_level <= CHUNK_BOUNDARY_LEVEL
    )


def _section_label(section: Sequence[Node], text: str) -> str:
    return text.split("\n", 1)[0] if section and _starts_a_chunk(section[0]) else OPENING_SECTION_LABEL


@dataclass(frozen=True)
class NotionChunks:
    chunks: tuple[str, ...]
    oversized_sections: tuple[str, ...]


def chunk_notion(nodes: Sequence[Node], limit: int) -> NotionChunks:
    sections: list[list[Node]] = [[]]
    for node in nodes:
        if _starts_a_chunk(node) and sections[-1]:
            sections.append([])
        sections[-1].append(node)
    chunks: list[str] = []
    oversized: list[str] = []
    current_chunk = ""
    for section in sections:
        text = render_notion(section)
        if len(text) > limit:
            oversized.append(_section_label(section, text))
        if current_chunk and len(current_chunk) + len(text) > limit:
            chunks.append(current_chunk)
            current_chunk = ""
        current_chunk += text
    if current_chunk:
        chunks.append(current_chunk)
    return NotionChunks(tuple(chunks), tuple(oversized))
