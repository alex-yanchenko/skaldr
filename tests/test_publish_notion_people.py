from typing import Any

import pytest

from skaldr.publish.content import ItemContent
from skaldr.publish.transport import AddSection, ContentWrite, NewItem, SectionRequest, Stamp
from skaldr.publish_block import NotionTarget
from tests.factories import NOTION_PAGE_ID, make_notion_target
from tests.factories.notion_factory import PERSON_ID, InMemoryNotion, Scripted

STAMP = Stamp("garden-handbook", None)
STAMP_LINE = 'Published with skaldr from document garden-handbook {color="gray"}'
TARGET = NotionTarget.model_validate(make_notion_target())
STRANGER_ID = "11111111-2222-3333-4444-555555555555"
OTHER_STRANGER_ID = "66666666-7777-8888-9999-000000000000"


def _mention(user_id: str, label: str) -> str:
    return f'<mention-user url="user://{user_id}">{label}</mention-user>'


def _notion() -> InMemoryNotion:
    notion = InMemoryNotion()
    notion.add_database(NOTION_PAGE_ID)
    notion.users[PERSON_ID] = "Ada Gardener"
    return notion


def _user_reads(notion: InMemoryNotion) -> list[str]:
    return [request.url.path for request in notion.requests if request.url.path.startswith("/v1/users/")]


def _created(notion: InMemoryNotion, sections: dict[str, str]) -> tuple[Any, Any]:
    transport = notion.transport()
    created = transport.create_item(NewItem(TARGET, STAMP, ItemContent(title="Garden", sections=sections)))
    return transport, created


def test_a_person_notion_knows_stays_a_mention() -> None:
    notion = _notion()
    sections = {"intro": f"Owner: {_mention(PERSON_ID, 'Ada')}\n"}

    _, created = _created(notion, sections)

    assert (notion.markdown_of(created.item_id), _user_reads(notion)) == (
        f"Owner: {_mention(PERSON_ID, 'Ada')}\n{STAMP_LINE}",
        [f"/v1/users/{PERSON_ID}"],
    )


def test_a_person_notion_does_not_know_is_written_as_the_label(capsys: pytest.CaptureFixture[str]) -> None:
    notion = _notion()
    sections = {"intro": f"Owner: {_mention(STRANGER_ID, 'Grace')}\n"}

    _, created = _created(notion, sections)

    assert (notion.markdown_of(created.item_id), _user_reads(notion), capsys.readouterr().err) == (
        f"Owner: Grace\n{STAMP_LINE}",
        [f"/v1/users/{STRANGER_ID}"],
        f"warning: Notion has no user user://{STRANGER_ID}, so the page shows Grace as text instead of a "
        "mention\n",
    )


def test_a_known_and_an_unknown_person_in_one_section_are_told_apart() -> None:
    notion = _notion()
    sections = {"intro": f"{_mention(PERSON_ID, 'Ada')} and {_mention(STRANGER_ID, 'Grace')}\n"}

    _, created = _created(notion, sections)

    assert notion.markdown_of(created.item_id) == (f"{_mention(PERSON_ID, 'Ada')} and Grace\n{STAMP_LINE}")


def test_each_distinct_person_is_looked_up_once_for_a_whole_run(
    capsys: pytest.CaptureFixture[str],
) -> None:
    notion = _notion()
    grace = _mention(STRANGER_ID, "Grace")
    sections = {
        "intro": f"{grace} and {_mention(PERSON_ID, 'Ada')} and {_mention(OTHER_STRANGER_ID, 'Linus')}\n",
        "tools": f"{grace} again\n",
    }
    transport, created = _created(notion, sections)
    read = transport.read_item(created.item_id, created.comparable)

    transport.write_content(created.item_id, ContentWrite({"intro": f"{grace}\n"}, read.raw_sections, STAMP))
    transport.comparable_form(ItemContent(title="Garden", sections={"tools": f"{grace}\n"}))

    assert (_user_reads(notion), capsys.readouterr().err.count("warning:")) == (
        [f"/v1/users/{STRANGER_ID}", f"/v1/users/{PERSON_ID}", f"/v1/users/{OTHER_STRANGER_ID}"],
        2,
    )


def test_a_document_with_no_people_makes_no_user_reads() -> None:
    notion = _notion()

    transport, created = _created(notion, {"intro": "Welcome.\n", "tools": "A <b>spade</b>.\n"})
    transport.comparable_form(ItemContent(title="Garden", sections={"intro": "Welcome.\n"}))

    assert _user_reads(notion) == []
    assert notion.markdown_of(created.item_id) == f"Welcome.\nA <b>spade</b>.\n{STAMP_LINE}"


def test_a_content_write_writes_an_unknown_person_as_the_label() -> None:
    notion = _notion()
    transport, created = _created(notion, {"intro": "Welcome.\n"})
    read = transport.read_item(created.item_id, created.comparable)

    transport.write_content(
        created.item_id,
        ContentWrite({"intro": f"Owner: {_mention(STRANGER_ID, 'Grace')}\n"}, read.raw_sections, STAMP),
    )

    assert notion.markdown_of(created.item_id) == f"Owner: Grace\n{STAMP_LINE}"


def test_a_section_write_writes_an_unknown_person_as_the_label() -> None:
    notion = _notion()
    transport, created = _created(notion, {"intro": "Welcome.\n"})
    read = transport.read_item(created.item_id, created.comparable)

    transport.write_section(
        created.item_id,
        SectionRequest(
            AddSection("tools", f"Owner: {_mention(STRANGER_ID, 'Grace')}\n", "intro"),
            read.raw_sections,
            STAMP,
        ),
    )

    assert notion.markdown_of(created.item_id) == f"Welcome.\nOwner: Grace\n{STAMP_LINE}"


def test_a_draft_with_an_unknown_person_compares_equal_to_the_page_that_shows_the_label() -> None:
    notion = _notion()
    draft = ItemContent(title="Garden", sections={"intro": f"Owner: {_mention(STRANGER_ID, 'Grace')}\n"})
    transport, created = _created(notion, draft.sections)
    read = transport.read_item(created.item_id, draft)

    assert transport.comparable_form(draft).sections == read.comparable.sections


def test_a_person_notion_fails_to_answer_for_is_left_a_mention() -> None:
    notion = _notion()
    refusal = {"object": "error", "code": "restricted_resource", "message": "No."}
    notion.scripted = [Scripted(403, refusal, path_prefix="/v1/users/")]
    sections = {"intro": f"Owner: {_mention(STRANGER_ID, 'Grace')}\n"}

    _, created = _created(notion, sections)

    assert notion.markdown_of(created.item_id) == f"Owner: {_mention(STRANGER_ID, 'Grace')}\n{STAMP_LINE}"
