from pathlib import Path
from typing import Any

import pytest

from skaldr.publish.cli import main
from skaldr.publish.content import TITLE, section_part
from skaldr.publish.engine import (
    Applied,
    DryRun,
    ItemStatus,
    PublishDiff,
    YamlChange,
    apply_publish,
    diff_publish,
    dry_run_publish,
    prepare_publish,
    publish_status,
)
from skaldr.publish.plan import ArchiveStep, ItemRef, ReleaseStep, describe_plan
from skaldr.publish.state import load_state, state_path_for
from tests.factories.publish_factory import (
    DOC_ID,
    INTO_LABEL,
    INTRO_KEY,
    TARGET_LABEL,
    FakeTransport,
    fake_registry,
    make_notion_publish,
    write_garden_report,
)
from tests.factories.report_factory import NOTION_PAGE_ID

DOCUMENT = ItemRef(TARGET_LABEL, None)
TOOLS = ItemRef(TARGET_LABEL, "tools")
RETIRED: dict[str, Any] = {"doc_id": DOC_ID, "targets": []}
INTO_THE_PAGE = make_notion_publish(split=["tools"], where={"page": NOTION_PAGE_ID})
NOTHING_PUBLISHED = (
    "Nothing to publish: the `publish` block has no targets and no item of this document is published.\n"
)
LEGEND_TEXT = (
    "<details>\n"
    "<summary>Legend: badges used on this page</summary>\n"
    '\t- <span color="blue">**api**</span> the API\n'
    "</details>\n"
)
HEADER_TEXT = 'For new members {color="gray"}\n<table_of_contents/>\n'
TOOLS_TEXT = '## Tools\n<span color="blue">**api**</span>\n- Spade.\n'


def _run(argv: list[str], transport: FakeTransport) -> int:
    return main(argv, registry=fake_registry(transport))


def _prepared(path: Path, transport: FakeTransport) -> Any:
    return prepare_publish(path, fake_registry(transport))


def _published_then_retired(tmp_path: Path, transport: FakeTransport, **first: Any) -> Path:
    path = write_garden_report(tmp_path, **first)
    apply_publish(_prepared(path, transport))
    write_garden_report(tmp_path, publish=RETIRED)
    transport.forget_calls()
    return path


def test_the_plan_for_no_targets_archives_every_item_the_document_created(tmp_path: Path) -> None:
    transport = FakeTransport()
    path = _published_then_retired(tmp_path, transport)

    plan = _prepared(path, transport).plan

    assert (plan.targets[0].steps, describe_plan(plan)) == (
        (ArchiveStep(TOOLS, "page-2"), ArchiveStep(DOCUMENT, "page-1")),
        [
            f"{TARGET_LABEL}: 0 to create, 0 to update, 2 to archive",
            "  archive  section tools (page-2)",
            "  archive  document (page-1)",
        ],
    )


def test_a_dry_run_for_no_targets_shows_the_archives_and_sends_nothing(tmp_path: Path) -> None:
    transport = FakeTransport()
    path = _published_then_retired(tmp_path, transport)

    dry_run = dry_run_publish(_prepared(path, transport))

    assert (dry_run, transport.writes()) == (DryRun(dry_run.plan, (), None), [])
    assert describe_plan(dry_run.plan) == [
        f"{TARGET_LABEL}: 0 to create, 0 to update, 2 to archive",
        "  archive  section tools (page-2)",
        "  archive  document (page-1)",
    ]


def test_applying_no_targets_archives_each_created_item_and_empties_the_state_file(tmp_path: Path) -> None:
    transport = FakeTransport()
    path = _published_then_retired(tmp_path, transport)

    outcome = apply_publish(_prepared(path, transport))

    assert (
        outcome,
        transport.writes(),
        transport.items["page-1"].archived,
        transport.items["page-2"].archived,
        load_state(state_path_for(path), DOC_ID).targets,
    ) == (
        Applied(("archive  section tools (page-2)", "archive  document (page-1)")),
        [("archive", "page-2"), ("archive", "page-1")],
        True,
        True,
        {},
    )


def test_applying_no_targets_releases_an_adopted_page_and_archives_what_was_created(tmp_path: Path) -> None:
    transport = FakeTransport()
    transport.seed(NOTION_PAGE_ID, "Blank page", None)
    path = _published_then_retired(tmp_path, transport, publish=INTO_THE_PAGE)
    plan = _prepared(path, transport).plan

    outcome = apply_publish(_prepared(path, transport))

    assert (
        plan.targets[0].steps,
        outcome,
        transport.writes(),
        (transport.items[NOTION_PAGE_ID].raw_sections, transport.items[NOTION_PAGE_ID].stamp),
        transport.items[NOTION_PAGE_ID].archived,
        load_state(state_path_for(path), DOC_ID).targets,
    ) == (
        (
            ArchiveStep(ItemRef(INTO_LABEL, "tools"), "page-2"),
            ReleaseStep(ItemRef(INTO_LABEL, None), NOTION_PAGE_ID),
        ),
        Applied(("archive  section tools (page-2)", f"release  document ({NOTION_PAGE_ID})")),
        [("archive", "page-2"), ("release", NOTION_PAGE_ID)],
        ({}, None),
        False,
        {},
    )


def test_applying_no_targets_twice_publishes_nothing_the_second_time(tmp_path: Path) -> None:
    transport = FakeTransport()
    path = _published_then_retired(tmp_path, transport)
    apply_publish(_prepared(path, transport))
    transport.forget_calls()

    outcome = apply_publish(_prepared(path, transport))

    assert (outcome, transport.calls) == (Applied(()), [])


def test_the_status_names_every_item_of_a_retired_document_as_removed(tmp_path: Path) -> None:
    transport = FakeTransport()
    path = _published_then_retired(tmp_path, transport)

    assert publish_status(_prepared(path, transport)) == (
        ItemStatus(DOCUMENT, "page-1", ("removed",)),
        ItemStatus(TOOLS, "page-2", ("removed",)),
    )


def test_the_diff_shows_every_part_of_a_retired_document_as_removed(tmp_path: Path) -> None:
    transport = FakeTransport()
    path = _published_then_retired(tmp_path, transport)

    diff = diff_publish(_prepared(path, transport))

    assert diff == PublishDiff(
        (),
        (
            YamlChange(DOCUMENT, TITLE, None, "Garden handbook\n", None),
            YamlChange(DOCUMENT, section_part("page header"), None, HEADER_TEXT, None),
            YamlChange(DOCUMENT, section_part(INTRO_KEY), None, "Welcome to the garden.\n", None),
            YamlChange(DOCUMENT, section_part("planting"), None, "## Planting\nSow in spring.\n", None),
            YamlChange(TOOLS, TITLE, None, "Tools\n", None),
            YamlChange(TOOLS, section_part("page legend"), None, LEGEND_TEXT, None),
            YamlChange(TOOLS, section_part("tools"), None, TOOLS_TEXT, None),
        ),
    )


def test_no_targets_and_no_state_file_plans_nothing_and_sends_nothing(tmp_path: Path) -> None:
    transport = FakeTransport()
    path = write_garden_report(tmp_path, publish=RETIRED)

    prepared = _prepared(path, transport)

    assert (
        prepared.plan.targets,
        dry_run_publish(prepared),
        apply_publish(prepared),
        publish_status(prepared),
        diff_publish(prepared),
        transport.calls,
        state_path_for(path).exists(),
    ) == ((), DryRun(prepared.plan, (), None), Applied(()), (), PublishDiff((), ()), [], False)


def test_a_dry_run_cli_for_no_targets_and_no_state_file_says_nothing_is_published(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_garden_report(tmp_path, publish=RETIRED)
    transport = FakeTransport()

    exit_code = _run(["publish", str(path)], transport)

    assert (exit_code, capsys.readouterr().out, transport.calls) == (0, NOTHING_PUBLISHED, [])


def test_an_apply_cli_for_no_targets_and_no_state_file_says_nothing_is_published(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_garden_report(tmp_path, publish=RETIRED)
    transport = FakeTransport()

    exit_code = _run(["publish", str(path), "--apply"], transport)

    assert (exit_code, capsys.readouterr().out, transport.calls, state_path_for(path).exists()) == (
        0,
        NOTHING_PUBLISHED,
        [],
        False,
    )


def test_a_dry_run_cli_for_no_targets_prints_the_archives(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    transport = FakeTransport()
    path = _published_then_retired(tmp_path, transport)
    capsys.readouterr()

    exit_code = _run(["publish", str(path)], transport)

    assert (exit_code, capsys.readouterr().out, transport.writes()) == (
        0,
        f"{TARGET_LABEL}: 0 to create, 0 to update, 2 to archive\n"
        "  archive  section tools (page-2)\n"
        "  archive  document (page-1)\n"
        f"Dry run: nothing was sent. Publish with `skaldr publish {path} --apply`.\n",
        [],
    )


def test_an_apply_cli_for_no_targets_archives_each_item_and_says_where_the_state_is(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    transport = FakeTransport()
    path = _published_then_retired(tmp_path, transport)
    capsys.readouterr()

    exit_code = _run(["publish", str(path), "--apply"], transport)

    assert (exit_code, capsys.readouterr().out, transport.writes()) == (
        0,
        f"{TARGET_LABEL}: archive  section tools (page-2)\n"
        f"{TARGET_LABEL}: archive  document (page-1)\n"
        f"Published 2 steps. The publish state is in {state_path_for(path)}.\n",
        [("archive", "page-2"), ("archive", "page-1")],
    )


def test_a_status_cli_for_a_retired_document_prints_each_item_as_removed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    transport = FakeTransport()
    path = _published_then_retired(tmp_path, transport)
    capsys.readouterr()

    exit_code = _run(["status", str(path)], transport)

    assert (exit_code, capsys.readouterr().out) == (
        0,
        f"{TARGET_LABEL}, document (page-1): removed\n{TARGET_LABEL}, section tools (page-2): removed\n",
    )
