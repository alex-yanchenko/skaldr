import inspect
from collections.abc import Callable
from typing import Any, get_args, get_type_hints

import pytest
from pydantic import BaseModel

from skaldr import models, render
from skaldr.compute import rich_text_strings
from skaldr.export import inline
from skaldr.export.lower import lower_report
from skaldr.models import RichTextMarker
from skaldr.richtext import Rich, RichContext, parse_rich
from tests.conftest import REPO_ROOT
from tests.factories import make_report

TABLE_CELL_FIELDS = frozenset({"Group.rows", "Table.rows"})
PLAIN_TEXT_FIELDS = frozenset(
    {
        "Badge.label",
        "Badge.legend",
        "BadgeGroup.label",
        "BadgeLiteral.label",
        "BadgeRef.key",
        "BadgeRow.label",
        "Callout.title",
        "Callout.icon",
        "Card.label",
        "Card.value",
        "Card.note",
        "Card.badges",
        "Card.badge",
        "Card.of_matrix",
        "Card.of_tables",
        "CardDelta.label",
        "Chart.title",
        "Chart.categories",
        "ChartSeries.label",
        "ChartSlice.label",
        "Code.content",
        "Code.label",
        "Code.lang",
        "Column.key",
        "Column.label",
        "Comparison.options",
        "ComparisonRow.feature",
        "DefItem.term",
        "Fact.label",
        "Fact.value",
        "FlowStep.label",
        "FlowStep.badges",
        "Group.name",
        "Handled.label",
        "Heading.text",
        "Heading.id",
        "Image.src",
        "Image.alt",
        "Image.caption",
        "Index.parts",
        "InnerToggle.title",
        "KVPair.label",
        "Link.url",
        "Link.title",
        "Link.caption",
        "Math.expression",
        "Matrix.rows",
        "Matrix.columns",
        "Matrix.id",
        "MatrixCell.row",
        "MatrixCell.col",
        "MatrixCell.badge",
        "MatrixCell.label",
        "Meta.title",
        "Meta.subtitle",
        "Meta.date",
        "Meta.icon",
        "Meta.cover",
        "Meta.updated",
        "MeterItem.label",
        "Note.title",
        "Note.icon",
        "Panel.title",
        "Part.title",
        "Quote.cite",
        "RangeAxis.min",
        "RangeAxis.max",
        "RangeSegment.label",
        "Reconcile.column",
        "ReferenceItem.key",
        "ReferenceItem.url",
        "Report.badges",
        "Request.id",
        "Request.label",
        "Request.url",
        "Request.command",
        "Request.headers",
        "Request.body",
        "Request.case_variable",
        "RequestCapture.name",
        "RequestCapture.json_path",
        "RequestCase.label",
        "RequestCase.value",
        "RequestCase.values",
        "RequestCase.headers",
        "RequestCase.headers_add",
        "RequestCase.command",
        "RequestFlow.id",
        "RequestFlow.label",
        "RequestQuery.content",
        "RequestQuery.lang",
        "RequestQuery.runner",
        "RequestResponse.reason",
        "RequestResponse.headers",
        "RequestResponse.body",
        "RequestStep.label",
        "RequestStep.url",
        "RequestStep.command",
        "RequestStep.headers",
        "RequestStep.body",
        "RequestStep.case_variable",
        "RequestVariable.name",
        "RequestVariable.label",
        "RequestVariable.example",
        "Rollup.by",
        "Rollup.label",
        "Section.title",
        "Section.id",
        "Section.updated",
        "SwimlaneColumn.name",
        "SwimlaneColumn.id",
        "SwimlaneColumn.sub",
        "SwimlaneGroup.name",
        "SwimlaneGroup.columns",
        "SwimlaneLane.name",
        "SwimlaneLane.id",
        "SwimlaneStep.lane",
        "SwimlaneStep.col",
        "SwimlaneStep.n",
        "SwimlaneStep.label",
        "SwimlaneStep.group",
        "SwimlaneStep.url",
        "SwimlaneStep.id",
        "SwimlaneStep.depends_on",
        "Tab.label",
        "Table.tint_by",
        "Table.id",
        "TimelineItem.time",
        "TimelineItem.title",
        "TimelineItem.badges",
        "Toggle.title",
        "Totals.column",
        "WalkthroughStep.label",
        "_RequestCore.label",
        "_RequestCore.url",
        "_RequestCore.command",
        "_RequestCore.headers",
        "_RequestCore.body",
        "_RequestCore.case_variable",
        "_ToggleBase.title",
        "_VariableOwner.id",
    }
)
MULTI_PARAGRAPH_BLOCKS: list[dict[str, Any]] = [
    {"type": "list", "items": ["one\n\ntwo **three**", {"text": "a\n\nb", "items": [" c \n\n d "]}]},
    {"type": "callout", "tone": "info", "body": " first *x* \n\n second \n\n"},
    {"type": "key_value", "pairs": [{"label": "K", "value": "v\n\nw"}]},
]


def _holds_str(hint: object) -> bool:
    return hint is str or any(_holds_str(argument) for argument in get_args(hint))


def _is_marked_rich(hint: object) -> bool:
    return any(
        isinstance(argument, RichTextMarker) or _is_marked_rich(argument) for argument in get_args(hint)
    )


def _unmarked_text_fields() -> set[str]:
    unmarked: set[str] = set()
    for name, model in inspect.getmembers(models, inspect.isclass):
        if not issubclass(model, BaseModel) or model.__module__ != models.__name__:
            continue
        hints = get_type_hints(model, include_extras=True)
        unmarked |= {
            f"{name}.{field}"
            for field in model.model_fields
            if _holds_str(hints[field]) and not _is_marked_rich(hints[field])
        }
    return unmarked


def test_every_text_field_is_classified_as_rich_or_plain() -> None:
    assert sorted(_unmarked_text_fields()) == sorted(PLAIN_TEXT_FIELDS | TABLE_CELL_FIELDS)


def _recording_parse_rich(seen: set[str]) -> Callable[[str, RichContext | None], Rich]:
    def parse(text: str, context: RichContext | None = None) -> Rich:
        seen.add(text)
        return parse_rich(text, context)

    return parse


def _report(source: str) -> models.Report:
    if source == "multi-paragraph":
        return models.parse_report(make_report(blocks=MULTI_PARAGRAPH_BLOCKS))
    return models.load_report(REPO_ROOT / source)


@pytest.mark.parametrize("source", ["data/example.yaml", "examples/sales-pipeline.yaml", "multi-paragraph"])
def test_render_and_export_parse_exactly_the_validated_strings(
    monkeypatch: pytest.MonkeyPatch, source: str
) -> None:
    report = _report(source)
    rendered: set[str] = set()
    exported: set[str] = set()
    monkeypatch.setattr(render, "parse_rich", _recording_parse_rich(rendered))
    monkeypatch.setattr(inline, "parse_rich", _recording_parse_rich(exported))

    render.render_html(report)
    lower_report(report)

    validated = {text for _, text in rich_text_strings(report) if text}
    assert (rendered - {""}, exported - {""}) == (validated, validated)


def test_the_validated_strings_follow_each_fields_paragraph_policy() -> None:
    report = _report("multi-paragraph")

    assert list(rich_text_strings(report)) == [
        (("blocks", "0", "items", "0"), "one\n\ntwo **three**"),
        (("blocks", "0", "items", "1", "text"), "a\n\nb"),
        (("blocks", "0", "items", "1", "items", "0"), " c \n\n d "),
        (("blocks", "1", "body"), "first *x*"),
        (("blocks", "1", "body"), "second"),
        (("blocks", "2", "pairs", "0", "value"), "v\n\nw"),
    ]
