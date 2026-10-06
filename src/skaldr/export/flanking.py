import string
import unicodedata
from typing import Final

from skaldr.export.markup import styled, styled_in_tags
from skaldr.richtext import MarkerStyle

LINE_EDGE: Final = ""
EMPHASIS_OPENER_STAND_IN: Final = "*"


def _is_whitespace(character: str) -> bool:
    return character == LINE_EDGE or character.isspace()


def _is_certainly_punctuation(character: str) -> bool:
    return character in string.punctuation or unicodedata.category(character).startswith("P")


def _might_be_punctuation(character: str) -> bool:
    return _is_certainly_punctuation(character) or unicodedata.category(character).startswith("S")


def _opens(first_inside: str, before: str) -> bool:
    if _is_whitespace(first_inside):
        return False
    if not _might_be_punctuation(first_inside):
        return True
    return _is_whitespace(before) or _is_certainly_punctuation(before)


def _closes(last_inside: str, after: str) -> bool:
    if _is_whitespace(last_inside):
        return False
    if not _might_be_punctuation(last_inside):
        return True
    return _is_whitespace(after) or _is_certainly_punctuation(after)


def emphasis_github_reads(style: MarkerStyle, inner: str, before: str, after: str) -> str:
    core = inner.strip()
    if not core:
        return inner
    lead_edge = inner[: len(inner) - len(inner.lstrip())][-1:] or before
    trail_edge = inner[len(inner.rstrip()) :][:1] or after
    if _opens(core[0], lead_edge) and _closes(core[-1], trail_edge):
        return styled(style, inner)
    return styled_in_tags(style, inner)
