from typing import Final, Literal

from markupsafe import Markup, escape
from pygments.lexer import Lexer
from pygments.lexers import get_lexer_by_name  # pyright: ignore[reportUnknownVariableType]
from pygments.token import Token, _TokenType  # pyright: ignore[reportPrivateUsage]
from pygments.util import ClassNotFound

from skaldr.code_language import block_code_language
from skaldr.models import Code

MAX_HIGHLIGHTED_CHARACTERS: Final = 200_000

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


def token_class(kind: _TokenType) -> str:
    return next((name for family, name in TOKEN_CLASSES if kind in family), "")


def lexer_for(language: str, text: str) -> Lexer | None:
    if not language or len(text) > MAX_HIGHLIGHTED_CHARACTERS:
        return None
    try:
        return get_lexer_by_name(language, ensurenl=False, stripnl=False)
    except ClassNotFound:
        return None


def with_line_feeds(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def pieces_by_line(text: str, lexer: Lexer) -> list[list[Piece]]:
    lines: list[list[Piece]] = [[]]
    for kind, value in lexer.get_tokens(text):
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


def lexed_lines(text: str, lexer: Lexer) -> list[Markup]:
    lines = pieces_by_line(with_line_feeds(text), lexer)
    return [Markup("").join(piece_markup(piece) for piece in line) for line in lines]


def plain_lines(text: str) -> list[Markup]:
    return [escape(line) for line in text.split("\n")]


def highlighted_code(block: Code) -> Markup:
    lexer = lexer_for(block_code_language(block), block.content)
    lines = plain_lines(block.content) if lexer is None else lexed_lines(block.content, lexer)
    return Markup("\n").join(lines)


def diff_line_kind(line: str) -> DiffKind:
    if line.startswith("+"):
        return "add"
    if line.startswith("-"):
        return "del"
    return "ctx"


def diff_rows(content: str) -> list[tuple[DiffKind, str]]:
    rows: list[tuple[DiffKind, str]] = []
    for line in content.split("\n"):
        kind = diff_line_kind(line)
        rows.append((kind, line if kind == "ctx" else line[1:]))
    return rows


def highlighted_diff_lines(block: Code) -> list[tuple[DiffKind, Markup]]:
    lexer = lexer_for(block_code_language(block), block.content)
    if lexer is None:
        return [(kind, escape(text)) for kind, text in diff_rows(block.content)]
    rows = diff_rows(with_line_feeds(block.content))
    old_side = iter(lexed_lines("\n".join(text for kind, text in rows if kind != "add"), lexer))
    new_side = iter(lexed_lines("\n".join(text for kind, text in rows if kind != "del"), lexer))
    highlighted: list[tuple[DiffKind, Markup]] = []
    for kind, _ in rows:
        old_line = next(old_side) if kind != "add" else None
        new_line = next(new_side) if kind != "del" else None
        highlighted.append((kind, new_line if new_line is not None else old_line or Markup("")))
    return highlighted
