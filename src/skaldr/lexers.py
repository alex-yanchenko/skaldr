from pygments.lexer import Lexer
from pygments.lexers import get_lexer_by_name  # pyright: ignore[reportUnknownVariableType]
from pygments.util import ClassNotFound


def find_lexer(language: str) -> Lexer | None:
    try:
        return get_lexer_by_name(language, ensurenl=True, stripnl=False)
    except ClassNotFound:
        return None
