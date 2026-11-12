import json
from typing import Any

import pytest

from skaldr.export.adf import render_adf_document
from skaldr.export.lower import lower_report
from skaldr.models import parse_report
from tests.factories import make_report, markdown_of, notion_of, slack_of

DOUBLE_COLON_LABELS: list[dict[str, Any]] = [
    {"type": "key_value", "pairs": [{"label": "Ratio::", "value": "1"}]},
    {"type": "def_list", "items": [{"term": "Term::", "body": "b"}]},
    {"type": "cards", "items": [{"label": "K::", "value": 2}]},
]


def _adf_of(blocks: list[dict[str, Any]]) -> list[Any]:
    document = render_adf_document(lower_report(parse_report(make_report(blocks=blocks))))
    return json.loads(json.dumps(document))["content"]


def _header_cell(label: str) -> dict[str, Any]:
    return {
        "type": "tableHeader",
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": label}]}],
    }


def _body_cell(text: str) -> dict[str, Any]:
    return {
        "type": "tableCell",
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}],
    }


def _table(*rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "type": "table",
        "attrs": {"isNumberColumnEnabled": False, "layout": "default"},
        "content": [{"type": "tableRow", "content": list(row)} for row in rows],
    }


def test_a_label_ending_in_two_colons_loses_one_in_markdown() -> None:
    assert markdown_of(DOUBLE_COLON_LABELS) == (
        "- **Ratio:**: 1\n\n<dl>\n<dt>Term:</dt>\n<dd>\n\nb\n\n</dd>\n</dl>\n\n| K: |\n| --- |\n| 2 |\n"
    )


def test_a_label_ending_in_two_colons_loses_one_in_notion() -> None:
    assert notion_of(DOUBLE_COLON_LABELS) == (
        '<table fit-page-width="true" header-column="true">\n\t<tr>\n\t\t<td>**Ratio:**</td>\n'
        "\t\t<td>1</td>\n\t</tr>\n</table>\n**Term:**\n\tb\n"
        '<callout icon="📝" color="gray_bg">\n\t**K:**\n\t2\n</callout>\n'
    )


def test_a_label_ending_in_two_colons_loses_one_in_slack() -> None:
    assert slack_of(DOUBLE_COLON_LABELS) == "* **Ratio:**: 1\n\n**Term:**\n\nb\n\n**K:**: 2\n"


def test_a_label_ending_in_two_colons_loses_one_in_adf() -> None:
    assert _adf_of(DOUBLE_COLON_LABELS) == [
        _table([_header_cell("Ratio:"), _body_cell("1")]),
        _table([_header_cell("Term:"), _body_cell("b")]),
        _table([_header_cell("K:")], [_body_cell("2")]),
    ]


def test_a_code_label_loses_one_trailing_colon() -> None:
    assert markdown_of([{"type": "code", "label": "Run:", "content": "ls", "lang": "shell"}]) == (
        "**Run**\n\n```shell\nls\n```\n"
    )


@pytest.mark.parametrize("label", [":", " : "], ids=["colon", "spaced-colon"])
def test_a_code_label_that_is_only_a_colon_writes_no_paragraph(label: str) -> None:
    assert markdown_of([{"type": "code", "label": label, "content": "ls", "lang": "shell"}]) == (
        "```shell\nls\n```\n"
    )
