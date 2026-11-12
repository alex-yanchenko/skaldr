from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from pydantic import ValidationError

from skaldr.errors import ReportError
from skaldr.models.containers import BUILT_BY_AN_INDEX
from skaldr.models.report import Report


def format_validation_error(error: ValidationError, within: tuple[str, ...] = ()) -> str:
    lines: list[str] = []
    for issue in error.errors():
        location = ".".join(str(part) for part in (*within, *issue["loc"]))
        lines.append(f"{location}: {issue['msg']}" if location else issue["msg"])
    return "invalid content data: " + "; ".join(lines)


def read_text_file(path: Path) -> str:
    if not path.exists():
        raise ReportError(f"file not found: {path}")
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as err:
        raise ReportError(f"could not read {path}: {err}") from err


def _first_unencodable(text: str) -> str | None:
    try:
        text.encode("utf-8")
    except UnicodeEncodeError as err:
        return f"U+{ord(text[err.start]):04X}"
    return None


_NESTS_TOO_DEEPLY = "the document nests too deeply or refers to itself"


@dataclass
class _Walk:
    visited: set[int] = field(default_factory=set[int])
    active: set[int] = field(default_factory=set[int])

    def enter(self, container: object) -> bool:
        if id(container) in self.active:
            raise ReportError(_NESTS_TOO_DEEPLY)
        if id(container) in self.visited:
            return False
        self.visited.add(id(container))
        self.active.add(id(container))
        return True

    def leave(self, container: object) -> None:
        self.active.discard(id(container))


def _refuse_unencodable_text(data: object, location: tuple[str, ...], walk: _Walk) -> None:
    where = ".".join(location)
    prefix = f"invalid content data: {where}: " if where else "invalid content data: "
    if isinstance(data, str):
        code_point = _first_unencodable(data)
        if code_point is not None:
            raise ReportError(f"{prefix}{code_point} is a lone surrogate, which a page cannot hold")
        return
    if isinstance(data, Mapping):
        mapping = cast("Mapping[object, object]", data)
        if not walk.enter(mapping):
            return
        for key, value in mapping.items():
            key_code_point = _first_unencodable(key) if isinstance(key, str) else None
            if key_code_point is not None:
                raise ReportError(
                    f"{prefix}the key {key!r} holds {key_code_point}, a lone surrogate, "
                    "which a page cannot hold"
                )
            _refuse_unencodable_text(value, (*location, str(key)), walk)
        walk.leave(mapping)
        return
    if isinstance(data, list | tuple):
        sequence = cast("Sequence[object]", data)
        if not walk.enter(sequence):
            return
        for index, item in enumerate(sequence):
            _refuse_unencodable_text(item, (*location, str(index)), walk)
        walk.leave(sequence)


def parse_report(data: Any, *, built_by_an_index: bool = False) -> Report:
    try:
        _refuse_unencodable_text(data, (), _Walk())
        return Report.model_validate(data, context={BUILT_BY_AN_INDEX: built_by_an_index})
    except ValidationError as err:
        raise ReportError(format_validation_error(err)) from err
    except RecursionError as err:
        raise ReportError(_NESTS_TOO_DEEPLY) from err
