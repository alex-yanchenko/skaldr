import json
from collections.abc import Iterator, Mapping
from datetime import date
from typing import Any, Protocol

import pytest
from jsonschema import Draft4Validator, ValidationError

from skaldr.export.adf import IssueLinks, render_adf, render_adf_document
from skaldr.export.inline import plain
from skaldr.export.lower import lower_report
from skaldr.export.tree import (
    Callout,
    Columns,
    Divider,
    GridColumn,
    LinkCard,
    ListEntry,
    ListNode,
    Node,
    Paragraph,
    Quote,
    TableCell,
    TableNode,
    TableRow,
    Toggle,
)
from skaldr.models import parse_report
from skaldr.richtext import DateMention, Plain, Styled
from tests.conftest import REPO_ROOT
from tests.factories import API_BADGES, BADGE_AND_STATE_BLOCKS, accepted_example, make_report
from tests.factories.adf_factory import minimal_nodes, showcase_nodes

ADF_SCHEMA_FILE = REPO_ROOT / "tests" / "schemas" / "adf-schema-57.7.4-full.json"
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


UPGRADED_FORMS = [
    pytest.param(LinkCard("Runbook", "https://example.com/runbook", "embed"), id="embed-card"),
    pytest.param(Toggle(plain("More"), None, (Paragraph(plain("body")),), open=True), id="open-toggle"),
    pytest.param(
        Callout("info", (LinkCard("Runbook", "https://example.com/runbook", "card", domain="example.com"),)),
        id="block-card-in-a-panel",
    ),
    pytest.param(
        Quote(
            (Paragraph(plain("Said:")), ListNode("number", (ListEntry(plain("a")),), start=3)), plain("Ana")
        ),
        id="quote-holding-a-list",
    ),
    pytest.param(
        TableNode(
            (TableCell(plain("Steps")),),
            (
                TableRow(
                    (
                        TableCell(
                            (),
                            blocks=(Paragraph(plain("Fix:")), ListNode("bullet", (ListEntry(plain("a")),))),
                        ),
                    ),
                    tone="muted",
                ),
            ),
        ),
        id="muted-row-holding-a-list",
    ),
    pytest.param(
        Columns(
            (
                GridColumn(50, (Paragraph(plain("left")),)),
                GridColumn(
                    50,
                    (
                        Callout(
                            "warning",
                            (Toggle(plain("t"), None, (Paragraph(plain("c")),)), Divider()),
                            authored_as="grid cell",
                        ),
                    ),
                ),
            )
        ),
        id="toned-grid",
    ),
]


@pytest.mark.parametrize("node", UPGRADED_FORMS)
def test_each_upgraded_form_writes_a_document_the_adf_schema_accepts(node: Node) -> None:
    assert _problems(render_adf((node,))) == []


def test_a_document_using_every_block_inline_and_mark_is_accepted_by_the_adf_schema() -> None:
    assert _problems(render_adf(showcase_nodes(), SITE)) == []


def test_a_date_with_a_label_and_a_date_range_with_a_label_are_accepted_by_the_adf_schema() -> None:
    paragraph = Paragraph(
        (
            DateMention((Styled("bold", (Plain("1 Oct"),)),), date(2026, 10, 1), None),
            Plain(" "),
            DateMention((Plain("the week"),), date(2026, 10, 5), date(2026, 10, 9)),
        )
    )

    document = render_adf((paragraph,))

    assert (document, _problems(document)) == (
        {
            "version": 1,
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {"type": "text", "text": "1 Oct", "marks": [{"type": "strong"}]},
                        {"type": "text", "text": " "},
                        {"type": "date", "attrs": {"timestamp": "1790812800000"}},
                        {"type": "text", "text": " the week "},
                        {"type": "date", "attrs": {"timestamp": "1791158400000"}},
                        {"type": "text", "text": " to "},
                        {"type": "date", "attrs": {"timestamp": "1791504000000"}},
                    ],
                }
            ],
        },
        [],
    )


def test_the_badge_and_state_blocks_are_accepted_by_the_adf_schema() -> None:
    lowered = lower_report(parse_report(make_report(blocks=BADGE_AND_STATE_BLOCKS, badges=API_BADGES)))

    assert _problems(render_adf_document(lowered)) == []


def test_the_example_reworked_for_jira_less_the_blocks_adf_refuses_is_accepted_by_the_adf_schema() -> None:
    assert _problems(render_adf_document(lower_report(accepted_example("adf")), SITE)) == []
