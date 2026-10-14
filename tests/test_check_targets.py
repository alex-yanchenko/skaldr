from pathlib import Path

import pytest

from skaldr.cli import main
from skaldr.export_targets import EXPORT_TARGETS, ExportTarget
from tests.factories import make_jira_target, make_notion_target, make_report, make_section, write_report
from tests.factories.capability_factory import (
    CLEAN_BLOCKS,
    SEEDED_CASES,
    TABLE,
    TABLE_IN_A_PANEL,
    RefusedCase,
    in_a_panel,
    published_report,
)

FOR_WITHOUT_CHECK = "--for only applies to --check (it names the export targets to check for)"


@pytest.mark.parametrize("case", SEEDED_CASES)
def test_check_for_a_target_refuses_each_seeded_case(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], case: RefusedCase
) -> None:
    data_path = write_report(tmp_path, make_report(blocks=case.blocks))

    assert main(["--check", str(data_path), "--for", case.target]) == 1

    captured = capsys.readouterr()
    assert (captured.out, captured.err) == ("", f"FAIL  {data_path}: {case.message()}\n\n1 file failed\n")


@pytest.mark.parametrize("case", SEEDED_CASES)
def test_check_without_a_target_passes_what_only_a_target_refuses(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], case: RefusedCase
) -> None:
    data_path = write_report(tmp_path, make_report(blocks=case.blocks))

    assert main(["--check", str(data_path)]) == 0

    assert capsys.readouterr().out == f"OK    {data_path}\n"


def test_check_for_several_targets_takes_the_flag_once_per_target(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data_path = write_report(tmp_path, make_report(blocks=[{"type": "text", "body": "3. a\n4. b"}]))

    assert main(["--check", str(data_path), "--for", "adf", "--for", "slack"]) == 1

    assert capsys.readouterr().err.startswith(f"FAIL  {data_path}: a Slack canvas numbers every list from 1")


@pytest.mark.parametrize("target", EXPORT_TARGETS)
def test_a_clean_document_passes_check_for_every_target(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], target: ExportTarget
) -> None:
    data_path = write_report(tmp_path, make_report(blocks=CLEAN_BLOCKS))

    assert main(["--check", str(data_path), "--for", target]) == 0

    assert capsys.readouterr().out == f"OK    {data_path}\n"


def test_for_without_check_is_a_usage_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    data_path = write_report(tmp_path, make_report())

    with pytest.raises(SystemExit) as exited:
        main([str(data_path), "--for", "adf"])

    assert (exited.value.code, capsys.readouterr().err.splitlines()[-1].endswith(FOR_WITHOUT_CHECK)) == (
        2,
        True,
    )


def test_check_of_a_document_publishing_to_jira_refuses_what_adf_cannot_show(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data_path = write_report(tmp_path, published_report(TABLE_IN_A_PANEL.blocks, make_jira_target()))

    assert main(["--check", str(data_path)]) == 1

    assert capsys.readouterr().err == f"FAIL  {data_path}: {TABLE_IN_A_PANEL.message()}\n\n1 file failed\n"


def test_check_of_a_document_publishing_to_notion_passes_what_only_adf_refuses(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data_path = write_report(tmp_path, published_report(in_a_panel(TABLE), make_notion_target()))

    assert main(["--check", str(data_path)]) == 0

    assert capsys.readouterr().out == f"OK    {data_path}\n"


def test_check_of_a_jira_target_looks_only_at_the_sections_it_is_built_from(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    blocks = [make_section("kept"), make_section("left-out", blocks=in_a_panel(TABLE))]
    data_path = write_report(tmp_path, published_report(blocks, make_jira_target(**{"from": ["kept"]})))

    assert main(["--check", str(data_path)]) == 0

    assert capsys.readouterr().out == f"OK    {data_path}\n"


def test_check_with_a_publish_block_also_checks_the_targets_for_names(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data_path = write_report(tmp_path, published_report(in_a_panel(TABLE), make_notion_target()))

    assert main(["--check", str(data_path), "--for", "adf"]) == 1

    assert capsys.readouterr().err == f"FAIL  {data_path}: {TABLE_IN_A_PANEL.message()}\n\n1 file failed\n"


def test_check_then_export_refuses_before_writing_anything(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data_path = write_report(tmp_path, make_report(blocks=TABLE_IN_A_PANEL.blocks))
    export_dir = tmp_path / "exported"

    exit_code = main(
        ["--check", str(data_path), "--for", "adf", "--export", "adf", "--export-dir", str(export_dir)]
    )

    assert (exit_code, capsys.readouterr().err, export_dir.exists()) == (
        1,
        f"FAIL  {data_path}: {TABLE_IN_A_PANEL.message()}\n\n1 file failed\n",
        False,
    )
