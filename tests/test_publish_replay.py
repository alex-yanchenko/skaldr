import re
from pathlib import Path
from typing import Any

import pytest

from skaldr.errors import ConnectorError, PublishError
from skaldr.models import load_report
from skaldr.publish.content import FIELDS, ItemContent, section_part
from skaldr.publish.drafts import draft_targets
from skaldr.publish.engine import (
    Applied,
    ApplyOutcome,
    ItemStatus,
    Refused,
    RemoteEdit,
    apply_publish,
    diff_publish,
    prepare_publish,
    publish_status,
)
from skaldr.publish.plan import ItemRef
from skaldr.publish.state import held_state_lock, load_state, state_path_for
from skaldr.publish_block import JiraTarget, NotionTarget
from tests.factories.publish_factory import (
    DOC_ID,
    DROPPED_AFTER_WRITE,
    REFUSED_WRITE,
    TARGET_LABEL,
    FakeTransport,
    fake_registry,
    make_garden_blocks,
    make_notion_publish,
    write_garden_report,
)
from tests.factories.report_factory import make_jira_target

DOCUMENT = ItemRef(TARGET_LABEL, None)
TOOLS = ItemRef(TARGET_LABEL, "tools")
LATE_SPRING = "## Planting\nSow in late spring.\n"
JIRA_LABEL = "jira project PLAN under no parent issue"


def _publish(path: Path, transport: FakeTransport, *, overwrite: bool = False) -> ApplyOutcome:
    registry = fake_registry(transport, target_types=(NotionTarget, JiraTarget))
    return apply_publish(prepare_publish(path, registry), overwrite=overwrite)


def _drafted(path: Path, section_id: str | None = None) -> ItemContent:
    (target,) = draft_targets(load_report(path), fake_registry(FakeTransport()))
    return next(item.content for item in target.items if item.section_id == section_id)


def _published_then_rewritten(tmp_path: Path, transport: FakeTransport, **rewritten: Any) -> Path:
    path = write_garden_report(tmp_path)
    _publish(path, transport)
    write_garden_report(tmp_path, **rewritten)
    transport.forget_calls()
    return path


def _interrupted_create(path: Path) -> str:
    return (
        f'{TARGET_LABEL}, section tools: skaldr stopped while creating "Tools" under page-1, so it cannot '
        'tell whether that item exists. Look under page-1 for an item titled "Tools" stamped with doc_id '
        f"'{DOC_ID}' and archive it if it is there; then delete its entry from `pending_creates` in "
        f"{state_path_for(path)} and publish again"
    )


@pytest.mark.parametrize(
    ("interrupt", "error"),
    [
        pytest.param("drop_the_connection_after_write", DROPPED_AFTER_WRITE, id="created-then-dropped"),
        pytest.param("fail_on_write", REFUSED_WRITE, id="refused"),
    ],
)
def test_an_interrupted_create_stops_the_next_run_naming_the_parent_and_title_to_check(
    tmp_path: Path, interrupt: str, error: str
) -> None:
    path = write_garden_report(tmp_path)
    transport = FakeTransport()
    getattr(transport, interrupt)(2)
    with pytest.raises(ConnectorError, match=f"^{error}$"):
        _publish(path, transport)
    transport.stop_failing()
    transport.forget_calls()

    with pytest.raises(PublishError, match=f"^{re.escape(_interrupted_create(path))}$"):
        _publish(path, transport)
    assert (transport.writes(), publish_status(prepare_publish(path, fake_registry(transport)))) == (
        [],
        (ItemStatus(DOCUMENT, "page-1", ("in sync",)), ItemStatus(TOOLS, None, ("create interrupted",))),
    )


def test_a_write_that_landed_before_the_connection_dropped_is_recorded_and_the_run_carries_on(
    tmp_path: Path,
) -> None:
    transport = FakeTransport()
    path = _published_then_rewritten(
        tmp_path, transport, blocks=make_garden_blocks(tools="Rake.", planting="Sow in May.")
    )
    transport.drop_the_connection_after_write(1)
    with pytest.raises(ConnectorError, match=f"^{DROPPED_AFTER_WRITE}$"):
        _publish(path, transport)
    transport.stop_failing()
    transport.forget_calls()

    outcome = _publish(path, transport)

    assert (
        outcome,
        transport.writes(),
        transport.items["page-1"].content,
        transport.items["page-2"].content,
    ) == (
        Applied(("update   section tools: tools (blocks[1])",)),
        [("write_section", "page-2", "tools")],
        _drafted(path),
        _drafted(path, "tools"),
    )


def test_a_hand_edit_over_an_interrupted_write_is_still_a_remote_edit(tmp_path: Path) -> None:
    transport = FakeTransport()
    path = _published_then_rewritten(tmp_path, transport, blocks=make_garden_blocks(planting="Sow in May."))
    transport.drop_the_connection_after_write(1)
    with pytest.raises(ConnectorError, match=f"^{DROPPED_AFTER_WRITE}$"):
        _publish(path, transport)
    transport.stop_failing()
    transport.edit_section_by_hand("page-1", "planting", LATE_SPRING)
    transport.forget_calls()

    outcome = _publish(path, transport)

    assert (outcome, transport.writes()) == (
        Refused(
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
            "edited",
        ),
        [],
    )


def test_an_archive_that_landed_before_the_connection_dropped_is_archived_again_and_forgotten(
    tmp_path: Path,
) -> None:
    transport = FakeTransport()
    without_tools = [block for block in make_garden_blocks() if block.get("id") != "tools"]
    path = _published_then_rewritten(tmp_path, transport, publish=make_notion_publish(), blocks=without_tools)
    transport.drop_the_connection_after_write(1)
    with pytest.raises(ConnectorError, match=f"^{DROPPED_AFTER_WRITE}$"):
        _publish(path, transport)
    transport.stop_failing()
    transport.forget_calls()

    outcome = _publish(path, transport)

    assert (
        outcome,
        transport.writes(),
        list(load_state(state_path_for(path), DOC_ID).targets[TARGET_LABEL].sections),
    ) == (
        Applied(("archive  section tools (page-2)",)),
        [("archive", "page-2")],
        [],
    )


def test_a_target_removed_from_the_publish_block_has_every_item_archived(tmp_path: Path) -> None:
    transport = FakeTransport()
    jira = {"doc_id": DOC_ID, "targets": [{**make_jira_target(), "split": ["tools"]}]}
    path = write_garden_report(tmp_path, publish=jira)
    _publish(path, transport)
    write_garden_report(tmp_path)
    transport.forget_calls()

    outcome = _publish(path, transport)

    assert (outcome, transport.writes()[2:], list(load_state(state_path_for(path), DOC_ID).targets)) == (
        Applied(
            (
                'create   document "Garden handbook"',
                'create   section tools "Tools"',
                "archive  section tools (page-2)",
                "archive  document (page-1)",
            )
        ),
        [("archive", "page-2"), ("archive", "page-1")],
        [TARGET_LABEL],
    )


def test_a_section_already_gone_from_the_service_is_removed_without_a_write(tmp_path: Path) -> None:
    transport = FakeTransport()
    without_planting = [block for block in make_garden_blocks() if block.get("id") != "planting"]
    path = _published_then_rewritten(tmp_path, transport, blocks=without_planting)
    transport.delete_section_by_hand("page-1", "planting")
    _publish(path, transport)
    transport.forget_calls()

    outcome = _publish(path, transport, overwrite=True)

    assert (outcome, transport.writes(), transport.items["page-1"].content) == (
        Applied(("remove   document: planting",)),
        [],
        _drafted(path),
    )


def test_a_state_target_this_skaldr_cannot_read_is_refused(tmp_path: Path) -> None:
    transport = FakeTransport()
    path = write_garden_report(tmp_path)
    _publish(path, transport)
    state_path = state_path_for(path)
    text = state_path.read_text(encoding="utf-8").replace('"to": "notion"', '"to": "notion", "colour": "red"')
    state_path.write_text(text, encoding="utf-8")
    write_garden_report(tmp_path, publish={"doc_id": DOC_ID, "targets": [make_jira_target()]})
    expected = (
        f"the state file records the target '{TARGET_LABEL}' in a form this version of skaldr cannot read, "
        "so skaldr cannot archive its items; publish with the version of skaldr that wrote it, or put the "
        "target back in the `publish` block"
    )

    with pytest.raises(PublishError, match=f"^{re.escape(expected)}$"):
        prepare_publish(path, fake_registry(transport, target_types=(NotionTarget, JiraTarget)))


def test_a_publish_is_refused_while_another_holds_the_state_lock(tmp_path: Path) -> None:
    transport = FakeTransport()
    path = write_garden_report(tmp_path)
    expected = (
        f"another skaldr publish of {path} is running and holds {state_path_for(path)}.lock; wait for it to "
        "finish, then run this again"
    )

    with (
        held_state_lock(state_path_for(path), path),
        pytest.raises(PublishError, match=f"^{re.escape(expected)}$"),
    ):
        _publish(path, transport)
    assert transport.calls == []


def test_overwrite_after_a_diff_ignores_a_new_service_marker_on_the_same_unchanged_edit(
    tmp_path: Path,
) -> None:
    transport = FakeTransport()
    path = _published_then_rewritten(tmp_path, transport)
    transport.edit_section_by_hand("page-1", "planting", LATE_SPRING)
    diff_publish(prepare_publish(path, fake_registry(transport)))
    transport.report_an_edit_without_changing_content("page-1", section_part("planting"))

    assert _publish(path, transport, overwrite=True) == Applied(("update   document: planting (blocks[2])",))


def test_overwrite_after_a_diff_refuses_when_the_service_reports_another_part_edited(tmp_path: Path) -> None:
    transport = FakeTransport()
    path = _published_then_rewritten(tmp_path, transport)
    transport.edit_section_by_hand("page-1", "planting", LATE_SPRING)
    diff_publish(prepare_publish(path, fake_registry(transport)))
    transport.report_an_edit_without_changing_content("page-1", FIELDS)

    outcome = _publish(path, transport, overwrite=True)

    assert (type(outcome), outcome.reason if isinstance(outcome, Refused) else None, transport.writes()) == (
        Refused,
        "changed since the diff",
        [],
    )
