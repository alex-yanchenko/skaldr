import difflib
import json
import os
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Final

import pytest
from pydantic import JsonValue

from skaldr.export_targets import ExportTarget
from tests.factories.example_factory import GOLDEN_REWRITE_VARIABLE_FOR, golden_of
from tests.factories.export_factory import folder_texts

MOST_DIFFERENCES_SHOWN: Final = 10
MOST_LINES_SHOWN_PER_SIDE: Final = 4
LONGEST_VALUE_SHOWN: Final = 80
LONGEST_LINE_SHOWN: Final = 120
HTML_COMPONENT: Final = re.compile(r"^<\w+[^>]* class=\"[^\"]+\"[^>]*>")
MARKDOWN_HEADING: Final = re.compile(r"^#{1,6} ")


def _shown(value: object) -> str:
    text = repr(value)
    return text if len(text) <= LONGEST_VALUE_SHOWN else text[: LONGEST_VALUE_SHOWN - 3] + "..."


def _json_differences(path: str, expected: JsonValue, written: JsonValue) -> Iterator[str]:
    if isinstance(expected, dict) and isinstance(written, dict):
        expected_keys = set(expected)
        written_keys = set(written)
        for key in sorted(expected_keys | written_keys):
            if key not in written_keys:
                yield f"{path}.{key}: missing from the output"
            elif key not in expected_keys:
                yield f"{path}.{key}: not in the golden"
            else:
                yield from _json_differences(f"{path}.{key}", expected[key], written[key])
    elif isinstance(expected, list) and isinstance(written, list):
        if len(expected) != len(written):
            yield f"{path}: expected {len(expected)} items, got {len(written)}"
        for index, (before, after) in enumerate(zip(expected, written, strict=False)):
            yield from _json_differences(f"{path}[{index}]", before, after)
    elif expected != written:
        yield f"{path}: expected {_shown(expected)}, got {_shown(written)}"


def _with_a_count(name: str, places: list[str]) -> str:
    noun = "place" if len(places) == 1 else "places"
    shown = places[:MOST_DIFFERENCES_SHOWN]
    hidden = len(places) - len(shown)
    more = [f"  ... and {hidden} more"] if hidden else []
    return "\n".join([f"{name} differs from the golden in {len(places)} {noun}:", *shown, *more])


def _json_mismatch(name: str, expected: str, written: str) -> str | None:
    differences = list(_json_differences("$", json.loads(expected), json.loads(written)))
    return _with_a_count(name, [f"  {difference}" for difference in differences]) if differences else None


def _where(golden_lines: list[str], at: int, html: bool) -> str:
    pattern = HTML_COMPONENT if html else MARKDOWN_HEADING
    anchor = next((line for line in reversed(golden_lines[: at + 1]) if pattern.match(line)), None)
    if anchor is None:
        return "before the first component" if html else "before the first heading"
    return f"in {anchor}" if html else f"under '{anchor}'"


def _side(marker: str, lines: list[str]) -> list[str]:
    shown = [f"    {marker} {line[:LONGEST_LINE_SHOWN]}" for line in lines[:MOST_LINES_SHOWN_PER_SIDE]]
    hidden = len(lines) - len(shown)
    return [*shown, f"    {marker} ... {hidden} more lines"] if hidden > 0 else shown


def _line_mismatch(name: str, expected: str, written: str) -> str | None:
    golden_lines = expected.splitlines()
    written_lines = written.splitlines()
    matcher = difflib.SequenceMatcher(a=golden_lines, b=written_lines, autojunk=False)
    places = [
        "\n".join(
            [
                f"  {_where(golden_lines, start, name.endswith('.html'))} (golden line {start + 1}):",
                *_side("-", golden_lines[start:end]),
                *_side("+", written_lines[written_start:written_end]),
            ]
        )
        for tag, start, end, written_start, written_end in matcher.get_opcodes()
        if tag != "equal"
    ]
    return _with_a_count(name, places) if places else None


def golden_mismatch(name: str, expected: str, written: str) -> str | None:
    if name.endswith(".json"):
        return _json_mismatch(name, expected, written)
    return _line_mismatch(name, expected, written)


def assert_matches_golden(target: ExportTarget, written: Path, golden: Path | None = None) -> None:
    variable = GOLDEN_REWRITE_VARIABLE_FOR[target]
    if os.environ.get(variable):
        pytest.fail(
            f"{variable} is set, so the {target} golden was rewritten from this run and nothing was "
            "compared; review the golden's diff, then run again without the variable"
        )
    expected = folder_texts(golden or golden_of(target))
    exported = folder_texts(written)
    if expected.keys() != exported.keys():
        raise AssertionError(f"the golden holds {sorted(expected)} but the export wrote {sorted(exported)}")
    mismatches = [
        mismatch
        for name in sorted(expected)
        if (mismatch := golden_mismatch(name, expected[name], exported[name])) is not None
    ]
    if mismatches:
        raise AssertionError("\n".join(mismatches))
