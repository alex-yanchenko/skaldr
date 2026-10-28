from types import TracebackType
from typing import Generic, Self, TypeVar

HTTP_TIMEOUT_SECONDS = 30.0
_JOINERS = frozenset({"\N{ZERO WIDTH NON-JOINER}", "\N{ZERO WIDTH JOINER}"})

CaughtT = TypeVar("CaughtT", bound=Exception)


def printable_only(text: str) -> str:
    kept = "".join(character for character in text if character.isspace() or _is_shown(character))
    return " ".join(kept.split())


def _is_shown(character: str) -> bool:
    return character in _JOINERS or character.isprintable()


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
