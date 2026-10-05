from pathlib import Path

import pytest

from skaldr.cli import main
from skaldr.export import EXPORT_MANIFEST, ExportTarget
from tests.factories import heading_sections, make_report, write_report

EXPORT_CLASH = "--export writes its own files; it can't combine with -o/--pdf/--embed/--watch/--emit-json"
HTML_ONLY = "--live, --if-stale and --no-source shape an HTML render; --export writes none"
DIR_OR_CHUNK_ALONE = "--export-dir and --chunk only apply with --export"
CHUNK_NOT_POSITIVE = "--chunk takes a positive character count"
CHUNK_NOTION_ONLY = "--chunk splits a Notion page into files; it only applies with --export notion"
BLANK_EXPORT_DIR = "--export-dir needs a folder path"


@pytest.fixture
def export_dir(tmp_path: Path) -> Path:
    return tmp_path / "exported"


@pytest.mark.parametrize(
    ("target", "expected_page"),
    [
        pytest.param("notion", "Hi.\n", id="notion"),
        pytest.param("markdown", "# Test Report\n\nHi.\n", id="markdown"),
    ],
)
def test_the_cli_exports_the_page_and_prints_its_path(
    tmp_path: Path,
    export_dir: Path,
    capsys: pytest.CaptureFixture[str],
    target: ExportTarget,
    expected_page: str,
) -> None:
    data_path = write_report(tmp_path, make_report(blocks=[{"type": "text", "body": "Hi."}]))

    assert main([str(data_path), "--export", target, "--export-dir", str(export_dir)]) == 0

    assert capsys.readouterr().out.splitlines() == [f"OK  {export_dir / 'page.md'}"]
    assert (export_dir / "page.md").read_text(encoding="utf-8") == expected_page


def test_the_cli_writes_an_export_under_out_named_for_the_file_and_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_path = write_report(tmp_path, make_report())
    monkeypatch.chdir(tmp_path)

    assert main([str(data_path), "--export", "markdown"]) == 0

    assert (tmp_path / "out" / "doc.markdown" / "page.md").read_text(
        encoding="utf-8"
    ) == "# Test Report\n\nHello.\n"


def test_the_cli_prints_one_ok_line_per_chunk_file(
    tmp_path: Path, export_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data_path = write_report(tmp_path, make_report(blocks=heading_sections(2, "v = 5\n" * 20)))

    argv = [str(data_path), "--export", "notion", "--chunk", "200", "--export-dir", str(export_dir)]

    assert main(argv) == 0

    assert capsys.readouterr().out.splitlines() == [
        f"OK  {export_dir / 'page.00.md'}",
        f"OK  {export_dir / 'page.01.md'}",
    ]


def test_check_then_export_of_a_valid_file_writes_the_page(tmp_path: Path, export_dir: Path) -> None:
    data_path = write_report(tmp_path, make_report())

    assert main(["--check", str(data_path), "--export", "markdown", "--export-dir", str(export_dir)]) == 0

    assert (export_dir / "page.md").read_text(encoding="utf-8") == "# Test Report\n\nHello.\n"


def test_the_cli_checks_before_it_exports_and_writes_nothing_for_an_invalid_file(
    tmp_path: Path, export_dir: Path
) -> None:
    data_path = write_report(tmp_path, make_report(blocks=[{"type": "text", "oops": 1}]))

    assert main(["--check", str(data_path), "--export", "notion", "--export-dir", str(export_dir)]) == 1

    assert not export_dir.exists()


def test_an_export_of_an_invalid_file_without_check_reports_the_error_and_writes_nothing(
    tmp_path: Path, export_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data_path = write_report(tmp_path, make_report(blocks=[{"type": "text", "body": "[x](#nowhere)"}]))

    assert main([str(data_path), "--export", "markdown", "--export-dir", str(export_dir)]) == 1

    assert capsys.readouterr().err == (
        "error: blocks.0.body: rich text links to unknown anchor '#nowhere': "
        "no heading or section has that id\n"
    )
    assert not export_dir.exists()


def test_an_export_dir_that_cannot_be_written_reports_the_error_and_leaves_the_file_alone(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data_path = write_report(tmp_path, make_report())
    blocker = tmp_path / "taken"
    blocker.write_text("a file, not a folder", encoding="utf-8")

    assert main([str(data_path), "--export", "notion", "--export-dir", str(blocker)]) == 1

    assert capsys.readouterr().err == f"error: [Errno 17] File exists: '{blocker}'\n"
    assert blocker.read_text(encoding="utf-8") == "a file, not a folder"


@pytest.mark.parametrize(
    ("argv_tail", "message"),
    [
        pytest.param(["--export", "notion", "-o", "x.html"], EXPORT_CLASH, id="with-out"),
        pytest.param(["--export", "notion", "--pdf", "x.pdf"], EXPORT_CLASH, id="with-pdf"),
        pytest.param(["--export", "notion", "--embed"], EXPORT_CLASH, id="with-embed"),
        pytest.param(["--export", "notion", "--watch"], EXPORT_CLASH, id="with-watch"),
        pytest.param(["--export", "notion", "--emit-json"], EXPORT_CLASH, id="with-emit-json"),
        pytest.param(["--export", "notion", "--live"], HTML_ONLY, id="with-live"),
        pytest.param(["--export", "notion", "--if-stale"], HTML_ONLY, id="with-if-stale"),
        pytest.param(["--export", "notion", "--no-source"], HTML_ONLY, id="with-no-source"),
        pytest.param(["--export", "markdown", "--export-dir", ""], BLANK_EXPORT_DIR, id="empty-dir"),
        pytest.param(["--export", "notion", "--export-dir", "  "], BLANK_EXPORT_DIR, id="blank-dir"),
        pytest.param(["--chunk", "100"], DIR_OR_CHUNK_ALONE, id="chunk-alone"),
        pytest.param(["--export-dir", "d"], DIR_OR_CHUNK_ALONE, id="dir-alone"),
        pytest.param(["--export-dir", ""], DIR_OR_CHUNK_ALONE, id="empty-dir-alone"),
        pytest.param(["--export", "markdown", "--chunk", "100"], CHUNK_NOTION_ONLY, id="chunk-markdown"),
        pytest.param(["--export", "notion", "--chunk", "0"], CHUNK_NOT_POSITIVE, id="chunk-zero"),
        pytest.param(["--export", "notion", "--chunk", "-5"], CHUNK_NOT_POSITIVE, id="chunk-negative"),
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
        main(["--check", str(first), str(second), "--export", "notion"])

    assert raised.value.code == 2
    assert (
        "an output flag renders one file: pass a single content file, or drop -o/--pdf/--embed/--export"
        in capsys.readouterr().err
    )


@pytest.mark.parametrize(
    ("manifest", "expected_warning"),
    [
        pytest.param(None, "", id="first-export"),
        pytest.param('{"title": "T", "files": ["page.md"]}', "", id="readable"),
        pytest.param(
            "not json",
            "warning: {path} could not be read; pages an earlier export wrote were left in place\n",
            id="unreadable",
        ),
    ],
)
def test_the_cli_warns_when_an_earlier_export_manifest_cannot_be_read(
    tmp_path: Path,
    export_dir: Path,
    capsys: pytest.CaptureFixture[str],
    manifest: str | None,
    expected_warning: str,
) -> None:
    data_path = write_report(tmp_path, make_report())
    if manifest is not None:
        export_dir.mkdir()
        (export_dir / EXPORT_MANIFEST).write_text(manifest, encoding="utf-8")

    assert main([str(data_path), "--export", "notion", "--export-dir", str(export_dir)]) == 0

    captured = capsys.readouterr()
    assert (captured.err, captured.out) == (
        expected_warning.format(path=export_dir / EXPORT_MANIFEST),
        f"OK  {export_dir / 'page.md'}\n",
    )


def test_the_cli_reports_a_section_too_long_for_the_chunk(
    tmp_path: Path, export_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data_path = write_report(tmp_path, make_report(blocks=heading_sections(1, "w = 4\n" * 40)))

    assert main([str(data_path), "--export", "notion", "--chunk", "50", "--export-dir", str(export_dir)]) == 0

    captured = capsys.readouterr()
    assert (captured.err, captured.out) == (
        "warning: section '## Part 0' is longer than --chunk 50 and stays whole\n",
        f"OK  {export_dir / 'page.00.md'}\n",
    )
