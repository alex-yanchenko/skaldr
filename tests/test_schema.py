from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any, Protocol

import pytest
import yaml
from jsonschema import Draft202012Validator, ValidationError
from pydantic import JsonValue

from skaldr.errors import ReportError
from skaldr.models import Report, load_report, package_path, parse_report
from tests.conftest import REPO_ROOT
from tests.factories import make_cell, make_grid, make_report, make_request, make_swimlane, make_table


class DocumentValidator(Protocol):
    def iter_errors(self, instance: Any) -> Iterator[ValidationError]: ...

    def is_valid(self, instance: Any) -> bool: ...


SCHEMA = Report.model_json_schema()
SCHEMA_VALIDATOR: DocumentValidator = Draft202012Validator(SCHEMA)
PYDANTIC_ONLY_BOUND_KEYWORDS = frozenset({"ge", "le", "gt", "lt"})
SchemaPath = tuple[str | int, ...]


def schema_errors(document: Any) -> list[str]:
    return [error.message for error in SCHEMA_VALIDATOR.iter_errors(document)]


def as_json(value: Any) -> JsonValue:
    return value


def _ref_the_discriminator_picks(error: ValidationError) -> JsonValue:
    schema, instance = as_json(error.schema), as_json(error.instance)
    if not isinstance(schema, dict) or not isinstance(instance, dict):
        return None
    discriminator = schema.get("discriminator")
    if not isinstance(discriminator, dict):
        return None
    mapping, property_name = discriminator.get("mapping"), discriminator.get("propertyName")
    if not isinstance(mapping, dict) or not isinstance(property_name, str):
        return None
    tag = instance.get(property_name)
    return mapping.get(tag) if isinstance(tag, str) else None


def _ref_of_branch(error: ValidationError, branch_error: ValidationError) -> JsonValue:
    branches, index = as_json(error.validator_value), branch_error.relative_schema_path[0]
    if not isinstance(branches, list) or not isinstance(index, int):
        return None
    branch = branches[index]
    return branch.get("$ref") if isinstance(branch, dict) else None


def _branch_the_discriminator_picks(error: ValidationError) -> list[ValidationError]:
    picked = _ref_the_discriminator_picks(error)
    if picked is None:
        return list(error.context)
    return [branch_error for branch_error in error.context if _ref_of_branch(error, branch_error) == picked]


def _leaf_errors(errors: Iterable[ValidationError]) -> Iterator[ValidationError]:
    for error in errors:
        if error.context:
            yield from _leaf_errors(_branch_the_discriminator_picks(error))
        else:
            yield error


def schema_messages_at(document: Any, path: SchemaPath) -> set[str]:
    return {
        error.message
        for error in _leaf_errors(SCHEMA_VALIDATOR.iter_errors(document))
        if tuple(error.absolute_path) == path
    }


def schema_keys(node: JsonValue) -> Iterator[str]:
    if isinstance(node, dict):
        for key, value in node.items():
            yield key
            yield from schema_keys(value)
    elif isinstance(node, list):
        for item in node:
            yield from schema_keys(item)


def test_the_generated_schema_is_a_valid_draft_2020_12_schema() -> None:
    Draft202012Validator.check_schema(SCHEMA)


@pytest.mark.parametrize(
    "path",
    [
        pytest.param(REPO_ROOT / "data" / "example.yaml", id="repo-example"),
        pytest.param(package_path("skill") / "example.yaml", id="guide-example"),
    ],
)
def test_an_example_document_passes_the_generated_schema(path: Path) -> None:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))

    load_report(path)
    assert schema_errors(document) == []


SWIMLANE_STEP = {"lane": "Product", "col": "Sprint 1", "n": "1", "label": "Spec"}


@pytest.mark.parametrize(
    "block",
    [
        pytest.param(make_swimlane([SWIMLANE_STEP]), id="bare-string-lanes-and-columns"),
        pytest.param(
            make_swimlane([SWIMLANE_STEP], lanes=[{"name": "Product"}], columns=[{"name": "Sprint 1"}]),
            id="named-lanes-and-columns",
        ),
    ],
)
def test_a_swimlane_in_either_documented_form_passes_both_the_build_and_the_schema(
    block: dict[str, Any],
) -> None:
    document = make_report(blocks=[block])

    parse_report(document)
    assert schema_errors(document) == []


def test_an_empty_bare_string_lane_is_refused_by_both_the_build_and_the_schema() -> None:
    document = make_report(blocks=[make_swimlane([SWIMLANE_STEP], lanes=["Product", ""])])

    with pytest.raises(ReportError) as raised:
        parse_report(document)

    assert (str(raised.value), schema_messages_at(document, ("blocks", 0, "lanes", 1))) == (
        "invalid content data: blocks.0.swimlane.lanes.1.name: Value error, must not be blank",
        {"'' should be non-empty", "'' does not match '\\\\S'", "'' is not of type 'object'"},
    )


def test_every_numeric_bound_in_the_schema_is_a_json_schema_keyword() -> None:
    assert sorted(set(schema_keys(as_json(SCHEMA))) & PYDANTIC_ONLY_BOUND_KEYWORDS) == []


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
    ("block", "build_message"),
    [
        pytest.param(
            {"type": "text", "body": "x", "span": 2.0},
            "blocks.0.text.span: Input should be a valid integer",
            id="integral-float-span",
        ),
        pytest.param(
            {"type": "meter", "items": [{"label": "m", "value": 1, "max": 1e301}]},
            "blocks.0.meter.items.0.max: Value error, must be between -1e+300 and 1e+300",
            id="number-past-the-bound",
        ),
    ],
)
def test_the_schema_accepts_what_the_guide_says_only_the_build_refuses(
    block: dict[str, Any], build_message: str
) -> None:
    document = make_report(blocks=[block])

    with pytest.raises(ReportError) as raised:
        parse_report(document)

    assert (str(raised.value), schema_errors(document)) == (f"invalid content data: {build_message}", [])


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


SPACES = "   "
SPACES_REFUSED = "'   ' does not match '\\\\S'"
SPACES_NOT_AN_OBJECT = "'   ' is not of type 'object'"
EMPTY_REFUSED = {"'' should be non-empty", "'' does not match '\\\\S'"}
TEXT_BODY = [{"type": "text", "body": "x"}]


@pytest.mark.parametrize(
    ("block", "location", "build_message", "schema_path", "schema_messages"),
    [
        pytest.param(
            {"type": "section", "title": "", "blocks": TEXT_BODY},
            "blocks.0.section.title",
            "Value error, must not be blank",
            ("blocks", 0, "title"),
            EMPTY_REFUSED,
            id="empty-section-title",
        ),
        pytest.param(
            {"type": "section", "title": SPACES, "blocks": TEXT_BODY},
            "blocks.0.section.title",
            "Value error, must not be blank",
            ("blocks", 0, "title"),
            {SPACES_REFUSED},
            id="blank-section-title",
        ),
        pytest.param(
            {"type": "panel", "title": SPACES, "blocks": TEXT_BODY},
            "blocks.0.panel.title",
            "Value error, must not be blank",
            ("blocks", 0, "title"),
            {SPACES_REFUSED},
            id="blank-panel-title",
        ),
        pytest.param(
            {"type": "heading", "text": SPACES},
            "blocks.0.heading.text",
            "Value error, must not be blank",
            ("blocks", 0, "text"),
            {SPACES_REFUSED},
            id="blank-heading-text",
        ),
        pytest.param(
            {"type": "heading", "text": "H", "sub": SPACES},
            "blocks.0.heading.sub",
            "Value error, must not be blank (omit it instead)",
            ("blocks", 0, "sub"),
            {SPACES_REFUSED, f"{SPACES!r} is not of type 'null'"},
            id="blank-heading-sub",
        ),
        pytest.param(
            {"type": "list", "items": ["a", ""]},
            "blocks.0.list.items.1.str",
            "Value error, must not be blank",
            ("blocks", 0, "items", 1),
            {*EMPTY_REFUSED, "'' is not of type 'object'"},
            id="empty-list-point",
        ),
        pytest.param(
            {"type": "list", "items": ["a", SPACES]},
            "blocks.0.list.items.1.str",
            "Value error, must not be blank",
            ("blocks", 0, "items", 1),
            {SPACES_REFUSED, SPACES_NOT_AN_OBJECT},
            id="blank-list-point",
        ),
        pytest.param(
            {"type": "list", "items": [{"text": "a", "items": [SPACES]}]},
            "blocks.0.list.items.0.ListItem.items.0.str",
            "Value error, must not be blank",
            ("blocks", 0, "items", 0, "items", 0),
            {SPACES_REFUSED, SPACES_NOT_AN_OBJECT},
            id="blank-nested-list-point",
        ),
        pytest.param(
            {"type": "list", "items": [{"text": SPACES}]},
            "blocks.0.list.items.0.ListItem.text",
            "Value error, must not be blank",
            ("blocks", 0, "items", 0, "text"),
            {SPACES_REFUSED},
            id="blank-list-item-text",
        ),
        pytest.param(
            make_swimlane([SWIMLANE_STEP], lanes=["Product", SPACES]),
            "blocks.0.swimlane.lanes.1.name",
            "Value error, must not be blank",
            ("blocks", 0, "lanes", 1),
            {SPACES_REFUSED, SPACES_NOT_AN_OBJECT},
            id="blank-bare-swimlane-lane",
        ),
    ],
)
def test_the_schema_refuses_blank_text_as_the_build_does(
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
