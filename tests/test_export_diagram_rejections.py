import json
from pathlib import Path
from typing import Any

import pytest
from typing_extensions import assert_never

from skaldr.cli import main
from skaldr.errors import ExportInvariantError, ExportRejectedError
from skaldr.export import check as check_module
from skaldr.export.adf import render_adf
from skaldr.export.capabilities import CAPABILITIES, TARGET_SUBJECTS, Feature, Rejection, Swap
from skaldr.export.check import reject_what_the_target_cannot_show
from skaldr.export.lower import lower_report
from skaldr.export.markdown import render_markdown
from skaldr.export.notion import render_notion
from skaldr.export.slack import render_slack
from skaldr.export_targets import EXPORT_TARGETS, ExportTarget
from skaldr.models import parse_report
from tests.conftest import REPO_ROOT
from tests.factories import lowered, make_report, make_toggle, markdown_of, slack_of, write_report
from tests.factories.capability_factory import (
    DIAGRAM_ACCEPTED_CASES,
    DIAGRAM_CASES,
    DIAGRAM_REFUSALS,
    DONUT,
    FAN,
    FLOW,
    MATH_BLOCKS,
    RANGE,
    SWAPPED_BLOCKS,
    AcceptedCase,
    RefusedCase,
    xy_chart,
)

EXAMPLE = REPO_ROOT / "data" / "example.yaml"
EXAMPLE_RANGE_PATH = "blocks.4.range"


MERMAID_SEVERAL_SERIES_ERROR = (
    "a Mermaid xy chart cannot tell several series apart; the export should have written its data table"
)
TWO_SERIES_TABLE = "| Series | Mon | Tue |\n| --- | --- | --- |\n| Zone 1 | 4 | 6 |\n| Zone 2 | 1 | 2 |\n"
STACKED_TABLE = f"{TWO_SERIES_TABLE}| **Total** | **5** | **8** |\n"
ONE_BAR_MERMAID = '```mermaid\nxychart-beta\n    x-axis ["Mon", "Tue"]\n    bar [4, 6]\n```\n'
SWAP_CELLS = [
    pytest.param(feature, target, id=f"{target}-{feature}")
    for feature, cells in CAPABILITIES.items()
    for target, capability in cells.items()
    if isinstance(capability, Swap)
]


def _check(blocks: list[dict[str, Any]], target: ExportTarget) -> None:
    report = parse_report(make_report(blocks=blocks))
    reject_what_the_target_cannot_show(report, lower_report(report), target)


def _written_without_the_check(blocks: list[dict[str, Any]], target: ExportTarget) -> str:
    nodes = lowered(blocks)
    match target:
        case "markdown":
            return render_markdown(nodes)
        case "notion":
            return render_notion(nodes)
        case "adf":
            return json.dumps(render_adf(nodes))
        case "slack":
            return render_slack(nodes)
        case _:
            assert_never(target)


@pytest.mark.parametrize(("feature", "target"), SWAP_CELLS)
def test_a_writer_swaps_a_feature_only_while_its_capability_cell_lists_the_swap(
    monkeypatch: pytest.MonkeyPatch, feature: Feature, target: ExportTarget
) -> None:
    monkeypatch.setitem(CAPABILITIES[feature], target, "keep")

    with pytest.raises(ExportInvariantError) as raised:
        _written_without_the_check(SWAPPED_BLOCKS[feature], target)

    assert str(raised.value) == _what_a_writer_without_the_swap_raises(feature, target)


def _what_a_writer_without_the_swap_raises(feature: Feature, target: ExportTarget) -> str:
    if target in ("markdown", "notion"):
        return MERMAID_SEVERAL_SERIES_ERROR
    return f"{TARGET_SUBJECTS[target]} has no form for '{feature}'; the export check should have refused it"


@pytest.mark.parametrize("target", ["adf", "slack"])
@pytest.mark.parametrize("blocks", [pytest.param([FLOW], id="flow"), pytest.param([FAN], id="fan")])
def test_a_writer_that_cannot_draw_a_diagram_raises_an_internal_error_for_a_flow_or_fan_handed_to_it(
    target: ExportTarget, blocks: list[dict[str, Any]]
) -> None:
    with pytest.raises(ExportInvariantError) as raised:
        _written_without_the_check(blocks, target)

    assert str(raised.value) == (
        f"{TARGET_SUBJECTS[target]} has no form for '{blocks[0]['type']} diagram'; "
        "the export check should have refused it"
    )


@pytest.mark.parametrize(
    ("target", "table"),
    [
        pytest.param(
            "markdown",
            "| Slice | Value | Share |\n| --- | --- | --- |\n"
            "| Fixed | 9 | 75% |\n| Open | 3 | 25% |\n| **Total** | **12** |  |\n",
            id="markdown",
        ),
        pytest.param(
            "notion",
            '<table fit-page-width="true" header-row="true">\n'
            "\t<tr>\n\t\t<td>**Slice**</td>\n\t\t<td>**Value**</td>\n\t\t<td>**Share**</td>\n\t</tr>\n"
            '\t<tr>\n\t\t<td color="green_bg">Fixed</td>\n\t\t<td>9</td>\n\t\t<td>75%</td>\n\t</tr>\n'
            "\t<tr>\n\t\t<td>Open</td>\n\t\t<td>3</td>\n\t\t<td>25%</td>\n\t</tr>\n"
            "\t<tr>\n\t\t<td>**Total**</td>\n\t\t<td>**12**</td>\n\t\t<td></td>\n\t</tr>\n"
            "</table>\n",
            id="notion",
        ),
    ],
)
def test_a_markdown_writer_writes_a_chart_as_its_data_table_alone_once_its_cell_lists_the_swap(
    monkeypatch: pytest.MonkeyPatch, target: ExportTarget, table: str
) -> None:
    monkeypatch.setitem(CAPABILITIES["chart"], target, Swap("the chart's data table"))

    assert _written_without_the_check([DONUT], target) == table


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
        f"{STACKED_TABLE}"
    )


@pytest.mark.parametrize(
    ("target", "written"),
    [
        pytest.param("markdown", TWO_SERIES_TABLE, id="markdown"),
        pytest.param(
            "notion",
            '<table fit-page-width="true" header-row="true">\n'
            "\t<tr>\n\t\t<td>**Series**</td>\n\t\t<td>**Mon**</td>\n\t\t<td>**Tue**</td>\n\t</tr>\n"
            "\t<tr>\n\t\t<td>Zone 1</td>\n\t\t<td>4</td>\n\t\t<td>6</td>\n\t</tr>\n"
            "\t<tr>\n\t\t<td>Zone 2</td>\n\t\t<td>1</td>\n\t\t<td>2</td>\n\t</tr>\n"
            "</table>\n",
            id="notion",
        ),
    ],
)
def test_github_and_notion_write_a_chart_with_several_series_as_its_data_table_alone(
    target: ExportTarget, written: str
) -> None:
    assert _written_without_the_check([xy_chart("line", [4, 6], [1, 2])], target) == written


def test_a_stacked_chart_with_several_series_adds_a_total_row_holding_each_category_s_stack() -> None:
    assert markdown_of([xy_chart("bar", [4, 6], [1, 2], stacked=True)]) == STACKED_TABLE


@pytest.mark.parametrize("target", ["markdown", "notion"])
def test_a_stacked_bar_chart_with_one_series_is_drawn_as_the_same_mermaid_chart_as_an_unstacked_one(
    target: ExportTarget,
) -> None:
    stacked = _written_without_the_check([xy_chart("bar", [4, 6], stacked=True)], target)

    assert (stacked, stacked.startswith(ONE_BAR_MERMAID)) == (
        _written_without_the_check([xy_chart("bar", [4, 6])], target),
        True,
    )


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
