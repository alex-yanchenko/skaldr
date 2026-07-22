import json
from pathlib import Path

import pytest
import yaml

from skaldr.cli import main
from skaldr.errors import ReportError
from skaldr.models import Report
from tests.conftest import REPO_ROOT
from tests.factories import make_reconciled_table, make_report


def _write(tmp_path: Path, data: dict[str, object], name: str = "report.yaml") -> Path:
    path = tmp_path / name
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return path


def test_success_exit_code_and_summary(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    data_path = _write(tmp_path, make_report())
    out_path = tmp_path / "report.html"

    exit_code = main([str(data_path), "-o", str(out_path)])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert out_path.exists()
    assert "1 block, 0 badges" in captured.out


def test_reconciliation_failure_exits_1_on_stderr(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    table = make_reconciled_table(
        reconcile={"total": 100, "column": "count", "handled": {"label": "Clean", "value": 80}},
    )
    data_path = _write(tmp_path, make_report(blocks=[table]))

    exit_code = main([str(data_path), "-o", str(tmp_path / "report.html")])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "RECONCILIATION FAILED" in captured.err
    assert not (tmp_path / "report.html").exists()


def test_missing_data_file_exits_1(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main([str(tmp_path / "nope.yaml")])

    assert exit_code == 1
    assert "file not found" in capsys.readouterr().err


def test_no_arguments_is_a_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main([])

    captured = capsys.readouterr()
    assert excinfo.value.code == 2
    assert "a content file is required (or use --write-schema)" in captured.err


def test_malformed_yaml_exits_1(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    data_path = tmp_path / "broken.yaml"
    data_path.write_text("blocks: [unclosed\nversion: 1", encoding="utf-8")

    exit_code = main([str(data_path), "-o", str(tmp_path / "r.html")])

    assert exit_code == 1
    assert "invalid YAML in" in capsys.readouterr().err


def test_pdf_renders_the_full_page_with_sections_expanded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, Path]] = []

    def record(html: str, path: Path) -> None:
        calls.append((html, path))

    monkeypatch.setattr("skaldr.cli.html_to_pdf", record)
    section = {"type": "section", "title": "S", "collapsed": True, "blocks": [{"type": "text", "body": "hi"}]}
    data_path = _write(tmp_path, make_report(blocks=[section]))
    pdf_out = tmp_path / "r.pdf"

    exit_code = main([str(data_path), "--pdf", str(pdf_out)])

    assert exit_code == 0
    assert len(calls) == 1
    html, path = calls[0]
    assert path == pdf_out.resolve()
    # a collapsed section is forced open so the PDF captures its body (headless print can't run JS)
    assert '<details class="section" open><summary>S</summary>' in html


def test_pdf_with_out_writes_html_first_then_the_pdf(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[Path] = []

    def record(_html: str, path: Path) -> None:
        calls.append(path)

    monkeypatch.setattr("skaldr.cli.html_to_pdf", record)
    data_path = _write(tmp_path, make_report())
    html_out, pdf_out = tmp_path / "r.html", tmp_path / "r.pdf"

    exit_code = main([str(data_path), "-o", str(html_out), "--pdf", str(pdf_out)])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert html_out.exists()
    assert calls == [pdf_out.resolve()]
    assert f"OK  {html_out.resolve()}" in captured.out
    assert f"OK  {pdf_out.resolve()}" in captured.out


def test_pdf_failure_still_writes_the_requested_html(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def boom(_html: str, _path: Path) -> None:
        raise ReportError("no browser")

    monkeypatch.setattr("skaldr.cli.html_to_pdf", boom)
    data_path = _write(tmp_path, make_report())
    html_out, pdf_out = tmp_path / "r.html", tmp_path / "r.pdf"

    exit_code = main([str(data_path), "-o", str(html_out), "--pdf", str(pdf_out)])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert html_out.exists()  # HTML is written before the PDF step, so a browser failure doesn't lose it
    assert f"OK  {html_out.resolve()}" in captured.out
    assert "error: no browser" in captured.err
    assert not pdf_out.exists()


def test_embed_with_pdf_and_no_out_is_a_usage_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data_path = _write(tmp_path, make_report())

    with pytest.raises(SystemExit) as excinfo:
        main([str(data_path), "--pdf", str(tmp_path / "r.pdf"), "--embed"])

    assert excinfo.value.code == 2
    assert "--embed has no effect with --pdf alone" in capsys.readouterr().err


def test_write_schema_writes_current_schema(tmp_path: Path) -> None:
    schema_path = tmp_path / "schema" / "page.schema.json"

    exit_code = main(["--write-schema", str(schema_path)])

    assert exit_code == 0
    assert json.loads(schema_path.read_text(encoding="utf-8")) == Report.model_json_schema()


def test_committed_schema_is_fresh() -> None:
    committed = json.loads((REPO_ROOT / "schema" / "page.schema.json").read_text(encoding="utf-8"))

    assert committed == Report.model_json_schema()


def test_every_field_has_a_description() -> None:
    """The schema is the API + docs (principle 9), so every field is documented — except the
    `type` discriminator, whose value (e.g. 'heading') is self-evident."""
    schema = Report.model_json_schema()
    undocumented = [
        f"{def_name}.{field}"
        for def_name, definition in schema.get("$defs", {}).items()
        for field, spec in definition.get("properties", {}).items()
        if field != "type" and "description" not in spec
    ]

    assert undocumented == []


def test_check_valid_file_exits_0_without_rendering(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data_path = _write(tmp_path, make_report())
    out_path = tmp_path / "report.html"

    exit_code = main(["--check", str(data_path)])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert f"OK    {data_path}" in captured.out
    assert not out_path.exists()  # --check never writes


def test_check_invalid_file_exits_1_on_stderr(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    data_path = _write(tmp_path, make_report(blocks=[{"type": "text", "oops": 1}]))

    exit_code = main(["--check", str(data_path)])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert f"FAIL  {data_path}" in captured.err


def test_check_multiple_files_fails_if_any_is_invalid(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # bad BEFORE good: proves --check keeps going after the first failure (a stop-on-first-failure
    # regression would drop the trailing good file and its OK line).
    bad = _write(tmp_path, make_report(blocks=[{"type": "text", "oops": 1}]), "bad.yaml")
    good = _write(tmp_path, make_report(), "good.yaml")

    exit_code = main(["--check", str(bad), str(good)])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert f"OK    {good}" in captured.out  # the good one, reported after the failing one
    assert f"FAIL  {bad}" in captured.err
    assert "1 file failed" in captured.err


def test_check_without_a_file_errors(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["--check"])

    assert excinfo.value.code == 2
    assert "--check needs at least one content file" in capsys.readouterr().err


def test_check_reports_a_missing_file_as_a_failure(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "nope.yaml"

    exit_code = main(["--check", str(missing)])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert f"FAIL  {missing}: file not found" in captured.err  # no traceback escapes


def test_check_validates_through_an_include(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # an invalid block hidden inside an !included fragment must fail --check on that block's error,
    # not merely because the splice produced something else — so assert the offending field surfaces.
    (tmp_path / "blocks.yaml").write_text("- type: text\n  oops: 1\n", encoding="utf-8")
    main_path = tmp_path / "main.yaml"
    main_path.write_text("version: 1\nmeta:\n  title: T\nblocks: !include blocks.yaml\n", encoding="utf-8")

    exit_code = main(["--check", str(main_path)])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert f"FAIL  {main_path}" in captured.err
    assert "oops" in captured.err  # the fragment's bad field, not a generic splice failure


def test_emit_json_flattens_an_include(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "blocks.yaml").write_text("- type: text\n  body: from fragment\n", encoding="utf-8")
    main_path = tmp_path / "main.yaml"
    main_path.write_text("version: 1\nmeta:\n  title: T\nblocks: !include blocks.yaml\n", encoding="utf-8")

    exit_code = main(["--emit-json", str(main_path)])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert json.loads(captured.out)["blocks"] == [
        {"type": "text", "body": "from fragment", "muted": False, "span": None}
    ]


def test_render_rejects_multiple_files(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    good = _write(tmp_path, make_report(), "a.yaml")
    other = _write(tmp_path, make_report(), "b.yaml")

    with pytest.raises(SystemExit) as excinfo:
        main([str(good), str(other), "-o", str(tmp_path / "out.html")])

    assert excinfo.value.code == 2
    assert "only one content file can be processed at a time" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("argv_tail", "expected"),
    [
        (["--emit-json"], "mutually exclusive"),
        (["-o", "out.html"], "-o/--pdf/--embed do nothing"),
        (["--embed"], "-o/--pdf/--embed do nothing"),
    ],
)
def test_check_rejects_conflicting_output_flags(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], argv_tail: list[str], expected: str
) -> None:
    data_path = _write(tmp_path, make_report())

    with pytest.raises(SystemExit) as excinfo:
        main(["--check", str(data_path), *argv_tail])

    assert excinfo.value.code == 2
    assert expected in capsys.readouterr().err


@pytest.mark.parametrize(
    "raw",
    [
        make_report(blocks=[{"type": "text", "body": "hi"}]),
        make_report(blocks=[make_reconciled_table()]),  # a nested block with rows + reconcile
    ],
)
def test_emit_json_prints_the_normalised_model(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], raw: dict[str, object]
) -> None:
    data_path = _write(tmp_path, raw)
    out_path = tmp_path / "report.html"

    exit_code = main(["--emit-json", str(data_path)])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert not out_path.exists()  # no HTML written
    # stdout is exactly the validated model dumped as JSON — every field (meta, badges, nested
    # blocks) filled with its normalised default, nothing dropped or reshaped.
    assert json.loads(captured.out) == Report.model_validate(raw).model_dump(mode="json")


def test_emit_json_invalid_file_exits_1(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    data_path = _write(tmp_path, make_report(blocks=[{"type": "text", "oops": 1}]))

    exit_code = main(["--emit-json", str(data_path)])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "error: invalid content data" in captured.err
