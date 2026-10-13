import string
import unicodedata
from typing import Final

NO_CHARACTER: Final = ""
LINE_EDGE: Final = "\n"
EMPHASIS_OPENER_STAND_IN: Final = "*"


def _is_certainly_punctuation(character: str) -> bool:
    if character == NO_CHARACTER:
        return False
    return character in string.punctuation or unicodedata.category(character).startswith("P")


def _might_be_punctuation(character: str) -> bool:
    return _is_certainly_punctuation(character) or unicodedata.category(character).startswith("S")


def _opens(first_inside: str, before: str) -> bool:
    if not _might_be_punctuation(first_inside):
        return True
    return before.isspace() or _is_certainly_punctuation(before)


def _closes(last_inside: str, after: str) -> bool:
    if not _might_be_punctuation(last_inside):
        return True
    return after.isspace() or _is_certainly_punctuation(after)


def markers_flank(inner: str, before: str, after: str) -> bool:
    core = inner.strip()
    if not core:
        return True
    lead_edge = inner[: len(inner) - len(inner.lstrip())][-1:] or before
    trail_edge = inner[len(inner.rstrip()) :][:1] or after
    return _opens(core[0], lead_edge) and _closes(core[-1], trail_edge)
