from pathlib import Path

import pytest

from skaldr.cli import main
from skaldr.errors import ReportError
from skaldr.models import content_files, load_report, parse_report
from tests.factories import make_report

_NESTS_TOO_DEEPLY = "nests too deeply or refers to itself"
_NOT_AN_ITEM = "Input should be a valid dictionary or instance of ListItem"


def _alias_bomb(levels: int) -> str:
    lines = ["version: 1", 'meta: {title: "Bomb"}']
    lines.append('x0: &a0 ["lol","lol","lol","lol","lol","lol","lol","lol","lol","lol"]')
    for level in range(1, levels):
        lines.append(f"x{level}: &a{level} [{','.join([f'*a{level - 1}'] * 10)}]")
    lines.extend(["blocks:", "  - type: list", f"    items: *a{levels - 1}"])
    return "\n".join(lines) + "\n"


def _shared_nest(levels: int, leaf: str) -> object:
    node: object = [leaf] * 10
    for _ in range(levels):
        node = [node] * 10
    return node


def _deep_document_text() -> str:
    return "version: 1\nmeta: {title: Deep}\nblocks: " + "[" * 5000 + "]" * 5000 + "\n"


def _include_fan_out(folder: Path, levels: int) -> Path:
    for level in range(levels):
        include = f"- !include f{level + 1}.yaml\n"
        (folder / f"f{level}.yaml").write_text(include * 2, encoding="utf-8")
    (folder / f"f{levels}.yaml").write_text("- type: text\n  body: x\n", encoding="utf-8")
    document = folder / "main.yaml"
    document.write_text("version: 1\nmeta: {title: T}\nblocks: !include f0.yaml\n", encoding="utf-8")
    return document


def test_an_alias_bomb_is_refused_with_the_validation_errors_of_its_shape(tmp_path: Path) -> None:
    document = tmp_path / "bomb.yaml"
    document.write_text(_alias_bomb(8), encoding="utf-8")

    with pytest.raises(ReportError) as refused:
        load_report(document)

    assert str(refused.value) == "invalid content data: " + "; ".join(
        [
            *(f"blocks.0.list.items.{position}.ListItem: {_NOT_AN_ITEM}" for position in range(10)),
            *(f"x{level}: Extra inputs are not permitted" for level in range(8)),
        ]
    )


class _TextThatCountsItsChecks(str):
    checks = 0

    def encode(self, encoding: str = "utf-8", errors: str = "strict") -> bytes:
        type(self).checks += 1
        assert type(self).checks < 1000, "a shared container was walked again"
        return super().encode(encoding, errors)


def test_a_container_shared_by_many_references_is_checked_once() -> None:
    _TextThatCountsItsChecks.checks = 0
    document = {
        "version": 1,
        "meta": {"title": "Bomb"},
        "blocks": [{"type": "list", "items": _shared_nest(8, _TextThatCountsItsChecks("lol"))}],
    }

    with pytest.raises(ReportError):
        parse_report(document)

    assert _TextThatCountsItsChecks.checks == 10


def test_a_document_with_more_aliases_than_the_limit_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("skaldr.models.loading._MAX_ALIASES", 3)
    document = tmp_path / "aliases.yaml"
    document.write_text(
        "version: 1\nmeta: {title: &n x}\nblocks:\n  - {type: text, body: *n}\n"
        "  - {type: text, body: *n}\n  - {type: text, body: *n}\n  - {type: text, body: *n}\n",
        encoding="utf-8",
    )

    with pytest.raises(ReportError) as refused:
        load_report(document)

    assert str(refused.value) == (
        f"{document} uses more than 3 YAML aliases, counting every file it includes; no real document "
        "needs that many, and a flood of them is how a YAML bomb is built"
    )


def test_a_document_with_exactly_the_alias_limit_still_loads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("skaldr.models.loading._MAX_ALIASES", 2)
    document = tmp_path / "aliases.yaml"
    document.write_text(
        "version: 1\nmeta: {title: &n x}\nblocks:\n  - {type: text, body: *n}\n  - {type: text, body: *n}\n",
        encoding="utf-8",
    )

    assert [block.model_dump(mode="json")["body"] for block in load_report(document).blocks] == ["x", "x"]


def test_aliases_are_counted_across_the_files_a_document_includes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("skaldr.models.loading._MAX_ALIASES", 3)
    fragment = tmp_path / "fragment.yaml"
    fragment.write_text(
        "- &n {type: text, body: x}\n- *n\n- *n\n",
        encoding="utf-8",
    )
    document = tmp_path / "main.yaml"
    document.write_text(
        "version: 1\nmeta: {title: &t x}\nnote: [*t, *t]\nblocks: !include fragment.yaml\n", encoding="utf-8"
    )

    with pytest.raises(ReportError) as refused:
        load_report(document)

    assert str(refused.value) == (
        f"{fragment} uses more than 3 YAML aliases, counting every file it includes; no real document "
        "needs that many, and a flood of them is how a YAML bomb is built"
    )


def test_a_document_reading_more_files_than_the_limit_through_include_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("skaldr.models.loading._MAX_FILES", 5)
    document = _include_fan_out(tmp_path, 3)

    with pytest.raises(ReportError) as refused:
        load_report(document)

    assert str(refused.value) == (
        f"the document reads more than 5 files through !include, reaching {tmp_path / 'f3.yaml'}; no real "
        "document needs that many, and a fan-out of includes is how an include bomb is built"
    )


def test_a_document_reading_exactly_the_file_limit_still_loads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("skaldr.models.loading._MAX_FILES", 16)
    document = _include_fan_out(tmp_path, 3)

    assert len(content_files(document)) == 16


def test_a_fan_out_of_includes_is_refused_at_the_default_file_limit(tmp_path: Path) -> None:
    document = _include_fan_out(tmp_path, 12)

    with pytest.raises(ReportError, match=r"^the document reads more than 1000 files through !include, "):
        load_report(document)


def test_a_self_referencing_alias_is_a_report_error(tmp_path: Path) -> None:
    document = tmp_path / "loop.yaml"
    document.write_text(
        "version: 1\nmeta: {title: Loop}\nblocks: &b\n  - type: list\n    items: *b\n", encoding="utf-8"
    )

    with pytest.raises(ReportError, match=_NESTS_TOO_DEEPLY):
        load_report(document)


def test_deep_nesting_is_a_report_error_naming_the_file(tmp_path: Path) -> None:
    document = tmp_path / "deep.yaml"
    document.write_text(_deep_document_text(), encoding="utf-8")

    with pytest.raises(ReportError) as refused:
        load_report(document)

    assert str(refused.value) == f"{document} {_NESTS_TOO_DEEPLY}"


def test_parse_report_turns_data_nested_too_deep_into_a_report_error() -> None:
    node: list[object] = []
    for _ in range(5000):
        node = [node]

    with pytest.raises(ReportError) as refused:
        parse_report({"version": 1, "meta": {"title": "Deep"}, "blocks": node})

    assert str(refused.value) == f"the document {_NESTS_TOO_DEEPLY}"


def test_parse_report_turns_data_that_contains_itself_into_a_report_error() -> None:
    blocks: list[object] = []
    blocks.append({"type": "list", "items": blocks})

    with pytest.raises(ReportError) as refused:
        parse_report({"version": 1, "meta": {"title": "Loop"}, "blocks": blocks})

    assert str(refused.value) == f"the document {_NESTS_TOO_DEEPLY}"


def test_check_keeps_going_after_a_file_that_nests_too_deeply(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    deep = tmp_path / "a.yaml"
    deep.write_text(_deep_document_text(), encoding="utf-8")
    fine = tmp_path / "b.yaml"
    fine.write_text(
        "version: 1\nmeta: {title: Fine}\nblocks:\n  - {type: text, body: ok}\n", encoding="utf-8"
    )

    exit_code = main(["--check", str(deep), str(fine)])

    captured = capsys.readouterr()
    assert (exit_code, captured.out, captured.err) == (
        1,
        f"OK    {fine}\n",
        f"FAIL  {deep}: {deep} {_NESTS_TOO_DEEPLY}\n\n1 file failed\n",
    )


def test_a_plain_document_still_parses_after_the_guards() -> None:
    assert parse_report(make_report()).meta.title == "Test Report"
