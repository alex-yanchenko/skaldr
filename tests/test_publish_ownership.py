import re
from pathlib import Path

import pytest

from skaldr.errors import ConnectorError, PublishError
from skaldr.publish import ConnectorRegistry
from skaldr.publish.cli import main
from skaldr.publish.content import ItemContent
from skaldr.publish.engine import Applied, apply_publish, dry_run_publish, prepare_publish
from skaldr.publish.notion.connector import NotionConnector
from skaldr.publish.notion.page_markdown import stamp_line
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
from tests.factories import NOTION_PAGE_ID
from tests.factories.auth_factory import make_notion_credentials, seed_notion
from tests.factories.notion_factory import InMemoryNotion, numbered_id
from tests.factories.publish_factory import (
    DOC_ID,
    DROPPED_AFTER_WRITE,
    TARGET_LABEL,
    FakeTransport,
    fake_registry,
    make_garden_blocks,
    make_notion_publish,
    write_garden_report,
)

TEAMMATE_PAGE = "fedcba9876543210fedcba9876543210"
TEAMMATE_TITLE = "Platform roadmap"
TEAMMATE_TEXT = "Quarterly plan the platform team keeps here."
DOCUMENT_PAGE = numbered_id(1).replace("-", "")
TOOLS_PAGE = numbered_id(2).replace("-", "")
SAVED_SECTION = "## Gone\nWhat skaldr wrote here.\n"


def _notion() -> InMemoryNotion:
    seed_notion(make_notion_credentials())
    notion = InMemoryNotion()
    notion.add_page(NOTION_PAGE_ID, "Team plans")
    notion.add_page(TEAMMATE_PAGE, TEAMMATE_TITLE, TEAMMATE_TEXT)
    return notion


def _notion_registry(notion: InMemoryNotion) -> ConnectorRegistry:
    return ConnectorRegistry([NotionConnector(http=notion.mock(), sleep=lambda _: None)])


def _fake() -> FakeTransport:
    transport = FakeTransport()
    transport.seed(TEAMMATE_PAGE, TEAMMATE_TITLE, None, {"intro": f"{TEAMMATE_TEXT}\n"})
    return transport


def _planted_item(
    retiring: Retirement | None = "archive", origin: ItemOrigin = "created", saved: str = SAVED_SECTION
) -> PublishedItem:
    copy = ItemContent(title="Gone", sections={"gone": saved})
    return PublishedItem(item_id=TEAMMATE_PAGE, origin=origin, rendered=copy, remote=copy, retiring=retiring)


def _plant_a_section(path: Path, registry: ConnectorRegistry, item: PublishedItem) -> None:
    target = prepare_publish(path, registry).plan.targets[0].target.model_dump(mode="json")
    planted = PublishedTarget(service="notion", target=target, sections={"gone": item})
    save_state(state_path_for(path), PublishState(doc_id=DOC_ID, targets={TARGET_LABEL: planted}))


def _plant_a_pending_create(path: Path) -> None:
    pending = PendingCreate(
        target=TARGET_LABEL,
        section_id=None,
        parent_id=None,
        title="Garden handbook",
        created_id=TEAMMATE_PAGE,
    )
    save_state(state_path_for(path), PublishState(doc_id=DOC_ID, pending_creates=[pending]))


def _refusal(path: Path, label: str, verb: str, item_id: str = TEAMMATE_PAGE) -> str:
    return (
        f"{TARGET_LABEL}, {label} ({item_id}) carries no skaldr stamp and holds content that is not what "
        f"skaldr last wrote there, so skaldr will not {verb} it; if it is this document's item, "
        "empty it in Notion and publish again, and if it is not, remove its entry from "
        f"{state_path_for(path)}"
    )


def _pending_refusal(path: Path, item_id: str = TEAMMATE_PAGE) -> str:
    return (
        f"{TARGET_LABEL}, document ({item_id}) carries no skaldr stamp and holds content that is not what "
        "skaldr was creating there, so skaldr will not adopt it; if it is the item skaldr created, empty "
        "it in Notion and publish again, and if it is not, delete its entry from `pending_creates` in "
        f"{state_path_for(path)}"
    )


def test_a_planted_retiring_entry_does_not_trash_an_unstamped_notion_page_that_holds_other_content(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    notion = _notion()
    path = write_garden_report(tmp_path)
    _plant_a_section(path, _notion_registry(notion), _planted_item())
    capsys.readouterr()

    exit_code = main(["publish", str(path), "--apply"], registry=_notion_registry(notion))

    assert (exit_code, capsys.readouterr().err, notion.pages[TEAMMATE_PAGE].in_trash, notion.writes()) == (
        1,
        f"error: {_refusal(path, 'section gone', 'archive')}\n",
        False,
        [],
    )


def test_a_dry_run_says_apply_would_refuse_a_planted_retiring_entry(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    notion = _notion()
    path = write_garden_report(tmp_path)
    _plant_a_section(path, _notion_registry(notion), _planted_item())
    capsys.readouterr()

    exit_code = main(["publish", str(path)], registry=_notion_registry(notion))

    assert (exit_code, capsys.readouterr().err, notion.writes()) == (
        1,
        f"error: --apply would refuse: {_refusal(path, 'section gone', 'archive')}\n",
        [],
    )


def test_a_planted_pending_create_does_not_adopt_an_unstamped_notion_page_that_holds_other_content(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    notion = _notion()
    path = write_garden_report(tmp_path)
    _plant_a_pending_create(path)
    capsys.readouterr()

    exit_code = main(["publish", str(path), "--apply"], registry=_notion_registry(notion))

    assert (exit_code, capsys.readouterr().err, notion.markdown_of(TEAMMATE_PAGE), notion.writes()) == (
        1,
        f"error: {_pending_refusal(path)}\n",
        TEAMMATE_TEXT,
        [],
    )


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
    _plant_a_section(path, fake_registry(transport), _planted_item(retiring, origin))

    with pytest.raises(PublishError, match=f"^{re.escape(_refusal(path, 'section gone', verb))}$"):
        apply_publish(prepare_publish(path, fake_registry(transport)))
    assert (transport.writes(), transport.items[TEAMMATE_PAGE].archived) == ([], False)


def test_a_planted_pending_create_does_not_adopt_an_unstamped_fake_item_that_holds_other_content(
    tmp_path: Path,
) -> None:
    transport = _fake()
    path = write_garden_report(tmp_path)
    _plant_a_pending_create(path)

    with pytest.raises(PublishError, match=f"^{re.escape(_pending_refusal(path))}$"):
        apply_publish(prepare_publish(path, fake_registry(transport)))
    assert (transport.writes(), transport.items[TEAMMATE_PAGE].content.sections) == (
        [],
        {"intro": f"{TEAMMATE_TEXT}\n"},
    )


def test_an_unstamped_item_with_child_pages_this_document_does_not_hold_is_not_archived(
    tmp_path: Path,
) -> None:
    transport = FakeTransport()
    transport.seed(TEAMMATE_PAGE, TEAMMATE_TITLE, None, children=("teammate-child",))
    path = write_garden_report(tmp_path)
    _plant_a_section(path, fake_registry(transport), _planted_item())

    with pytest.raises(PublishError, match=f"^{re.escape(_refusal(path, 'section gone', 'archive'))}$"):
        apply_publish(prepare_publish(path, fake_registry(transport)))
    assert transport.writes() == []


def test_an_empty_unstamped_item_the_state_file_retires_is_archived_as_before(tmp_path: Path) -> None:
    transport = FakeTransport()
    transport.seed(TEAMMATE_PAGE, TEAMMATE_TITLE, None)
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


def test_an_unstamped_item_holding_exactly_what_skaldr_last_wrote_is_archived(tmp_path: Path) -> None:
    transport = FakeTransport()
    transport.seed(TEAMMATE_PAGE, "Gone", None, {"gone": SAVED_SECTION})
    path = write_garden_report(tmp_path)
    _plant_a_section(path, fake_registry(transport), _planted_item())

    apply_publish(prepare_publish(path, fake_registry(transport)))

    assert transport.items[TEAMMATE_PAGE].archived


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
    refusal = _refusal(path, "section tools", "write to", "page-2")

    with pytest.raises(PublishError, match=f"^{re.escape(refusal)}$"):
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


def test_a_notion_page_that_lost_its_stamp_but_holds_what_skaldr_wrote_gets_the_write_and_its_stamp_back(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    notion = _notion()
    path = write_garden_report(tmp_path)
    main(["publish", str(path), "--apply"], registry=_notion_registry(notion))
    stamp = stamp_line(Stamp(DOC_ID, "tools")).rstrip("\n")
    notion.edit_by_hand(TOOLS_PAGE, stamp, "")
    write_garden_report(tmp_path, blocks=make_garden_blocks(tools="Rake."))
    capsys.readouterr()

    exit_code = main(["publish", str(path), "--apply"], registry=_notion_registry(notion))

    markdown = notion.markdown_of(TOOLS_PAGE)
    assert (exit_code, capsys.readouterr().err, "- Rake." in markdown, stamp in markdown) == (
        0,
        "",
        True,
        True,
    )


def test_a_notion_document_page_that_lost_its_stamp_keeps_its_own_child_pages_and_gets_its_stamp_back(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    notion = _notion()
    path = write_garden_report(tmp_path)
    main(["publish", str(path), "--apply"], registry=_notion_registry(notion))
    stamp = stamp_line(Stamp(DOC_ID, None)).rstrip("\n")
    notion.edit_by_hand(DOCUMENT_PAGE, stamp, "")
    write_garden_report(tmp_path, blocks=make_garden_blocks(planting="Sow in May."))
    capsys.readouterr()

    exit_code = main(["publish", str(path), "--apply"], registry=_notion_registry(notion))

    markdown = notion.markdown_of(DOCUMENT_PAGE)
    assert (exit_code, capsys.readouterr().err, "Sow in May." in markdown, stamp in markdown) == (
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
    with pytest.raises(ConnectorError, match=f"^{DROPPED_AFTER_WRITE}$"):
        apply_publish(prepare_publish(path, registry))

    outcome = apply_publish(prepare_publish(path, registry))

    assert (outcome, transport.items["page-1"].stamp) == (
        Applied(("update   document: planting (blocks[2])",)),
        Stamp(DOC_ID, None),
    )


def test_a_dry_run_shows_a_planted_entry_refused_without_writing(tmp_path: Path) -> None:
    transport = _fake()
    path = write_garden_report(tmp_path)
    _plant_a_section(path, fake_registry(transport), _planted_item())

    dry_run = dry_run_publish(prepare_publish(path, fake_registry(transport)))

    assert (dry_run.refusal, transport.writes()) == (_refusal(path, "section gone", "archive"), [])
