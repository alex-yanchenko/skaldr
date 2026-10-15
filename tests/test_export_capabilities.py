from dataclasses import fields, replace
from pathlib import Path
from string import Formatter
from typing import Any, Literal, get_args, get_type_hints

import pytest

from skaldr.cli import main
from skaldr.errors import ExportRejectedError
from skaldr.export.adf import render_adf
from skaldr.export.capabilities import CAPABILITIES, Capability, Details, Feature, Rejection, Swap
from skaldr.export.check import reject_what_the_target_cannot_show
from skaldr.export.lower import assemble_page, lower_regions, lower_report, lowering_for
from skaldr.export.notion import render_notion
from skaldr.export.tree import Paragraph, Tab, Tabs
from skaldr.export_targets import EXPORT_TARGETS, ExportTarget
from skaldr.models import parse_report
from skaldr.publish import ConnectorRegistry
from skaldr.publish.cli import main as publish_main
from skaldr.publish_block import JiraTarget, NotionTarget
from skaldr.richtext import Plain
from tests.factories import make_jira_target, make_report, make_request, make_section, make_tabs, write_report
from tests.factories.capability_factory import (
    ADF_CASES,
    CLEAN_BLOCKS,
    SEEDED_CASES,
    SEEDED_REFUSALS,
    TABLE,
    RefusedCase,
    in_a_panel,
    published_report,
    text_grid,
    two_cell_grid,
    walkthrough_holding,
)
from tests.factories.publish_factory import FakeConnector, FakeTransport

Verdict = Literal["keep", "reject", "swap"]
FEATURES: tuple[Feature, ...] = get_args(Feature)
DETAILS_KINDS: tuple[type[Details], ...] = get_args(Details)
SEEDED_VERDICTS: dict[Feature, dict[ExportTarget, Verdict]] = {
    "table inside a callout": {"adf": "reject", "slack": "reject"},
    "callout inside a callout": {"adf": "reject", "slack": "reject"},
    "quote inside a callout": {"adf": "reject"},
    "toggle inside a callout": {"adf": "reject", "slack": "reject"},
    "table inside a toggle inside a toggle": {"adf": "reject"},
    "toggle inside a toggle inside a toggle": {"adf": "reject"},
    "block inside a list item": {"slack": "reject"},
    "block inside a walkthrough step": {"slack": "reject"},
    "numbered list starting past 1": {"slack": "reject"},
    "table over 300 cells": {"slack": "reject"},
    "grid inside a walkthrough step": {"slack": "reject"},
    "subscript or superscript with no Unicode form": {"slack": "reject"},
    "divider inside a callout": {"slack": "reject"},
    "grid with more than three cells": {"slack": "reject"},
    "table inside a grid cell": {"adf": "reject", "slack": "reject"},
    "callout inside a grid cell": {"slack": "reject"},
    "divider inside a grid cell": {"slack": "reject"},
    "toned grid cell": {"slack": "reject"},
    "grid inside a grid cell": {"slack": "reject"},
    "divider inside a walkthrough step": {"adf": "reject"},
    "set of tabs": {"notion": "swap", "adf": "swap"},
    "request with several cases": {"notion": "swap", "adf": "swap"},
}
REQUEST_WITH_TWO_CASES = make_request(
    cases=[{"label": "a", "response": {"body": "1"}}, {"label": "b", "response": {"body": "2"}}]
)
SWAPPED_BLOCKS = [
    pytest.param(make_tabs(), id="tabs"),
    pytest.param(REQUEST_WITH_TWO_CASES, id="request-with-two-cases"),
]
SWAPPED_BLOCKS_OF_EACH_FEATURE = [
    pytest.param("set of tabs", make_tabs(), id="tabs"),
    pytest.param("request with several cases", REQUEST_WITH_TWO_CASES, id="request-with-two-cases"),
]
TWO_TABS = Tabs(
    (
        Tab((Plain("One"),), (Paragraph((Plain("a"),)),), "warning"),
        Tab((Plain("Two"),), (Paragraph((Plain("b"),)),)),
    )
)
REQUEST_CASES = replace(TWO_TABS, kind="request cases")
PANES_OF_EACH_FEATURE = [
    pytest.param("set of tabs", TWO_TABS, id="tabs"),
    pytest.param("request with several cases", REQUEST_CASES, id="request-cases"),
]
KEPT_BY_THE_OTHER_TARGETS = [
    pytest.param(case, other, id=f"{name}-kept-by-{other}")
    for name, case in SEEDED_REFUSALS.items()
    for other in EXPORT_TARGETS
    if other != case.target and other not in case.also_refused_by
]


def _features_carried_by(details: type[Details]) -> tuple[Feature, ...]:
    return get_args(get_type_hints(details)["feature"])


DETAILS_OF_A_FEATURE: dict[Feature, type[Details]] = {
    feature: details for details in DETAILS_KINDS for feature in _features_carried_by(details)
}
REJECTIONS = [
    pytest.param(capability, DETAILS_OF_A_FEATURE[feature], id=f"{target}-{feature}")
    for feature, cells in CAPABILITIES.items()
    for target, capability in cells.items()
    if isinstance(capability, Rejection)
]


def _verdict(capability: Capability) -> Verdict:
    if isinstance(capability, Rejection):
        return "reject"
    return "swap" if isinstance(capability, Swap) else capability


def _adf_expands(*titles: str) -> list[dict[str, Any]]:
    return [
        {
            "type": "expand",
            "attrs": {"title": title},
            "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}],
        }
        for title, text in zip(titles, "ab", strict=True)
    ]


def _template_fields(template: str) -> set[str]:
    return {name for _, name, _, _ in Formatter().parse(template) if name is not None}


def _check(blocks: list[dict[str, Any]], target: ExportTarget) -> None:
    report = parse_report(make_report(blocks=blocks))
    reject_what_the_target_cannot_show(report, lower_report(report), target)


def _publish_with_a_fake_jira(data_path: Path, transport: FakeTransport) -> int:
    registry = ConnectorRegistry(
        [FakeConnector(NotionTarget, transport), FakeConnector(JiraTarget, transport, export_target="adf")]
    )
    return publish_main(["publish", str(data_path), "--apply"], registry=registry)


def test_the_table_holds_a_cell_for_every_feature_and_target_and_rejects_only_the_seeded_ones() -> None:
    verdicts = {
        feature: {target: _verdict(capability) for target, capability in cells.items()}
        for feature, cells in CAPABILITIES.items()
    }

    assert verdicts == {
        feature: {target: seeded.get(target, "keep") for target in EXPORT_TARGETS}
        for feature, seeded in SEEDED_VERDICTS.items()
    }


def test_each_feature_is_carried_by_exactly_one_kind_of_details() -> None:
    carried = [feature for details in DETAILS_KINDS for feature in _features_carried_by(details)]

    assert sorted(carried) == sorted(FEATURES)


@pytest.mark.parametrize(("rejection", "details"), REJECTIONS)
def test_every_rejection_names_only_details_its_feature_supplies(
    rejection: Rejection, details: type[Details]
) -> None:
    supplied = {detail.name for detail in fields(details)}

    assert _template_fields(rejection.why) | _template_fields(rejection.instead) <= supplied


def test_every_rejection_in_the_table_has_a_seeded_case_and_every_seeded_case_names_a_rejection() -> None:
    rejections = {
        (feature, target)
        for feature, cells in CAPABILITIES.items()
        for target, capability in cells.items()
        if isinstance(capability, Rejection)
    }

    assert {(case.feature, case.target) for case in SEEDED_REFUSALS.values()} == rejections


@pytest.mark.parametrize("case", SEEDED_CASES)
def test_each_seeded_case_passes_once_the_cell_it_names_keeps_the_feature(
    monkeypatch: pytest.MonkeyPatch, case: RefusedCase
) -> None:
    monkeypatch.setitem(CAPABILITIES[case.feature], case.target, "keep")

    _check(case.blocks, case.target)


@pytest.mark.parametrize("case", SEEDED_CASES)
def test_the_check_refuses_each_seeded_case_naming_its_yaml_path(case: RefusedCase) -> None:
    with pytest.raises(ExportRejectedError) as raised:
        _check(case.blocks, case.target)

    assert vars(raised.value) == case.rejection()


@pytest.mark.parametrize(("case", "other"), KEPT_BY_THE_OTHER_TARGETS)
def test_every_other_target_keeps_what_one_target_refuses(case: RefusedCase, other: ExportTarget) -> None:
    _check(case.blocks, other)


@pytest.mark.parametrize("target", EXPORT_TARGETS)
def test_a_document_no_target_refuses_passes_the_check(target: ExportTarget) -> None:
    _check(CLEAN_BLOCKS, target)


@pytest.mark.parametrize("target", EXPORT_TARGETS)
@pytest.mark.parametrize("block", SWAPPED_BLOCKS)
def test_a_block_a_target_swaps_for_another_form_passes_the_check(
    block: dict[str, Any], target: ExportTarget
) -> None:
    _check([block], target)


@pytest.mark.parametrize(("feature", "node"), PANES_OF_EACH_FEATURE)
def test_notion_writes_native_tabs_once_the_table_keeps_the_feature(
    monkeypatch: pytest.MonkeyPatch, feature: Feature, node: Tabs
) -> None:
    monkeypatch.setitem(CAPABILITIES[feature], "notion", "keep")

    assert render_notion([node]) == (
        '<tabs>\n\t<tab icon="⚠️">\n\t\tOne\n\t\ta\n\t</tab>\n\t<tab>\n\t\tTwo\n\t\tb\n\t</tab>\n</tabs>\n'
    )


@pytest.mark.parametrize(("feature", "node"), PANES_OF_EACH_FEATURE)
def test_adf_writes_expands_titled_without_an_icon_once_the_table_keeps_the_feature(
    monkeypatch: pytest.MonkeyPatch, feature: Feature, node: Tabs
) -> None:
    monkeypatch.setitem(CAPABILITIES[feature], "adf", "keep")

    assert render_adf([node])["content"] == _adf_expands("One", "Two")


@pytest.mark.parametrize(
    ("kept_feature", "swapped_node"),
    [
        pytest.param("set of tabs", REQUEST_CASES, id="tabs-kept-request-cases-swapped"),
        pytest.param("request with several cases", TWO_TABS, id="request-cases-kept-tabs-swapped"),
    ],
)
def test_a_writer_swaps_the_panes_whose_own_cell_says_swap(
    monkeypatch: pytest.MonkeyPatch, kept_feature: Feature, swapped_node: Tabs
) -> None:
    monkeypatch.setitem(CAPABILITIES[kept_feature], "notion", "keep")
    monkeypatch.setitem(CAPABILITIES[kept_feature], "adf", "keep")

    assert (render_notion([swapped_node]), render_adf([swapped_node])["content"]) == (
        "<details>\n<summary>⚠️ One</summary>\n\ta\n</details>\n"
        "<details>\n<summary>Two</summary>\n\tb\n</details>\n",
        _adf_expands("⚠️ One", "Two"),
    )


@pytest.mark.parametrize(("feature", "block"), SWAPPED_BLOCKS_OF_EACH_FEATURE)
def test_a_panes_cell_made_a_rejection_refuses_the_block(
    monkeypatch: pytest.MonkeyPatch, feature: Feature, block: dict[str, Any]
) -> None:
    monkeypatch.setitem(CAPABILITIES[feature], "markdown", Rejection("Markdown cannot show it", "drop it"))

    with pytest.raises(ExportRejectedError) as raised:
        _check([block], "markdown")

    assert vars(raised.value) == {
        "target": "markdown",
        "why": "Markdown cannot show it",
        "instead": "drop it",
        "where": f"at blocks.0.{block['type']}",
    }


def test_a_grid_in_a_walkthrough_step_is_named_before_a_block_inside_the_grid() -> None:
    grid = text_grid()
    grid["cells"][1]["blocks"] = [{"type": "code", "content": "recount"}]

    with pytest.raises(ExportRejectedError) as raised:
        _check([walkthrough_holding(grid)], "slack")

    assert raised.value.where == "at blocks.0.walkthrough.steps.0.detail.0.grid"


def test_the_first_refusal_reported_is_the_first_in_the_document() -> None:
    blocks = [*in_a_panel({"type": "divider"}), two_cell_grid(text_grid())]

    with pytest.raises(ExportRejectedError) as raised:
        _check(blocks, "slack")

    assert raised.value.where == "at blocks.0.panel.blocks.0.divider"


def test_a_refusal_found_on_the_model_names_the_heading_above_it() -> None:
    blocks = [{"type": "heading", "text": "Layout"}, two_cell_grid(text_grid())]

    with pytest.raises(ExportRejectedError) as raised:
        _check(blocks, "slack")

    assert raised.value.where == "at blocks.1.grid.cells.1.blocks.0.grid, under the heading 'Layout'"


@pytest.mark.parametrize(
    ("target", "refused_at"),
    [
        pytest.param("adf", "at blocks.2.panel.blocks.0.table", id="adf"),
        pytest.param("slack", "at blocks.1.walkthrough.steps.0.detail.0.grid", id="slack"),
    ],
)
def test_the_check_of_a_page_built_from_some_regions_looks_only_at_their_blocks(
    target: ExportTarget, refused_at: str
) -> None:
    blocks = [{"type": "text", "body": "Fine."}, walkthrough_holding(text_grid()), *in_a_panel(TABLE)]
    report = parse_report(make_report(blocks=blocks))
    lowering = lowering_for(report)
    regions = lower_regions(lowering)

    with pytest.raises(ExportRejectedError) as raised:
        reject_what_the_target_cannot_show(report, assemble_page(regions, lowering), target)
    reject_what_the_target_cannot_show(report, assemble_page(regions[:1], lowering), target)

    assert raised.value.where == refused_at


@pytest.mark.parametrize("case", SEEDED_CASES)
def test_export_refuses_each_seeded_case_and_writes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], case: RefusedCase
) -> None:
    data_path = write_report(tmp_path, make_report(blocks=case.blocks))
    export_dir = tmp_path / "exported"

    assert main([str(data_path), "--export", case.target, "--export-dir", str(export_dir)]) == 1

    captured = capsys.readouterr()
    assert (captured.out, captured.err, export_dir.exists()) == ("", f"error: {case.message()}\n", False)


@pytest.mark.parametrize("target", EXPORT_TARGETS)
def test_a_clean_document_exports_to_every_target(tmp_path: Path, target: ExportTarget) -> None:
    data_path = write_report(tmp_path, make_report(blocks=CLEAN_BLOCKS))

    assert main([str(data_path), "--export", target, "--export-dir", str(tmp_path / "exported")]) == 0


@pytest.mark.parametrize("case", ADF_CASES)
def test_publishing_to_jira_refuses_each_adf_case_before_any_transport_call(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], case: RefusedCase
) -> None:
    data_path = write_report(tmp_path, published_report(case.blocks, make_jira_target()))
    transport = FakeTransport()

    exit_code = _publish_with_a_fake_jira(data_path, transport)

    assert (exit_code, capsys.readouterr().err, transport.calls) == (1, f"error: {case.message()}\n", [])


def test_publishing_to_jira_checks_only_the_sections_the_target_is_built_from(tmp_path: Path) -> None:
    blocks = [make_section("kept"), make_section("left-out", blocks=in_a_panel(TABLE))]
    target = make_jira_target(**{"from": ["kept"]})
    data_path = write_report(tmp_path, published_report(blocks, target))

    assert _publish_with_a_fake_jira(data_path, FakeTransport()) == 0


def test_publishing_a_clean_document_to_jira_sends_it(tmp_path: Path) -> None:
    data_path = write_report(tmp_path, published_report(CLEAN_BLOCKS, make_jira_target()))
    transport = FakeTransport()

    assert _publish_with_a_fake_jira(data_path, transport) == 0

    assert transport.writes() != []
