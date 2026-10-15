from pathlib import Path
from typing import Any

import pytest

from skaldr.cli import main
from skaldr.errors import ExportRejectedError
from skaldr.export import check as check_module
from skaldr.export.adf import render_adf
from skaldr.export.capabilities import CAPABILITIES, Feature, Rejection
from skaldr.export.check import reject_what_the_target_cannot_show
from skaldr.export.lower import lower_report
from skaldr.export.tree import Diagram, TableNode
from skaldr.export_targets import EXPORT_TARGETS, ExportTarget
from skaldr.models import parse_report
from tests.conftest import REPO_ROOT
from tests.factories import lowered, make_report, make_toggle, slack_of, write_report
from tests.factories.capability_factory import (
    DIAGRAM_ACCEPTED_CASES,
    DIAGRAM_CASES,
    DIAGRAM_REFUSALS,
    DONUT,
    FLOW,
    MATH_BLOCKS,
    ONE_SERIES_CHARTS,
    RANGE,
    SEVERAL_SERIES_OR_STACKED,
    AcceptedCase,
    RefusedCase,
    xy_chart,
)

EXAMPLE = REPO_ROOT / "data" / "example.yaml"
EXAMPLE_RANGE_PATH = "blocks.4.range"


def _check(blocks: list[dict[str, Any]], target: ExportTarget) -> None:
    report = parse_report(make_report(blocks=blocks))
    reject_what_the_target_cannot_show(report, lower_report(report), target)


@pytest.mark.parametrize("case", DIAGRAM_CASES)
def test_the_check_refuses_each_diagram_case_naming_its_yaml_path(case: RefusedCase) -> None:
    with pytest.raises(ExportRejectedError) as raised:
        _check(case.blocks, case.target)

    assert vars(raised.value) == case.rejection()


def test_the_first_refusal_in_the_document_is_reported_though_a_later_block_is_found_on_the_model() -> None:
    with pytest.raises(ExportRejectedError) as raised:
        _check([FLOW, RANGE], "adf")

    assert raised.value.where == "at blocks.0.flow"


@pytest.mark.parametrize("case", DIAGRAM_CASES)
def test_export_refuses_each_diagram_case_and_writes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], case: RefusedCase
) -> None:
    data_path = write_report(tmp_path, make_report(blocks=case.blocks))
    export_dir = tmp_path / "exported"

    assert main([str(data_path), "--export", case.target, "--export-dir", str(export_dir)]) == 1

    captured = capsys.readouterr()
    assert (captured.out, captured.err, export_dir.exists()) == ("", f"error: {case.message()}\n", False)


@pytest.mark.parametrize("case", DIAGRAM_ACCEPTED_CASES)
def test_a_target_that_shows_a_diagram_case_exports_it(tmp_path: Path, case: AcceptedCase) -> None:
    data_path = write_report(tmp_path, make_report(blocks=case.blocks))

    assert main([str(data_path), "--export", case.target, "--export-dir", str(tmp_path / "exported")]) == 0


def test_a_slack_canvas_writes_each_chart_as_its_data_table_alone() -> None:
    charts = [{**DONUT, "title": "Mix"}, xy_chart("bar", [4, 6], [1, 2], stacked=True)]

    assert slack_of(charts) == (
        "**Mix**\n\n"
        "| Slice | Value | Share |\n| --- | --- | --- |\n"
        "| Fixed | 9 | 75% |\n| Open | 3 | 25% |\n| **Total** | **12** |  |\n\n"
        "| Series | Mon | Tue |\n| --- | --- | --- |\n| Zone 1 | 4 | 6 |\n| Zone 2 | 1 | 2 |\n"
    )


@pytest.mark.parametrize("chart", [*ONE_SERIES_CHARTS.values(), *SEVERAL_SERIES_OR_STACKED.values()])
def test_adf_writes_each_chart_as_exactly_its_data_table(chart: dict[str, Any]) -> None:
    (diagram,) = lowered([chart])
    assert isinstance(diagram, Diagram)

    assert render_adf((diagram,)) == render_adf(diagram.supplement)
    assert [type(node) for node in diagram.supplement] == [TableNode]


@pytest.mark.parametrize(
    ("feature", "blocks", "where"),
    [
        pytest.param("chart", [DONUT], "at blocks.0.chart", id="donut"),
        pytest.param("chart", [xy_chart("line", [1, 2])], "at blocks.0.chart", id="line"),
        pytest.param(
            "math block", [make_toggle(MATH_BLOCKS[0])], "at blocks.0.toggle.blocks.0.math", id="math"
        ),
        pytest.param(
            "inline math",
            [{"type": "list", "items": ["plain", {"text": "deep", "items": ["at $`x_i`$"]}]}],
            "at blocks.0.list",
            id="inline-math-in-a-nested-list-item",
        ),
        pytest.param(
            "inline math",
            [{"type": "text", "body": "**bold [$`x`$](https://example.com/x)**"}],
            "at blocks.0.text",
            id="inline-math-in-a-link-in-bold",
        ),
    ],
)
def test_the_check_finds_each_swapped_feature_where_a_target_would_refuse_it(
    monkeypatch: pytest.MonkeyPatch, feature: Feature, blocks: list[dict[str, Any]], where: str
) -> None:
    refusing = Rejection("refused", "instead")
    monkeypatch.setattr(check_module, "CAPABILITIES", {**CAPABILITIES, feature: {"adf": refusing}})

    with pytest.raises(ExportRejectedError) as raised:
        _check(blocks, "adf")

    assert vars(raised.value) == {"target": "adf", "why": "refused", "instead": "instead", "where": where}


def test_a_slack_canvas_writes_math_as_a_latex_code_block_and_inline_math_as_inline_code() -> None:
    assert slack_of(MATH_BLOCKS) == "```latex\nx^2 + 1\n```\n\nrate `x_i` now\n"


def test_adf_writes_math_as_a_latex_code_block_and_inline_math_as_a_code_mark() -> None:
    assert render_adf(lowered(MATH_BLOCKS)) == {
        "version": 1,
        "type": "doc",
        "content": [
            {
                "type": "codeBlock",
                "attrs": {"language": "latex"},
                "content": [{"type": "text", "text": "x^2 + 1"}],
            },
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "rate "},
                    {"type": "text", "text": "x_i", "marks": [{"type": "code"}]},
                    {"type": "text", "text": " now"},
                ],
            },
        ],
    }


@pytest.mark.parametrize("target", EXPORT_TARGETS)
def test_the_shipped_example_stays_an_html_showcase_that_every_export_refuses_for_its_range(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], target: ExportTarget
) -> None:
    export_dir = tmp_path / "exported"

    assert main([str(EXAMPLE), "--export", target, "--export-dir", str(export_dir)]) == 1

    refusal = DIAGRAM_REFUSALS[f"{target}-range"]
    captured = capsys.readouterr()
    assert (captured.err, export_dir.exists()) == (
        f"error: {refusal.why}, at {EXAMPLE_RANGE_PATH}; {refusal.instead}\n",
        False,
    )


@pytest.mark.parametrize("case", DIAGRAM_CASES)
def test_check_for_a_target_refuses_each_diagram_case(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], case: RefusedCase
) -> None:
    data_path = write_report(tmp_path, make_report(blocks=case.blocks))

    assert main(["--check", str(data_path), "--for", case.target]) == 1

    captured = capsys.readouterr()
    assert (captured.out, captured.err) == ("", f"FAIL  {data_path}: {case.message()}\n\n1 file failed\n")
