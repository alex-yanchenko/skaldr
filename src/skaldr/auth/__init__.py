import unicodedata
from types import TracebackType
from typing import Generic, TypeVar

from typing_extensions import Self

HTTP_TIMEOUT_SECONDS = 30.0
_JOINERS = frozenset({"\N{ZERO WIDTH NON-JOINER}", "\N{ZERO WIDTH JOINER}"})

CaughtT = TypeVar("CaughtT", bound=Exception)


def printable_only(text: str) -> str:
    return "".join(_shown(character) for character in text)


def _shown(character: str) -> str:
    if unicodedata.category(character) == "Zs":
        return " "
    if character in _JOINERS or character.isprintable():
        return character
    return ""


class CaughtWithoutChaining(Generic[CaughtT]):
    def __init__(self, caught_type: type[CaughtT]) -> None:
        self._caught_type = caught_type
        self._caught: CaughtT | None = None

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        if isinstance(exc, self._caught_type):
            self._caught = exc
            return True
        return False

    @property
    def error(self) -> CaughtT:
        if self._caught is None:
            raise AssertionError(f"no {self._caught_type.__name__} was caught")
        return self._caught


def caught_without_chaining(caught_type: type[CaughtT]) -> CaughtWithoutChaining[CaughtT]:
    return CaughtWithoutChaining(caught_type)
