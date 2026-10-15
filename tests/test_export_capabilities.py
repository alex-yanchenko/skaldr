from dataclasses import fields
from pathlib import Path
from string import Formatter
from typing import Any, Literal, get_args, get_type_hints

import pytest

from skaldr.cli import main
from skaldr.errors import ExportRejectedError
from skaldr.export import render_export
from skaldr.export.capabilities import CAPABILITIES, Capability, Details, Feature, Rejection
from skaldr.export.check import reject_what_the_target_cannot_show
from skaldr.export.lower import assemble_page, lower_regions, lower_report, lowering_for
from skaldr.export_targets import EXPORT_TARGETS, ExportTarget
from skaldr.models import parse_report
from skaldr.publish import ConnectorRegistry
from skaldr.publish.cli import main as publish_main
from skaldr.publish_block import JiraTarget, NotionTarget
from tests.factories import make_jira_target, make_notion_target, make_report, make_section, write_report
from tests.factories.capability_factory import (
    ADF_CASES,
    CLEAN_BLOCKS,
    COLOURED_TEXT,
    LETTERED_LIST,
    NOTION_CASES,
    SEEDED_CASES,
    SEEDED_REFUSALS,
    TABLE,
    RefusedCase,
    in_a_panel,
    published_report,
    text_grid,
    walkthrough_holding,
)
from tests.factories.publish_factory import FakeConnector, FakeTransport

Verdict = Literal["keep", "reject"]
FEATURES: tuple[Feature, ...] = get_args(Feature)
DETAILS_KINDS: tuple[type[Details], ...] = get_args(Details)
SEEDED_VERDICTS: dict[Feature, dict[ExportTarget, Verdict]] = {
    "table inside a callout": {"adf": "reject"},
    "callout inside a callout": {"adf": "reject"},
    "quote inside a callout": {"adf": "reject"},
    "toggle inside a callout": {"adf": "reject"},
    "table inside a toggle inside a toggle": {"adf": "reject"},
    "toggle inside a toggle inside a toggle": {"adf": "reject"},
    "block inside a list item": {"slack": "reject"},
    "block inside a walkthrough step": {"slack": "reject"},
    "numbered list starting past 1": {"notion": "reject", "slack": "reject"},
    "table over 300 cells": {"slack": "reject"},
    "grid inside a walkthrough step": {"slack": "reject"},
    "subscript or superscript with no Unicode form": {"slack": "reject"},
}
TEXT_AND_LIST_VERDICTS: dict[Feature, dict[ExportTarget, Verdict]] = {
    "colour span": {"markdown": "reject", "slack": "reject"},
    "highlight span": {"adf": "reject", "slack": "reject"},
    "colour and highlight span": {
        "markdown": "reject",
        "notion": "reject",
        "adf": "reject",
        "slack": "reject",
    },
    "underline": {"slack": "reject"},
    "link to a heading of the same document": {"notion": "reject", "adf": "reject", "slack": "reject"},
    "link to another skaldr document": {"notion": "reject", "slack": "reject"},
    "inline code holding a backtick": {"notion": "reject"},
    "inline code holding a closing tag in a table cell": {"notion": "reject"},
    "inline code holding a closing tag in a coloured or highlighted span": {"notion": "reject"},
    "highlight span inside a toned walkthrough step title": {"notion": "reject"},
    "list numbered with letters or roman numerals": {"adf": "reject", "slack": "reject"},
    "table, callout, heading, quote, toggle or divider inside a list item or walkthrough step": {
        "adf": "reject"
    },
    "list inside a quote": {"slack": "reject"},
}


def _targets_refusing(blocks: list[dict[str, Any]]) -> set[ExportTarget]:
    return {case.target for case in SEEDED_REFUSALS.values() if case.blocks == blocks}


KEPT_BY_THE_OTHER_TARGETS = [
    pytest.param(case, other, id=f"{name}-kept-by-{other}")
    for name, case in SEEDED_REFUSALS.items()
    for other in EXPORT_TARGETS
    if other not in _targets_refusing(case.blocks)
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
    return "reject" if isinstance(capability, Rejection) else capability


def _template_fields(template: str) -> set[str]:
    return {name for _, name, _, _ in Formatter().parse(template) if name is not None}


def _check(blocks: list[dict[str, Any]], target: ExportTarget) -> None:
    report = parse_report(make_report(blocks=blocks))
    reject_what_the_target_cannot_show(report, lower_report(report), target)


def _publish_with_fake_connectors(data_path: Path, transport: FakeTransport) -> int:
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
        for feature, seeded in {**SEEDED_VERDICTS, **TEXT_AND_LIST_VERDICTS}.items()
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


@pytest.mark.parametrize("case", SEEDED_CASES)
def test_the_check_refuses_each_seeded_case_naming_its_yaml_path(case: RefusedCase) -> None:
    with pytest.raises(ExportRejectedError) as raised:
        _check(case.blocks, case.target)

    assert vars(raised.value) == case.rejection()


@pytest.mark.parametrize(("case", "other"), KEPT_BY_THE_OTHER_TARGETS)
def test_every_other_target_keeps_what_one_target_refuses(case: RefusedCase, other: ExportTarget) -> None:
    report = parse_report(make_report(blocks=case.blocks))

    assert render_export(report, other).pages != {}


@pytest.mark.parametrize("target", EXPORT_TARGETS)
def test_a_document_no_target_refuses_passes_the_check(target: ExportTarget) -> None:
    _check(CLEAN_BLOCKS, target)


def test_a_grid_in_a_walkthrough_step_is_named_before_a_block_inside_the_grid() -> None:
    grid = text_grid()
    grid["cells"][1]["blocks"] = [{"type": "code", "content": "recount"}]

    with pytest.raises(ExportRejectedError) as raised:
        _check([walkthrough_holding(grid)], "slack")

    assert raised.value.where == "at blocks.0.walkthrough.steps.0.detail.0.grid"


def test_a_refusal_in_the_source_line_of_the_footer_names_meta_source() -> None:
    meta = {"title": "Counts", "source": "the [cold room]{tone=danger} log"}
    report = parse_report(make_report(meta=meta))

    with pytest.raises(ExportRejectedError) as raised:
        reject_what_the_target_cannot_show(report, lower_report(report), "markdown")

    assert vars(raised.value) == {
        "target": "markdown",
        "why": "GitHub Markdown cannot colour text, so it cannot show the colour of 'cold room'",
        "instead": "write the text without the colour or export the document elsewhere",
        "where": "at meta.source",
    }


def test_the_first_refusal_reported_is_the_first_in_the_document() -> None:
    with pytest.raises(ExportRejectedError) as raised:
        _check([*COLOURED_TEXT, *LETTERED_LIST], "slack")

    assert raised.value.where == "at blocks.0.text"


@pytest.mark.parametrize(
    ("target", "refused_at"),
    [
        pytest.param("adf", "at blocks.1.panel.blocks.0.table", id="adf"),
        pytest.param("slack", "at blocks.2.walkthrough.steps.0.detail.0.grid", id="slack"),
    ],
)
def test_the_check_of_a_page_built_from_some_regions_looks_only_at_their_blocks(
    target: ExportTarget, refused_at: str
) -> None:
    blocks = [{"type": "text", "body": "Fine."}, *in_a_panel(TABLE), walkthrough_holding(text_grid())]
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

    exit_code = _publish_with_fake_connectors(data_path, transport)

    assert (exit_code, capsys.readouterr().err, transport.calls) == (1, f"error: {case.message()}\n", [])


@pytest.mark.parametrize("case", NOTION_CASES)
def test_publishing_to_notion_refuses_each_notion_case_before_any_transport_call(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], case: RefusedCase
) -> None:
    data_path = write_report(tmp_path, published_report(case.blocks, make_notion_target()))
    transport = FakeTransport()

    exit_code = _publish_with_fake_connectors(data_path, transport)

    assert (exit_code, capsys.readouterr().err, transport.calls) == (1, f"error: {case.message()}\n", [])


def test_publishing_a_clean_document_to_notion_sends_it(tmp_path: Path) -> None:
    data_path = write_report(tmp_path, published_report(CLEAN_BLOCKS, make_notion_target()))
    transport = FakeTransport()

    assert _publish_with_fake_connectors(data_path, transport) == 0

    assert transport.writes() != []


def test_publishing_to_jira_checks_only_the_sections_the_target_is_built_from(tmp_path: Path) -> None:
    blocks = [make_section("kept"), make_section("left-out", blocks=in_a_panel(TABLE))]
    target = make_jira_target(**{"from": ["kept"]})
    data_path = write_report(tmp_path, published_report(blocks, target))

    assert _publish_with_fake_connectors(data_path, FakeTransport()) == 0


def test_publishing_a_clean_document_to_jira_sends_it(tmp_path: Path) -> None:
    data_path = write_report(tmp_path, published_report(CLEAN_BLOCKS, make_jira_target()))
    transport = FakeTransport()

    assert _publish_with_fake_connectors(data_path, transport) == 0

    assert transport.writes() != []
