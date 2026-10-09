import json
from pathlib import Path

import pytest

from skaldr.cli import main
from skaldr.export import EXPORT_MANIFEST, ExportResult, export_adf
from skaldr.export.adf import compact_adf_length
from skaldr.models import load_report
from tests.conftest import REPO_ROOT
from tests.factories import folder_texts, make_report, make_toggle, write_report

EXAMPLE = REPO_ROOT / "data" / "example.yaml"
ADF_GOLDEN = REPO_ROOT / "tests" / "golden" / "example.adf"
HI_DOCUMENT = {
    "version": 1,
    "type": "doc",
    "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Hi."}]}],
}


@pytest.fixture
def export_dir(tmp_path: Path) -> Path:
    return tmp_path / "exported"


def test_the_example_exports_to_the_adf_golden_regenerated_by_the_export_command(tmp_path: Path) -> None:
    export_adf(load_report(EXAMPLE), tmp_path)

    assert folder_texts(tmp_path) == folder_texts(ADF_GOLDEN)


def test_an_adf_export_writes_the_body_as_page_adf_json_without_the_title(tmp_path: Path) -> None:
    report = load_report(write_report(tmp_path, make_report(blocks=[{"type": "text", "body": "Hi."}])))
    out_dir = tmp_path / "out"

    result = export_adf(report, out_dir)

    assert result == ExportResult("Test Report", (out_dir / "page.adf.json",))
    assert json.loads((out_dir / "page.adf.json").read_text(encoding="utf-8")) == HI_DOCUMENT


def test_the_cli_exports_adf_and_prints_the_path(
    tmp_path: Path, export_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data_path = write_report(tmp_path, make_report(blocks=[{"type": "text", "body": "Hi."}]))

    assert main([str(data_path), "--export", "adf", "--export-dir", str(export_dir)]) == 0

    assert capsys.readouterr().out.splitlines() == [f"OK  {export_dir / 'page.adf.json'}"]
    assert json.loads((export_dir / "page.adf.json").read_text(encoding="utf-8")) == HI_DOCUMENT


def test_the_cli_writes_an_adf_export_under_out_named_for_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_path = write_report(tmp_path, make_report())
    monkeypatch.chdir(tmp_path)

    assert main([str(data_path), "--export", "adf"]) == 0

    assert (tmp_path / "out" / "doc.adf" / "page.adf.json").is_file()


def test_the_manifest_lists_the_adf_page(tmp_path: Path, export_dir: Path) -> None:
    data_path = write_report(tmp_path, make_report())

    assert main([str(data_path), "--export", "adf", "--export-dir", str(export_dir)]) == 0
    manifest = json.loads((export_dir / EXPORT_MANIFEST).read_text(encoding="utf-8"))

    assert manifest == {"title": "Test Report", "files": ["page.adf.json"]}


def test_a_re_export_to_the_same_folder_with_another_target_removes_the_earlier_adf_page(
    tmp_path: Path, export_dir: Path
) -> None:
    data_path = write_report(tmp_path, make_report())
    assert main([str(data_path), "--export", "adf", "--export-dir", str(export_dir)]) == 0

    assert main([str(data_path), "--export", "markdown", "--export-dir", str(export_dir)]) == 0

    assert sorted(path.name for path in export_dir.iterdir()) == [EXPORT_MANIFEST, "page.md"]


def test_the_cli_fails_and_keeps_a_page_adf_json_it_did_not_write(
    tmp_path: Path, export_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data_path = write_report(tmp_path, make_report())
    export_dir.mkdir()
    (export_dir / "page.adf.json").write_text("{}\n", encoding="utf-8")

    assert main([str(data_path), "--export", "adf", "--export-dir", str(export_dir)]) == 1

    captured = capsys.readouterr()
    assert (captured.out, captured.err, (export_dir / "page.adf.json").read_text(encoding="utf-8")) == (
        "",
        f"error: refusing to overwrite {export_dir / 'page.adf.json'}, which is not on the "
        f"{EXPORT_MANIFEST} list of files skaldr wrote; move it away or choose another --export-dir\n",
        "{}\n",
    )


def test_the_cli_names_the_block_adf_cannot_place_and_writes_nothing(
    tmp_path: Path, export_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    blocks = [make_toggle(make_toggle(make_toggle(make_toggle())))]
    data_path = write_report(tmp_path, make_report(blocks=blocks))

    assert main([str(data_path), "--export", "adf", "--export-dir", str(export_dir)]) == 1

    captured = capsys.readouterr()
    assert (captured.out, captured.err, export_dir.exists()) == (
        "",
        "error: ADF cannot place a toggle inside a toggle that is itself inside a toggle\n",
        False,
    )


def _oversize_warning(size: int) -> str:
    return f"the ADF description is {size:,} characters, over Jira's limit of 32,767"


def test_the_compact_length_counts_characters_of_the_json_a_description_field_receives() -> None:
    accented = {**HI_DOCUMENT, "content": [{"type": "paragraph", "content": [{"type": "text", "text": "é"}]}]}

    assert (compact_adf_length(HI_DOCUMENT), compact_adf_length(accented)) == (100, 98)


def test_an_adf_export_over_the_jira_limit_names_the_size_and_the_limit(tmp_path: Path) -> None:
    out_dir = tmp_path / "out"

    result = export_adf(load_report(EXAMPLE), out_dir)

    written = json.loads((out_dir / "page.adf.json").read_text(encoding="utf-8"))
    assert result.oversized_sections == (_oversize_warning(compact_adf_length(written)),)
    assert compact_adf_length(written) > 32_767


def test_an_adf_export_within_the_limit_has_no_warning(tmp_path: Path) -> None:
    report = load_report(write_report(tmp_path, make_report(blocks=[{"type": "text", "body": "Hi."}])))

    assert export_adf(report, tmp_path / "out").oversized_sections == ()


def test_the_cli_warns_when_the_adf_description_is_over_the_jira_limit(
    export_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main([str(EXAMPLE), "--export", "adf", "--export-dir", str(export_dir)]) == 0

    written = json.loads((export_dir / "page.adf.json").read_text(encoding="utf-8"))
    captured = capsys.readouterr()
    assert (captured.out, captured.err) == (
        f"OK  {export_dir / 'page.adf.json'}\n",
        f"warning: {_oversize_warning(compact_adf_length(written))}\n",
    )


def test_chunk_applies_only_to_notion(
    tmp_path: Path, export_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data_path = write_report(tmp_path, make_report())

    with pytest.raises(SystemExit):
        main([str(data_path), "--export", "adf", "--chunk", "100", "--export-dir", str(export_dir)])

    assert (
        capsys.readouterr()
        .err.splitlines()[-1]
        .endswith("--chunk splits a Notion page into files; it only applies with --export notion")
    )
