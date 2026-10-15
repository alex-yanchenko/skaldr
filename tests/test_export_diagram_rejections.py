from pathlib import Path
from typing import Any

import pytest

from skaldr.cli import main
from skaldr.errors import ExportRejectedError
from skaldr.export.adf import render_adf
from skaldr.export.check import reject_what_the_target_cannot_show
from skaldr.export.lower import lower_report
from skaldr.export.tree import Diagram, TableNode
from skaldr.export_targets import EXPORT_TARGETS, ExportTarget
from skaldr.models import parse_report
from tests.conftest import REPO_ROOT
from tests.factories import lowered, make_report, slack_of, write_report
from tests.factories.capability_factory import (
    DIAGRAM_ACCEPTED_CASES,
    DIAGRAM_CASES,
    DIAGRAM_REFUSALS,
    DONUT,
    ONE_SERIES_CHARTS,
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
