import json
import sys
from pathlib import Path

import pytest

from skaldr.cli import main as skaldr_main
from skaldr.publish.cli import main
from skaldr.publish.state import state_path_for
from tests.factories.publish_factory import (
    TARGET_LABEL,
    FakeTransport,
    fake_registry,
    make_garden_blocks,
    make_notion_publish,
    write_garden_report,
)

SPRING = "## Planting\nSow in spring.\n"
LATE_SPRING = "## Planting\nSow in late spring.\n"
TOOLS_TEXT = '## Tools\n<span color="blue">**api**</span>\n- Spade.\n'
RAKE_TEXT = '## Tools\n<span color="blue">**api**</span>\n- Rake.\n'


def _run(argv: list[str], transport: FakeTransport) -> int:
    return main(argv, registry=fake_registry(transport))


def _published_then_edited(tmp_path: Path, transport: FakeTransport) -> Path:
    path = write_garden_report(tmp_path)
    _run(["publish", str(path), "--apply"], transport)
    write_garden_report(tmp_path, blocks=make_garden_blocks(tools="Rake."))
    transport.edit_section_by_hand("page-1", "planting", LATE_SPRING)
    transport.forget_calls()
    return path


def test_a_dry_run_prints_the_plan_and_sends_and_writes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_garden_report(tmp_path)
    transport = FakeTransport()

    exit_code = _run(["publish", str(path)], transport)

    assert (exit_code, capsys.readouterr().out, transport.calls, state_path_for(path).exists()) == (
        0,
        f"{TARGET_LABEL}: 2 to create, 0 to update, 0 to archive\n"
        '  create   document "Garden handbook"\n'
        '  create   section tools "Tools"\n'
        f"Dry run: nothing was sent. Publish with `skaldr publish {path} --apply`.\n",
        [],
        False,
    )


def test_apply_prints_each_step_as_it_lands_and_where_the_state_is(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_garden_report(tmp_path)

    exit_code = _run(["publish", str(path), "--apply"], FakeTransport())

    assert (exit_code, capsys.readouterr().out) == (
        0,
        f'{TARGET_LABEL}: create   document "Garden handbook"\n'
        f'{TARGET_LABEL}: create   section tools "Tools"\n'
        f"Published 2 steps. The publish state is in {state_path_for(path)}.\n",
    )


def test_apply_with_nothing_changed_says_so(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = write_garden_report(tmp_path)
    transport = FakeTransport()
    _run(["publish", str(path), "--apply"], transport)
    capsys.readouterr()

    exit_code = _run(["publish", str(path), "--apply"], transport)

    assert (exit_code, capsys.readouterr().out) == (0, "Nothing to publish: every item matches the YAML.\n")


def test_apply_over_a_remote_edit_prints_the_edit_and_fails_writing_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    transport = FakeTransport()
    path = _published_then_edited(tmp_path, transport)
    capsys.readouterr()

    exit_code = _run(["publish", str(path), "--apply"], transport)

    assert (exit_code, capsys.readouterr(), transport.writes()) == (
        1,
        (
            f"--- {TARGET_LABEL}, document: planting (blocks[2]), as published\n"
            f"+++ {TARGET_LABEL}, document: planting (blocks[2]), now\n"
            "@@ -1,2 +1,2 @@\n"
            " ## Planting\n"
            "-Sow in spring.\n"
            "+Sow in late spring.\n",
            "error: 1 part was edited in the service since the last publish, so nothing was written. To keep "
            "the edit, copy it into the YAML first; to replace it, publish with --apply --overwrite.\n",
        ),
        [],
    )


def test_the_refusal_counts_several_edited_parts(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    transport = FakeTransport()
    path = _published_then_edited(tmp_path, transport)
    transport.edit_section_by_hand("page-2", "tools", "## Tools\n- Rake.\n")
    capsys.readouterr()

    exit_code = _run(["publish", str(path), "--apply"], transport)

    assert (exit_code, capsys.readouterr().err) == (
        1,
        "error: 2 parts were edited in the service since the last publish, so nothing was written. To keep "
        "the edits, copy them into the YAML first; to replace them, publish with --apply --overwrite.\n",
    )


def test_overwrite_after_the_refusal_replaces_the_edit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    transport = FakeTransport()
    path = _published_then_edited(tmp_path, transport)
    _run(["publish", str(path), "--apply"], transport)
    capsys.readouterr()

    exit_code = _run(["publish", str(path), "--apply", "--overwrite"], transport)

    assert (exit_code, capsys.readouterr().out) == (
        0,
        f"{TARGET_LABEL}: update   document: planting (blocks[2])\n"
        f"{TARGET_LABEL}: update   section tools: tools (blocks[1])\n"
        f"Published 2 steps. The publish state is in {state_path_for(path)}.\n",
    )


def test_overwrite_of_an_edit_no_diff_has_shown_fails_and_says_why(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    transport = FakeTransport()
    path = _published_then_edited(tmp_path, transport)
    capsys.readouterr()

    exit_code = _run(["publish", str(path), "--apply", "--overwrite"], transport)

    assert (exit_code, capsys.readouterr().err, transport.writes()) == (
        1,
        "error: 1 part edited in the service changed after the last diff showed it, or no diff has shown it "
        "yet, so nothing was written. Read the diff above, then publish with --apply --overwrite again.\n",
        [],
    )


def test_overwrite_needs_apply(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = write_garden_report(tmp_path)

    with pytest.raises(SystemExit) as stopped:
        _run(["publish", str(path), "--overwrite"], FakeTransport())

    assert (stopped.value.code, capsys.readouterr().err.splitlines()[-1]) == (
        2,
        "skaldr publish: error: --overwrite replaces remote edits while publishing, so it needs --apply",
    )


def test_diff_prints_the_remote_edits_then_what_the_yaml_would_change(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    transport = FakeTransport()
    path = _published_then_edited(tmp_path, transport)
    capsys.readouterr()

    exit_code = _run(["diff", str(path)], transport)

    assert (exit_code, capsys.readouterr().out, transport.writes()) == (
        0,
        "Remote edits since the last publish:\n"
        f"--- {TARGET_LABEL}, document: planting (blocks[2]), as published\n"
        f"+++ {TARGET_LABEL}, document: planting (blocks[2]), now\n"
        "@@ -1,2 +1,2 @@\n"
        " ## Planting\n"
        "-Sow in spring.\n"
        "+Sow in late spring.\n"
        "What this YAML would change:\n"
        f"--- {TARGET_LABEL}, section tools: tools (blocks[1]), as published\n"
        f"+++ {TARGET_LABEL}, section tools: tools (blocks[1]), in the YAML\n"
        "@@ -1,3 +1,3 @@\n"
        " ## Tools\n"
        ' <span color="blue">**api**</span>\n'
        "-- Spade.\n"
        "+- Rake.\n",
        [],
    )


def test_diff_of_a_document_in_sync_says_there_is_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_garden_report(tmp_path)
    transport = FakeTransport()
    _run(["publish", str(path), "--apply"], transport)
    capsys.readouterr()

    exit_code = _run(["diff", str(path)], transport)

    assert (exit_code, capsys.readouterr().out) == (
        0,
        "Remote edits since the last publish: none\nWhat this YAML would change: nothing\n",
    )


def test_diff_json_holds_the_same_facts_as_the_text(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    transport = FakeTransport()
    path = _published_then_edited(tmp_path, transport)
    capsys.readouterr()
    expected = {
        "remote_edits": [
            {
                "target": TARGET_LABEL,
                "item": "document",
                "part": "section",
                "section": "planting",
                "yaml_path": "blocks[2]",
                "published": SPRING,
                "current": LATE_SPRING,
                "edited_by": None,
                "edited_at": None,
            }
        ],
        "yaml_changes": [
            {
                "target": TARGET_LABEL,
                "item": "section tools",
                "part": "section",
                "section": "tools",
                "yaml_path": "blocks[1]",
                "published": TOOLS_TEXT,
                "next": RAKE_TEXT,
            }
        ],
        "missing_remotely": [],
    }

    exit_code = _run(["diff", str(path), "--json"], transport)

    assert (exit_code, capsys.readouterr().out) == (0, json.dumps(expected, indent=2) + "\n")


def test_status_prints_one_line_per_item(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = write_garden_report(tmp_path)
    transport = FakeTransport()
    _run(["publish", str(path), "--apply"], transport)
    write_garden_report(tmp_path, publish=make_notion_publish(split=["tools", "planting"]))
    transport.edit_section_by_hand("page-2", "tools", "## Tools\n- Rake.\n")
    capsys.readouterr()

    exit_code = _run(["status", str(path)], transport)

    assert (exit_code, capsys.readouterr().out) == (
        0,
        f"{TARGET_LABEL}, document (page-1): changed in the YAML\n"
        f"{TARGET_LABEL}, section tools (page-2): edited remotely\n"
        f"{TARGET_LABEL}, section planting: never published\n",
    )


def test_a_document_without_a_publish_block_fails_with_the_reason(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "plain.yaml"
    path.write_text("version: 1\nmeta: {title: Plain}\nblocks: [{type: text, body: Hi.}]\n", encoding="utf-8")

    exit_code = _run(["status", str(path)], FakeTransport())

    assert (exit_code, capsys.readouterr().err) == (
        1,
        "error: the document has no `publish` block, so it has nowhere to publish; add one (see `skaldr "
        "--guide`)\n",
    )


@pytest.mark.parametrize(
    ("command", "first_line"),
    [
        pytest.param("publish", f"{TARGET_LABEL}: 2 to create, 0 to update, 0 to archive", id="publish"),
        pytest.param("diff", "Remote edits since the last publish: none", id="diff"),
        pytest.param("status", f"{TARGET_LABEL}, document: never published", id="status"),
    ],
)
def test_skaldr_hands_the_publish_commands_to_the_publish_cli_with_its_notion_connector(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], command: str, first_line: str
) -> None:
    path = write_garden_report(tmp_path)

    exit_code = skaldr_main([command, str(path)])

    printed = capsys.readouterr()
    assert (exit_code, printed.err, printed.out.splitlines()[0]) == (0, "", first_line)


def test_one_applied_step_is_counted_in_the_singular(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_garden_report(tmp_path, publish=make_notion_publish())

    exit_code = _run(["publish", str(path), "--apply"], FakeTransport())

    assert (exit_code, capsys.readouterr().out.splitlines()[-1]) == (
        0,
        f"Published 1 step. The publish state is in {state_path_for(path)}.",
    )


def test_diff_json_keeps_non_ascii_text_as_written(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    transport = FakeTransport()
    path = write_garden_report(tmp_path)
    _run(["publish", str(path), "--apply"], transport)
    write_garden_report(tmp_path, blocks=make_garden_blocks(tools="Gießkanne."))
    capsys.readouterr()

    _run(["diff", str(path), "--json"], transport)

    out = capsys.readouterr().out
    assert (json.loads(out)["yaml_changes"][0]["next"], "\\u00df" in out, "Gießkanne" in out) == (
        '## Tools\n<span color="blue">**api**</span>\n- Gießkanne.\n',
        False,
        True,
    )


def test_a_publish_command_without_the_publish_extra_names_the_install_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    for module in [name for name in sys.modules if name.startswith("skaldr.publish")]:
        monkeypatch.delitem(sys.modules, module)
    monkeypatch.setitem(sys.modules, "filelock", None)

    exit_code = skaldr_main(["diff", str(tmp_path / "doc.yaml")])

    assert (exit_code, capsys.readouterr().err) == (
        1,
        "error: `skaldr diff` needs the publish extra (filelock is not installed). Reinstall with it: "
        "uv tool install --force 'skaldr[publish]', pipx install --force 'skaldr[publish]', "
        "or pip install 'skaldr[publish]'\n",
    )
