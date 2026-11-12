import time
from pathlib import Path

import pytest

from skaldr.cli import main
from skaldr.errors import ReportError
from skaldr.models import load_report, parse_report
from tests.factories import make_report

_NESTS_TOO_DEEPLY = "nests too deeply or refers to itself"


def _alias_bomb(levels: int) -> str:
    lines = ["version: 1", 'meta: {title: "Bomb"}']
    lines.append('x0: &a0 ["lol","lol","lol","lol","lol","lol","lol","lol","lol","lol"]')
    for level in range(1, levels):
        lines.append(f"x{level}: &a{level} [{','.join([f'*a{level - 1}'] * 10)}]")
    lines.extend(["blocks:", "  - type: list", f"    items: *a{levels - 1}"])
    return "\n".join(lines) + "\n"


def _shared_nest(levels: int) -> object:
    node: object = ["lol"] * 10
    for _ in range(levels):
        node = [node] * 10
    return node


def test_a_493_byte_alias_bomb_is_refused_at_once(tmp_path: Path) -> None:
    document = tmp_path / "bomb.yaml"
    document.write_text(_alias_bomb(8), encoding="utf-8")

    started = time.monotonic()
    with pytest.raises(ReportError) as refused:
        load_report(document)
    elapsed = time.monotonic() - started

    assert elapsed < 1.0
    assert str(refused.value).startswith("invalid content data: blocks.0.list.items.0")


def test_a_container_shared_by_many_references_is_walked_once() -> None:
    document = {
        "version": 1,
        "meta": {"title": "Bomb"},
        "blocks": [{"type": "list", "items": _shared_nest(8)}],
    }

    started = time.monotonic()
    with pytest.raises(ReportError):
        parse_report(document)

    assert time.monotonic() - started < 1.0


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
        f"{document} uses more than 3 YAML aliases; no real document needs that many, "
        "and a flood of them is how a YAML bomb is built"
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


def test_a_self_referencing_alias_is_a_report_error(tmp_path: Path) -> None:
    document = tmp_path / "loop.yaml"
    document.write_text(
        "version: 1\nmeta: {title: Loop}\nblocks: &b\n  - type: list\n    items: *b\n", encoding="utf-8"
    )

    with pytest.raises(ReportError, match=_NESTS_TOO_DEEPLY):
        load_report(document)


def test_deep_nesting_is_a_report_error_naming_the_file(tmp_path: Path) -> None:
    document = tmp_path / "deep.yaml"
    document.write_text(
        "version: 1\nmeta: {title: Deep}\nblocks: " + "[" * 5000 + "]" * 5000 + "\n", encoding="utf-8"
    )

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
    deep.write_text(
        "version: 1\nmeta: {title: Deep}\nblocks: " + "[" * 5000 + "]" * 5000 + "\n", encoding="utf-8"
    )
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
