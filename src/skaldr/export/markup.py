import re
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping, Sequence
from datetime import date
from typing import Final
from urllib.parse import quote

from typing_extensions import assert_never

from skaldr.export.glyphs import gauge_bar, mark_glyph
from skaldr.export.runs import Chip, ExportRich, Gauge, Mark
from skaldr.export.tree import CodeBlock, TableNode, TableRow
from skaldr.models import Person, ToneLiteral
from skaldr.richtext import Citation, MarkerStyle, ScriptPosition, StyleName, TextRunWriter

STYLE_MARKER: Final[Mapping[MarkerStyle, str]] = {"bold": "**", "italic": "*", "strike": "~~"}
STYLE_TAG: Final[Mapping[MarkerStyle, str]] = {"bold": "strong", "italic": "em", "strike": "del"}
DIVIDER_LINE: Final = "---"
BLOCK_START_MARKER = re.compile(r"^(#{1,6}|[-+]+|=+|>)(?=\s|$)")
ORDERED_START_MARKER = re.compile(r"^(\d{1,9})([.)])(?=\s|$)")
BACKTICK_RUN = re.compile(r"`+")
HEADING_CLOSING_RUN = re.compile(r"(?:(?<=\s)|^)(#+\s*)$")
URL_SAFE_CHARACTERS: Final = "/:?#[]@!$&'*+,;=%~"


def wrap_around_core(inner: str, opener: str, closer: str) -> str:
    core = inner.strip()
    if not core:
        return inner
    lead = inner[: len(inner) - len(inner.lstrip())]
    trail = inner[len(inner.rstrip()) :]
    return f"{lead}{opener}{core}{closer}{trail}"


def styled(style: MarkerStyle, inner: str) -> str:
    marker = STYLE_MARKER[style]
    return wrap_around_core(inner, marker, marker)


def styled_in_tags(style: MarkerStyle, inner: str) -> str:
    tag = STYLE_TAG[style]
    return wrap_around_core(inner, f"<{tag}>", f"</{tag}>")


def is_emphasised_body_cell(table: TableNode, row: TableRow, index: int) -> bool:
    return row.emphasis is not None or (table.header_column and index == 0)


def body_cell_texts(table: TableNode, row: TableRow, texts: Sequence[str]) -> list[str]:
    return [
        styled("bold", text) if is_emphasised_body_cell(table, row, index) else text
        for index, text in enumerate(texts)
    ]


def _longest_backtick_run(text: str) -> int:
    return max((len(run) for run in BACKTICK_RUN.findall(text)), default=0)


def _commonmark_would_strip_a_space_from_each_end(text: str) -> bool:
    return text.startswith(" ") and text.endswith(" ") and bool(text.strip(" "))


def code_span(text: str) -> str:
    ticks = "`" * (_longest_backtick_run(text) + 1)
    needs_padding = (
        text.startswith("`") or text.endswith("`") or _commonmark_would_strip_a_space_from_each_end(text)
    )
    padding = " " if needs_padding else ""
    return f"{ticks}{padding}{text}{padding}{ticks}"


def code_block_lines(block: CodeBlock) -> list[str]:
    fence = "`" * max(3, _longest_backtick_run(block.content) + 1)
    return [f"{fence}{block.language}", *block.content.split("\n"), fence]


def escape_block_start(text: str) -> str:
    text = BLOCK_START_MARKER.sub(lambda match: "\\" + match.group(1), text)
    return ORDERED_START_MARKER.sub(lambda match: match.group(1) + "\\" + match.group(2), text)


def bang_cannot_open_an_image(escaped_text: str) -> str:
    return escaped_text[:-1] + "\\!" if escaped_text.endswith("!") else escaped_text


def encode_url(url: str) -> str:
    return quote(url, safe=URL_SAFE_CHARACTERS + "\\").replace("\\", "\\\\")


def indent_lines(lines: Sequence[str], prefix: str) -> list[str]:
    return [prefix + line if line else line for line in lines]


def heading_line(level: int, text: str) -> str:
    kept_hashes = HEADING_CLOSING_RUN.sub(lambda match: "\\" + match.group(1), text)
    return f"{'#' * level} {kept_hashes}"


def spaced(lines: Sequence[str]) -> list[str]:
    return ["", *lines] if lines else []


def quoted(lines: Sequence[str]) -> list[str]:
    return [f"> {line}" if line else ">" for line in lines]


def joined(sections: Sequence[Sequence[str]]) -> list[str]:
    out: list[str] = []
    for lines in sections:
        if lines:
            out += ["", *lines] if out else lines
    return out


def _padded(cells: Sequence[str], width: int) -> list[str]:
    return [*cells, *[""] * (width - len(cells))]


def _pipe_table_row(cells: Sequence[str]) -> str:
    return "| " + " | ".join(cells) + " |"


def pipe_table_lines(table: TableNode, inline: Callable[[ExportRich], str]) -> list[str]:
    def cell_text(runs: ExportRich) -> str:
        return inline(runs).replace("|", "\\|")

    width = max(len(cells) for cells in (table.header, *(row.cells for row in table.rows)))
    lines = [
        _pipe_table_row(_padded([cell_text(cell.text) for cell in table.header], width)),
        _pipe_table_row(["---"] * width),
    ]
    for row in table.rows:
        texts = body_cell_texts(table, row, [cell_text(cell.text) for cell in row.cells])
        lines.append(_pipe_table_row(_padded(texts, width)))
    return lines


class MarkupRuns(TextRunWriter, ABC):
    @abstractmethod
    def escape(self, text: str, /) -> str: ...

    @abstractmethod
    def code(self, text: str, /) -> str: ...

    @abstractmethod
    def anchor_link(self, label: str, anchor: str, /) -> str: ...

    @abstractmethod
    def placeholder(self, name: str, /) -> str: ...

    @abstractmethod
    def chip(self, run: Chip, /) -> str: ...

    @abstractmethod
    def underline(self, inner: str, /) -> str: ...

    @abstractmethod
    def script(self, position: ScriptPosition, text: str, /) -> str: ...

    def tinted(self, _tone: ToneLiteral | None, _background: ToneLiteral | None, inner: str, /) -> str:
        return inner

    def math(self, expression: str, /) -> str:
        return f"$`{expression}`$"

    def text(self, text: str, /) -> str:
        return bang_cannot_open_an_image(self.escape(text))

    def link(self, label: str, url: str, /) -> str:
        return f"[{label}]({encode_url(url)})"

    def date_mention(self, label: str, _start: date, _end: date | None, /) -> str:
        return label

    def person_mention(self, label: str, _key: str, _person: Person, /) -> str:
        return label

    def issue_link(self, label: str, _key: str, url: str | None, /) -> str:
        return self.link(label, url) if url else label

    def document_link(self, label: str, _doc_id: str, _section: str | None, /) -> str:
        return label

    def citation(self, run: Citation, /) -> str:
        label = self.escape(f"[{run.number}]")
        return f"[{label}]({encode_url(run.url)})" if run.url else label

    def line_break(self) -> str:
        return "<br>"

    def styled(self, style: StyleName, inner: str, /) -> str:
        match style:
            case "underline":
                return self.underline(inner)
            case "bold" | "italic" | "strike":
                return styled(style, inner)
            case _:
                assert_never(style)

    def mark(self, run: Mark, /) -> str:
        return mark_glyph(run)

    def gauge(self, run: Gauge, /) -> str:
        return gauge_bar(run.value, run.maximum)
