from collections.abc import Mapping, Sequence
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


def _refuse_unencodable_text(data: object, location: tuple[str, ...]) -> None:
    where = ".".join(location)
    prefix = f"invalid content data: {where}: " if where else "invalid content data: "
    if isinstance(data, str):
        code_point = _first_unencodable(data)
        if code_point is not None:
            raise ReportError(f"{prefix}{code_point} is a lone surrogate, which a page cannot hold")
        return
    if isinstance(data, Mapping):
        for key, value in cast("Mapping[object, object]", data).items():
            key_code_point = _first_unencodable(key) if isinstance(key, str) else None
            if key_code_point is not None:
                raise ReportError(
                    f"{prefix}the key {key!r} holds {key_code_point}, a lone surrogate, "
                    "which a page cannot hold"
                )
            _refuse_unencodable_text(value, (*location, str(key)))
        return
    if isinstance(data, list | tuple):
        for index, item in enumerate(cast("Sequence[object]", data)):
            _refuse_unencodable_text(item, (*location, str(index)))


def parse_report(data: Any, *, built_by_an_index: bool = False) -> Report:
    _refuse_unencodable_text(data, ())
    try:
        return Report.model_validate(data, context={BUILT_BY_AN_INDEX: built_by_an_index})
    except ValidationError as err:
        raise ReportError(format_validation_error(err)) from err
