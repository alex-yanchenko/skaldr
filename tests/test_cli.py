import errno
import itertools
import json
import os
import re
import stat
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml

from skaldr.cli import main
from skaldr.errors import ReportError
from skaldr.models import Report, load_report, parse_report
from skaldr.render import render_embed, render_html
from skaldr.version import skaldr_version
from tests.conftest import REPO_ROOT
from tests.factories import make_query_request, make_reconciled_table, make_report

_UNKNOWN_TONE_TEXT = "x [a]{tone=x}"
_UNKNOWN_TONE_MESSAGE = (
    "unknown tone 'x' in {tone=x}: a tone is one of neutral, info, success, warning, danger, accent, teal, "
    "sky, or a palette name slate, blue, green, amber, red, violet"
)


def _note_table(**rows_or_groups: object) -> dict[str, object]:
    return {
        "type": "table",
        "columns": [{"key": "item", "label": "Item"}, {"key": "note", "label": "Note"}],
        **rows_or_groups,
    }


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


def test_check_fails_on_a_malformed_placeholder(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # a `{{a.b}}` blank must not slip past the gate as prose — --check (which runs a render pass) FAILs.
    data_path = _write(tmp_path, make_report(blocks=[{"type": "text", "body": "threshold {{a.b}}"}]))

    exit_code = main(["--check", str(data_path)])

    assert exit_code == 1
    assert "invalid placeholder '{{a.b}}'" in capsys.readouterr().err


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


def test_extract_source_recovers_a_source_that_carries_a_closing_script_tag(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data_path = tmp_path / "hostile.yaml"
    data_path.write_text(
        'version: 1\nmeta: {title: T}\nblocks:\n  - {type: code, content: "</script><img onerror=x>"}\n',
        encoding="utf-8",
    )
    out_path = tmp_path / "report.html"

    assert main([str(data_path), "-o", str(out_path)]) == 0
    capsys.readouterr()
    assert main(["--extract-source", str(out_path)]) == 0

    assert "</script><img onerror=x>" not in out_path.read_text(encoding="utf-8")
    assert capsys.readouterr().out == data_path.read_text(encoding="utf-8")


def test_embed_fragment_carries_the_source_so_extract_source_recovers_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data_path = _write(tmp_path, make_report())
    out_path = tmp_path / "fragment.html"

    assert main([str(data_path), "--embed", "-o", str(out_path)]) == 0
    capsys.readouterr()
    assert main(["--extract-source", str(out_path)]) == 0

    assert capsys.readouterr().out == data_path.read_text(encoding="utf-8")


@pytest.mark.parametrize("mode", [[], ["--embed"]], ids=["full-page", "embed-fragment"])
def test_no_source_suppresses_the_embed(tmp_path: Path, mode: list[str]) -> None:
    data_path = _write(tmp_path, make_report())
    out_path = tmp_path / "report.html"

    assert main([str(data_path), "-o", str(out_path), "--no-source", *mode]) == 0

    assert "skaldr-source" not in out_path.read_text(encoding="utf-8")


@pytest.mark.parametrize("mode", [[], ["--embed"]], ids=["full-page", "embed-fragment"])
def test_a_no_source_render_can_be_grepped_for_unfilled_placeholders(tmp_path: Path, mode: list[str]) -> None:
    data_path = _write(tmp_path, make_report(blocks=[{"type": "text", "body": "owner {{owner}}"}]))
    with_source = tmp_path / "with.html"
    without_source = tmp_path / "without.html"

    assert main([str(data_path), "-o", str(with_source), *mode]) == 0
    assert main([str(data_path), "-o", str(without_source), "--no-source", *mode]) == 0

    assert with_source.read_text(encoding="utf-8").count("{{owner}}") == 1
    assert "{{owner}}" not in without_source.read_text(encoding="utf-8")


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


def test_extract_source_gives_up_on_a_url_that_stalls_naming_it(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[tuple[str, float | None]] = []

    def stalled_urlopen(url: str, timeout: float | None = None) -> object:
        calls.append((url, timeout))
        raise TimeoutError("timed out")

    monkeypatch.setattr("skaldr.cli.urllib.request.urlopen", stalled_urlopen)

    exit_code = main(["--extract-source", "https://pages.example.com/plan.html"])

    assert (exit_code, capsys.readouterr().err, calls) == (
        1,
        "error: could not read https://pages.example.com/plan.html: timed out\n",
        [("https://pages.example.com/plan.html", 30)],
    )


class _StreamedResponse:
    def __init__(self, chunks: Iterator[bytes]) -> None:
        self._chunks = chunks

    def read(self, _size: int = -1) -> bytes:
        return next(self._chunks, b"")

    def __enter__(self) -> "_StreamedResponse":
        return self

    def __exit__(self, *_exc: object) -> None:
        return None


def _serve(monkeypatch: pytest.MonkeyPatch, chunks: Iterator[bytes]) -> None:
    def urlopen(_url: str, timeout: float | None = None) -> _StreamedResponse:
        assert timeout == 30
        return _StreamedResponse(chunks)

    monkeypatch.setattr("skaldr.cli.urllib.request.urlopen", urlopen)


def test_extract_source_reads_a_page_streamed_in_chunks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    data_path = _write(tmp_path, make_report())
    out_path = tmp_path / "report.html"
    assert main([str(data_path), "-o", str(out_path)]) == 0
    page = out_path.read_bytes()
    _serve(monkeypatch, iter([page[:1000], page[1000:]]))
    capsys.readouterr()

    exit_code = main(["--extract-source", "https://pages.example.com/plan.html"])

    assert (exit_code, capsys.readouterr().out) == (0, data_path.read_text(encoding="utf-8"))


def test_extract_source_gives_up_when_the_whole_fetch_outlasts_its_deadline(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    clock = iter(range(0, 1000, 10))
    monkeypatch.setattr("skaldr.cli.time.monotonic", lambda: float(next(clock)))
    _serve(monkeypatch, itertools.repeat(b"x"))

    exit_code = main(["--extract-source", "https://pages.example.com/plan.html"])

    assert (exit_code, capsys.readouterr().err) == (
        1,
        "error: could not read https://pages.example.com/plan.html: "
        "the page took longer than 30 seconds to download\n",
    )


def test_extract_source_refuses_a_page_larger_than_its_cap(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _serve(monkeypatch, itertools.repeat(b"x" * 1024 * 1024))

    exit_code = main(["--extract-source", "https://pages.example.com/plan.html"])

    assert (exit_code, capsys.readouterr().err) == (
        1,
        "error: could not read https://pages.example.com/plan.html: the page is larger than 16 MB\n",
    )


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


def test_write_schema_writes_through_a_symlink_and_keeps_the_link(tmp_path: Path) -> None:
    target = tmp_path / "shared" / "page.schema.json"
    target.parent.mkdir()
    target.write_text("{}", encoding="utf-8")
    link = tmp_path / "page.schema.json"
    link.symlink_to(target)

    exit_code = main(["--write-schema", str(link)])

    assert (exit_code, link.is_symlink(), json.loads(target.read_text(encoding="utf-8"))) == (
        0,
        True,
        Report.model_json_schema(),
    )


def test_write_schema_keeps_the_mode_of_the_file_it_replaces(tmp_path: Path) -> None:
    schema_path = tmp_path / "page.schema.json"
    schema_path.write_text("{}", encoding="utf-8")
    schema_path.chmod(0o600)

    assert main(["--write-schema", str(schema_path)]) == 0

    assert (
        json.loads(schema_path.read_text(encoding="utf-8")),
        stat.S_IMODE(schema_path.stat().st_mode),
        sorted(tmp_path.iterdir()),
    ) == (Report.model_json_schema(), 0o600, [schema_path])


@pytest.mark.skipif(os.geteuid() == 0, reason="root writes a read-only file")
def test_write_schema_refuses_a_read_only_file_naming_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    schema_path = tmp_path / "page.schema.json"
    schema_path.write_text("{}", encoding="utf-8")
    schema_path.chmod(0o444)

    exit_code = main(["--write-schema", str(schema_path)])

    assert (exit_code, capsys.readouterr().err, schema_path.read_text(encoding="utf-8")) == (
        1,
        f"error: [Errno {errno.EACCES}] the file is read-only, so skaldr leaves it as it is: "
        f"'{schema_path}'\n",
        "{}",
    )


def test_a_render_keeps_the_mode_of_the_page_it_replaces(tmp_path: Path) -> None:
    data_path = _write(tmp_path, make_report())
    out_path = tmp_path / "report.html"
    out_path.write_text("earlier page", encoding="utf-8")
    out_path.chmod(0o640)

    assert main([str(data_path), "-o", str(out_path), "--no-source"]) == 0

    assert (
        out_path.read_text(encoding="utf-8"),
        stat.S_IMODE(out_path.stat().st_mode),
        sorted(tmp_path.iterdir()),
    ) == (render_html(parse_report(make_report())), 0o640, [out_path, data_path])


def test_a_render_into_a_symlink_whose_folder_is_missing_creates_the_folder(tmp_path: Path) -> None:
    data_path = _write(tmp_path, make_report())
    target = tmp_path / "published" / "deep" / "report.html"
    link = tmp_path / "report.html"
    link.symlink_to(target)

    assert main([str(data_path), "-o", str(link), "--no-source"]) == 0

    assert (link.is_symlink(), target.read_text(encoding="utf-8")) == (
        True,
        render_html(parse_report(make_report())),
    )


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


def test_check_with_an_output_flag_renders_after_it_passes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """An output flag renders the file once the check passes, in one invocation."""
    data_path = _write(tmp_path, make_report())
    out_path = tmp_path / "report.html"

    exit_code = main(["--check", "--strict", str(data_path), "-o", str(out_path)])

    assert exit_code == 0
    assert f"OK    {data_path}" in capsys.readouterr().out
    assert out_path.is_file()


def test_check_gates_an_embed_fragment_too(tmp_path: Path) -> None:
    """The fallthrough reads `out or pdf or embed`, so every writing flag takes the same gate."""
    data_path = _write(tmp_path, make_report())
    out_path = tmp_path / "fragment.html"

    exit_code = main(["--check", str(data_path), "-o", str(out_path), "--embed"])

    assert exit_code == 0
    assert "<!doctype html>" not in out_path.read_text(encoding="utf-8").lower()


def test_checking_a_set_while_asking_for_one_render_is_refused_before_any_work(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """--check takes many files and an output flag renders one, so the combination has no meaning and
    is refused before any file is read. Reaching the single-file guard instead would print an OK line
    per file and then advise passing --check, which the reader already did."""
    first = _write(tmp_path, make_report(), name="a.yaml")
    second = _write(tmp_path, make_report(), name="b.yaml")

    with pytest.raises(SystemExit) as excinfo:
        main(["--check", str(first), str(second), "-o", str(tmp_path / "out.html")])

    captured = capsys.readouterr()
    assert excinfo.value.code == 2
    assert "an output flag renders one file" in captured.err
    assert "OK" not in captured.out


def _return_without_watching(*_args: object, **_kwargs: object) -> int:
    return 0


_NO_SOURCE_WITHOUT_A_PAGE = (
    "--no-source shapes the HTML page, and this command writes none; add -o to write one, or drop --no-source"
)


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        pytest.param(
            ["{data}", "--watch", "--if-stale"],
            "--watch re-renders on every save, so --if-stale has nothing to skip; drop one of them",
            id="watch-if-stale",
        ),
        pytest.param(["--check", "{data}", "--no-source"], _NO_SOURCE_WITHOUT_A_PAGE, id="check-no-source"),
        pytest.param(
            ["{data}", "--pdf", "{tmp}/x.pdf", "--no-source"], _NO_SOURCE_WITHOUT_A_PAGE, id="pdf-no-source"
        ),
        pytest.param(
            ["--emit-json", "{data}", "--no-source"], _NO_SOURCE_WITHOUT_A_PAGE, id="emit-json-no-source"
        ),
        pytest.param(
            ["--write-schema", "{tmp}/s.json", "--watch"],
            "--write-schema runs on its own; drop --watch",
            id="write-schema-watch",
        ),
        pytest.param(
            ["--guide", "{data}"], "--guide runs on its own; drop the content file", id="guide-data"
        ),
        pytest.param(
            ["--extract-source", "{tmp}/page.html", "-o", "{tmp}/x.html", "--no-source"],
            "--extract-source runs on its own; drop --out, --no-source",
            id="extract-source-out",
        ),
        pytest.param(
            ["--install-skill", "--install-plan-rule"],
            "--install-skill runs on its own; drop --install-plan-rule",
            id="two-installs",
        ),
        pytest.param(
            ["--install-plan-rule", "{data}", "--strict"],
            "--install-plan-rule runs on its own; drop the content file, --strict",
            id="plan-rule-with-a-file",
        ),
    ],
)
def test_a_flag_that_would_be_silently_ignored_is_refused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    argv: list[str],
    message: str,
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    monkeypatch.setattr("skaldr.cli._watch", _return_without_watching)
    data_path = _write(tmp_path, make_report())
    filled = [part.format(data=data_path, tmp=tmp_path) for part in argv]

    with pytest.raises(SystemExit) as raised:
        main(filled)

    assert (raised.value.code, capsys.readouterr().err.splitlines()[-1].split(": error: ", 1)[1]) == (
        2,
        message,
    )
    assert sorted(tmp_path.iterdir()) == [data_path]


def test_no_source_with_a_checked_render_writes_the_page_without_its_source(tmp_path: Path) -> None:
    data_path = _write(tmp_path, make_report())
    out_path = tmp_path / "report.html"

    assert main(["--check", str(data_path), "-o", str(out_path), "--no-source"]) == 0

    assert out_path.read_text(encoding="utf-8") == render_html(parse_report(make_report()))


def test_no_source_with_a_checked_embed_writes_the_default_fragment_without_its_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    data_path = _write(tmp_path, make_report())

    assert main(["--check", str(data_path), "--embed", "--no-source"]) == 0

    assert (tmp_path / "out" / "report.html").read_text(encoding="utf-8") == render_embed(
        parse_report(make_report())
    )


def test_no_source_is_accepted_with_watch_and_reaches_the_watch_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    watched: list[bool] = []

    def record_watch(*_args: object, no_source: bool = False, **_kwargs: object) -> int:
        watched.append(no_source)
        return 0

    monkeypatch.setattr("skaldr.cli._watch", record_watch)
    data_path = _write(tmp_path, make_report())

    assert (main([str(data_path), "--watch", "--no-source"]), watched) == (0, [True])


@pytest.mark.parametrize(
    ("argv_tail", "expected"),
    [
        (["--pdf", "r.pdf", "--embed"], "--embed has no effect with --pdf alone"),
        (["--live"], "shape a render"),
        (["--if-stale"], "shape a render"),
    ],
)
def test_a_flag_shape_conflict_is_settled_before_a_file_is_read(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], argv_tail: list[str], expected: str
) -> None:
    """Every argument-shape conflict is refused up front, so a check never prints a passing OK line
    for content that is valid and then exits non-zero for a reason that has nothing to do with it.
    A script reading the exit code would take that as invalid content. Each case names the guard it
    expects, since these reach two different ones and the exit code alone cannot tell them apart."""
    data_path = _write(tmp_path, make_report())
    tail = [str(tmp_path / part) if part.endswith(".pdf") else part for part in argv_tail]

    with pytest.raises(SystemExit) as excinfo:
        main(["--check", str(data_path), *tail])

    captured = capsys.readouterr()
    assert excinfo.value.code == 2
    assert expected in captured.err
    assert "OK" not in captured.out


def test_check_gates_an_embed_written_to_the_default_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--embed alone is the third of the gate's three writing flags, and it renders to the default
    path rather than one the reader named."""
    monkeypatch.chdir(tmp_path)
    data_path = _write(tmp_path, make_report())

    exit_code = main(["--check", str(data_path), "--embed"])

    written = tmp_path / "out" / f"{data_path.stem}.html"
    assert exit_code == 0
    assert "<!doctype html>" not in written.read_text(encoding="utf-8").lower()


def test_a_strict_failure_gates_the_render_like_an_invalid_one(tmp_path: Path) -> None:
    """A page whose placeholders are unfilled fails the check by a different path inside _check_files
    than a schema-invalid one, and the gate holds for both."""
    block = {"type": "text", "body": "hello {{name}}"}
    data_path = _write(tmp_path, make_report(blocks=[block]))
    out_path = tmp_path / "report.html"

    exit_code = main(["--check", "--strict", str(data_path), "-o", str(out_path)])

    assert exit_code == 1
    assert not out_path.exists()


def test_check_gates_a_pdf_render_too(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """--pdf without -o writes no HTML at all, so it reaches the render by its own branch."""
    calls: list[Path] = []

    def record(_html: str, path: Path) -> None:
        calls.append(path)

    monkeypatch.setattr("skaldr.cli.html_to_pdf", record)
    data_path = _write(tmp_path, make_report())
    pdf_out = tmp_path / "report.pdf"

    exit_code = main(["--check", str(data_path), "--pdf", str(pdf_out)])

    assert exit_code == 0
    assert calls == [pdf_out.resolve()]


def test_a_failed_check_writes_no_pdf_either(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[Path] = []

    def record(_html: str, path: Path) -> None:
        calls.append(path)

    monkeypatch.setattr("skaldr.cli.html_to_pdf", record)
    data_path = _write(tmp_path, make_report(blocks=[{"type": "text", "oops": 1}]))

    exit_code = main(["--check", str(data_path), "--pdf", str(tmp_path / "report.pdf")])

    assert exit_code == 1
    assert calls == []


def test_a_failed_check_writes_nothing_even_with_an_output_flag(tmp_path: Path) -> None:
    """The check is a gate, not a preamble: a page that fails it must not reach disk, or the loop
    would hand the author a rendered page and a FAIL line at the same time."""
    data_path = _write(tmp_path, make_report(blocks=[{"type": "text", "oops": 1}]))
    out_path = tmp_path / "report.html"

    exit_code = main(["--check", str(data_path), "-o", str(out_path)])

    assert exit_code == 1
    assert not out_path.exists()


def test_emit_json_still_refuses_an_output_flag(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    data_path = _write(tmp_path, make_report())

    with pytest.raises(SystemExit) as excinfo:
        main(["--emit-json", str(data_path), "-o", str(tmp_path / "report.html")])

    assert excinfo.value.code == 2
    assert "--emit-json only validates" in capsys.readouterr().err


def test_emit_json_refuses_a_heading_id_used_twice(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    blocks = [{"type": "heading", "text": "A", "id": "dup"}, {"type": "heading", "text": "B", "id": "dup"}]
    data_path = _write(tmp_path, make_report(blocks=blocks))

    exit_code = main(["--emit-json", str(data_path)])

    assert (exit_code, capsys.readouterr()) == (
        1,
        (
            "",
            "error: invalid content data: Value error, heading/section id(s) used more than once: ['dup'], "
            "at blocks.0.heading.id, blocks.1.heading.id; heading and section ids must be unique\n",
        ),
    )


def test_check_invalid_file_exits_1_on_stderr(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    data_path = _write(tmp_path, make_report(blocks=[{"type": "text", "oops": 1}]))

    exit_code = main(["--check", str(data_path)])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert f"FAIL  {data_path}" in captured.err


def test_check_reports_a_number_cell_beyond_float_range_as_a_failed_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    table = make_reconciled_table(groups=[{"name": "g", "rows": [{"issue": "x", "count": 10**400}]}])
    data_path = _write(tmp_path, make_report(blocks=[table]))

    exit_code = main(["--check", str(data_path)])

    assert (exit_code, capsys.readouterr().err) == (
        1,
        f"FAIL  {data_path}: invalid content data: blocks.0.table: Value error, groups.0.rows.0.count: "
        "must be between -1e+300 and 1e+300\n\n1 file failed\n",
    )


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


def test_check_strict_fails_on_placeholders_inside_a_link_label_and_url(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    body = (
        "Review [the PR](https://github.com/acme/repo/pull/{{pr}}) "
        "and [ticket {{ticket}}](https://example.com/t)."
    )
    data_path = _write(tmp_path, make_report(blocks=[{"type": "text", "body": body}]))

    exit_code = main(["--check", "--strict", str(data_path)])

    assert (exit_code, capsys.readouterr().err) == (
        1,
        f"FAIL  {data_path}: 2 unfilled placeholders: pr, ticket\n\n1 file failed\n",
    )


@pytest.mark.parametrize(
    ("blocks", "message"),
    [
        pytest.param(
            [
                {"type": "text", "body": "Intro."},
                {"type": "list", "items": ["fine", "the rate $`\\simga`$"]},
            ],
            "blocks.1.items.1: math expression '\\simga' uses \\simga, which latex2mathml does not know: "
            "check its spelling, or write \\text{...} for literal text",
            id="math-in-a-list-item",
        ),
        pytest.param(
            [{"type": "list", "items": [{"text": "parent", "items": ["ok", "see [a]{tone=purple}"]}]}],
            "blocks.0.items.0.items.1: unknown tone 'purple' in {tone=purple}: a tone is one of neutral, "
            "info, success, warning, danger, accent, teal, sky, or a palette name slate, blue, green, amber, "
            "red, violet",
            id="tone-in-a-nested-point",
        ),
        pytest.param(
            [{"type": "callout", "tone": "info", "body": "First.\n\nThen {{two words}}."}],
            "blocks.0.body: invalid placeholder '{{two words}}': a placeholder name is letters, digits, '_' "
            "or '-' only (a fill-me-later blank is written {{name}}; for a literal {{ use a `code` span)",
            id="placeholder-in-a-second-paragraph",
        ),
        pytest.param(
            [
                {"type": "code", "content": "write {{a b}} here"},
                {"type": "callout", "tone": "info", "body": "{{a b}}"},
            ],
            "blocks.1.body: invalid placeholder '{{a b}}': a placeholder name is letters, digits, '_' "
            "or '-' only (a fill-me-later blank is written {{name}}; for a literal {{ use a `code` span)",
            id="an-earlier-plain-field-holding-the-same-text-is-not-blamed",
        ),
        pytest.param(
            [
                {
                    "type": "comparison",
                    "options": ["A", "B"],
                    "rows": [{"feature": "f", "values": [True, "x [a]{tone=x}"]}],
                }
            ],
            "blocks.0.rows.0.values.1: unknown tone 'x' in {tone=x}: a tone is one of neutral, info, "
            "success, warning, danger, accent, teal, sky, or a palette name slate, blue, green, amber, red, "
            "violet",
            id="comparison-cell",
        ),
        pytest.param(
            [
                {
                    "type": "table",
                    "columns": [
                        {"key": "item", "label": "Item"},
                        {"key": "n", "label": "N", "kind": "number"},
                    ],
                    "groups": [
                        {
                            "name": "G",
                            "rows": [{"item": "a", "n": 1, "subrows": [{"label": "$` `$", "value": 1}]}],
                        }
                    ],
                }
            ],
            "blocks.0.groups.0.rows.0.subrows.0.label: inline math $` `$ is empty: write an expression "
            "between $` and `$, as in $`x_i`$",
            id="subrow-label-in-a-group",
        ),
        pytest.param(
            [{"type": "text", "body": "*a " * 260 + "b" + "*" * 260}],
            "blocks.0.body: rich text nests more than 20 marks, links or [text]{…} spans inside one "
            "another: flatten it",
            id="emphasis-nested-past-the-limit",
        ),
        pytest.param(
            [{"type": "list", "items": ["{{a\n\nb}}"]}],
            "blocks.0.items.0: invalid placeholder '{{a\n\nb}}': a placeholder name is letters, digits, "
            "'_' or '-' only (a fill-me-later blank is written {{name}}; for a literal {{ use a `code` span)",
            id="a-list-item-is-parsed-whole-across-a-blank-line",
        ),
        pytest.param(
            [{"type": "flow", "steps": [{"label": "A", "points": [_UNKNOWN_TONE_TEXT]}, {"label": "B"}]}],
            f"blocks.0.steps.0.points.0: {_UNKNOWN_TONE_MESSAGE}",
            id="flow-step-point",
        ),
        pytest.param(
            [
                {
                    "type": "fan",
                    "hub": {"label": "H"},
                    "spokes": [{"label": "S1"}, {"label": "S2", "points": ["ok", _UNKNOWN_TONE_TEXT]}],
                }
            ],
            f"blocks.0.spokes.1.points.1: {_UNKNOWN_TONE_MESSAGE}",
            id="fan-spoke-point",
        ),
        pytest.param(
            [_note_table(rows=[{"item": "a", "note": "ok"}, {"item": "b", "note": _UNKNOWN_TONE_TEXT}])],
            f"blocks.0.rows.1.note: {_UNKNOWN_TONE_MESSAGE}",
            id="ungrouped-table-cell",
        ),
        pytest.param(
            [
                _note_table(
                    groups=[
                        {"name": "G1", "rows": [{"item": "a", "note": "ok"}]},
                        {
                            "name": "G2",
                            "rows": [{"item": "b", "note": "ok"}, {"item": _UNKNOWN_TONE_TEXT, "note": ""}],
                        },
                    ]
                )
            ],
            f"blocks.0.groups.1.rows.1.item: {_UNKNOWN_TONE_MESSAGE}",
            id="second-group-second-row",
        ),
        pytest.param(
            [
                _note_table(
                    rows=[
                        {
                            "item": "a",
                            "note": "ok",
                            "subrows": [
                                {"label": "ok", "value": 1},
                                {"label": _UNKNOWN_TONE_TEXT, "value": 2},
                            ],
                        }
                    ]
                )
            ],
            f"blocks.0.rows.0.subrows.1.label: {_UNKNOWN_TONE_MESSAGE}",
            id="second-subrow",
        ),
    ],
)
def test_check_names_the_field_whose_rich_text_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], blocks: list[dict[str, object]], message: str
) -> None:
    data_path = _write(tmp_path, make_report(blocks=blocks))

    exit_code = main(["--check", str(data_path)])

    assert (exit_code, capsys.readouterr().err) == (1, f"FAIL  {data_path}: {message}\n\n1 file failed\n")


def test_check_passes_a_span_across_a_blank_line_in_a_list_item(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data_path = _write(tmp_path, make_report(blocks=[{"type": "list", "items": ["[a\n\nb]{tone=info}"]}]))

    exit_code = main(["--check", str(data_path)])

    assert (exit_code, capsys.readouterr().out) == (0, f"OK    {data_path}\n")


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


def test_emit_json_carries_a_requests_query_with_its_runner_language_and_text(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data_path = _write(tmp_path, make_report(blocks=[make_query_request()]))

    exit_code = main(["--emit-json", str(data_path)])

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out)["blocks"][0]["query"] == {
        "runner": "mongosh, orders database",
        "lang": "json",
        "content": '[{"$match": {"status": "open"}}, {"$count": "n"}]',
    }


def test_render_rejects_multiple_files(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    good = _write(tmp_path, make_report(), "a.yaml")
    other = _write(tmp_path, make_report(), "b.yaml")

    with pytest.raises(SystemExit) as excinfo:
        main([str(good), str(other), "-o", str(tmp_path / "out.html")])

    assert excinfo.value.code == 2
    assert "only one content file can be processed at a time" in capsys.readouterr().err


@pytest.mark.parametrize("flag", ["-o", "--embed"])
def test_emit_json_rejects_an_output_flag(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], flag: str
) -> None:
    data_path = _write(tmp_path, make_report())
    argv_tail = [flag, str(tmp_path / "out.html")] if flag == "-o" else [flag]

    with pytest.raises(SystemExit) as excinfo:
        main(["--emit-json", str(data_path), *argv_tail])

    assert excinfo.value.code == 2
    assert "-o/--pdf/--embed do nothing" in capsys.readouterr().err


def test_check_and_emit_json_are_mutually_exclusive(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data_path = _write(tmp_path, make_report())

    with pytest.raises(SystemExit) as excinfo:
        main(["--check", str(data_path), "--emit-json"])

    assert excinfo.value.code == 2
    assert "mutually exclusive" in capsys.readouterr().err


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


def test_watch_re_renders_a_save_that_leaves_the_yaml_unreadable_so_its_error_shows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    data_path = _write(tmp_path, make_report())
    sleeps = {"n": 0}

    def save_broken_yaml_then_stop(_seconds: float) -> None:
        sleeps["n"] += 1
        if sleeps["n"] > 1:
            raise KeyboardInterrupt
        mtime = data_path.stat().st_mtime
        data_path.write_text("blocks: [unclosed\n", encoding="utf-8")
        os.utime(data_path, (mtime + 10, mtime + 10))

    monkeypatch.setattr("time.sleep", save_broken_yaml_then_stop)

    assert main(["--watch", str(data_path), "-o", str(tmp_path / "out.html")]) == 0
    assert "changed, re-rendering" in capsys.readouterr().out


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

    def fake_render(
        _dp: Path,
        op: Path,
        *,
        embed: bool,  # noqa: ARG001
        no_source: bool = False,  # noqa: ARG001
        live: int | None = None,  # noqa: ARG001
    ) -> int:
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


def test_watch_honours_no_source_on_the_start_render_and_every_re_render(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_path = _write(tmp_path, make_report())
    no_source_per_render: list[bool] = []

    def fake_render(
        _dp: Path,
        _op: Path,
        *,
        embed: bool,  # noqa: ARG001
        no_source: bool = False,
        live: int | None = None,  # noqa: ARG001
    ) -> int:
        no_source_per_render.append(no_source)
        return 0

    monkeypatch.setattr("skaldr.cli._render_once", fake_render)
    mtimes = iter([1.0, 2.0])

    def fake_mtime(_p: Path) -> float | None:
        return next(mtimes)

    monkeypatch.setattr("skaldr.cli._mtime", fake_mtime)
    sleeps = {"n": 0}

    def fake_sleep(_seconds: float) -> None:
        sleeps["n"] += 1
        if sleeps["n"] >= 2:
            raise KeyboardInterrupt

    monkeypatch.setattr("time.sleep", fake_sleep)

    assert main(["--watch", str(data_path), "-o", str(tmp_path / "out.html"), "--no-source"]) == 0

    assert no_source_per_render == [True, True]


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
    def interrupt(
        _dp: Path,
        _op: Path,
        *,
        embed: bool,  # noqa: ARG001
        no_source: bool = False,  # noqa: ARG001
        live: int | None = None,  # noqa: ARG001
    ) -> int:
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


def test_live_adds_the_reloader_and_its_default_is_focus_only(tmp_path: Path) -> None:
    data_path = _write(tmp_path, make_report())
    out_path = tmp_path / "report.html"

    assert main([str(data_path), "-o", str(out_path), "--live"]) == 0

    html = out_path.read_text(encoding="utf-8")
    assert 'data-skaldr-live="0"' in html
    assert "visibilitychange" in html
    assert html.count("<script>") == 3


def test_live_with_an_interval_carries_it_as_the_poll_period(tmp_path: Path) -> None:
    data_path = _write(tmp_path, make_report())
    out_path = tmp_path / "report.html"

    assert main([str(data_path), "-o", str(out_path), "--live", "500"]) == 0

    assert 'data-skaldr-live="500"' in out_path.read_text(encoding="utf-8")


def test_a_page_rendered_without_live_carries_no_reloader(tmp_path: Path) -> None:
    data_path = _write(tmp_path, make_report())
    out_path = tmp_path / "report.html"

    assert main([str(data_path), "-o", str(out_path)]) == 0

    html = out_path.read_text(encoding="utf-8")
    assert "data-skaldr-live" not in html
    assert "skaldr:live:" not in html
    assert html.count("<script>") == 2


def test_live_is_refused_for_an_embed_fragment_which_ships_as_a_shared_artifact(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data_path = _write(tmp_path, make_report())

    with pytest.raises(SystemExit) as exc:
        main([str(data_path), "-o", str(tmp_path / "o.html"), "--embed", "--live"])

    assert exc.value.code == 2
    assert "--embed" in capsys.readouterr().err


def test_live_is_refused_with_pdf_alone_because_no_page_is_written(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`--pdf` without `-o` writes no HTML, and the reloader lives in the HTML. Accepting the pair
    renders the PDF and drops `--live` without saying so."""
    data_path = _write(tmp_path, make_report())

    with pytest.raises(SystemExit) as exc:
        main([str(data_path), "--pdf", str(tmp_path / "r.pdf"), "--live"])

    assert exc.value.code == 2
    assert "--live" in capsys.readouterr().err


def test_live_is_refused_for_emit_json_which_writes_no_page(tmp_path: Path) -> None:
    data_path = _write(tmp_path, make_report())

    with pytest.raises(SystemExit) as exc:
        main(["--emit-json", str(data_path), "--live"])

    assert exc.value.code == 2


def test_check_renders_a_live_page_once_it_passes(tmp_path: Path) -> None:
    """--check gates the render rather than replacing it, so every flag shaping the page still applies."""
    data_path = _write(tmp_path, make_report())
    out_path = tmp_path / "report.html"

    exit_code = main(["--check", str(data_path), "-o", str(out_path), "--live"])

    assert exit_code == 0
    assert "skaldr-live" in out_path.read_text(encoding="utf-8")


def test_live_refuses_a_negative_interval(tmp_path: Path) -> None:
    data_path = _write(tmp_path, make_report())

    with pytest.raises(SystemExit) as exc:
        main([str(data_path), "-o", str(tmp_path / "o.html"), "--live", "-5"])

    assert exc.value.code == 2


def test_if_stale_skips_a_render_when_the_output_is_current(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data_path = _write(tmp_path, make_report())
    out_path = tmp_path / "report.html"
    assert main([str(data_path), "-o", str(out_path)]) == 0
    first = out_path.stat().st_mtime_ns
    capsys.readouterr()

    assert main([str(data_path), "-o", str(out_path), "--if-stale"]) == 0

    assert out_path.stat().st_mtime_ns == first
    assert "up to date" in capsys.readouterr().out


def test_if_stale_renders_when_the_content_file_is_newer(tmp_path: Path) -> None:
    data_path = _write(tmp_path, make_report())
    out_path = tmp_path / "report.html"
    assert main([str(data_path), "-o", str(out_path)]) == 0
    first = out_path.stat().st_mtime_ns
    stale = out_path.stat().st_mtime - 60
    os.utime(out_path, (stale, stale))

    assert main([str(data_path), "-o", str(out_path), "--if-stale"]) == 0

    assert out_path.stat().st_mtime_ns != first


def test_if_stale_renders_when_the_output_does_not_exist(tmp_path: Path) -> None:
    data_path = _write(tmp_path, make_report())
    out_path = tmp_path / "report.html"

    assert main([str(data_path), "-o", str(out_path), "--if-stale"]) == 0

    assert out_path.exists()


def test_if_stale_is_refused_for_emit_json_which_renders_nothing(tmp_path: Path) -> None:
    data_path = _write(tmp_path, make_report())

    with pytest.raises(SystemExit) as exc:
        main(["--emit-json", str(data_path), "--if-stale"])

    assert exc.value.code == 2


def test_check_and_if_stale_are_the_plan_loop(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Validate, then re-render only if the page is behind the source: one invocation."""
    data_path = _write(tmp_path, make_report())
    out_path = tmp_path / "report.html"
    assert main(["--check", str(data_path), "-o", str(out_path)]) == 0
    first = out_path.stat().st_mtime_ns
    capsys.readouterr()

    assert main(["--check", str(data_path), "-o", str(out_path), "--if-stale"]) == 0
    assert out_path.stat().st_mtime_ns == first


def _set_mtime(path: Path, seconds_ago: int) -> None:
    moment = time.time() - seconds_ago
    os.utime(path, (moment, moment))


def test_the_live_plan_loop_keeps_the_reloader_through_every_if_stale_re_render(tmp_path: Path) -> None:
    data_path = _write(tmp_path, make_report())
    out_path = tmp_path / "plan.html"
    assert main([str(data_path), "-o", str(out_path), "--live"]) == 0
    for body in ("first edit", "second edit"):
        _set_mtime(out_path, 60)
        _write(tmp_path, make_report(blocks=[{"type": "text", "body": body}]))
        assert main([str(data_path), "-o", str(out_path), "--if-stale"]) == 0

    edited = parse_report(make_report(blocks=[{"type": "text", "body": "second edit"}]))
    source = data_path.read_text(encoding="utf-8")
    assert out_path.read_text(encoding="utf-8") == render_html(edited, source=source, live=0)


def test_if_stale_keeps_a_live_page_that_is_current_untouched(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data_path = _write(tmp_path, make_report())
    out_path = tmp_path / "plan.html"
    assert main([str(data_path), "-o", str(out_path), "--live", "500"]) == 0
    first = out_path.stat().st_mtime_ns
    capsys.readouterr()

    exit_code = main([str(data_path), "-o", str(out_path), "--if-stale"])

    assert (exit_code, capsys.readouterr().out, out_path.stat().st_mtime_ns) == (
        0,
        f"up to date  {out_path}\n",
        first,
    )


@pytest.mark.parametrize(
    ("first_render", "if_stale_render", "embed", "with_source", "live"),
    [
        pytest.param([], ["--embed"], True, True, None, id="to-embed"),
        pytest.param([], ["--no-source"], False, False, None, id="to-no-source"),
        pytest.param(["--no-source"], [], False, True, None, id="back-to-source"),
        pytest.param(["--live"], ["--live", "500"], False, True, 500, id="to-another-interval"),
        pytest.param([], ["--live"], False, True, 0, id="to-live"),
    ],
)
def test_if_stale_re_renders_a_current_page_written_with_other_options(
    tmp_path: Path,
    first_render: list[str],
    if_stale_render: list[str],
    embed: bool,
    with_source: bool,
    live: int | None,
) -> None:
    data_path = _write(tmp_path, make_report())
    out_path = tmp_path / "plan.html"
    assert main([str(data_path), "-o", str(out_path), *first_render]) == 0

    assert main([str(data_path), "-o", str(out_path), "--if-stale", *if_stale_render]) == 0

    report = parse_report(make_report())
    source = data_path.read_text(encoding="utf-8") if with_source else None
    expected = render_embed(report, source=source) if embed else render_html(report, source=source, live=live)
    assert out_path.read_text(encoding="utf-8") == expected


def test_if_stale_re_renders_a_page_from_an_older_skaldr_and_keeps_its_live_interval(tmp_path: Path) -> None:
    data_path = _write(tmp_path, make_report())
    _set_mtime(data_path, 60)
    out_path = tmp_path / "plan.html"
    out_path.write_text('<!doctype html><html><body data-skaldr-live="300"></body></html>', encoding="utf-8")

    assert main([str(data_path), "-o", str(out_path), "--if-stale"]) == 0

    source = data_path.read_text(encoding="utf-8")
    assert out_path.read_text(encoding="utf-8") == render_html(
        parse_report(make_report()), source=source, live=300
    )


def test_if_stale_re_renders_when_an_included_fragment_is_newer_than_the_page(tmp_path: Path) -> None:
    part_path = tmp_path / "part.yaml"
    part_path.write_text("type: text\nbody: version one\n", encoding="utf-8")
    nested_path = tmp_path / "nested.yaml"
    nested_path.write_text("- !include part.yaml\n", encoding="utf-8")
    main_path = tmp_path / "main.yaml"
    main_path.write_text("version: 1\nmeta:\n  title: T\nblocks: !include nested.yaml\n", encoding="utf-8")
    out_path = tmp_path / "main.html"
    assert main([str(main_path), "-o", str(out_path)]) == 0
    for path, seconds_ago in ((main_path, 120), (nested_path, 120), (out_path, 60)):
        _set_mtime(path, seconds_ago)
    part_path.write_text("type: text\nbody: version two\n", encoding="utf-8")

    assert main([str(main_path), "-o", str(out_path), "--if-stale"]) == 0

    source = main_path.read_text(encoding="utf-8")
    assert out_path.read_text(encoding="utf-8") == render_html(load_report(main_path), source=source)


def test_if_stale_leaves_a_current_embed_fragment_alone(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data_path = _write(tmp_path, make_report())
    out_path = tmp_path / "fragment.html"
    assert main([str(data_path), "-o", str(out_path), "--embed"]) == 0
    first = out_path.stat().st_mtime_ns
    capsys.readouterr()

    exit_code = main([str(data_path), "-o", str(out_path), "--embed", "--if-stale"])

    assert (exit_code, capsys.readouterr().out, out_path.stat().st_mtime_ns) == (
        0,
        f"up to date  {out_path}\n",
        first,
    )


def test_if_stale_counts_a_page_exactly_as_old_as_its_content_as_current(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data_path = _write(tmp_path, make_report())
    out_path = tmp_path / "plan.html"
    assert main([str(data_path), "-o", str(out_path)]) == 0
    moment = time.time() - 60
    os.utime(data_path, (moment, moment))
    os.utime(out_path, (moment, moment))
    capsys.readouterr()

    exit_code = main([str(data_path), "-o", str(out_path), "--if-stale"])

    assert (exit_code, capsys.readouterr().out) == (0, f"up to date  {out_path}\n")


@pytest.mark.parametrize(
    ("content", "error"),
    [
        pytest.param("version: 1\nmeta: [unclosed\n", "error: invalid YAML in ", id="unloadable-yaml"),
        pytest.param(
            "version: 1\nmeta: {title: T}\nblocks: !include gone.yaml\n",
            "error: file not found: ",
            id="missing-include",
        ),
    ],
)
def test_if_stale_counts_content_it_cannot_load_as_stale_so_the_render_reports_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], content: str, error: str
) -> None:
    data_path = _write(tmp_path, make_report())
    out_path = tmp_path / "plan.html"
    assert main([str(data_path), "-o", str(out_path)]) == 0
    _set_mtime(data_path, 120)
    _set_mtime(out_path, 60)
    data_path.write_text(content, encoding="utf-8")
    _set_mtime(data_path, 120)
    capsys.readouterr()

    exit_code = main([str(data_path), "-o", str(out_path), "--if-stale"])

    captured = capsys.readouterr()
    assert (exit_code, captured.out, captured.err.startswith(error)) == (1, "", True)


def test_if_stale_with_pdf_always_renders_both_outputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    printed: list[Path] = []

    def record(_html: str, path: Path) -> None:
        printed.append(path)

    monkeypatch.setattr("skaldr.cli.html_to_pdf", record)
    data_path = _write(tmp_path, make_report())
    out_path, pdf_path = tmp_path / "plan.html", tmp_path / "plan.pdf"
    assert main([str(data_path), "-o", str(out_path)]) == 0
    out_path.write_text("a current page the pdf run must replace", encoding="utf-8")
    capsys.readouterr()

    exit_code = main([str(data_path), "-o", str(out_path), "--pdf", str(pdf_path), "--if-stale"])

    source = data_path.read_text(encoding="utf-8")
    assert (exit_code, printed, out_path.read_text(encoding="utf-8")) == (
        0,
        [pdf_path],
        render_html(parse_report(make_report()), source=source),
    )


@pytest.mark.parametrize(
    "earlier_page",
    [
        pytest.param(
            b'<html><head><meta name="skaldr-render" content="not json"></head></html>',
            id="bad-stamp",
        ),
        pytest.param(b"\xff\xfe not utf-8 \x80", id="not-utf-8"),
    ],
)
def test_if_stale_re_renders_a_page_it_cannot_read_a_stamp_from(tmp_path: Path, earlier_page: bytes) -> None:
    data_path = _write(tmp_path, make_report())
    _set_mtime(data_path, 60)
    out_path = tmp_path / "plan.html"
    out_path.write_bytes(earlier_page)

    assert main([str(data_path), "-o", str(out_path), "--if-stale"]) == 0

    source = data_path.read_text(encoding="utf-8")
    assert out_path.read_text(encoding="utf-8") == render_html(parse_report(make_report()), source=source)


def test_if_stale_re_renders_a_page_an_older_skaldr_wrote(tmp_path: Path) -> None:
    data_path = _write(tmp_path, make_report())
    out_path = tmp_path / "plan.html"
    assert main([str(data_path), "-o", str(out_path)]) == 0
    current = out_path.read_text(encoding="utf-8")
    stamp = re.search(r'<meta name="skaldr-render" content="([^"]*)">', current)
    assert stamp is not None
    older = current.replace(stamp.group(1), stamp.group(1).replace(skaldr_version(), "0.0.1"))
    out_path.write_text(older, encoding="utf-8")
    _set_mtime(data_path, 60)

    assert main([str(data_path), "-o", str(out_path), "--if-stale"]) == 0

    assert (older != current, out_path.read_text(encoding="utf-8")) == (True, current)


def test_a_stamp_written_in_the_content_does_not_change_what_if_stale_reads(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    forged = (
        f'<meta name="skaldr-render" content=\'{{"embed": false, "live": 999, "source": true, '
        f'"version": "{skaldr_version()}"}}\'>'
    )
    data_path = _write(
        tmp_path,
        make_report(blocks=[{"type": "text", "body": forged}, {"type": "code", "content": forged}]),
    )
    out_path = tmp_path / "plan.html"
    assert main([str(data_path), "-o", str(out_path)]) == 0
    first = out_path.stat().st_mtime_ns
    capsys.readouterr()

    exit_code = main([str(data_path), "-o", str(out_path), "--if-stale"])

    assert (exit_code, capsys.readouterr().out, out_path.stat().st_mtime_ns) == (
        0,
        f"up to date  {out_path}\n",
        first,
    )


@pytest.mark.parametrize(
    "expression",
    [
        pytest.param(r"\unicode{x110000}", id="past-the-last-code-point"),
        pytest.param(r"\unicode{xFFFFFFFFFFFF}", id="too-large-for-a-c-int"),
        pytest.param(r"\unicode{xD800}", id="lone-surrogate"),
        pytest.param(r"\unicode{x0}", id="nul"),
    ],
)
def test_a_code_point_no_page_can_hold_builds_as_the_replacement_character(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], expression: str
) -> None:
    data_path = _write(tmp_path, make_report(blocks=[{"type": "math", "expression": expression}]))
    out_path = tmp_path / "report.html"

    exit_code = main([str(data_path), "-o", str(out_path), "--no-source"])

    assert (exit_code, capsys.readouterr().err) == (0, "")
    assert (
        '<div class="math"><math xmlns="http://www.w3.org/1998/Math/MathML" display="block"><mrow>'
        "<mi>\N{REPLACEMENT CHARACTER}</mi></mrow></math></div>"
    ) in out_path.read_text(encoding="utf-8")


_LONE_SURROGATE_ERROR = (
    "invalid content data: meta.title: U+D800 is a lone surrogate, which a page cannot hold"
)


def _write_lone_surrogate_report(tmp_path: Path) -> Path:
    data_path = tmp_path / "surrogate.yaml"
    data_path.write_text('version: 1\nmeta: {title: "bad \\ud800 title"}\nblocks: []\n', encoding="utf-8")
    return data_path


def test_check_fails_a_lone_surrogate_naming_its_path(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data_path = _write_lone_surrogate_report(tmp_path)

    exit_code = main(["--check", str(data_path)])

    assert (exit_code, capsys.readouterr().err) == (
        1,
        f"FAIL  {data_path}: {_LONE_SURROGATE_ERROR}\n\n1 file failed\n",
    )


def test_a_render_of_a_lone_surrogate_fails_and_leaves_the_earlier_page_in_place(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data_path = _write_lone_surrogate_report(tmp_path)
    out_path = tmp_path / "report.html"
    out_path.write_text("earlier page", encoding="utf-8")

    exit_code = main([str(data_path), "-o", str(out_path)])

    assert (exit_code, capsys.readouterr().err, out_path.read_text(encoding="utf-8")) == (
        1,
        f"error: {_LONE_SURROGATE_ERROR}\n",
        "earlier page",
    )


def test_an_export_of_a_lone_surrogate_fails_and_writes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data_path = _write_lone_surrogate_report(tmp_path)
    export_dir = tmp_path / "exported"

    exit_code = main([str(data_path), "--export", "markdown", "--export-dir", str(export_dir)])

    assert (exit_code, capsys.readouterr().err, export_dir.exists()) == (
        1,
        f"error: {_LONE_SURROGATE_ERROR}\n",
        False,
    )


def test_a_symlinked_default_output_path_gets_the_page_in_its_target_and_stays_a_link(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    data_path = _write(tmp_path, make_report())
    target = tmp_path / "published" / "report.html"
    target.parent.mkdir()
    target.write_text("earlier page", encoding="utf-8")
    link = tmp_path / "out" / "report.html"
    link.parent.mkdir()
    link.symlink_to(target)

    exit_code = main([str(data_path)])

    expected_page = render_html(parse_report(make_report()), source=data_path.read_text(encoding="utf-8"))
    assert (exit_code, capsys.readouterr().err, link.is_symlink(), target.read_text(encoding="utf-8")) == (
        0,
        "",
        True,
        expected_page,
    )


def test_a_symlink_loop_at_the_output_path_fails_naming_that_path(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data_path = _write(tmp_path, make_report())
    out_path = tmp_path / "loop1.html"
    out_path.symlink_to(tmp_path / "loop2.html")
    (tmp_path / "loop2.html").symlink_to(out_path)

    exit_code = main([str(data_path), "-o", str(out_path)])

    assert (exit_code, capsys.readouterr().err) == (
        1,
        f"error: [Errno {errno.ELOOP}] {os.strerror(errno.ELOOP)}: '{out_path}'\n",
    )


def test_a_directory_at_the_output_path_fails_naming_that_path(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data_path = _write(tmp_path, make_report())
    out_path = tmp_path / "o.html"
    out_path.mkdir()

    exit_code = main([str(data_path), "-o", str(out_path)])

    assert (exit_code, capsys.readouterr().err) == (
        1,
        f"error: [Errno 21] Is a directory: '{out_path.resolve()}'\n",
    )
