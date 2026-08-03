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


def test_version_prints_the_installed_version_and_exits(capsys: pytest.CaptureFixture[str]) -> None:
    # argparse's version action prints to stdout and exits 0 via SystemExit.
    from importlib.metadata import version

    with pytest.raises(SystemExit) as exc:
        main(["--version"])

    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == f"skaldr {version('skaldr')}"


def test_render_embeds_source_and_extract_source_recovers_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data_path = _write(tmp_path, make_report())
    out_path = tmp_path / "report.html"

    assert main([str(data_path), "-o", str(out_path)]) == 0
    capsys.readouterr()  # drain the render summary
    assert main(["--extract-source", str(out_path)]) == 0

    recovered = capsys.readouterr().out
    assert recovered == data_path.read_text(encoding="utf-8")  # exact round-trip, no HTML/CSS


def test_no_source_suppresses_the_embed(tmp_path: Path) -> None:
    data_path = _write(tmp_path, make_report())
    out_path = tmp_path / "report.html"

    assert main([str(data_path), "-o", str(out_path), "--no-source"]) == 0

    assert "skaldr-source" not in out_path.read_text(encoding="utf-8")


def test_extract_source_reports_when_no_source_is_embedded(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    plain = tmp_path / "plain.html"
    plain.write_text("<html><body>not a skaldr page</body></html>", encoding="utf-8")

    assert main(["--extract-source", str(plain)]) == 1
    assert "no embedded skaldr source" in capsys.readouterr().err


def test_extract_source_reports_an_unreadable_target(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--extract-source", str(tmp_path / "nope.html")]) == 1
    assert "could not read" in capsys.readouterr().err


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
    assert '<details class="section" id="s" open><summary>S</summary>' in html


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


def test_check_notes_unfilled_placeholders_but_passes_without_strict(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data_path = _write(tmp_path, make_report(blocks=[{"type": "text", "body": "Open {{url}}."}]))

    exit_code = main(["--check", str(data_path)])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "1 unfilled placeholder: url" in captured.out


def test_check_strict_fails_on_unfilled_placeholders_with_a_plural_message(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data_path = _write(tmp_path, make_report(blocks=[{"type": "text", "body": "{{url}} and {{ticket}}."}]))

    exit_code = main(["--check", "--strict", str(data_path)])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "2 unfilled placeholders: ticket, url" in captured.err  # plural + sorted


def test_check_strict_passes_when_no_placeholders_remain(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data_path = _write(tmp_path, make_report(blocks=[{"type": "text", "body": "Open the real URL."}]))

    exit_code = main(["--check", "--strict", str(data_path)])

    assert exit_code == 0
    assert f"OK    {data_path}" in capsys.readouterr().out


def test_strict_without_check_is_an_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    data_path = _write(tmp_path, make_report())

    with pytest.raises(SystemExit) as excinfo:
        main(["--strict", str(data_path)])

    assert excinfo.value.code == 2  # argparse usage error
    assert "--strict only applies to --check" in capsys.readouterr().err


def test_check_fails_cleanly_on_a_render_time_error_without_a_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # A dangling `#anchor` link is schema-valid but fails at render; --check must report FAIL and keep
    # going (never escape as a traceback), then still process the next file.
    bad = _write(tmp_path, make_report(blocks=[{"type": "text", "body": "[x](#nope)"}]), name="bad.yaml")
    good = _write(tmp_path, make_report(), name="good.yaml")

    exit_code = main(["--check", str(bad), str(good)])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert f"FAIL  {bad}" in captured.err
    assert "unknown anchor '#nope'" in captured.err
    assert f"OK    {good}" in captured.out  # the batch continued past the failing file


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


def test_watch_renders_on_start_then_stops_on_interrupt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # the initial render runs before the first sleep; interrupting there leaves just that render
    def stop(_seconds: float) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr("time.sleep", stop)
    data_path = _write(tmp_path, make_report())
    out_path = tmp_path / "out.html"

    rc = main(["--watch", str(data_path), "-o", str(out_path)])

    captured = capsys.readouterr()
    assert rc == 0
    assert out_path.exists()  # the real render ran on start
    assert f"OK  {out_path}" in captured.out
    assert "stopped watching" in captured.out


def test_watch_survives_an_invalid_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # an invalid file must not crash the loop: the start render prints its error and returns, the loop
    # reaches the interrupt and exits 0.
    def stop(_seconds: float) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr("time.sleep", stop)
    data_path = _write(tmp_path, make_report(blocks=[{"type": "text", "oops": 1}]))
    out_path = tmp_path / "out.html"

    rc = main(["--watch", str(data_path), "-o", str(out_path)])

    captured = capsys.readouterr()
    assert rc == 0  # the bad render didn't crash the loop
    assert "error:" in captured.err
    assert not out_path.exists()
    assert "stopped watching" in captured.out


@pytest.mark.parametrize("argv_tail", [["--check"], ["--emit-json"], ["--pdf", "r.pdf"]])
def test_watch_rejects_incompatible_modes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], argv_tail: list[str]
) -> None:
    data_path = _write(tmp_path, make_report())

    with pytest.raises(SystemExit) as excinfo:
        main(["--watch", str(data_path), *argv_tail])

    assert excinfo.value.code == 2
    assert "--watch" in capsys.readouterr().err


def test_watch_re_renders_only_when_the_file_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    data_path = _write(tmp_path, make_report())
    out_path = tmp_path / "out.html"
    renders: list[Path] = []

    def fake_render(_dp: Path, op: Path, *, embed: bool, no_source: bool = False) -> int:  # noqa: ARG001
        renders.append(op)
        return 0

    monkeypatch.setattr("skaldr.cli._render_once", fake_render)
    # after the initial render (last=1.0): unchanged (1.0, no render), momentarily missing (None, no
    # render), then changed (2.0, one render) — exercises all three branches of the poll guard.
    mtimes = iter([1.0, 1.0, None, 2.0])

    def fake_mtime(_p: Path) -> float | None:
        return next(mtimes)

    monkeypatch.setattr("skaldr.cli._mtime", fake_mtime)
    sleeps = {"n": 0}

    def fake_sleep(_seconds: float) -> None:
        sleeps["n"] += 1
        if sleeps["n"] >= 4:  # let the same / missing / changed iterations all run first
            raise KeyboardInterrupt

    monkeypatch.setattr("time.sleep", fake_sleep)

    rc = main(["--watch", str(data_path), "-o", str(out_path)])

    assert rc == 0
    # initial render + exactly one on-change render (the unchanged and missing polls did NOT render)
    assert len(renders) == 2
    assert "stopped watching" in capsys.readouterr().out


def test_watch_uses_the_default_out_path_when_no_output_given(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def stop(_seconds: float) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr("time.sleep", stop)
    monkeypatch.chdir(tmp_path)  # default out is out/<stem>.html under the cwd
    data_path = _write(tmp_path, make_report(), "plan.yaml")

    rc = main(["--watch", str(data_path)])

    assert rc == 0
    assert (tmp_path / "out" / "plan.html").exists()


def test_watch_exits_cleanly_on_interrupt_during_the_initial_render(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Ctrl-C landing during the very first render must still exit cleanly (the initial render is inside
    # the interrupt handler, not before it).
    def interrupt(_dp: Path, _op: Path, *, embed: bool, no_source: bool = False) -> int:  # noqa: ARG001
        raise KeyboardInterrupt

    monkeypatch.setattr("skaldr.cli._render_once", interrupt)
    data_path = _write(tmp_path, make_report())

    rc = main(["--watch", str(data_path), "-o", str(tmp_path / "o.html")])

    assert rc == 0
    assert "stopped watching" in capsys.readouterr().out


def test_watch_survives_a_render_error_that_is_not_a_report_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # a non-ReportError/OSError failure (e.g. a template bug) must be caught too, not crash the loop
    def boom(*_args: object, **_kwargs: object) -> None:
        raise ValueError("boom")

    monkeypatch.setattr("skaldr.cli.render_report", boom)

    def stop(_seconds: float) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr("time.sleep", stop)
    data_path = _write(tmp_path, make_report())

    rc = main(["--watch", str(data_path), "-o", str(tmp_path / "o.html")])

    captured = capsys.readouterr()
    assert rc == 0  # the ValueError was caught; the loop reached the interrupt
    assert "boom" in captured.err
