from collections.abc import Iterable, Iterator
from typing import Any, Protocol, cast

import pytest
from jsonschema import Draft202012Validator, ValidationError

from skaldr.errors import ReportError
from skaldr.models import Report, parse_report
from tests.factories import make_cell, make_grid, make_report, make_request, make_table


class DocumentValidator(Protocol):
    def iter_errors(self, instance: Any) -> Iterator[ValidationError]: ...

    def is_valid(self, instance: Any) -> bool: ...


SCHEMA = Report.model_json_schema()
SCHEMA_VALIDATOR: DocumentValidator = Draft202012Validator(SCHEMA)
PYDANTIC_ONLY_BOUND_KEYWORDS = frozenset({"ge", "le", "gt", "lt"})
SchemaPath = tuple[str | int, ...]


def schema_errors(document: Any) -> list[str]:
    return [error.message for error in SCHEMA_VALIDATOR.iter_errors(document)]


def _leaf_errors(errors: Iterable[ValidationError]) -> Iterator[ValidationError]:
    for error in errors:
        if error.context:
            yield from _leaf_errors(error.context)
        else:
            yield error


def schema_messages_at(document: Any, path: SchemaPath) -> set[str]:
    return {
        error.message
        for error in _leaf_errors(SCHEMA_VALIDATOR.iter_errors(document))
        if tuple(error.absolute_path) == path
    }


def schema_keys(node: object) -> Iterator[str]:
    if isinstance(node, dict):
        for key, value in cast("dict[str, object]", node).items():
            yield key
            yield from schema_keys(value)
    elif isinstance(node, list):
        for item in cast("list[object]", node):
            yield from schema_keys(item)


def test_the_generated_schema_is_a_valid_draft_2020_12_schema() -> None:
    Draft202012Validator.check_schema(SCHEMA)


def test_every_numeric_bound_in_the_schema_is_a_json_schema_keyword() -> None:
    assert sorted(set(schema_keys(SCHEMA)) & PYDANTIC_ONLY_BOUND_KEYWORDS) == []


def _numbered_list(start: int) -> dict[str, Any]:
    return {"type": "list", "style": "number", "start": start, "items": ["a"]}


def _text_spanning(span: int) -> dict[str, Any]:
    return {"type": "text", "body": "x", "span": span}


def _table_with_width(width: int) -> dict[str, Any]:
    return make_table([{"key": "name", "label": "Name", "width": width}], rows=[{"name": "x"}])


def _request_recording(status: int) -> dict[str, Any]:
    return make_request(cases=[{"label": "one", "response": {"status": status, "body": "[]"}}])


@pytest.mark.parametrize(
    "block",
    [
        pytest.param(_numbered_list(1), id="list-start-at-its-floor"),
        pytest.param(_numbered_list(999_999_999), id="list-start-at-its-ceiling"),
        pytest.param(_text_spanning(1), id="span-at-its-floor"),
        pytest.param(_text_spanning(6), id="span-at-its-ceiling"),
        pytest.param(_table_with_width(6), id="column-width-at-its-ceiling"),
        pytest.param(_request_recording(100), id="status-at-its-floor"),
        pytest.param(_request_recording(599), id="status-at-its-ceiling"),
    ],
)
def test_a_bounded_number_at_its_edge_passes_both_the_build_and_the_schema(block: dict[str, Any]) -> None:
    document = make_report(blocks=[block])

    parse_report(document)
    assert schema_errors(document) == []


@pytest.mark.parametrize(
    ("block", "location", "build_message", "schema_path", "schema_messages"),
    [
        pytest.param(
            _numbered_list(0),
            "blocks.0.list.start",
            "Input should be greater than or equal to 1",
            ("blocks", 0, "start"),
            {"0 is less than the minimum of 1", "0 is not of type 'null'"},
            id="list-start-below-one",
        ),
        pytest.param(
            _numbered_list(1_000_000_000),
            "blocks.0.list.start",
            "Input should be less than or equal to 999999999",
            ("blocks", 0, "start"),
            {"1000000000 is greater than the maximum of 999999999", "1000000000 is not of type 'null'"},
            id="list-start-past-nine-digits",
        ),
        pytest.param(
            _text_spanning(0),
            "blocks.0.text.span",
            "Input should be greater than or equal to 1",
            ("blocks", 0, "span"),
            {"0 is less than the minimum of 1", "0 is not of type 'null'"},
            id="span-below-one",
        ),
        pytest.param(
            _text_spanning(7),
            "blocks.0.text.span",
            "Input should be less than or equal to 6",
            ("blocks", 0, "span"),
            {"7 is greater than the maximum of 6", "7 is not of type 'null'"},
            id="span-past-six",
        ),
        pytest.param(
            _table_with_width(7),
            "blocks.0.table.columns.0.width",
            "Input should be less than or equal to 6",
            ("blocks", 0, "columns", 0, "width"),
            {"7 is greater than the maximum of 6", "7 is not of type 'null'"},
            id="column-width-past-six",
        ),
        pytest.param(
            _request_recording(99),
            "blocks.0.request.cases.0.response.status",
            "Input should be greater than or equal to 100",
            ("blocks", 0, "cases", 0, "response", "status"),
            {"99 is less than the minimum of 100", "99 is not of type 'null'"},
            id="status-below-100",
        ),
        pytest.param(
            make_grid([make_cell(7)]),
            "blocks.0.grid.cells.0.span",
            "Input should be less than or equal to 6",
            ("blocks", 0, "cells", 0, "span"),
            {"7 is greater than the maximum of 6"},
            id="grid-cell-span-past-six",
        ),
    ],
)
def test_the_schema_refuses_an_out_of_range_number_as_the_build_does(
    block: dict[str, Any],
    location: str,
    build_message: str,
    schema_path: SchemaPath,
    schema_messages: set[str],
) -> None:
    document = make_report(blocks=[block])

    with pytest.raises(ReportError) as raised:
        parse_report(document)

    assert (
        str(raised.value),
        SCHEMA_VALIDATOR.is_valid(document),
        schema_messages_at(document, schema_path),
    ) == (f"invalid content data: {location}: {build_message}", False, schema_messages)
