from pathlib import Path

import pytest

from skaldr.cli import main
from tests.factories import make_report, write_report

EXPORT_CLASH = "--export writes its own files; it can't combine with -o/--pdf/--embed/--watch/--emit-json"
HTML_ONLY = "--live, --if-stale and --no-source shape an HTML render; --export writes none"
BLANK_EXPORT_DIR = "--export-dir needs a folder path"


@pytest.fixture
def export_dir(tmp_path: Path) -> Path:
    return tmp_path / "exported"


def test_the_cli_exports_the_page_and_prints_its_path(
    tmp_path: Path, export_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data_path = write_report(tmp_path, make_report(blocks=[{"type": "text", "body": "Hi."}]))

    assert main([str(data_path), "--export", "markdown", "--export-dir", str(export_dir)]) == 0

    assert capsys.readouterr().out.splitlines() == [f"OK  {export_dir / 'page.md'}"]
    assert (export_dir / "page.md").read_text(encoding="utf-8") == "# Test Report\n\nHi.\n"


def test_the_cli_writes_an_export_under_out_named_for_the_file_and_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_path = write_report(tmp_path, make_report())
    monkeypatch.chdir(tmp_path)

    assert main([str(data_path), "--export", "markdown"]) == 0

    assert (tmp_path / "out" / "doc.markdown" / "page.md").read_text(
        encoding="utf-8"
    ) == "# Test Report\n\nHello.\n"


def test_check_then_export_of_a_valid_file_writes_the_page(tmp_path: Path, export_dir: Path) -> None:
    data_path = write_report(tmp_path, make_report())

    assert main(["--check", str(data_path), "--export", "markdown", "--export-dir", str(export_dir)]) == 0

    assert (export_dir / "page.md").read_text(encoding="utf-8") == "# Test Report\n\nHello.\n"


def test_the_cli_checks_before_it_exports_and_writes_nothing_for_an_invalid_file(
    tmp_path: Path, export_dir: Path
) -> None:
    data_path = write_report(tmp_path, make_report(blocks=[{"type": "text", "oops": 1}]))

    assert main(["--check", str(data_path), "--export", "markdown", "--export-dir", str(export_dir)]) == 1

    assert not export_dir.exists()


def test_an_export_of_an_invalid_file_without_check_reports_the_error_and_writes_nothing(
    tmp_path: Path, export_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data_path = write_report(tmp_path, make_report(blocks=[{"type": "text", "body": "[x](#nowhere)"}]))

    assert main([str(data_path), "--export", "markdown", "--export-dir", str(export_dir)]) == 1

    assert capsys.readouterr().err.startswith("error: rich text links to unknown anchor '#nowhere'")
    assert not export_dir.exists()


def test_an_export_of_a_block_with_no_markdown_form_reports_it_and_writes_nothing(
    tmp_path: Path, export_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    flow = {"type": "flow", "steps": [{"label": "a"}, {"label": "b"}]}
    data_path = write_report(tmp_path, make_report(blocks=[flow]))

    assert main([str(data_path), "--export", "markdown", "--export-dir", str(export_dir)]) == 1

    assert capsys.readouterr().err == "error: a `flow` block has no Markdown export yet\n"
    assert not export_dir.exists()


def test_an_export_dir_that_cannot_be_written_reports_the_error_and_leaves_the_file_alone(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data_path = write_report(tmp_path, make_report())
    blocker = tmp_path / "taken"
    blocker.write_text("a file, not a folder", encoding="utf-8")

    assert main([str(data_path), "--export", "markdown", "--export-dir", str(blocker)]) == 1

    assert capsys.readouterr().err == f"error: [Errno 17] File exists: '{blocker}'\n"
    assert blocker.read_text(encoding="utf-8") == "a file, not a folder"


@pytest.mark.parametrize(
    ("argv_tail", "message"),
    [
        pytest.param(["--export", "markdown", "-o", "x.html"], EXPORT_CLASH, id="with-out"),
        pytest.param(["--export", "markdown", "--pdf", "x.pdf"], EXPORT_CLASH, id="with-pdf"),
        pytest.param(["--export", "markdown", "--embed"], EXPORT_CLASH, id="with-embed"),
        pytest.param(["--export", "markdown", "--watch"], EXPORT_CLASH, id="with-watch"),
        pytest.param(["--export", "markdown", "--emit-json"], EXPORT_CLASH, id="with-emit-json"),
        pytest.param(["--export", "markdown", "--live"], HTML_ONLY, id="with-live"),
        pytest.param(["--export", "markdown", "--if-stale"], HTML_ONLY, id="with-if-stale"),
        pytest.param(["--export", "markdown", "--no-source"], HTML_ONLY, id="with-no-source"),
        pytest.param(["--export", "markdown", "--export-dir", ""], BLANK_EXPORT_DIR, id="empty-dir"),
        pytest.param(["--export", "markdown", "--export-dir", "  "], BLANK_EXPORT_DIR, id="blank-dir"),
        pytest.param(["--export-dir", "d"], "--export-dir only applies with --export", id="dir-alone"),
        pytest.param(["--export-dir", ""], "--export-dir only applies with --export", id="empty-dir-alone"),
        pytest.param(["--export", "jira"], "invalid choice: 'jira'", id="unknown-target"),
    ],
)
def test_the_cli_rejects_flags_that_do_not_fit_an_export(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], argv_tail: list[str], message: str
) -> None:
    data_path = write_report(tmp_path, make_report())

    with pytest.raises(SystemExit) as raised:
        main([str(data_path), *argv_tail])

    assert raised.value.code == 2
    assert message in capsys.readouterr().err


def test_the_cli_refuses_to_check_and_export_several_files(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    first = write_report(tmp_path, make_report())
    second = tmp_path / "other.yaml"
    second.write_text(first.read_text(encoding="utf-8"), encoding="utf-8")

    with pytest.raises(SystemExit) as raised:
        main(["--check", str(first), str(second), "--export", "markdown"])

    assert raised.value.code == 2
    assert (
        "an output flag renders one file — pass a single content file, or drop -o/--pdf/--embed/--export"
        in capsys.readouterr().err
    )
