import re
from pathlib import Path

import pytest

from skaldr.errors import ConnectorError, PublishError
from skaldr.publish.content import section_part
from skaldr.publish.engine import (
    Applied,
    ApplyOutcome,
    ItemStatus,
    Refused,
    RemoteEdit,
    apply_publish,
    prepare_publish,
    publish_status,
)
from skaldr.publish.plan import ItemRef
from skaldr.publish.state import load_state, state_path_for
from skaldr.publish.transport import Stamp
from skaldr.publish_block import JiraTarget, NotionTarget
from tests.factories.publish_factory import (
    DOC_ID,
    DROPPED_AFTER_WRITE,
    INTRO_KEY,
    LOST_WRITE,
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
INTO_THE_PAGE = make_notion_publish(where={"page": NOTION_PAGE_ID})
JIRA_PUBLISH = {"doc_id": DOC_ID, "targets": [make_jira_target()]}


def _publish(path: Path, transport: FakeTransport) -> ApplyOutcome:
    registry = fake_registry(transport, target_types=(NotionTarget, JiraTarget))
    return apply_publish(prepare_publish(path, registry))


def _interrupted(path: Path, transport: FakeTransport, error: str) -> None:
    with pytest.raises(ConnectorError, match=f"^{error}$"):
        _publish(path, transport)
    transport.stop_failing()
    transport.forget_calls()


def _adopted_page(tmp_path: Path, transport: FakeTransport) -> Path:
    transport.seed(NOTION_PAGE_ID, "Blank page", None)
    path = write_garden_report(tmp_path, publish=INTO_THE_PAGE)
    _publish(path, transport)
    transport.forget_calls()
    return path


def test_an_interrupted_adoption_whose_target_left_the_yaml_is_settled_and_released(tmp_path: Path) -> None:
    transport = FakeTransport()
    transport.seed(NOTION_PAGE_ID, "Blank page", None)
    path = write_garden_report(tmp_path, publish=INTO_THE_PAGE)
    transport.drop_the_connection_after_write(1)
    _interrupted(path, transport, DROPPED_AFTER_WRITE)
    write_garden_report(tmp_path, publish=JIRA_PUBLISH)

    outcome = _publish(path, transport)

    assert (outcome, transport.writes()[1:], transport.items[NOTION_PAGE_ID].stamp) == (
        Applied(('create   document "Garden handbook"', f"release  document ({NOTION_PAGE_ID})")),
        [("release", NOTION_PAGE_ID)],
        None,
    )


def test_a_section_back_in_the_yaml_after_an_archive_that_never_landed_is_tracked_again(
    tmp_path: Path,
) -> None:
    transport = FakeTransport()
    path = write_garden_report(tmp_path)
    _publish(path, transport)
    without_tools = [block for block in make_garden_blocks() if block.get("id") != "tools"]
    write_garden_report(tmp_path, publish=make_notion_publish(), blocks=without_tools)
    transport.lose_the_next_write()
    _interrupted(path, transport, LOST_WRITE)
    write_garden_report(tmp_path)
    _publish(path, transport)
    retiring = load_state(state_path_for(path), DOC_ID).targets[TARGET_LABEL].sections["tools"].retiring
    transport.delete_item_by_hand("page-2")

    statuses = publish_status(prepare_publish(path, fake_registry(transport)))

    assert (retiring, statuses) == (
        None,
        (ItemStatus(DOCUMENT, "page-1", ("in sync",)), ItemStatus(TOOLS, "page-2", ("missing remotely",))),
    )


def test_a_release_that_partly_landed_is_sent_again(tmp_path: Path) -> None:
    transport = FakeTransport()
    path = _adopted_page(tmp_path, transport)
    write_garden_report(tmp_path, publish=JIRA_PUBLISH)
    transport.land_part_of_the_next_release(after_writes=1)
    _interrupted(path, transport, DROPPED_AFTER_WRITE)

    outcome = _publish(path, transport)

    assert (outcome, transport.writes(), transport.items[NOTION_PAGE_ID].stamp) == (
        Applied((f"release  document ({NOTION_PAGE_ID})",)),
        [("release", NOTION_PAGE_ID)],
        None,
    )


def test_a_landed_release_on_a_page_with_a_property_skaldr_did_not_set_is_forgotten(tmp_path: Path) -> None:
    transport = FakeTransport()
    path = _adopted_page(tmp_path, transport)
    transport.items[NOTION_PAGE_ID].fields["Status"] = "Done"
    write_garden_report(tmp_path, publish=JIRA_PUBLISH)
    transport.drop_the_connection_after_write(2)
    _interrupted(path, transport, DROPPED_AFTER_WRITE)

    outcome = _publish(path, transport)

    assert (outcome, transport.writes(), list(load_state(state_path_for(path), DOC_ID).targets)) == (
        Applied(()),
        [],
        ["jira project PLAN under no parent issue"],
    )


def test_an_apply_whose_yaml_changed_after_it_was_planned_is_refused(tmp_path: Path) -> None:
    transport = FakeTransport()
    path = write_garden_report(tmp_path)
    prepared = prepare_publish(path, fake_registry(transport))
    write_garden_report(tmp_path, blocks=make_garden_blocks(planting="Sow in May."))
    expected = (
        f"{path} changed after this publish was planned; run it again to plan from the YAML as it is now"
    )

    with pytest.raises(PublishError, match=f"^{re.escape(expected)}$"):
        apply_publish(prepared)
    assert transport.calls == []


def test_the_landed_parts_of_an_interrupted_write_are_kept_and_only_the_rest_is_an_edit(
    tmp_path: Path,
) -> None:
    transport = FakeTransport()
    path = write_garden_report(tmp_path, publish=make_notion_publish())
    _publish(path, transport)
    write_garden_report(
        tmp_path, publish=make_notion_publish(), blocks=make_garden_blocks(planting="Sow in May.")
    )
    transport.drop_the_connection_after_write(1)
    _interrupted(path, transport, DROPPED_AFTER_WRITE)
    transport.edit_section_by_hand("page-1", INTRO_KEY, "Welcome, gardeners.\n")

    outcome = _publish(path, transport)
    document = load_state(state_path_for(path), DOC_ID).targets[TARGET_LABEL].document

    assert (outcome, document and document.rendered.sections["planting"]) == (
        Refused(
            (
                RemoteEdit(
                    DOCUMENT,
                    section_part(INTRO_KEY),
                    "blocks[0]",
                    "Welcome to the garden.\n",
                    "Welcome, gardeners.\n",
                    None,
                    None,
                ),
            ),
            "edited",
        ),
        "## Planting\nSow in May.\n",
    )


def test_an_interrupted_adoption_on_a_service_that_normalises_text_publishes_nothing_more(
    tmp_path: Path,
) -> None:
    transport = FakeTransport(strips_trailing_whitespace=True)
    transport.seed(NOTION_PAGE_ID, "Blank page", None)
    path = write_garden_report(tmp_path, publish=INTO_THE_PAGE)
    transport.drop_the_connection_after_write(1)
    _interrupted(path, transport, DROPPED_AFTER_WRITE)

    assert (_publish(path, transport), transport.writes()) == (Applied(()), [])


def test_an_adoption_that_wrote_the_content_but_not_the_stamp_is_written_again(tmp_path: Path) -> None:
    transport = FakeTransport()
    transport.seed(NOTION_PAGE_ID, "Blank page", None)
    path = write_garden_report(tmp_path, publish=INTO_THE_PAGE)
    transport.land_the_next_create_into_without_its_stamp()
    _interrupted(path, transport, DROPPED_AFTER_WRITE)

    outcome = _publish(path, transport)

    assert (outcome, transport.writes(), transport.items[NOTION_PAGE_ID].stamp) == (
        Applied((f'create   document "Garden handbook" into {NOTION_PAGE_ID}',)),
        [("create", "Garden handbook", "", NOTION_PAGE_ID)],
        Stamp(DOC_ID, None),
    )
