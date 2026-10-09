import re
from typing import Any

import pytest

from skaldr.errors import PublishError
from skaldr.publish.content import FIELDS, TITLE, ItemContent
from skaldr.publish.drafts import ItemDraft, TargetDraft, draft_targets
from skaldr.publish.plan import (
    ArchiveStep,
    CreateStep,
    ItemRef,
    PublishPlan,
    RemoveSectionStep,
    TargetPlan,
    WriteFieldsStep,
    WriteSectionStep,
    describe_plan,
    plan_publish,
)
from skaldr.publish.state import PublishedItem, PublishedTarget, PublishState
from skaldr.publish_block import JiraTarget, NotionTarget
from tests.factories.publish_factory import (
    DOC_ID,
    INTRO_KEY,
    TARGET_LABEL,
    FakeTransport,
    fake_registry,
    make_garden_blocks,
    make_notion_publish,
    parse_garden_report,
)
from tests.factories.report_factory import NOTION_PAGE_ID, make_jira_target

DOCUMENT = ItemRef(TARGET_LABEL, None)
TOOLS = ItemRef(TARGET_LABEL, "tools")
OLD_TARGET_LABEL = "jira project PLAN under no parent issue"


def _drafts(**report: Any) -> tuple[TargetDraft, ...]:
    return draft_targets(parse_garden_report(**report), fake_registry(FakeTransport()))


def _published(draft: ItemDraft, item_id: str) -> PublishedItem:
    return PublishedItem(item_id=item_id, rendered=draft.content, remote=draft.content)


def _state_of(drafts: tuple[TargetDraft, ...]) -> PublishState:
    (target,) = drafts
    return PublishState(
        doc_id=DOC_ID,
        targets={
            target.label: PublishedTarget(
                service="notion",
                target=target.target.model_dump(mode="json"),
                document=_published(target.document, "page-1"),
                sections={
                    item.section_id or "": _published(item, f"page-{n}")
                    for n, item in enumerate(target.sections, 2)
                },
            )
        },
    )


def _plan(drafts: tuple[TargetDraft, ...], state: PublishState) -> PublishPlan:
    return plan_publish(drafts, state, fake_registry(FakeTransport()))


def test_a_first_publish_creates_the_document_and_then_each_split_section() -> None:
    drafts = _drafts()
    (target,) = drafts

    plan = _plan(drafts, PublishState(doc_id=DOC_ID))

    assert plan == PublishPlan(
        (
            TargetPlan(
                TARGET_LABEL,
                target.target,
                (CreateStep(DOCUMENT, target.document), CreateStep(TOOLS, target.sections[0])),
            ),
        )
    )


def test_a_document_in_sync_with_its_last_publish_plans_nothing() -> None:
    drafts = _drafts()

    assert _plan(drafts, _state_of(drafts)).targets[0].steps == ()


def test_one_changed_section_plans_one_section_write_after_the_section_before_it() -> None:
    state = _state_of(_drafts())
    changed = _drafts(blocks=make_garden_blocks(planting="Sow after the last frost."))

    assert _plan(changed, state).targets[0].steps == (
        WriteSectionStep(
            DOCUMENT, "planting", "## Planting\nSow after the last frost.\n", INTRO_KEY, "blocks[2]"
        ),
    )


def test_a_section_title_change_writes_the_title_of_its_own_item() -> None:
    state = _state_of(_drafts())
    (changed,) = _drafts(blocks=make_garden_blocks(tools_title="Garden tools"))

    assert _plan((changed,), state).targets[0].steps == (
        WriteFieldsStep(TOOLS, (TITLE,), changed.sections[0].content),
        WriteSectionStep(
            TOOLS,
            "tools",
            '## Garden tools\n<span color="blue">**api**</span>\n- Spade.\n',
            "page legend",
            "blocks[1]",
        ),
    )


def test_reordered_labels_plan_nothing_and_a_new_label_writes_the_fields() -> None:
    labelled = {"parent_page": NOTION_PAGE_ID, "fields": {"Tags": ["soil", "seeds"]}}
    state = _state_of(_drafts(publish=make_notion_publish(split=["tools"], where=labelled)))
    reordered = _drafts(
        publish=make_notion_publish(
            split=["tools"], where={**labelled, "fields": {"Tags": ["seeds", "soil"]}}
        )
    )
    (relabelled,) = _drafts(
        publish=make_notion_publish(
            split=["tools"], where={**labelled, "fields": {"Tags": ["seeds", "soil", "tools"]}}
        )
    )

    assert (_plan(reordered, state).targets[0].steps, _plan((relabelled,), state).targets[0].steps) == (
        (),
        (
            WriteFieldsStep(DOCUMENT, (FIELDS,), relabelled.document.content),
            WriteFieldsStep(TOOLS, (FIELDS,), relabelled.sections[0].content),
        ),
    )


def test_a_split_section_removed_from_the_document_archives_its_item() -> None:
    state = _state_of(_drafts())
    without_tools = [block for block in make_garden_blocks() if block.get("id") != "tools"]

    assert _plan(_drafts(publish=make_notion_publish(), blocks=without_tools), state).targets[0].steps == (
        ArchiveStep(TOOLS, "page-2"),
    )


def test_writes_come_before_archives_and_removed_sections_come_last() -> None:
    state = _state_of(_drafts())
    (target,) = _drafts(publish=make_notion_publish(), blocks=make_garden_blocks()[1:])
    sections = target.document.content.sections

    assert _plan((target,), state).targets[0].steps == (
        WriteSectionStep(DOCUMENT, "page legend", sections["page legend"], "page header", "badges"),
        WriteSectionStep(DOCUMENT, "tools", sections["tools"], "page legend", "blocks[0]"),
        ArchiveStep(TOOLS, "page-2"),
        RemoveSectionStep(DOCUMENT, INTRO_KEY),
    )


def _plain_texts(*bodies: str) -> list[dict[str, Any]]:
    return [{"type": "text", "body": body} for body in bodies]


def test_a_block_inserted_at_the_top_writes_only_that_block() -> None:
    publish = make_notion_publish()
    state = _state_of(_drafts(publish=publish, blocks=_plain_texts("Water daily.", "Weed weekly.")))
    (target,) = _drafts(
        publish=publish, blocks=_plain_texts("Welcome to the garden.", "Water daily.", "Weed weekly.")
    )

    assert _plan((target,), state).targets[0].steps == (
        WriteSectionStep(DOCUMENT, INTRO_KEY, "Welcome to the garden.\n", "page header", "blocks[0]"),
    )


def test_a_block_deleted_from_the_middle_removes_only_that_block() -> None:
    publish = make_notion_publish()
    state = _state_of(
        _drafts(
            publish=publish, blocks=_plain_texts("Welcome to the garden.", "Water daily.", "Weed weekly.")
        )
    )
    (target,) = _drafts(publish=publish, blocks=_plain_texts("Welcome to the garden.", "Weed weekly."))

    assert _plan((target,), state).targets[0].steps == (RemoveSectionStep(DOCUMENT, "block 355f322b"),)


def test_a_target_removed_from_the_publish_block_archives_its_section_items_then_its_document() -> None:
    old_target = JiraTarget.model_validate(make_jira_target())
    content = ItemContent(title="Garden handbook")
    state = PublishState(
        doc_id=DOC_ID,
        targets={
            OLD_TARGET_LABEL: PublishedTarget(
                service="jira",
                target=old_target.model_dump(mode="json"),
                document=PublishedItem(item_id="PLAN-1", rendered=content, remote=content),
                sections={"tools": PublishedItem(item_id="PLAN-2", rendered=content, remote=content)},
            )
        },
    )
    registry = fake_registry(FakeTransport(), target_types=(NotionTarget, JiraTarget))

    plan = plan_publish(_drafts(), state, registry)

    assert plan.targets[1] == TargetPlan(
        OLD_TARGET_LABEL,
        old_target,
        (
            ArchiveStep(ItemRef(OLD_TARGET_LABEL, "tools"), "PLAN-2"),
            ArchiveStep(ItemRef(OLD_TARGET_LABEL, None), "PLAN-1"),
        ),
    )


def test_a_document_written_into_an_existing_page_creates_into_that_page() -> None:
    drafts = _drafts(publish=make_notion_publish(where={"page": NOTION_PAGE_ID}))
    (target,) = drafts

    assert _plan(drafts, PublishState(doc_id=DOC_ID)).targets[0].steps == (
        CreateStep(DOCUMENT, target.document, NOTION_PAGE_ID),
    )


def test_two_targets_holding_the_same_item_in_the_state_file_are_refused() -> None:
    drafts = _drafts()
    state = _state_of(drafts)
    shared = state.targets[TARGET_LABEL].model_copy(
        update={"sections": {"tools": _published(drafts[0].sections[0], "page-1")}}
    )
    expected = (
        f"the state file lists page-1 as both {TARGET_LABEL}, document and {TARGET_LABEL}, section tools; "
        "two items may not write to one place, so restore the state file"
    )

    with pytest.raises(PublishError, match=f"^{re.escape(expected)}$"):
        _plan(drafts, state.model_copy(update={"targets": {TARGET_LABEL: shared}}))


def test_the_plan_reads_as_creates_updates_archives_and_deletes_with_deletes_last() -> None:
    state = _state_of(_drafts())
    (target,) = _drafts(publish=make_notion_publish(), blocks=make_garden_blocks()[1:])

    assert describe_plan(_plan((target,), state)) == [
        f"{TARGET_LABEL}: 0 to create, 2 to update, 1 to archive, 1 to delete",
        "  update   document: page legend (badges)",
        "  update   document: tools (blocks[0])",
        "  archive  section tools (page-2)",
        f"  DELETE   document: {INTRO_KEY}, removed from the item",
    ]


def test_a_first_publish_reads_as_creates_naming_each_item() -> None:
    assert describe_plan(_plan(_drafts(), PublishState(doc_id=DOC_ID))) == [
        f"{TARGET_LABEL}: 2 to create, 0 to update, 0 to archive, 0 to delete",
        '  create   document "Garden handbook"',
        '  create   section tools "Tools"',
    ]


def test_a_target_with_nothing_to_do_says_so() -> None:
    drafts = _drafts()

    assert describe_plan(_plan(drafts, _state_of(drafts))) == [f"{TARGET_LABEL}: nothing to change"]
