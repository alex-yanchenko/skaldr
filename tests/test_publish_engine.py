import re
from pathlib import Path
from typing import Any

import pytest

from skaldr.errors import ConnectorError, PublishError
from skaldr.models import load_report
from skaldr.publish.content import FIELDS, TITLE, ItemContent, section_part
from skaldr.publish.drafts import draft_targets
from skaldr.publish.engine import (
    Applied,
    ApplyOutcome,
    ItemStatus,
    PublishDiff,
    Refused,
    RemoteEdit,
    YamlChange,
    apply_publish,
    diff_publish,
    prepare_publish,
    publish_status,
)
from skaldr.publish.plan import ItemRef
from skaldr.publish.state import load_state, state_path_for
from skaldr.publish.transport import Stamp
from tests.factories.publish_factory import (
    DOC_ID,
    INTRO_KEY,
    OTHER_DOC_ID,
    REFUSED_WRITE,
    TARGET_LABEL,
    FakeTransport,
    fake_registry,
    make_garden_blocks,
    make_notion_publish,
    write_garden_report,
)
from tests.factories.report_factory import NOTION_PAGE_ID

DOCUMENT = ItemRef(TARGET_LABEL, None)
TOOLS = ItemRef(TARGET_LABEL, "tools")
PLANTING = ItemRef(TARGET_LABEL, "planting")
SPRING = "## Planting\nSow in spring.\n"
LATE_SPRING = "## Planting\nSow in late spring.\n"
TOOLS_TEXT = '## Tools\n<span color="blue">**api**</span>\n- Spade.\n'
RAKE_TEXT = '## Tools\n<span color="blue">**api**</span>\n- Rake.\n'
LEGEND_TEXT = (
    "<details>\n"
    "<summary>Legend: badges used on this page</summary>\n"
    '\t- <span color="blue">**api**</span> the API\n'
    "</details>\n"
)
FIRST_PUBLISH = ('create   document "Garden handbook"', 'create   section tools "Tools"')


def _publish(path: Path, transport: FakeTransport, *, overwrite: bool = False) -> ApplyOutcome:
    return apply_publish(prepare_publish(path, fake_registry(transport)), overwrite=overwrite)


def _drafted(path: Path, section_id: str | None = None) -> ItemContent:
    (target,) = draft_targets(load_report(path), fake_registry(FakeTransport()))
    return next(item.content for item in target.items if item.section_id == section_id)


def _published_then_rewritten(tmp_path: Path, transport: FakeTransport, **rewritten: Any) -> Path:
    path = write_garden_report(tmp_path)
    _publish(path, transport)
    write_garden_report(tmp_path, **rewritten)
    transport.forget_calls()
    return path


def _planting_edit(published: str = SPRING, current: str = LATE_SPRING) -> RemoteEdit:
    return RemoteEdit(DOCUMENT, section_part("planting"), "blocks[2]", published, current, None, None)


def test_a_first_publish_creates_the_document_then_its_split_section_under_it(tmp_path: Path) -> None:
    path = write_garden_report(tmp_path)
    transport = FakeTransport()

    outcome = _publish(path, transport)

    assert (outcome, transport.writes(), transport.items["page-2"].content) == (
        Applied(FIRST_PUBLISH),
        [("create", "Garden handbook", "", ""), ("create", "Tools", "page-1", "")],
        _drafted(path, "tools"),
    )


def test_publishing_again_writes_only_the_section_the_yaml_changed(tmp_path: Path) -> None:
    transport = FakeTransport()
    path = _published_then_rewritten(
        tmp_path, transport, blocks=make_garden_blocks(planting="Sow after the last frost.")
    )

    outcome = _publish(path, transport)

    assert (outcome, transport.writes(), transport.items["page-1"].content) == (
        Applied(("update   document: planting (blocks[2])",)),
        [("write_section", "page-1", "planting")],
        _drafted(path),
    )


def test_a_dry_run_reads_and_writes_nothing(tmp_path: Path) -> None:
    path = write_garden_report(tmp_path)
    transport = FakeTransport()

    prepare_publish(path, fake_registry(transport))

    assert (transport.calls, state_path_for(path).exists()) == ([], False)


def test_an_apply_that_fails_midway_resumes_from_the_step_that_failed(tmp_path: Path) -> None:
    transport = FakeTransport()
    path = _published_then_rewritten(
        tmp_path, transport, blocks=make_garden_blocks(tools="Rake.", planting="Sow in May.")
    )
    transport.fail_on_write(2)

    with pytest.raises(ConnectorError, match=f"^{REFUSED_WRITE}$"):
        _publish(path, transport)
    first_try = transport.writes()
    transport.forget_calls()
    transport.stop_failing()
    second_try = _publish(path, transport)

    assert (first_try, second_try, transport.writes(), transport.items["page-2"].content) == (
        [("write_section", "page-1", "planting")],
        Applied(("update   section tools: tools (blocks[1])",)),
        [("write_section", "page-2", "tools")],
        _drafted(path, "tools"),
    )


def test_a_remote_edit_stops_the_publish_and_overwrite_then_replaces_it(tmp_path: Path) -> None:
    transport = FakeTransport()
    path = _published_then_rewritten(tmp_path, transport, blocks=make_garden_blocks(tools="Rake."))
    transport.edit_section_by_hand("page-1", "planting", LATE_SPRING)

    refused = _publish(path, transport)
    refused_writes = transport.writes()
    overwritten = _publish(path, transport, overwrite=True)

    assert (refused, refused_writes, overwritten, transport.writes(), transport.items["page-1"].content) == (
        Refused((_planting_edit(),), "edited"),
        [],
        Applied(("update   document: planting (blocks[2])", "update   section tools: tools (blocks[1])")),
        [("write_section", "page-1", "planting"), ("write_section", "page-2", "tools")],
        _drafted(path),
    )


def test_overwrite_refuses_again_when_the_item_changed_after_the_diff(tmp_path: Path) -> None:
    transport = FakeTransport()
    path = _published_then_rewritten(tmp_path, transport)
    transport.edit_section_by_hand("page-1", "planting", LATE_SPRING)
    _publish(path, transport)
    transport.edit_section_by_hand("page-1", "planting", "## Planting\nSow in summer.\n")

    outcome = _publish(path, transport, overwrite=True)

    assert (outcome, transport.writes()) == (
        Refused((_planting_edit(current="## Planting\nSow in summer.\n"),), "changed since the diff"),
        [],
    )


def test_overwrite_refuses_an_edit_no_diff_has_shown_and_proceeds_once_it_has(tmp_path: Path) -> None:
    transport = FakeTransport()
    path = _published_then_rewritten(tmp_path, transport)
    transport.edit_section_by_hand("page-1", "planting", LATE_SPRING)

    unseen = _publish(path, transport, overwrite=True)
    seen = _publish(path, transport, overwrite=True)

    assert (unseen, seen, transport.writes()) == (
        Refused((_planting_edit(),), "changed since the diff"),
        Applied(("update   document: planting (blocks[2])",)),
        [("write_section", "page-1", "planting")],
    )


def test_an_edit_the_service_reports_without_a_visible_change_still_stops_the_publish(tmp_path: Path) -> None:
    transport = FakeTransport()
    path = _published_then_rewritten(tmp_path, transport)
    transport.report_an_edit_without_changing_content("page-1", FIELDS)

    assert _publish(path, transport) == Refused(
        (RemoteEdit(DOCUMENT, FIELDS, "publish.targets[0].where.fields", "{}\n", "{}\n", None, None),),
        "edited",
    )


def test_labels_the_service_reads_back_in_another_order_are_not_a_remote_edit(tmp_path: Path) -> None:
    transport = FakeTransport(reads_list_fields_reversed=True)
    labelled = {"parent_page": NOTION_PAGE_ID, "fields": {"Tags": ["soil", "seeds"]}}
    reordered = {**labelled, "fields": {"Tags": ["seeds", "soil"]}}
    path = write_garden_report(tmp_path, publish=make_notion_publish(split=["tools"], where=labelled))
    _publish(path, transport)
    write_garden_report(tmp_path, publish=make_notion_publish(split=["tools"], where=reordered))
    transport.forget_calls()

    assert (_publish(path, transport), transport.writes()) == (Applied(()), [])


def test_a_page_stamped_by_another_document_is_refused_naming_both_documents(tmp_path: Path) -> None:
    transport = FakeTransport()
    transport.seed(NOTION_PAGE_ID, "Kitchen rota", OTHER_DOC_ID)
    path = write_garden_report(tmp_path, publish=make_notion_publish(where={"page": NOTION_PAGE_ID}))
    expected = (
        f"{TARGET_LABEL}, document ({NOTION_PAGE_ID}) is stamped with doc_id '{OTHER_DOC_ID}', so it belongs "
        f"to that document and not to '{DOC_ID}'; skaldr writes only to items of the document it publishes"
    )

    with pytest.raises(PublishError, match=f"^{re.escape(expected)}$"):
        _publish(path, transport)
    assert transport.writes() == []


def test_a_published_item_restamped_by_another_document_is_refused(tmp_path: Path) -> None:
    transport = FakeTransport()
    path = _published_then_rewritten(tmp_path, transport, blocks=make_garden_blocks(planting="Sow in May."))
    transport.items["page-2"].stamp = Stamp(OTHER_DOC_ID, "tools")
    expected = (
        f"{TARGET_LABEL}, section tools (page-2) is stamped with doc_id '{OTHER_DOC_ID}', so it belongs to "
        f"that document and not to '{DOC_ID}'; skaldr writes only to items of the document it publishes"
    )

    with pytest.raises(PublishError, match=f"^{re.escape(expected)}$"):
        _publish(path, transport)
    assert transport.writes() == []


def test_an_unstamped_page_the_target_names_is_written_into_and_stamped(tmp_path: Path) -> None:
    transport = FakeTransport()
    transport.seed(NOTION_PAGE_ID, "Blank page", None)
    path = write_garden_report(
        tmp_path, publish=make_notion_publish(split=["tools"], where={"page": NOTION_PAGE_ID})
    )

    outcome = _publish(path, transport)

    assert (
        outcome,
        transport.writes(),
        [transport.items[item_id].stamp for item_id in (NOTION_PAGE_ID, "page-2")],
    ) == (
        Applied(
            (f'create   document "Garden handbook" into {NOTION_PAGE_ID}', 'create   section tools "Tools"')
        ),
        [("create", "Garden handbook", "", NOTION_PAGE_ID), ("create", "Tools", NOTION_PAGE_ID, "")],
        [Stamp(DOC_ID, None), Stamp(DOC_ID, "tools")],
    )


def test_a_section_removed_from_the_yaml_archives_its_item_and_leaves_the_state_file(tmp_path: Path) -> None:
    transport = FakeTransport()
    without_tools = [block for block in make_garden_blocks() if block.get("id") != "tools"]
    path = _published_then_rewritten(tmp_path, transport, publish=make_notion_publish(), blocks=without_tools)

    outcome = _publish(path, transport)

    assert (
        outcome,
        transport.writes(),
        transport.items["page-2"].archived,
        list(load_state(state_path_for(path), DOC_ID).targets[TARGET_LABEL].sections),
    ) == (
        Applied(("archive  section tools (page-2)",)),
        [("archive", "page-2")],
        True,
        [],
    )


def test_the_diff_shows_remote_edits_and_what_the_yaml_would_change(tmp_path: Path) -> None:
    transport = FakeTransport()
    path = _published_then_rewritten(tmp_path, transport, blocks=make_garden_blocks(tools="Rake."))
    transport.edit_section_by_hand("page-1", "planting", LATE_SPRING)

    diff = diff_publish(prepare_publish(path, fake_registry(transport)))

    assert (diff, transport.writes()) == (
        PublishDiff(
            (_planting_edit(),),
            (YamlChange(TOOLS, section_part("tools"), "blocks[1]", TOOLS_TEXT, RAKE_TEXT),),
        ),
        [],
    )


def test_the_diff_shows_a_changed_title_with_its_yaml_location(tmp_path: Path) -> None:
    transport = FakeTransport()
    path = _published_then_rewritten(
        tmp_path, transport, blocks=make_garden_blocks(tools_title="Garden tools")
    )

    diff = diff_publish(prepare_publish(path, fake_registry(transport)))

    assert diff == PublishDiff(
        (),
        (
            YamlChange(TOOLS, TITLE, "blocks[1].title", "Tools\n", "Garden tools\n"),
            YamlChange(
                TOOLS,
                section_part("tools"),
                "blocks[1]",
                TOOLS_TEXT,
                TOOLS_TEXT.replace("Tools", "Garden tools"),
            ),
        ),
    )


def test_the_diff_lists_every_part_of_an_item_never_published_and_of_an_item_removed(tmp_path: Path) -> None:
    transport = FakeTransport()
    without_tools = [block for block in make_garden_blocks() if block.get("id") != "tools"]
    path = _published_then_rewritten(
        tmp_path, transport, publish=make_notion_publish(split=["planting"]), blocks=without_tools
    )

    diff = diff_publish(prepare_publish(path, fake_registry(transport)))

    assert diff == PublishDiff(
        (),
        (
            YamlChange(DOCUMENT, section_part("planting"), None, SPRING, None),
            YamlChange(PLANTING, TITLE, "blocks[1].title", None, "Planting\n"),
            YamlChange(PLANTING, section_part("planting"), "blocks[1]", None, SPRING),
            YamlChange(TOOLS, TITLE, None, "Tools\n", None),
            YamlChange(TOOLS, section_part("page legend"), None, LEGEND_TEXT, None),
            YamlChange(TOOLS, section_part("tools"), None, TOOLS_TEXT, None),
        ),
    )


def test_a_changed_plain_block_shows_as_one_block_added_and_one_removed(tmp_path: Path) -> None:
    transport = FakeTransport()
    path = _published_then_rewritten(
        tmp_path, transport, blocks=make_garden_blocks(intro="Welcome, new members.")
    )

    diff = diff_publish(prepare_publish(path, fake_registry(transport)))

    assert diff == PublishDiff(
        (),
        (
            YamlChange(
                DOCUMENT, section_part("block 86f0151a"), "blocks[0]", None, "Welcome, new members.\n"
            ),
            YamlChange(DOCUMENT, section_part(INTRO_KEY), None, "Welcome to the garden.\n", None),
        ),
    )


def test_a_diff_counts_as_showing_the_remote_edit_to_overwrite(tmp_path: Path) -> None:
    transport = FakeTransport()
    path = _published_then_rewritten(tmp_path, transport)
    transport.edit_section_by_hand("page-1", "planting", LATE_SPRING)

    diff_publish(prepare_publish(path, fake_registry(transport)))

    assert _publish(path, transport, overwrite=True) == Applied(("update   document: planting (blocks[2])",))


def test_the_status_names_each_item_in_sync_edited_changed_or_never_published(tmp_path: Path) -> None:
    transport = FakeTransport()
    path = _published_then_rewritten(
        tmp_path, transport, publish=make_notion_publish(split=["tools", "planting"])
    )
    transport.edit_section_by_hand("page-2", "tools", "## Tools\n- Rake.\n")

    statuses = publish_status(prepare_publish(path, fake_registry(transport)))

    assert (statuses, transport.writes()) == (
        (
            ItemStatus(DOCUMENT, "page-1", ("changed in the YAML",)),
            ItemStatus(TOOLS, "page-2", ("edited remotely",)),
            ItemStatus(PLANTING, None, ("never published",)),
        ),
        [],
    )


def test_the_status_names_an_item_whose_section_left_the_yaml_as_removed(tmp_path: Path) -> None:
    transport = FakeTransport()
    without_tools = [block for block in make_garden_blocks() if block.get("id") != "tools"]
    path = _published_then_rewritten(tmp_path, transport, publish=make_notion_publish(), blocks=without_tools)

    assert publish_status(prepare_publish(path, fake_registry(transport))) == (
        ItemStatus(DOCUMENT, "page-1", ("in sync",)),
        ItemStatus(TOOLS, "page-2", ("removed",)),
    )


def test_an_unchanged_published_document_is_in_sync(tmp_path: Path) -> None:
    transport = FakeTransport()
    path = _published_then_rewritten(tmp_path, transport)

    assert publish_status(prepare_publish(path, fake_registry(transport))) == (
        ItemStatus(DOCUMENT, "page-1", ("in sync",)),
        ItemStatus(TOOLS, "page-2", ("in sync",)),
    )
