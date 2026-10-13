import re
from pathlib import Path
from typing import Any

import pytest

from skaldr.errors import PublishError
from skaldr.publish.cli import main
from skaldr.publish.content import section_part
from skaldr.publish.engine import (
    Applied,
    ApplyOutcome,
    DryRun,
    ItemStatus,
    MissingItem,
    PublishDiff,
    RemoteEdit,
    apply_publish,
    diff_publish,
    dry_run_publish,
    prepare_publish,
    publish_status,
)
from skaldr.publish.plan import ArchiveStep, ItemRef, ReleaseStep, describe_plan
from skaldr.publish.state import load_state, state_path_for
from skaldr.publish_block import JiraTarget, NotionTarget
from tests.factories.publish_factory import (
    DOC_ID,
    INTO_LABEL,
    OTHER_DOC_ID,
    TARGET_LABEL,
    FakeTransport,
    fake_registry,
    make_garden_blocks,
    make_notion_publish,
    write_garden_report,
)
from tests.factories.report_factory import NOTION_PAGE_ID, make_jira_target

DOCUMENT = ItemRef(TARGET_LABEL, None)
TOOLS = ItemRef(TARGET_LABEL, "tools")
LATE_SPRING = "## Planting\nSow in late spring.\n"
OTHER_PAGE_ID = "fedcba9876543210fedcba9876543210"
OTHER_LABEL = f"notion page {OTHER_PAGE_ID}"
JIRA_PUBLISH = {"doc_id": DOC_ID, "targets": [make_jira_target()]}
INTO_THE_PAGE = make_notion_publish(split=["tools"], where={"page": NOTION_PAGE_ID})


def _registry(transport: FakeTransport) -> Any:
    return fake_registry(transport, target_types=(NotionTarget, JiraTarget))


def _publish(path: Path, transport: FakeTransport, *, overwrite: bool = False) -> ApplyOutcome:
    return apply_publish(prepare_publish(path, _registry(transport)), overwrite=overwrite)


def _published_then_rewritten(
    tmp_path: Path, transport: FakeTransport, first: dict[str, Any], **rewritten: Any
) -> Path:
    path = write_garden_report(tmp_path, **first)
    _publish(path, transport)
    write_garden_report(tmp_path, **rewritten)
    transport.forget_calls()
    return path


def test_an_empty_page_the_target_names_is_adopted_and_its_split_sections_are_created(tmp_path: Path) -> None:
    transport = FakeTransport()
    transport.seed(NOTION_PAGE_ID, "Blank page", None)
    path = write_garden_report(tmp_path, publish=INTO_THE_PAGE)

    _publish(path, transport)
    published = load_state(state_path_for(path), DOC_ID).targets[INTO_LABEL]

    assert (published.document and published.document.origin, published.sections["tools"].origin) == (
        "adopted",
        "created",
    )


def test_a_page_with_content_and_no_stamp_is_refused_naming_it(tmp_path: Path) -> None:
    transport = FakeTransport()
    transport.seed(NOTION_PAGE_ID, "Team notes", None, {"notes": "Bring gloves.\n"})
    path = write_garden_report(tmp_path, publish=INTO_THE_PAGE)
    expected = (
        f"{INTO_LABEL}, document: {NOTION_PAGE_ID} already holds content and carries no skaldr stamp, so "
        "skaldr will not write into it; empty the page, or publish under it with `parent_page` instead"
    )

    with pytest.raises(PublishError, match=f"^{re.escape(expected)}$"):
        _publish(path, transport)
    assert (transport.writes(), transport.items[NOTION_PAGE_ID].raw_sections) == (
        [],
        {"notes": "Bring gloves.\n"},
    )


@pytest.mark.parametrize(
    "existing",
    [
        pytest.param({"children": ("child-page",)}, id="a-child-page"),
        pytest.param({"fields": {"Status": "Draft"}}, id="a-property"),
    ],
)
def test_a_page_with_child_pages_or_properties_is_not_empty(tmp_path: Path, existing: dict[str, Any]) -> None:
    transport = FakeTransport()
    transport.seed(NOTION_PAGE_ID, "Team notes", None, **existing)
    path = write_garden_report(tmp_path, publish=INTO_THE_PAGE)
    expected = (
        f"{INTO_LABEL}, document: {NOTION_PAGE_ID} already holds content and carries no skaldr stamp, so "
        "skaldr will not write into it; empty the page, or publish under it with `parent_page` instead"
    )

    with pytest.raises(PublishError, match=f"^{re.escape(expected)}$"):
        _publish(path, transport)
    assert transport.writes() == []


def test_removing_the_target_of_an_adopted_page_releases_it_and_archives_what_skaldr_created(
    tmp_path: Path,
) -> None:
    transport = FakeTransport()
    transport.seed(NOTION_PAGE_ID, "Blank page", None)
    path = _published_then_rewritten(tmp_path, transport, {"publish": INTO_THE_PAGE}, publish=JIRA_PUBLISH)
    prepared = prepare_publish(path, _registry(transport))

    outcome = apply_publish(prepared)

    assert (
        prepared.plan.targets[1].steps,
        describe_plan(prepared.plan)[2:],
        outcome,
        transport.writes()[1:],
        (transport.items[NOTION_PAGE_ID].raw_sections, transport.items[NOTION_PAGE_ID].stamp),
        transport.items[NOTION_PAGE_ID].archived,
    ) == (
        (
            ArchiveStep(ItemRef(INTO_LABEL, "tools"), "page-2"),
            ReleaseStep(ItemRef(INTO_LABEL, None), NOTION_PAGE_ID),
        ),
        [
            f"{INTO_LABEL}: 0 to create, 0 to update, 1 to archive, 1 to release",
            "  archive  section tools (page-2)",
            f"  release  document ({NOTION_PAGE_ID})",
        ],
        Applied(
            (
                'create   document "Garden handbook"',
                "archive  section tools (page-2)",
                f"release  document ({NOTION_PAGE_ID})",
            )
        ),
        [("archive", "page-2"), ("release", NOTION_PAGE_ID)],
        ({}, None),
        False,
    )


def _moved(service: str, old: str, new: str) -> str:
    return (
        f"the {service} target moved from {old} to {new}; skaldr does not move pages or issues, so nothing "
        "was written. Publish once with the old target removed from the `publish` block, which archives the "
        "items skaldr created there and releases any page it wrote into, then add the new target and "
        "publish again"
    )


@pytest.mark.parametrize(
    ("moved", "new_label"),
    [
        pytest.param({"parent_page": OTHER_PAGE_ID}, OTHER_LABEL, id="parent-page"),
        pytest.param({"page": OTHER_PAGE_ID}, f"{OTHER_LABEL} (written into)", id="page"),
        pytest.param({"page": NOTION_PAGE_ID}, INTO_LABEL, id="same-page-written-into"),
    ],
)
def test_apply_refuses_a_target_whose_place_changed_and_writes_nothing(
    tmp_path: Path, moved: dict[str, str], new_label: str
) -> None:
    transport = FakeTransport()
    path = _published_then_rewritten(tmp_path, transport, {}, publish=make_notion_publish(where=moved))

    with pytest.raises(PublishError, match=f"^{re.escape(_moved('Notion', TARGET_LABEL, new_label))}$"):
        _publish(path, transport)
    assert transport.writes() == []


def test_a_moved_target_shows_in_status_and_the_dry_run_names_the_refusal(tmp_path: Path) -> None:
    transport = FakeTransport()
    path = _published_then_rewritten(
        tmp_path, transport, {}, publish=make_notion_publish(where={"parent_page": OTHER_PAGE_ID})
    )

    status = publish_status(prepare_publish(path, _registry(transport)))
    dry_run = dry_run_publish(prepare_publish(path, _registry(transport)))

    assert (status, dry_run.refusal) == (
        (
            ItemStatus(ItemRef(OTHER_LABEL, None), None, ("never published",)),
            ItemStatus(DOCUMENT, "page-1", ("removed",)),
            ItemStatus(TOOLS, "page-2", ("removed",)),
        ),
        _moved("Notion", TARGET_LABEL, OTHER_LABEL),
    )


def test_a_page_written_into_moving_to_a_parent_page_is_a_move_too(tmp_path: Path) -> None:
    transport = FakeTransport()
    transport.seed(NOTION_PAGE_ID, "Blank page", None)
    path = _published_then_rewritten(
        tmp_path,
        transport,
        {"publish": INTO_THE_PAGE},
        publish=make_notion_publish(where={"parent_page": NOTION_PAGE_ID}),
    )

    with pytest.raises(PublishError, match=f"^{re.escape(_moved('Notion', INTO_LABEL, TARGET_LABEL))}$"):
        _publish(path, transport)
    assert transport.writes() == []


def test_a_jira_target_whose_parent_changed_is_refused(tmp_path: Path) -> None:
    transport = FakeTransport()
    first = {"doc_id": DOC_ID, "targets": [make_jira_target(where={"project": "PLAN", "issue_type": "Task"})]}
    then = {
        "doc_id": DOC_ID,
        "targets": [make_jira_target(where={"project": "PLAN", "issue_type": "Task", "parent": "PLAN-7"})],
    }
    path = _published_then_rewritten(tmp_path, transport, {"publish": first}, publish=then)
    old, new = "jira project PLAN under no parent issue", "jira project PLAN under PLAN-7"

    with pytest.raises(PublishError, match=f"^{re.escape(_moved('Jira', old, new))}$"):
        _publish(path, transport)


def test_an_item_deleted_in_the_service_shows_as_missing_in_status_and_diff(tmp_path: Path) -> None:
    transport = FakeTransport()
    path = _published_then_rewritten(tmp_path, transport, {})
    transport.delete_item_by_hand("page-2")

    status = publish_status(prepare_publish(path, _registry(transport)))
    diff = diff_publish(prepare_publish(path, _registry(transport)))

    assert (status, diff, transport.writes()) == (
        (ItemStatus(DOCUMENT, "page-1", ("in sync",)), ItemStatus(TOOLS, "page-2", ("missing remotely",))),
        PublishDiff((), (), (MissingItem(TOOLS, "page-2"),)),
        [],
    )


def test_apply_refuses_an_item_deleted_in_the_service_and_overwrite_creates_it_again(tmp_path: Path) -> None:
    transport = FakeTransport()
    path = _published_then_rewritten(tmp_path, transport, {})
    transport.delete_item_by_hand("page-2")
    expected = (
        f"{TARGET_LABEL}, section tools (page-2) is no longer in Notion; publish with --apply --overwrite to "
        "create it again, or to forget it if the YAML no longer has it"
    )

    with pytest.raises(PublishError, match=f"^{re.escape(expected)}$"):
        _publish(path, transport)
    refused_writes = transport.writes()
    outcome = _publish(path, transport, overwrite=True)

    assert (
        refused_writes,
        outcome,
        transport.writes(),
        load_state(state_path_for(path), DOC_ID).targets[TARGET_LABEL].sections["tools"].item_id,
    ) == (
        [],
        Applied(('create   section tools "Tools"',)),
        [("create", "Tools", "page-1", "")],
        "page-3",
    )


def test_overwrite_forgets_an_item_deleted_in_the_service_that_the_yaml_removed(tmp_path: Path) -> None:
    transport = FakeTransport()
    without_tools = [block for block in make_garden_blocks() if block.get("id") != "tools"]
    path = _published_then_rewritten(
        tmp_path, transport, {}, publish=make_notion_publish(), blocks=without_tools
    )
    transport.delete_item_by_hand("page-2")

    outcome = _publish(path, transport, overwrite=True)

    assert (
        outcome,
        transport.writes(),
        list(load_state(state_path_for(path), DOC_ID).targets[TARGET_LABEL].sections),
    ) == (
        Applied(("archive  section tools (page-2)",)),
        [],
        [],
    )


def test_the_dry_run_reads_the_services_and_shows_what_apply_would_refuse(tmp_path: Path) -> None:
    transport = FakeTransport()
    path = _published_then_rewritten(tmp_path, transport, {}, blocks=make_garden_blocks(tools="Rake."))
    transport.edit_section_by_hand("page-1", "planting", LATE_SPRING)
    before = state_path_for(path).read_bytes()

    dry_run = dry_run_publish(prepare_publish(path, _registry(transport)))

    assert (
        dry_run.edits,
        dry_run.refusal,
        transport.writes(),
        state_path_for(path).read_bytes() == before,
    ) == (
        (
            RemoteEdit(
                DOCUMENT,
                section_part("planting"),
                "blocks[2]",
                "## Planting\nSow in spring.\n",
                LATE_SPRING,
                None,
                None,
            ),
        ),
        "1 part was edited in the service since the last publish, so nothing was written. To keep the edit, "
        "copy it into the YAML first; to replace it, publish with --apply --overwrite.",
        [],
        True,
    )


def test_the_dry_run_names_a_stamp_conflict_apply_would_refuse(tmp_path: Path) -> None:
    transport = FakeTransport()
    transport.seed(NOTION_PAGE_ID, "Kitchen rota", OTHER_DOC_ID)
    path = write_garden_report(tmp_path, publish=INTO_THE_PAGE)

    dry_run = dry_run_publish(prepare_publish(path, _registry(transport)))

    assert (dry_run.refusal, transport.writes()) == (
        f"{INTO_LABEL}, document ({NOTION_PAGE_ID}) is stamped with doc_id '{OTHER_DOC_ID}', so it belongs "
        "to "
        f"that document and not to '{DOC_ID}'; skaldr writes only to items of the document it publishes",
        [],
    )


def test_a_clean_dry_run_has_the_plan_apply_carries_out(tmp_path: Path) -> None:
    transport = FakeTransport()
    path = _published_then_rewritten(tmp_path, transport, {}, blocks=make_garden_blocks(tools="Rake."))
    prepared = prepare_publish(path, _registry(transport))

    dry_run = dry_run_publish(prepared)

    assert (dry_run, transport.writes()) == (DryRun(prepared.plan, (), None), [])


def test_the_dry_run_command_prints_the_edit_and_fails_saying_apply_would_stop(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    transport = FakeTransport()
    path = _published_then_rewritten(tmp_path, transport, {})
    transport.edit_section_by_hand("page-1", "planting", LATE_SPRING)
    capsys.readouterr()

    exit_code = main(["publish", str(path)], registry=_registry(transport))

    assert (exit_code, capsys.readouterr()) == (
        1,
        (
            f"{TARGET_LABEL}: nothing to change\n"
            f"--- {TARGET_LABEL}, document: planting (blocks[2]), as published\n"
            f"+++ {TARGET_LABEL}, document: planting (blocks[2]), now\n"
            "@@ -1,2 +1,2 @@\n"
            " ## Planting\n"
            "-Sow in spring.\n"
            "+Sow in late spring.\n",
            "error: --apply would stop: 1 part was edited in the service since the last publish, so nothing "
            "was "
            "written. To keep the edit, copy it into the YAML first; to replace it, publish with --apply "
            "--overwrite.\n",
        ),
    )


def test_the_diff_and_status_commands_name_an_item_missing_remotely(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    transport = FakeTransport()
    path = _published_then_rewritten(tmp_path, transport, {})
    transport.delete_item_by_hand("page-2")
    capsys.readouterr()

    codes = [main([command, str(path)], registry=_registry(transport)) for command in ("diff", "status")]

    assert (codes, capsys.readouterr().out) == (
        [0, 0],
        "Remote edits since the last publish: none\n"
        "Missing remotely:\n"
        f"{TARGET_LABEL}, section tools (page-2)\n"
        "What this YAML would change: nothing\n"
        f"{TARGET_LABEL}, document (page-1): in sync\n"
        f"{TARGET_LABEL}, section tools (page-2): missing remotely\n",
    )


def test_the_diff_json_lists_an_item_missing_remotely(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    transport = FakeTransport()
    path = _published_then_rewritten(tmp_path, transport, {})
    transport.delete_item_by_hand("page-2")
    capsys.readouterr()

    main(["diff", str(path), "--json"], registry=_registry(transport))

    assert capsys.readouterr().out == (
        '{\n  "remote_edits": [],\n  "yaml_changes": [],\n  "missing_remotely": [\n    {\n'
        f'      "target": "{TARGET_LABEL}",\n      "item": "section tools",\n      "item_id": "page-2"\n'
        "    }\n  ]\n}\n"
    )


def test_the_dry_run_command_names_a_refusal_apply_would_make(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    transport = FakeTransport()
    path = _published_then_rewritten(tmp_path, transport, {})
    transport.delete_item_by_hand("page-2")
    capsys.readouterr()

    exit_code = main(["publish", str(path)], registry=_registry(transport))

    assert (exit_code, capsys.readouterr().err) == (
        1,
        f"error: --apply would refuse: {TARGET_LABEL}, section tools (page-2) is no longer in Notion; "
        "publish "
        "with --apply --overwrite to create it again, or to forget it if the YAML no longer has it\n",
    )
