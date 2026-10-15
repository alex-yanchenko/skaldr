import sys
from pathlib import Path
from typing import NoReturn

import pytest

from skaldr.cli import main
from skaldr.export import lower as lower_module
from skaldr.export.adf import JIRA_DESCRIPTION_LIMIT
from skaldr.export.lower import Lowering, lower_report
from skaldr.export_targets import EXPORT_TARGETS, ExportTarget
from skaldr.models import Report, parse_report
from skaldr.publish import drafts as drafts_module
from skaldr.publish.cli import installed_connectors
from skaldr.publish.cli import main as publish_main
from skaldr.publish.jira import JiraConnector
from skaldr.publish.jira import connector as jira_connector_module
from skaldr.publish.jira.description import description_length
from skaldr.publish.notion import connector as notion_connector_module
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

JIRA_TARGET_LABEL = "jira project PLAN under no parent issue"
FOR_WITHOUT_CHECK = "--for only applies to --check (it names the export targets to check for)"
CANVAS_OVER_THE_LIMIT_CODE_LENGTH = 1_048_568
LIST_FROM_3_REFUSAL = (
    "a Slack canvas numbers every list from 1, so it cannot show a numbered list that starts at 3, "
    "at blocks.1.text; number the list from 1, or export it elsewhere"
)


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

    assert capsys.readouterr().out == f"OK    {data_path}{case.unfilled_placeholders_note}\n"


@pytest.mark.parametrize(
    ("first", "second", "refusal"),
    [
        pytest.param("adf", "slack", TABLE_IN_A_PANEL.message(), id="adf-then-slack"),
        pytest.param("slack", "adf", LIST_FROM_3_REFUSAL, id="slack-then-adf"),
    ],
)
def test_check_for_two_targets_that_refuse_differently_fails_with_the_first_one_named(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    first: ExportTarget,
    second: ExportTarget,
    refusal: str,
) -> None:
    blocks = [*TABLE_IN_A_PANEL.blocks, {"type": "text", "body": "3. a\n4. b"}]
    data_path = write_report(tmp_path, make_report(blocks=blocks))

    assert main(["--check", str(data_path), "--for", first, "--for", second]) == 1

    assert capsys.readouterr().err == f"FAIL  {data_path}: {refusal}\n\n1 file failed\n"


def test_check_for_the_same_target_twice_fails_once(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data_path = write_report(tmp_path, make_report(blocks=TABLE_IN_A_PANEL.blocks))

    assert main(["--check", str(data_path), "--for", "adf", "--for", "adf"]) == 1

    assert capsys.readouterr().err == f"FAIL  {data_path}: {TABLE_IN_A_PANEL.message()}\n\n1 file failed\n"


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

    assert (exited.value.code, capsys.readouterr().err.splitlines()[-1]) == (
        2,
        f"{Path(sys.argv[0]).name}: error: {FOR_WITHOUT_CHECK}",
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


def test_check_with_a_publish_block_also_checks_each_target_named_with_for(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data_path = write_report(tmp_path, published_report(in_a_panel(TABLE), make_notion_target()))

    assert main(["--check", str(data_path), "--for", "adf"]) == 1

    assert capsys.readouterr().err == f"FAIL  {data_path}: {TABLE_IN_A_PANEL.message()}\n\n1 file failed\n"


def test_check_for_slack_refuses_a_canvas_the_export_refuses_for_its_size_and_writes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    blocks = [{"type": "code", "content": "x" * CANVAS_OVER_THE_LIMIT_CODE_LENGTH}]
    data_path = write_report(tmp_path, make_report(blocks=blocks))
    export_dir = tmp_path / "exported"

    exit_code = main(
        ["--check", str(data_path), "--for", "slack", "--export", "slack", "--export-dir", str(export_dir)]
    )

    assert (exit_code, capsys.readouterr().err, export_dir.exists()) == (
        1,
        f"FAIL  {data_path}: the canvas Markdown is 1,048,577 characters, over the 1,048,576 characters "
        "(1 MiB) a Slack canvas can hold; split the document into several canvases or export it elsewhere"
        "\n\n1 file failed\n",
        False,
    )


def test_check_of_a_jira_target_over_the_description_limit_fails_with_the_publish_refusal(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data = published_report([{"type": "text", "body": "x" * JIRA_DESCRIPTION_LIMIT}], make_jira_target())
    data_path = write_report(tmp_path, data)
    parsed = parse_report(data)
    size = description_length("".join(JiraConnector().render_regions(parsed, lower_report(parsed))))
    refusal = (
        f"{JIRA_TARGET_LABEL}, document: the item has {size:,} characters of ADF, over the 32,767 a Jira "
        "item can take; split the document further with `split`, or shorten it"
    )

    check_exit = main(["--check", str(data_path)])
    check_err = capsys.readouterr().err
    publish_exit = publish_main(["publish", str(data_path)], registry=installed_connectors())

    assert (check_exit, check_err, publish_exit, capsys.readouterr().err) == (
        1,
        f"FAIL  {data_path}: {refusal}\n\n1 file failed\n",
        1,
        f"error: {refusal}\n",
    )


def test_check_of_a_split_jira_target_names_the_heading_publish_names_for_each_item(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    blocks = [{"type": "heading", "text": "Before"}, make_section("tools"), *in_a_panel(TABLE)]
    data_path = write_report(tmp_path, published_report(blocks, make_jira_target(split=["tools"])))
    refusal = (
        "ADF cannot place a table inside a panel, at blocks.2.panel.blocks.0.table, under the heading "
        "'Before'; move the table out of the panel"
    )

    check_exit = main(["--check", str(data_path)])
    check_err = capsys.readouterr().err
    publish_exit = publish_main(["publish", str(data_path)], registry=installed_connectors())

    assert (check_exit, check_err, publish_exit, capsys.readouterr().err) == (
        1,
        f"FAIL  {data_path}: {refusal}\n\n1 file failed\n",
        1,
        f"error: {refusal}\n",
    )


def test_check_of_publish_targets_reads_no_sign_in(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_sign_in_is_read(*_args: object) -> NoReturn:
        raise NotImplementedError

    monkeypatch.setattr(jira_connector_module, "load_jira", no_sign_in_is_read)
    monkeypatch.setattr(jira_connector_module, "require_jira", no_sign_in_is_read)
    monkeypatch.setattr(notion_connector_module, "require_notion_for_a_target", no_sign_in_is_read)
    data_path = write_report(
        tmp_path, published_report(CLEAN_BLOCKS, make_jira_target(), make_notion_target())
    )

    assert main(["--check", str(data_path)]) == 0

    assert capsys.readouterr().out == f"OK    {data_path}\n"


def test_check_without_the_publish_extra_checks_the_publish_block_but_not_its_targets(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    for module in [name for name in sys.modules if name.startswith("skaldr.publish.")]:
        monkeypatch.delitem(sys.modules, module)
    monkeypatch.setitem(sys.modules, "httpx2", None)
    data_path = write_report(tmp_path, published_report(TABLE_IN_A_PANEL.blocks, make_jira_target()))

    assert main(["--check", str(data_path)]) == 0

    assert capsys.readouterr().out == f"OK    {data_path}\n"


def test_check_without_a_publish_block_or_a_for_target_lowers_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def lowering_nobody_asked_for(_report: Report) -> Lowering:
        raise NotImplementedError

    monkeypatch.setattr(drafts_module, "lowering_for", lowering_nobody_asked_for)
    monkeypatch.setattr(lower_module, "lowering_for", lowering_nobody_asked_for)
    data_path = write_report(tmp_path, make_report(blocks=TABLE_IN_A_PANEL.blocks))

    assert main(["--check", str(data_path)]) == 0

    assert capsys.readouterr().out == f"OK    {data_path}\n"


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
