import json
from pathlib import Path

import pytest
import yaml

from skaldr.cli import main
from skaldr.models import Report
from tests.conftest import REPO_ROOT
from tests.factories import make_reconciled_table, make_report


def _write(tmp_path: Path, data: dict[str, object]) -> Path:
    path = tmp_path / "report.yaml"
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
