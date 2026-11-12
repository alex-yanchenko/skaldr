import re
from pathlib import Path
from typing import Any

import pytest

from skaldr.auth.store import save_slack
from skaldr.errors import ConnectorError, PublishError, WriteRejectedError
from skaldr.publish import ConnectorRegistry
from skaldr.publish.cli import main
from skaldr.publish.content import ItemContent
from skaldr.publish.engine import Applied, apply_publish, prepare_publish
from skaldr.publish.jira import JiraConnector
from skaldr.publish.jira.description import section_text
from skaldr.publish.notion.page_markdown import stamp_line
from skaldr.publish.slack.connector import SlackConnector
from skaldr.publish.state import (
    ItemOrigin,
    PendingCreate,
    PublishedItem,
    PublishedTarget,
    PublishState,
    Retirement,
    save_state,
    state_path_for,
)
from skaldr.publish.transport import Stamp
from skaldr.services import Service
from tests.factories import NOTION_PAGE_ID, make_slack_target
from tests.factories.auth_factory import (
    make_jira_credentials,
    make_notion_credentials,
    make_slack_credentials,
    seed_notion,
)
from tests.factories.jira_factory import FakeJira
from tests.factories.notion_factory import InMemoryNotion, notion_registry, numbered_id
from tests.factories.publish_factory import (
    DOC_ID,
    DROPPED_AFTER_WRITE,
    INTO_LABEL,
    TARGET_LABEL,
    FakeTransport,
    fake_registry,
    make_garden_blocks,
    make_notion_publish,
    write_garden_report,
)
from tests.factories.slack_factory import InMemorySlack

TEAMMATE_PAGE = "fedcba9876543210fedcba9876543210"
TEAMMATE_TITLE = "Platform roadmap"
TEAMMATE_TEXT = "Quarterly plan the platform team keeps here."
DOCUMENT_PAGE = numbered_id(1).replace("-", "")
TOOLS_PAGE = numbered_id(2).replace("-", "")
SAVED_TITLE = "Gone"
SAVED_SECTION = "## Gone\nWhat skaldr wrote here.\n"
JIRA_LABEL = "jira project DEMO under no parent issue"
SAVED_JIRA_SECTION = section_text(
    [{"type": "paragraph", "content": [{"type": "text", "text": "What skaldr wrote."}]}]
)
SLACK_LABEL = "slack canvases"
NOT_STARTED = {"id": "not-started", "name": "Not started", "color": "default"}


def _notion() -> InMemoryNotion:
    seed_notion(make_notion_credentials())
    notion = InMemoryNotion()
    notion.add_page(NOTION_PAGE_ID, "Team plans")
    notion.add_page(TEAMMATE_PAGE, TEAMMATE_TITLE, TEAMMATE_TEXT)
    return notion


def _notion_database(schema: dict[str, str] | None = None) -> InMemoryNotion:
    seed_notion(make_notion_credentials())
    notion = InMemoryNotion()
    notion.add_database(NOTION_PAGE_ID, schema)
    return notion


def _fake() -> FakeTransport:
    transport = FakeTransport()
    transport.seed(TEAMMATE_PAGE, TEAMMATE_TITLE, None, {"intro": f"{TEAMMATE_TEXT}\n"})
    return transport


def _jira_registry(jira: FakeJira) -> ConnectorRegistry:
    connector = JiraConnector(
        sign_in=lambda _site: make_jira_credentials(),
        http_transport=jira.transport(),
        sleep=jira.sleeps.append,
    )
    return ConnectorRegistry([connector])


def _slack_registry(slack: InMemorySlack) -> ConnectorRegistry:
    save_slack(make_slack_credentials())
    return ConnectorRegistry([SlackConnector(http=slack.mock(), sleep=lambda _: None)])


def _planted_item(
    item_id: str = TEAMMATE_PAGE,
    retiring: Retirement | None = "archive",
    origin: ItemOrigin = "created",
    saved: str = SAVED_SECTION,
) -> PublishedItem:
    copy = ItemContent(title=SAVED_TITLE, sections={"gone": saved})
    return PublishedItem(item_id=item_id, origin=origin, rendered=copy, remote=copy, retiring=retiring)


def _plant_a_section(
    path: Path,
    registry: ConnectorRegistry,
    item: PublishedItem,
    label: str = TARGET_LABEL,
    service: Service = "notion",
) -> None:
    target = prepare_publish(path, registry).plan.targets[0].target.model_dump(mode="json")
    planted = PublishedTarget(service=service, target=target, sections={"gone": item})
    save_state(state_path_for(path), PublishState(doc_id=DOC_ID, targets={label: planted}))


def _plant_a_pending_create(path: Path) -> None:
    pending = PendingCreate(
        target=TARGET_LABEL,
        section_id=None,
        parent_id=None,
        title="Garden handbook",
        created_id=TEAMMATE_PAGE,
    )
    save_state(state_path_for(path), PublishState(doc_id=DOC_ID, pending_creates=[pending]))


def _refusal(
    path: Path,
    verb: str,
    parts: str,
    *,
    item: str = f"{TARGET_LABEL}, section gone ({TEAMMATE_PAGE})",
    service: str = "Notion",
) -> str:
    return (
        f"{item} carries no skaldr stamp and holds content that is not what skaldr last wrote there "
        f"({parts}), so skaldr will not {verb} it. If it is this document's item, put its stamp back, or "
        f"copy anything worth keeping into the YAML and then empty it in {service}, and publish again; if it "
        f"is not, remove its entry from {state_path_for(path)}"
    )


def _pending_refusal(path: Path, parts: str) -> str:
    return (
        f"{TARGET_LABEL}, document ({TEAMMATE_PAGE}) carries no skaldr stamp and holds content that is not "
        f"what skaldr was creating there ({parts}), so skaldr will not adopt it; if it is the item skaldr "
        "created, empty it in Notion and publish again, and if it is not, delete its entry from "
        f"`pending_creates` in {state_path_for(path)}"
    )


def _exactly(message: str) -> str:
    return f"^{re.escape(message)}$"


@pytest.mark.parametrize("apply", [pytest.param(["--apply"], id="apply"), pytest.param([], id="dry-run")])
def test_a_planted_retiring_entry_does_not_trash_an_unstamped_notion_page_that_holds_other_content(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], apply: list[str]
) -> None:
    notion = _notion()
    path = write_garden_report(tmp_path)
    _plant_a_section(path, notion_registry(notion), _planted_item())
    capsys.readouterr()

    exit_code = main(["publish", str(path), *apply], registry=notion_registry(notion))

    prefix = "" if apply else "--apply would refuse: "
    refusal = _refusal(path, "archive", "the title, section gone")
    assert (exit_code, capsys.readouterr().err, notion.pages[TEAMMATE_PAGE].in_trash, notion.writes()) == (
        1,
        f"error: {prefix}{refusal}\n",
        False,
        [],
    )


def test_a_planted_pending_create_does_not_adopt_an_unstamped_notion_page_that_holds_other_content(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    notion = _notion()
    path = write_garden_report(tmp_path)
    _plant_a_pending_create(path)
    capsys.readouterr()

    exit_code = main(["publish", str(path), "--apply"], registry=notion_registry(notion))

    assert (exit_code, capsys.readouterr().err, notion.markdown_of(TEAMMATE_PAGE), notion.writes()) == (
        1,
        f"error: {_pending_refusal(path, f'the title, section {_UNKEYED}')}\n",
        TEAMMATE_TEXT,
        [],
    )


_UNKEYED = "content skaldr did not publish"


@pytest.mark.parametrize(
    ("retiring", "origin", "verb"),
    [
        pytest.param("archive", "created", "archive", id="archive"),
        pytest.param("release", "adopted", "release", id="release"),
        pytest.param(None, "created", "archive", id="removed-from-the-yaml"),
    ],
)
def test_a_planted_section_entry_does_not_retire_an_unstamped_fake_item_that_holds_other_content(
    tmp_path: Path, retiring: Retirement | None, origin: ItemOrigin, verb: str
) -> None:
    transport = _fake()
    path = write_garden_report(tmp_path)
    _plant_a_section(path, fake_registry(transport), _planted_item(retiring=retiring, origin=origin))

    with pytest.raises(PublishError, match=_exactly(_refusal(path, verb, "the title, section intro"))):
        apply_publish(prepare_publish(path, fake_registry(transport)))
    assert (transport.writes(), transport.items[TEAMMATE_PAGE].archived) == ([], False)


@pytest.mark.parametrize(
    ("title", "sections", "fields", "parts"),
    [
        pytest.param(
            TEAMMATE_TITLE, {"intro": f"{TEAMMATE_TEXT}\n"}, {}, "the title, section intro", id="text"
        ),
        pytest.param(TEAMMATE_TITLE, {}, {}, "the title", id="empty-body-with-a-title"),
        pytest.param(
            "Garden handbook", {}, {"Owner": "Rowan"}, "property Owner", id="empty-body-with-a-property"
        ),
    ],
)
def test_a_planted_pending_create_does_not_adopt_or_fill_an_unstamped_fake_item_skaldr_did_not_create(
    tmp_path: Path, title: str, sections: dict[str, str], fields: dict[str, Any], parts: str
) -> None:
    transport = FakeTransport()
    transport.seed(TEAMMATE_PAGE, title, None, sections, fields=fields)
    path = write_garden_report(tmp_path)
    _plant_a_pending_create(path)

    with pytest.raises(PublishError, match=_exactly(_pending_refusal(path, parts))):
        apply_publish(prepare_publish(path, fake_registry(transport)))
    assert (transport.writes(), transport.items[TEAMMATE_PAGE].content) == (
        [],
        ItemContent(title=title, sections=sections, fields=fields),
    )


def test_an_unstamped_item_with_child_pages_this_document_does_not_hold_is_not_archived(
    tmp_path: Path,
) -> None:
    transport = FakeTransport()
    transport.seed(TEAMMATE_PAGE, SAVED_TITLE, None, children=("teammate-child",))
    path = write_garden_report(tmp_path)
    _plant_a_section(path, fake_registry(transport), _planted_item())

    with pytest.raises(PublishError, match=_exactly(_refusal(path, "archive", "child page teammate-child"))):
        apply_publish(prepare_publish(path, fake_registry(transport)))
    assert transport.writes() == []


def test_an_empty_unstamped_item_with_a_title_skaldr_did_not_write_is_not_archived(tmp_path: Path) -> None:
    transport = FakeTransport()
    transport.seed(TEAMMATE_PAGE, TEAMMATE_TITLE, None)
    path = write_garden_report(tmp_path)
    _plant_a_section(path, fake_registry(transport), _planted_item())

    with pytest.raises(PublishError, match=_exactly(_refusal(path, "archive", "the title"))):
        apply_publish(prepare_publish(path, fake_registry(transport)))
    assert transport.writes() == []


@pytest.mark.parametrize(
    "sections",
    [pytest.param({}, id="empty"), pytest.param({"gone": SAVED_SECTION}, id="holding-the-saved-copy")],
)
def test_an_unstamped_item_holding_nothing_but_what_skaldr_last_wrote_is_archived(
    tmp_path: Path, sections: dict[str, str]
) -> None:
    transport = FakeTransport()
    transport.seed(TEAMMATE_PAGE, SAVED_TITLE, None, sections)
    path = write_garden_report(tmp_path)
    _plant_a_section(path, fake_registry(transport), _planted_item())

    outcome = apply_publish(prepare_publish(path, fake_registry(transport)))

    assert (outcome, transport.writes()) == (
        Applied(
            (
                'create   document "Garden handbook"',
                'create   section tools "Tools"',
                f"archive  section gone ({TEAMMATE_PAGE})",
            )
        ),
        [
            ("create", "Garden handbook", "", ""),
            ("create", "Tools", "page-2", ""),
            ("archive", TEAMMATE_PAGE),
        ],
    )


def test_a_planted_entry_does_not_close_an_unstamped_jira_issue_with_a_summary_and_an_empty_description(
    tmp_path: Path,
) -> None:
    jira = FakeJira()
    jira.seed("DEMO-9", summary="Platform roadmap", labels=["platform"], priority={"name": "High"})
    publish = {
        "doc_id": DOC_ID,
        "targets": [{"to": "jira", "where": {"project": "DEMO", "issue_type": "Task"}}],
    }
    path = write_garden_report(tmp_path, publish=publish)
    registry = _jira_registry(jira)
    _plant_a_section(path, registry, _planted_item("DEMO-9", saved=SAVED_JIRA_SECTION), JIRA_LABEL, "jira")
    refusal = _refusal(
        path, "archive", "the title", item=f"{JIRA_LABEL}, section gone (DEMO-9)", service="Jira"
    )

    with pytest.raises(PublishError, match=_exactly(refusal)):
        apply_publish(prepare_publish(path, registry))
    assert [call for call in jira.calls() if call[0] != "GET"] == []


def test_a_planted_entry_does_not_trash_a_notion_database_row_whose_content_is_in_its_properties(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    notion = _notion_database()
    notion.add_row(TEAMMATE_PAGE, SAVED_TITLE, NOTION_PAGE_ID, Owner="Rowan")
    path = write_garden_report(tmp_path)
    _plant_a_section(path, notion_registry(notion), _planted_item())
    capsys.readouterr()

    exit_code = main(["publish", str(path), "--apply"], registry=notion_registry(notion))

    assert (exit_code, capsys.readouterr().err, notion.pages[TEAMMATE_PAGE].in_trash, notion.writes()) == (
        1,
        f"error: {_refusal(path, 'archive', 'property Owner')}\n",
        False,
        [],
    )


def test_a_planted_entry_does_not_archive_an_unstamped_slack_canvas_that_holds_other_content(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    slack = InMemorySlack()
    canvas = slack.add_canvas(TEAMMATE_TITLE, f"{TEAMMATE_TEXT}\n")
    path = write_garden_report(tmp_path, publish={"doc_id": DOC_ID, "targets": [make_slack_target()]})
    registry = _slack_registry(slack)
    _plant_a_section(path, registry, _planted_item(canvas), SLACK_LABEL, "slack")
    capsys.readouterr()

    exit_code = main(["publish", str(path), "--apply"], registry=registry)

    item = f"{SLACK_LABEL}, section gone ({canvas})"
    refusal = _refusal(path, "archive", "the title, section gone", item=item, service="Slack")
    assert (exit_code, capsys.readouterr().err, slack.canvases[canvas].title) == (
        1,
        f"error: {refusal}\n",
        TEAMMATE_TITLE,
    )


def test_overwrite_does_not_write_over_an_unstamped_item_whose_content_skaldr_did_not_write(
    tmp_path: Path,
) -> None:
    transport = FakeTransport()
    path = write_garden_report(tmp_path)
    apply_publish(prepare_publish(path, fake_registry(transport)))
    transport.stamp_by_hand("page-2", None)
    transport.items["page-2"].raw_sections = {"teammate": f"{TEAMMATE_TEXT}\n"}
    write_garden_report(tmp_path, blocks=make_garden_blocks(tools="Rake."))
    transport.forget_calls()
    refusal = _refusal(path, "write to", "section teammate", item=f"{TARGET_LABEL}, section tools (page-2)")

    with pytest.raises(PublishError, match=_exactly(refusal)):
        apply_publish(prepare_publish(path, fake_registry(transport)), overwrite=True)
    assert transport.writes() == []


def test_a_fake_item_that_lost_its_stamp_but_holds_what_skaldr_wrote_gets_the_write_and_its_stamp_back(
    tmp_path: Path,
) -> None:
    transport = FakeTransport()
    path = write_garden_report(tmp_path)
    apply_publish(prepare_publish(path, fake_registry(transport)))
    transport.stamp_by_hand("page-2", None)
    write_garden_report(tmp_path, blocks=make_garden_blocks(tools="Rake."))

    outcome = apply_publish(prepare_publish(path, fake_registry(transport)))

    assert (outcome, transport.items["page-2"].stamp) == (
        Applied(("update   section tools: tools (blocks[1])",)),
        Stamp(DOC_ID, "tools"),
    )


@pytest.mark.parametrize(
    ("page", "stamp", "blocks", "written"),
    [
        pytest.param(
            TOOLS_PAGE, Stamp(DOC_ID, "tools"), make_garden_blocks(tools="Rake."), "- Rake.", id="split-page"
        ),
        pytest.param(
            DOCUMENT_PAGE,
            Stamp(DOC_ID, None),
            make_garden_blocks(planting="Sow in May."),
            "Sow in May.",
            id="document-page-with-its-own-child-pages",
        ),
    ],
)
def test_a_notion_page_that_lost_its_stamp_but_holds_what_skaldr_wrote_gets_the_write_and_its_stamp_back(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    page: str,
    stamp: Stamp,
    blocks: list[dict[str, Any]],
    written: str,
) -> None:
    notion = _notion()
    path = write_garden_report(tmp_path)
    main(["publish", str(path), "--apply"], registry=notion_registry(notion))
    line = stamp_line(stamp).rstrip("\n")
    notion.edit_by_hand(page, line, "")
    write_garden_report(tmp_path, blocks=blocks)
    capsys.readouterr()

    exit_code = main(["publish", str(path), "--apply"], registry=notion_registry(notion))

    markdown = notion.markdown_of(page)
    assert (exit_code, capsys.readouterr().err, written in markdown, line in markdown) == (0, "", True, True)


def test_a_database_row_skaldr_made_that_lost_its_stamp_gets_it_back_whatever_status_notion_set_on_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    notion = _notion_database({"Name": "title", "Stage": "status"})
    path = write_garden_report(tmp_path)
    main(["publish", str(path), "--apply"], registry=notion_registry(notion))
    notion.pages[TOOLS_PAGE].properties["Stage"] = ("status", NOT_STARTED)
    line = stamp_line(Stamp(DOC_ID, "tools")).rstrip("\n")
    notion.edit_by_hand(TOOLS_PAGE, line, "")
    write_garden_report(tmp_path, blocks=make_garden_blocks(tools="Rake."))
    capsys.readouterr()

    exit_code = main(["publish", str(path), "--apply"], registry=notion_registry(notion))

    markdown = notion.markdown_of(TOOLS_PAGE)
    assert (exit_code, capsys.readouterr().err, "- Rake." in markdown, line in markdown) == (
        0,
        "",
        True,
        True,
    )


def test_a_write_that_partly_landed_on_an_item_that_lost_its_stamp_is_finished_and_stamps_it(
    tmp_path: Path,
) -> None:
    transport = FakeTransport()
    whole = make_notion_publish()
    path = write_garden_report(tmp_path, publish=whole)
    registry = fake_registry(transport, writes="content")
    apply_publish(prepare_publish(path, registry))
    transport.stamp_by_hand("page-1", None)
    write_garden_report(
        tmp_path, publish=whole, blocks=make_garden_blocks(tools="Rake.", planting="Sow in May.")
    )
    transport.land_only_the_first_section_of_the_next_content_write()
    with pytest.raises(ConnectorError, match=_exactly(DROPPED_AFTER_WRITE)):
        apply_publish(prepare_publish(path, registry))

    outcome = apply_publish(prepare_publish(path, registry))

    assert (outcome, transport.items["page-1"].stamp) == (
        Applied(("update   document: planting (blocks[2])",)),
        Stamp(DOC_ID, None),
    )


def test_an_item_that_loses_its_stamp_and_gains_text_during_the_run_is_not_written_to(tmp_path: Path) -> None:
    transport = FakeTransport()
    path = write_garden_report(tmp_path)
    apply_publish(prepare_publish(path, fake_registry(transport)))
    write_garden_report(tmp_path, blocks=make_garden_blocks(tools="Rake.", planting="Sow in May."))
    transport.forget_calls()
    transport.unstamp_and_edit_by_hand_during_the_next_write("page-2", "teammate", f"{TEAMMATE_TEXT}\n")
    refusal = (
        "page-2 carries no skaldr stamp and holds content skaldr did not write (section teammate), so skaldr "
        "will not write to it"
    )

    with pytest.raises(WriteRejectedError, match=_exactly(refusal)):
        apply_publish(prepare_publish(path, fake_registry(transport)))
    assert transport.writes() == [("write_section", "page-1", "planting")]


def test_a_named_page_holding_a_property_the_document_sets_to_another_value_is_not_written_into(
    tmp_path: Path,
) -> None:
    transport = FakeTransport()
    transport.seed(NOTION_PAGE_ID, "Blank page", None, fields={"Owner": "Rowan"})
    path = write_garden_report(
        tmp_path, publish=make_notion_publish(where={"page": NOTION_PAGE_ID, "fields": {"Owner": "Ash"}})
    )
    refusal = (
        f"{INTO_LABEL}, document: {NOTION_PAGE_ID} already holds content and carries no skaldr stamp, so "
        "skaldr will not write into it; empty the page, or publish under it with `parent_page` instead"
    )

    with pytest.raises(PublishError, match=_exactly(refusal)):
        apply_publish(prepare_publish(path, fake_registry(transport)))
    assert transport.writes() == []


def test_a_named_page_already_holding_the_property_value_the_document_sets_is_written_into(
    tmp_path: Path,
) -> None:
    transport = FakeTransport()
    transport.seed(NOTION_PAGE_ID, "Blank page", None, fields={"Owner": "Ash"})
    path = write_garden_report(
        tmp_path, publish=make_notion_publish(where={"page": NOTION_PAGE_ID, "fields": {"Owner": "Ash"}})
    )

    outcome = apply_publish(prepare_publish(path, fake_registry(transport)))

    assert (outcome, transport.items[NOTION_PAGE_ID].stamp) == (
        Applied((f'create   document "Garden handbook" into {NOTION_PAGE_ID}',)),
        Stamp(DOC_ID, None),
    )
