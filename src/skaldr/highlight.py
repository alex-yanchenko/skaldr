from collections.abc import Callable
from dataclasses import dataclass
from typing import Final, Literal

from markupsafe import Markup, escape
from pygments.lexer import Lexer
from pygments.token import Token, _TokenType  # pyright: ignore[reportPrivateUsage]

from skaldr.code_language import block_code_language
from skaldr.lexers import find_lexer
from skaldr.models import VARIABLE_TOKEN, Code

MAX_HIGHLIGHTED_CHARACTERS: Final = 20_000

TOKEN_CLASSES: Final[tuple[tuple[_TokenType, str], ...]] = (
    (Token.Comment, "t-com"),
    (Token.String, "t-str"),
    (Token.Number, "t-num"),
    (Token.Keyword, "t-kw"),
    (Token.Name.Function, "t-fn"),
    (Token.Name.Class, "t-cls"),
    (Token.Operator, "t-op"),
    (Token.Punctuation, "t-pun"),
)

DiffKind = Literal["add", "del", "ctx"]
Piece = tuple[str, str]


@dataclass(frozen=True)
class DiffRow:
    kind: DiffKind
    marker: str
    body: str


def token_class(kind: _TokenType) -> str:
    return next((name for family, name in TOKEN_CLASSES if kind in family), "")


def lexer_for(language: str, size: int) -> Lexer | None:
    if not language or size > MAX_HIGHLIGHTED_CHARACTERS:
        return None
    return find_lexer(language)


def with_line_feeds(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def pieces_by_line(tokens: list[tuple[_TokenType, str]]) -> list[list[Piece]]:
    lines: list[list[Piece]] = [[]]
    for kind, value in tokens:
        name = token_class(kind)
        for index, part in enumerate(value.split("\n")):
            if index:
                lines.append([])
            if not part:
                continue
            line = lines[-1]
            if line and line[-1][0] == name:
                line[-1] = (name, line[-1][1] + part)
            else:
                line.append((name, part))
    return lines


def piece_markup(piece: Piece) -> Markup:
    name, text = piece
    return Markup('<span class="{}">{}</span>').format(name, text) if name else escape(text)


def lexed_lines(text: str, lexer: Lexer) -> list[Markup] | None:
    tokens = list(lexer.get_tokens(text))
    ends_with_newline = text.endswith("\n")
    lexed_text = "".join(value for _, value in tokens)
    if lexed_text != (text if ends_with_newline else text + "\n"):
        return None
    lines = pieces_by_line(tokens)
    if not ends_with_newline:
        lines.pop()
    return [Markup("").join(piece_markup(piece) for piece in line) for line in lines]


def plain_lines(text: str) -> list[Markup]:
    return [escape(line) for line in text.split("\n")]


def highlighted_code(block: Code) -> Markup:
    text = with_line_feeds(block.content)
    lexer = lexer_for(block_code_language(block), len(text))
    lines = lexed_lines(text, lexer) if lexer else None
    return Markup("\n").join(plain_lines(text) if lines is None else lines)


def number_stand_in(index: int) -> str:
    return f"7{index:05d}7"


def word_stand_in(index: int) -> str:
    return f"SKALDRSLOT{index}X"


StandIn = Callable[[int], str]


def slot_markup(name: str) -> Markup:
    return Markup(
        '<span class="rq-slot" data-rq-slot="{}" data-rq-quote="none">&lsaquo;{}&rsaquo;</span>'
    ).format(name, name)


def highlighted_with_stand_ins(
    plain: str, names: list[str], lexer: Lexer, stand_in: StandIn
) -> Markup | None:
    if any(stand_in(index) in plain for index in range(len(names))):
        return None
    numbering = iter(range(len(names)))
    lines = lexed_lines(VARIABLE_TOKEN.sub(lambda _: stand_in(next(numbering)), plain), lexer)
    if lines is None:
        return None
    markup = Markup("\n").join(lines)
    if any(markup.count(stand_in(index)) != 1 for index in range(len(names))):
        return None
    for index, name in enumerate(names):
        markup = markup.replace(stand_in(index), slot_markup(name))
    return markup


def highlighted_query_keeping_slots_whole(text: str, language: str) -> Markup | None:
    plain = with_line_feeds(text)
    lexer = lexer_for(language, len(plain))
    if lexer is None:
        return None
    names = [match.group(1) for match in VARIABLE_TOKEN.finditer(plain)]
    for stand_in in (number_stand_in, word_stand_in):
        marked = highlighted_with_stand_ins(plain, names, lexer, stand_in)
        if marked is not None:
            return marked
    return None


def diff_row(line: str) -> DiffRow:
    if line.startswith("+"):
        return DiffRow("add", "", line[1:])
    if line.startswith("-"):
        return DiffRow("del", "", line[1:])
    marker = " " if line.startswith(" ") else ""
    return DiffRow("ctx", marker, line[len(marker) :])


def plain_diff_lines(rows: list[DiffRow]) -> list[tuple[DiffKind, Markup]]:
    return [(row.kind, escape(row.marker + row.body)) for row in rows]


def side_lines(rows: list[DiffRow], skipped: DiffKind, lexer: Lexer) -> list[Markup] | None:
    return lexed_lines("\n".join(row.body for row in rows if row.kind != skipped), lexer)


def highlighted_diff_lines(block: Code) -> list[tuple[DiffKind, Markup]]:
    rows = [diff_row(line) for line in with_line_feeds(block.content).split("\n")]
    size = sum(len(row.marker) + len(row.body) + 1 for row in rows) - 1
    lexer = lexer_for(block_code_language(block), size)
    old_lines = side_lines(rows, "add", lexer) if lexer else None
    new_lines = side_lines(rows, "del", lexer) if lexer else None
    if old_lines is None or new_lines is None:
        return plain_diff_lines(rows)
    old_side, new_side = iter(old_lines), iter(new_lines)
    highlighted: list[tuple[DiffKind, Markup]] = []
    for row in rows:
        old_line = next(old_side) if row.kind != "add" else Markup("")
        new_line = next(new_side) if row.kind != "del" else Markup("")
        highlighted.append((row.kind, escape(row.marker) + (old_line if row.kind == "del" else new_line)))
    return highlighted
