import json
from collections.abc import Iterator, Mapping
from typing import Any, Protocol

import pytest
from jsonschema import Draft4Validator, ValidationError

from skaldr.export.adf import IssueLinks, render_adf, render_adf_document
from skaldr.export.lower import lower_report
from skaldr.export.tree import Node
from skaldr.models import load_report, parse_report
from tests.conftest import REPO_ROOT
from tests.factories import API_BADGES, BADGE_AND_STATE_BLOCKS, make_report
from tests.factories.adf_factory import minimal_nodes, showcase_nodes

ADF_SCHEMA_FILE = REPO_ROOT / "tests" / "schemas" / "adf-schema-57.7.4-full.json"
EXAMPLE = REPO_ROOT / "data" / "example.yaml"
SITE = IssueLinks("https://example.atlassian.net", frozenset({"PLAN"}))


class AdfValidator(Protocol):
    def iter_errors(self, instance: Any) -> Iterator[ValidationError]: ...

    def is_valid(self, instance: Any) -> bool: ...


SCHEMA = json.loads(ADF_SCHEMA_FILE.read_text(encoding="utf-8"))
VALIDATOR: AdfValidator = Draft4Validator(SCHEMA)


def _problems(document: Mapping[str, object]) -> list[str]:
    return [error.message for error in VALIDATOR.iter_errors(json.loads(json.dumps(document)))]


def _doc(*blocks: Mapping[str, object]) -> Mapping[str, object]:
    return {"version": 1, "type": "doc", "content": list(blocks)}


def test_the_vendored_schema_is_atlassians_adf_schema() -> None:
    assert (SCHEMA["description"], SCHEMA["$schema"]) == (
        "Schema for Atlassian Document Format.",
        "http://json-schema.org/draft-04/schema#",
    )


@pytest.mark.parametrize(
    "document",
    [
        pytest.param(
            _doc(
                {
                    "type": "paragraph",
                    "content": [
                        {"type": "text", "text": "x", "marks": [{"type": "code"}, {"type": "strong"}]}
                    ],
                }
            ),
            id="strong-on-code",
        ),
        pytest.param(
            _doc(
                {
                    "type": "panel",
                    "attrs": {"panelType": "info"},
                    "content": [
                        {
                            "type": "table",
                            "content": [
                                {
                                    "type": "tableRow",
                                    "content": [
                                        {"type": "tableCell", "content": [{"type": "paragraph"}]},
                                    ],
                                }
                            ],
                        }
                    ],
                }
            ),
            id="table-in-panel",
        ),
        pytest.param(_doc({"type": "paragraph", "content": [{"type": "text", "text": ""}]}), id="empty-text"),
        pytest.param(_doc({"type": "taskList", "content": []}), id="task-list-without-local-id"),
    ],
)
def test_the_schema_check_refuses_documents_atlassian_would_refuse(document: Mapping[str, object]) -> None:
    assert _problems(document) != []


@pytest.mark.parametrize("node", minimal_nodes().values(), ids=lambda node: type(node).__name__)
def test_every_lowered_node_type_writes_a_document_the_adf_schema_accepts(node: Node) -> None:
    assert _problems(render_adf((node,))) == []


def test_a_document_using_every_block_inline_and_mark_is_accepted_by_the_adf_schema() -> None:
    assert _problems(render_adf(showcase_nodes(), SITE)) == []


def test_the_badge_and_state_blocks_are_accepted_by_the_adf_schema() -> None:
    lowered = lower_report(parse_report(make_report(blocks=BADGE_AND_STATE_BLOCKS, badges=API_BADGES)))

    assert _problems(render_adf_document(lowered)) == []


def test_the_example_document_is_accepted_by_the_adf_schema() -> None:
    assert _problems(render_adf_document(lower_report(load_report(EXAMPLE)), SITE)) == []
