import json
from pathlib import Path
from typing import Any

import pytest
from typing_extensions import assert_never

from skaldr.cli import main
from skaldr.errors import ExportInvariantError, ExportRejectedError
from skaldr.export import check as check_module
from skaldr.export.adf import render_adf
from skaldr.export.capabilities import (
    CAPABILITIES,
    PANES_FEATURES,
    TARGET_SUBJECTS,
    Feature,
    Rejection,
    Swap,
    swaps,
)
from skaldr.export.check import reject_what_the_target_cannot_show
from skaldr.export.lower import lower_report
from skaldr.export.markdown import render_markdown
from skaldr.export.notion import render_notion
from skaldr.export.slack import render_slack
from skaldr.export_targets import EXPORT_TARGETS, ExportTarget
from skaldr.models import parse_report
from tests.conftest import REPO_ROOT
from tests.factories import (
    lowered,
    make_report,
    make_section,
    make_toggle,
    markdown_of,
    slack_of,
    write_report,
)
from tests.factories.capability_factory import (
    DATA_IMAGE,
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
    text_grid,
    xy_chart,
)

EXAMPLE = REPO_ROOT / "data" / "example.yaml"
EXAMPLE_RANGE_PATH = "blocks.4.range"


PAGE_NAMES: dict[ExportTarget, str] = {
    "markdown": "page.md",
    "notion": "page.md",
    "adf": "page.adf.json",
    "slack": "page.md",
}
ONE_SERIES_TABLE = "| Series | Mon | Tue |\n| --- | --- | --- |\n| Zone 1 | 4 | 6 |\n"
TWO_SERIES_TABLE = f"{ONE_SERIES_TABLE}| Zone 2 | 1 | 2 |\n"
LATEX_FENCE = "```latex\nx^2 + 1\n```\n"
INLINE_LATEX = "rate `x_i` now\n"


def _notion_table(*rows: tuple[str, ...]) -> str:
    lines = ["\t<tr>\n" + "".join(f"\t\t<td>{cell}</td>\n" for cell in row) + "\t</tr>\n" for row in rows]
    return '<table fit-page-width="true" header-row="true">\n' + "".join(lines) + "</table>\n"


def _adf_text(text: str, *marks: dict[str, Any]) -> dict[str, Any]:
    return {"type": "text", "text": text, **({"marks": list(marks)} if marks else {})}


def _adf_cell(kind: str, text: str) -> dict[str, Any]:
    return {"type": kind, "content": [{"type": "paragraph", "content": [_adf_text(text)]}]}


def _adf_doc(*content: dict[str, Any]) -> dict[str, Any]:
    return {"version": 1, "type": "doc", "content": list(content)}


def _adf_series_table(*rows: tuple[str, str, str]) -> dict[str, Any]:
    header = {
        "type": "tableRow",
        "content": [_adf_cell("tableHeader", text) for text in ("Series", "Mon", "Tue")],
    }
    body = [{"type": "tableRow", "content": [_adf_cell("tableCell", text) for text in row]} for row in rows]
    attrs = {"isNumberColumnEnabled": False, "layout": "default"}
    return _adf_doc({"type": "table", "attrs": attrs, "content": [header, *body]})


SERIES_HEADER = ("**Series**", "**Mon**", "**Tue**")
SWAPPED_FORMS: dict[Feature, dict[ExportTarget, Any]] = {
    "chart": {
        "markdown": ONE_SERIES_TABLE,
        "notion": _notion_table(SERIES_HEADER, ("Zone 1", "4", "6")),
        "adf": _adf_series_table(("Zone 1", "4", "6")),
        "slack": ONE_SERIES_TABLE,
    },
    "chart with several series": {
        "markdown": TWO_SERIES_TABLE,
        "notion": _notion_table(SERIES_HEADER, ("Zone 1", "4", "6"), ("Zone 2", "1", "2")),
        "adf": _adf_series_table(("Zone 1", "4", "6"), ("Zone 2", "1", "2")),
        "slack": TWO_SERIES_TABLE,
    },
    "math block": {
        "markdown": LATEX_FENCE,
        "notion": LATEX_FENCE,
        "adf": _adf_doc(
            {"type": "codeBlock", "attrs": {"language": "latex"}, "content": [_adf_text("x^2 + 1")]}
        ),
        "slack": LATEX_FENCE,
    },
    "inline math": {
        "markdown": INLINE_LATEX,
        "notion": INLINE_LATEX,
        "adf": _adf_doc(
            {
                "type": "paragraph",
                "content": [_adf_text("rate "), _adf_text("x_i", {"type": "code"}), _adf_text(" now")],
            }
        ),
        "slack": INLINE_LATEX,
    },
}
STACKED_TABLE = f"{TWO_SERIES_TABLE}| **Total** | **5** | **8** |\n"
ONE_BAR_MERMAID_WITH_PAGE_PALETTE = (
    '```mermaid\n%%{init: {"theme": "base", '
    '"themeVariables": {"xyChart": {"plotColorPalette": "#1d4ed8"}}}}%%\n'
    'xychart-beta\n    x-axis ["Mon", "Tue"]\n    bar [4, 6]\n```\n'
)
SWAP_CELLS = [
    pytest.param(feature, target, id=f"{target}-{feature}")
    for feature, cells in CAPABILITIES.items()
    for target, capability in cells.items()
    if isinstance(capability, Swap) and feature not in PANES_FEATURES.values()
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

    assert str(raised.value) == (
        f"{TARGET_SUBJECTS[target]} has no form for '{feature}'; the export check should have refused it"
    )


@pytest.mark.parametrize(
    ("feature", "target"),
    [
        pytest.param(feature, target, id=f"{target}-{feature}")
        for feature in SWAPPED_BLOCKS
        for target in EXPORT_TARGETS
    ],
)
def test_a_writer_writes_the_swapped_form_exactly_where_the_capability_table_lists_a_swap(
    feature: Feature, target: ExportTarget
) -> None:
    written = _written_without_the_check(SWAPPED_BLOCKS[feature], target)
    form = SWAPPED_FORMS[feature][target]
    is_the_swapped_form = json.loads(written) == form if target == "adf" else written == form

    assert is_the_swapped_form == swaps(feature, target)


@pytest.mark.parametrize("target", ["markdown", "notion"])
def test_a_one_series_chart_is_written_as_its_data_table_once_its_cell_lists_a_swap(
    monkeypatch: pytest.MonkeyPatch, target: ExportTarget
) -> None:
    monkeypatch.setitem(CAPABILITIES["chart"], target, Swap("the chart's data table"))

    assert _written_without_the_check(SWAPPED_BLOCKS["chart"], target) == SWAPPED_FORMS["chart"][target]


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


@pytest.mark.parametrize("target", EXPORT_TARGETS)
def test_every_writer_raises_an_internal_error_for_an_image_from_a_data_uri_handed_to_it(
    target: ExportTarget,
) -> None:
    with pytest.raises(ExportInvariantError) as raised:
        _written_without_the_check([DATA_IMAGE], target)

    assert str(raised.value) == (
        f"{TARGET_SUBJECTS[target]} has no form for 'image from a data: URI'; "
        "the export check should have refused it"
    )


@pytest.mark.parametrize("case", DIAGRAM_CASES)
def test_the_check_refuses_each_diagram_case_naming_its_yaml_path(case: RefusedCase) -> None:
    with pytest.raises(ExportRejectedError) as raised:
        _check(case.blocks, case.target)

    assert vars(raised.value) == case.rejection()


def test_the_first_refusal_in_the_document_is_reported_though_a_later_block_is_found_on_the_model() -> None:
    with pytest.raises(ExportRejectedError) as raised:
        _check([FLOW, RANGE], "adf")

    assert raised.value.where == "at blocks.0.flow"


def _nine_texts() -> list[dict[str, Any]]:
    return [{"type": "text", "body": f"Row {index}."} for index in range(9)]


@pytest.mark.parametrize(
    ("blocks", "target", "where"),
    [
        pytest.param([*_nine_texts(), FLOW, RANGE], "adf", "at blocks.9.flow", id="flow-at-9-range-at-10"),
        pytest.param([*_nine_texts(), RANGE, FLOW], "adf", "at blocks.9.range", id="range-at-9-flow-at-10"),
        pytest.param(
            [make_section("counts", blocks=[*_nine_texts(), RANGE, FLOW])],
            "adf",
            "at blocks.0.section.blocks.9.range",
            id="range-at-9-then-a-flow-at-10-in-a-section",
        ),
    ],
)
def test_the_first_refusal_reported_compares_the_indexes_of_a_yaml_path_as_numbers(
    blocks: list[dict[str, Any]], target: ExportTarget, where: str
) -> None:
    with pytest.raises(ExportRejectedError) as raised:
        _check(blocks, target)

    assert raised.value.where == where


def test_a_range_in_the_first_walkthrough_step_is_reported_before_a_grid_in_the_second() -> None:
    steps = [{"label": "Scan", "detail": [RANGE]}, {"label": "Count", "detail": [text_grid()]}]

    with pytest.raises(ExportRejectedError) as raised:
        _check([{"type": "walkthrough", "steps": steps}], "slack")

    assert raised.value.where == "at blocks.0.walkthrough.steps.0.detail.0.range"


def test_a_container_the_target_cannot_place_is_reported_before_an_image_inside_it() -> None:
    with pytest.raises(ExportRejectedError) as raised:
        _check([make_toggle(make_toggle(make_toggle(DATA_IMAGE)))], "adf")

    assert vars(raised.value) == {
        "target": "adf",
        "why": "ADF cannot place a toggle inside a toggle that is itself inside a toggle",
        "instead": "move the toggle out of the toggle",
        "where": "at blocks.0.toggle.blocks.0.toggle.blocks.0.toggle",
    }


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
    data_path = write_report(tmp_path, case.report())
    export_dir = tmp_path / "exported"

    exit_code = main([str(data_path), "--export", case.target, "--export-dir", str(export_dir)])

    page = (export_dir / PAGE_NAMES[case.target]).read_text(encoding="utf-8")
    assert (exit_code, page if case.written is not None else None) == (0, case.written)


@pytest.mark.parametrize("case", DIAGRAM_ACCEPTED_CASES)
def test_check_for_a_target_passes_each_case_the_target_shows(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], case: AcceptedCase
) -> None:
    data_path = write_report(tmp_path, case.report())

    exit_code = main(["--check", str(data_path), "--for", case.target])

    assert (exit_code, capsys.readouterr().err) == (0, "")


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


def test_a_stacked_chart_with_several_series_adds_a_total_row_holding_the_stack_of_each_category() -> None:
    assert markdown_of([xy_chart("bar", [4, 6], [1, 2], stacked=True)]) == STACKED_TABLE


@pytest.mark.parametrize(
    ("target", "chart_fence"),
    [
        pytest.param("markdown", ONE_BAR_MERMAID_WITH_PAGE_PALETTE, id="markdown"),
        pytest.param("notion", ONE_BAR_MERMAID_WITH_PAGE_PALETTE, id="notion"),
    ],
)
def test_a_stacked_bar_chart_with_one_series_is_drawn_as_the_same_mermaid_chart_as_an_unstacked_one(
    target: ExportTarget, chart_fence: str
) -> None:
    stacked = _written_without_the_check([xy_chart("bar", [4, 6], stacked=True)], target)

    assert (stacked, stacked.startswith(chart_fence)) == (
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
        pytest.param(
            "chart",
            [xy_chart("bar", [4, 6], stacked=True)],
            "at blocks.0.chart",
            id="stacked-bar-with-one-series-is-a-chart",
        ),
    ],
)
def test_the_check_names_the_yaml_path_of_each_swapped_feature(
    monkeypatch: pytest.MonkeyPatch, feature: Feature, blocks: list[dict[str, Any]], where: str
) -> None:
    refusing = Rejection("refused", "instead", in_the_guide="refused here")
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
def test_every_export_refuses_the_shipped_example_at_its_range(
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
