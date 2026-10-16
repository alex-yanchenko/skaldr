import re
from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date
from typing import Final, NoReturn
from urllib.parse import quote

from typing_extensions import Self, assert_never

from skaldr.errors import ExportInvariantError
from skaldr.export.flanking import EMPHASIS_OPENER_STAND_IN, LINE_EDGE, NO_CHARACTER, markers_flank
from skaldr.export.folds import ItemMarker, cell_text
from skaldr.export.glyphs import gauge_bar, mark_glyph
from skaldr.export.runs import (
    Chip,
    ExportRich,
    Gauge,
    IndicatorMark,
    Mark,
    SectionLink,
    TonedLabel,
    write_chipless_export_run,
)
from skaldr.export.tree import CodeBlock, TableCell, TableNode, TableRow, ToneName
from skaldr.models import BADGE_COLOR_TONE, Person, ToneLiteral
from skaldr.richtext import (
    AnchorLink,
    Citation,
    DateMention,
    Link,
    MarkerStyle,
    ScriptPosition,
    Styled,
    StyleName,
    TextRunWriter,
    Tinted,
    write_runs,
)

STYLE_MARKER: Final[Mapping[MarkerStyle, str]] = {"bold": "**", "italic": "*", "strike": "~~"}
STYLE_TAG: Final[Mapping[MarkerStyle, str]] = {"bold": "strong", "italic": "em", "strike": "del"}
ENTITY_LOOKALIKE: Final = re.compile(r"&(?=#?\w+;)")
LARGEST_ORDERED_MARKER_NUMBER: Final = 999_999_999
DIVIDER_LINE: Final = "---"
HTML_LINE_BREAK: Final = "<br>"
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


def label_then(label: str, written_date: str) -> str:
    return f"{label} {written_date}" if label.strip() else written_date


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


def table_width(table: TableNode) -> int:
    return max(len(cells) for cells in (table.header, *(row.cells for row in table.rows)))


def _dot_tones_not_leading(tones: Sequence[ToneName], runs: ExportRich) -> tuple[ToneLiteral, ...]:
    return tuple(
        dict.fromkeys(tone for tone in tones if tone != "muted" and runs[:1] != (IndicatorMark(tone),))
    )


def _own_tone(cell: TableCell) -> tuple[ToneName, ...]:
    return (cell.tone,) if cell.tone is not None else ()


def _row_tone_on_title(table: TableNode, row: TableRow, index: int) -> tuple[ToneName, ...]:
    if row.tone is None or index != table.title_column:
        return ()
    return (row.tone,)


def _tones_a_cell_shows(table: TableNode, row: TableRow, index: int, cell: TableCell) -> tuple[ToneName, ...]:
    return _row_tone_on_title(table, row, index) + _own_tone(cell)


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

    def date_mention_around(self, run: DateMention, written_label: str, /) -> str:
        return self.date_mention(written_label, run.start, run.end)

    def person_mention(self, label: str, _key: str, _person: Person, /) -> str:
        return label

    def issue_link(self, label: str, _key: str, url: str | None, /) -> str:
        return self.link(label, url) if url else label

    def document_link(self, _label: str, _doc_id: str, _section: str | None, /) -> str:
        raise ExportInvariantError(
            "this target cannot link to another skaldr document; the export check should have refused it"
        )

    def citation(self, run: Citation, /) -> str:
        label = self.escape(f"[{run.number}]")
        return f"[{label}]({encode_url(run.url)})" if run.url else label

    def line_break(self) -> str:
        return HTML_LINE_BREAK

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

    def section_link(self, label: str, _anchor: str, /) -> str:
        return label

    def toned_label(self, _tone: ToneLiteral, inner: str, /) -> str:
        return inner


@dataclass(frozen=True)
class _Emphasis:
    style: MarkerStyle
    inner: str


_Piece = str | _Emphasis


@dataclass(frozen=True)
class _Enclosing:
    styles: frozenset[MarkerStyle] = frozenset()
    marker_character: str = NO_CHARACTER

    def inside(self, style: MarkerStyle) -> Self:
        return replace(self, styles=self.styles.union((style,)), marker_character=STYLE_MARKER[style][0])

    def inside_brackets(self) -> Self:
        return replace(self, marker_character=NO_CHARACTER)


def _writes_nothing_visible(pieces: Sequence[_Piece]) -> bool:
    return all(not (piece if isinstance(piece, str) else piece.inner).strip() for piece in pieces)


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


class CommonMarkRuns(MarkupRuns, ABC):
    @abstractmethod
    def unflanked_emphasis(self, style: MarkerStyle, inner: str, /) -> str: ...

    @abstractmethod
    def refuse_a_tint(self) -> NoReturn: ...

    @abstractmethod
    def require_links_to_its_own_headings(self) -> None: ...

    def heading_slug(self, _anchor: str, /) -> str | None:
        return None

    def write(self, runs: ExportRich) -> str:
        return self._written(runs, _Enclosing())

    def write_toned(self, tones: Sequence[ToneName], runs: ExportRich) -> str:
        dots = [self.mark(IndicatorMark(tone)) for tone in _dot_tones_not_leading(tones, runs)]
        text = self._written_struck(runs) if "muted" in tones else self.write(runs)
        return " ".join([*dots, text] if text else dots)

    def _written_struck(self, runs: ExportRich) -> str:
        struck = _Emphasis("strike", self._written(runs, _Enclosing().inside("strike")))
        return self._joined([struck], _Enclosing())

    def _tone_dot_prefix(self, tone: ToneLiteral) -> str:
        return f"{self.mark(IndicatorMark(tone))} "

    def _written(self, runs: ExportRich, enclosing: _Enclosing) -> str:
        return self._joined(self._pieces(runs, enclosing), enclosing)

    def _joined(self, pieces: Sequence[_Piece], enclosing: _Enclosing) -> str:
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
            runs_into_the_enclosing_marker = marker[0] == enclosing.marker_character and (
                not written.strip() or _writes_nothing_visible(pieces[index + 1 :])
            )
            following = _first_character(pieces[index + 1 :]) or LINE_EDGE
            if (
                runs_into_the_previous_marker
                or runs_into_the_enclosing_marker
                or not markers_flank(piece.inner, written[-1:] or LINE_EDGE, following)
            ):
                emphasis = self.unflanked_emphasis(piece.style, piece.inner)
            else:
                emphasis = styled(piece.style, piece.inner)
            written += emphasis
            open_marker_character = marker[0] if emphasis.endswith(marker) else NO_CHARACTER
        return written

    def _styled_pieces(self, run: Styled, enclosing: _Enclosing) -> list[_Piece]:
        marker_style = _marker_style(run.style)
        if marker_style is None:
            return [self.underline(self._written(run.runs, enclosing))]
        if marker_style in enclosing.styles:
            return self._pieces(run.runs, enclosing)
        return [_Emphasis(marker_style, self._written(run.runs, enclosing.inside(marker_style)))]

    def _pieces(self, runs: ExportRich, enclosing: _Enclosing) -> list[_Piece]:
        pieces: list[_Piece] = []
        for run in runs:
            match run:
                case Styled():
                    pieces += self._styled_pieces(run, enclosing)
                case Tinted():
                    self.refuse_a_tint()
                case TonedLabel():
                    pieces += [self._tone_dot_prefix(run.tone), *self._pieces(run.runs, enclosing)]
                case Link():
                    pieces.append(self.link(self._written(run.label, enclosing.inside_brackets()), run.url))
                case AnchorLink():
                    self.require_links_to_its_own_headings()
                    pieces += self._anchor_link_pieces(run, enclosing)
                case SectionLink():
                    pieces += self._anchor_link_pieces(run, enclosing)
                case DateMention():
                    pieces.append(self.date_mention_around(run, write_runs(run.label, self)))
                case Chip():
                    pieces += [
                        self._tone_dot_prefix(BADGE_COLOR_TONE[run.tone]),
                        _Emphasis("bold", self.escape(run.label)),
                    ]
                case _:
                    pieces.append(write_chipless_export_run(run, self))
        return pieces

    def _anchor_link_pieces(self, run: AnchorLink | SectionLink, enclosing: _Enclosing) -> list[_Piece]:
        slug = self.heading_slug(run.anchor)
        if not slug:
            return self._pieces(run.label, enclosing)
        return [self.anchor_link(self._written(run.label, enclosing.inside_brackets()), slug)]

    def code(self, text: str, /) -> str:
        return code_span(text)

    def anchor_link(self, label: str, slug: str, /) -> str:
        return f"[{label}](#{slug})"

    def placeholder(self, name: str, /) -> str:
        return code_span("{{" + name + "}}")


def pipe_table_lines(
    table: TableNode, writer: CommonMarkRuns, item_marker: ItemMarker | None = None
) -> list[str]:
    def cell_markup(cell: TableCell, tones: Sequence[ToneName]) -> str:
        text = cell_text(cell) if item_marker is None else cell_text(cell, item_marker)
        return writer.write_toned(tones, text).replace("|", "\\|")

    width = table_width(table)
    lines = [
        _pipe_table_row(_padded([cell_markup(cell, ()) for cell in table.header], width)),
        _pipe_table_row(["---"] * width),
    ]
    for row in table.rows:
        written = [
            cell_markup(cell, _tones_a_cell_shows(table, row, index, cell))
            for index, cell in enumerate(row.cells)
        ]
        lines.append(_pipe_table_row(_padded(body_cell_texts(table, row, written), width)))
    return lines
