import unicodedata
from typing import Final

from markdown_it.common.utils import isMdAsciiPunct, isPunctChar, isWhiteSpace

NO_CHARACTER: Final = ""
LINE_EDGE: Final = "\n"
EMPHASIS_OPENER_STAND_IN: Final = "*"


def _is_whitespace(character: str) -> bool:
    return character != NO_CHARACTER and isWhiteSpace(ord(character))


def _is_certainly_punctuation(character: str) -> bool:
    if character == NO_CHARACTER:
        return False
    return isMdAsciiPunct(ord(character)) or unicodedata.category(character).startswith("P")


def _opens(first_inside: str, before: str) -> bool:
    if not isPunctChar(first_inside):
        return True
    return _is_whitespace(before) or _is_certainly_punctuation(before)


def _closes(last_inside: str, after: str) -> bool:
    if not isPunctChar(last_inside):
        return True
    return _is_whitespace(after) or _is_certainly_punctuation(after)


def markers_flank(inner: str, before: str, after: str) -> bool:
    core = inner.strip()
    if not core:
        return True
    lead_edge = inner[: len(inner) - len(inner.lstrip())][-1:] or before
    trail_edge = inner[len(inner.rstrip()) :][:1] or after
    return _opens(core[0], lead_edge) and _closes(core[-1], trail_edge)
