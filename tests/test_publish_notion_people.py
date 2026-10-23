from typing import Any

import pytest

from skaldr.errors import AuthError
from skaldr.publish.content import ItemContent, differing_parts
from skaldr.publish.notion.api import RETRY_ATTEMPTS, NotionApi
from skaldr.publish.notion.people import KnownPeople
from skaldr.publish.transport import AddSection, ContentWrite, NewItem, SectionRequest, Stamp
from skaldr.publish_block import NotionTarget
from tests.factories import NOTION_PAGE_ID, make_notion_target
from tests.factories.notion_factory import PERSON_ID, InMemoryNotion, Scripted, numbered_id

STAMP = Stamp("garden-handbook", None)
STAMP_LINE = 'Published with skaldr from document garden-handbook {color="gray"}'
TARGET = NotionTarget.model_validate(make_notion_target())
STRANGER_ID = "11111111-2222-3333-4444-555555555555"
OTHER_STRANGER_ID = "66666666-7777-8888-9999-000000000000"
EMPTY_ROW = numbered_id(900).replace("-", "")


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
        f"warning: Notion has no user with id {STRANGER_ID}, so the page shows Grace as text instead of a "
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

    assert transport.comparable_draft(draft).sections == read.comparable.sections


def test_a_saved_remote_copy_is_left_as_stored_and_asks_notion_nothing() -> None:
    notion = _notion()
    saved = ItemContent(title="Garden", sections={"intro": f"Owner: {_mention(STRANGER_ID, 'Grace')}\n"})
    remote_now = ItemContent(title="Garden", sections={"intro": f"Owner: {_mention(STRANGER_ID, 'Grace')}\n"})
    transport = notion.transport()

    assert (
        differing_parts(transport.comparable_form(saved), remote_now),
        transport.comparable_form(saved).sections,
        _user_reads(notion),
    ) == ((), saved.sections, [])


def test_creating_into_an_empty_page_writes_an_unknown_person_as_the_label() -> None:
    notion = _notion()
    notion.add_row(EMPTY_ROW, "Blank page", NOTION_PAGE_ID)
    transport = notion.transport()
    raw = transport.read_item(EMPTY_ROW, ItemContent(title="")).raw_sections
    content = ItemContent(title="Garden", sections={"intro": f"Owner: {_mention(STRANGER_ID, 'Grace')}\n"})

    transport.fill_a_page_left_empty(
        EMPTY_ROW, NewItem(TARGET, STAMP, content, into_id=EMPTY_ROW, into_raw_sections=raw)
    )

    assert notion.markdown_of(EMPTY_ROW) == f"Owner: Grace\n{STAMP_LINE}"


def test_a_mention_tag_shown_as_code_is_kept_and_asks_notion_nothing() -> None:
    notion = _notion()
    tag = _mention(STRANGER_ID, "Grace")
    section = f"Write `{tag}` like this:\n```\n{tag}\n```\n``{tag}``\n"

    _, created = _created(notion, {"intro": section})

    assert (notion.markdown_of(created.item_id), _user_reads(notion)) == (f"{section}{STAMP_LINE}", [])


def test_a_label_that_runs_over_two_lines_is_written_whole() -> None:
    notion = _notion()

    two_lines = "Grace\nHopper"

    _, created = _created(notion, {"intro": f"Owner: {_mention(STRANGER_ID, two_lines)}\n"})

    assert notion.markdown_of(created.item_id) == f"Owner: Grace\nHopper\n{STAMP_LINE}"


def test_a_user_read_that_fails_with_a_server_error_is_asked_again_for_the_next_mention() -> None:
    notion = _notion()
    failure = {"object": "error", "code": "internal_server_error", "message": "Try later."}
    notion.scripted = [Scripted(500, failure, path_prefix="/v1/users/")] * RETRY_ATTEMPTS
    mention = _mention(STRANGER_ID, "Grace")

    _, created = _created(notion, {"intro": f"{mention} and {mention}\n"})

    assert (notion.markdown_of(created.item_id), len(_user_reads(notion))) == (
        f"{mention} and Grace\n{STAMP_LINE}",
        RETRY_ATTEMPTS + 1,
    )


class _TokensThatCannotBeRenewed:
    access_token = "access-token"

    def renew(self) -> None:
        raise AuthError("sign in again")


def test_a_sign_in_notion_refuses_while_asking_about_a_person_stops_the_write() -> None:
    notion = _notion()
    refusal = {"object": "error", "code": "unauthorized", "message": "Invalid token."}
    notion.scripted = [Scripted(401, refusal, path_prefix="/v1/users/")]
    people = KnownPeople(
        NotionApi(_TokensThatCannotBeRenewed(), transport=notion.mock(), sleep=lambda _: None)
    )

    with pytest.raises(AuthError, match=r"^sign in again$"):
        people.as_written(_mention(STRANGER_ID, "Grace"))


def test_a_person_notion_fails_to_answer_for_is_left_a_mention() -> None:
    notion = _notion()
    refusal = {"object": "error", "code": "restricted_resource", "message": "No."}
    notion.scripted = [Scripted(403, refusal, path_prefix="/v1/users/")]
    sections = {"intro": f"Owner: {_mention(STRANGER_ID, 'Grace')}\n"}

    _, created = _created(notion, sections)

    assert notion.markdown_of(created.item_id) == f"Owner: {_mention(STRANGER_ID, 'Grace')}\n{STAMP_LINE}"
