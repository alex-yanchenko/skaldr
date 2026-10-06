from collections.abc import Iterable
from typing import Final, Literal

from markupsafe import Markup, escape
from pygments.lexer import Lexer
from pygments.lexers import get_lexer_by_name  # pyright: ignore[reportUnknownVariableType]
from pygments.token import Token, _TokenType  # pyright: ignore[reportPrivateUsage]
from pygments.util import ClassNotFound

from skaldr.export.lower.prose import code_language
from skaldr.models import Code

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


def lexer_for(language: str) -> Lexer | None:
    if not language:
        return None
    try:
        return get_lexer_by_name(language, ensurenl=False, stripnl=False)
    except ClassNotFound:
        return None


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


def highlighted_lines(text: str, language: str) -> list[Markup]:
    lexer = lexer_for(language)
    if lexer is None:
        return [escape(line) for line in text.split("\n")]
    return [Markup("").join(piece_markup(piece) for piece in line) for line in pieces_by_line(text, lexer)]


def code_language_of(block: Code) -> str:
    return block.lang or code_language(block.label)


def highlighted_code(block: Code) -> Markup:
    return Markup("\n").join(highlighted_lines(block.content, code_language_of(block)))


def diff_line_kind(line: str) -> DiffKind:
    if line.startswith("+"):
        return "add"
    if line.startswith("-"):
        return "del"
    return "ctx"


def without_diff_marker(line: str) -> str:
    return line[1:] if diff_line_kind(line) != "ctx" else line


def highlighted_diff_lines(block: Code) -> Iterable[tuple[DiffKind, Markup]]:
    source_lines = block.content.split("\n")
    code_lines = highlighted_lines(
        "\n".join(without_diff_marker(line) for line in source_lines), code_language_of(block)
    )
    return [(diff_line_kind(line), code) for line, code in zip(source_lines, code_lines, strict=True)]
