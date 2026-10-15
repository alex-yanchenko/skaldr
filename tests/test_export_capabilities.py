from dataclasses import fields
from pathlib import Path
from string import Formatter
from typing import Any, Literal, get_args

import pytest

from skaldr.cli import main
from skaldr.errors import ExportInvariantError, ExportRejectedError
from skaldr.export.capabilities import (
    CAPABILITIES,
    FEATURE_DETAILS,
    Capability,
    Details,
    Feature,
    ListStart,
    Rejection,
)
from skaldr.export.check import FeatureHit, reject_what_the_target_cannot_show
from skaldr.export.lower import assemble_page, lower_regions, lower_report, lowering_for
from skaldr.export_targets import EXPORT_TARGETS, ExportTarget
from skaldr.models import parse_report
from skaldr.publish.cli import main as publish_main
from skaldr.publish_block import JiraTarget, NotionTarget
from tests.factories import make_jira_target, make_report, write_report
from tests.factories.capability_factory import (
    ADF_CASES,
    CLEAN_BLOCKS,
    SEEDED_CASES,
    TABLE,
    RefusedCase,
    in_a_panel,
    published_report,
    text_grid,
    walkthrough_holding,
)
from tests.factories.publish_factory import FakeTransport, fake_registry

Verdict = Literal["keep", "upgrade", "swap", "reject"]
FEATURES: tuple[Feature, ...] = get_args(Feature)
SEEDED_VERDICTS: dict[Feature, dict[ExportTarget, Verdict]] = {
    "table inside a callout": {"adf": "reject"},
    "callout inside a callout": {"adf": "reject"},
    "quote inside a callout": {"adf": "reject"},
    "toggle inside a callout": {"adf": "reject"},
    "table inside a toggle inside a toggle": {"adf": "reject"},
    "toggle inside a toggle inside a toggle": {"adf": "reject"},
    "block inside a list item": {"slack": "reject"},
    "block inside a walkthrough step": {"slack": "reject"},
    "numbered list starting past 1": {"slack": "reject"},
    "table over 300 cells": {"slack": "reject"},
    "grid inside a walkthrough step": {"slack": "reject"},
}
REJECTIONS = [
    pytest.param(capability, FEATURE_DETAILS[feature], id=f"{target}-{feature}")
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


def _publish_with_a_fake_jira(data_path: Path, transport: FakeTransport) -> int:
    registry = fake_registry(transport, target_types=(NotionTarget, JiraTarget))
    return publish_main(["publish", str(data_path), "--apply"], registry=registry)


def test_the_table_holds_a_cell_for_every_feature_and_target_and_rejects_only_the_seeded_ones() -> None:
    verdicts = {
        feature: {target: _verdict(capability) for target, capability in cells.items()}
        for feature, cells in CAPABILITIES.items()
    }

    assert verdicts == {
        feature: {target: SEEDED_VERDICTS[feature].get(target, "keep") for target in EXPORT_TARGETS}
        for feature in FEATURES
    }


def test_every_feature_names_the_details_its_hits_carry() -> None:
    assert set(FEATURE_DETAILS) == set(FEATURES)


@pytest.mark.parametrize(("rejection", "details"), REJECTIONS)
def test_every_rejection_names_only_details_its_feature_supplies(
    rejection: Rejection, details: type[Details]
) -> None:
    supplied = {detail.name for detail in fields(details)}

    assert _template_fields(rejection.why) | _template_fields(rejection.instead) <= supplied


def test_a_hit_carrying_details_its_feature_does_not_take_is_an_internal_error() -> None:
    with pytest.raises(ExportInvariantError) as raised:
        FeatureHit("table over 300 cells", ListStart(3))

    assert str(raised.value) == "the feature 'table over 300 cells' takes CellCount details, not ListStart"


@pytest.mark.parametrize("case", SEEDED_CASES)
def test_the_check_refuses_each_seeded_case_naming_its_yaml_path(case: RefusedCase) -> None:
    with pytest.raises(ExportRejectedError) as raised:
        _check(case.blocks, case.target)

    assert vars(raised.value) == case.rejection()


@pytest.mark.parametrize("case", SEEDED_CASES)
def test_every_other_target_keeps_what_one_target_refuses(case: RefusedCase) -> None:
    for other in EXPORT_TARGETS:
        if other != case.target:
            _check(case.blocks, other)


@pytest.mark.parametrize("target", EXPORT_TARGETS)
def test_a_document_no_target_refuses_passes_the_check(target: ExportTarget) -> None:
    _check(CLEAN_BLOCKS, target)


def test_a_grid_in_a_walkthrough_step_is_named_before_a_block_inside_the_grid() -> None:
    grid = text_grid()
    grid["cells"][1]["blocks"] = [{"type": "code", "content": "recount"}]

    with pytest.raises(ExportRejectedError) as raised:
        _check([walkthrough_holding(grid)], "slack")

    assert raised.value.where == "at blocks.0.walkthrough.steps.0.detail.0.grid"


@pytest.mark.parametrize("target", ["adf", "slack"])
def test_the_check_of_a_page_built_from_some_regions_looks_only_at_their_blocks(target: ExportTarget) -> None:
    blocks = [{"type": "text", "body": "Fine."}, *in_a_panel(TABLE), walkthrough_holding(text_grid())]
    report = parse_report(make_report(blocks=blocks))
    lowering = lowering_for(report)

    reject_what_the_target_cannot_show(report, assemble_page(lower_regions(lowering)[:1], lowering), target)


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
    blocks = [
        {"type": "section", "id": "kept", "title": "Kept", "blocks": [{"type": "text", "body": "x"}]},
        {"type": "section", "id": "left-out", "title": "Left out", "blocks": in_a_panel(TABLE)},
    ]
    target = make_jira_target(**{"from": ["kept"]})
    data_path = write_report(tmp_path, published_report(blocks, target))

    assert _publish_with_a_fake_jira(data_path, FakeTransport()) == 0


def test_publishing_a_clean_document_to_jira_sends_it(tmp_path: Path) -> None:
    data_path = write_report(tmp_path, published_report(CLEAN_BLOCKS, make_jira_target()))
    transport = FakeTransport()

    assert _publish_with_a_fake_jira(data_path, transport) == 0

    assert transport.writes() != []
