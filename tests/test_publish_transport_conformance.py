import re
from collections.abc import Callable
from dataclasses import dataclass, field, replace

import pytest

from skaldr.errors import ItemNotFoundError, WriteRejectedError
from skaldr.publish.content import ItemContent, Part, differing_parts, section_part
from skaldr.publish.jira.description import description_doc, section_blocks, section_text
from skaldr.publish.jira.transport import STAMP_PROPERTY, JiraTransport
from skaldr.publish.transport import (
    AddSection,
    ContentWrite,
    FieldsWrite,
    ItemLink,
    LinksWrite,
    NewItem,
    Release,
    RemoteItem,
    RemoveSection,
    ReplaceSection,
    SectionRequest,
    ShownLink,
    Stamp,
    Transport,
    is_unset,
)
from skaldr.publish_block import JiraTarget, NotionTarget, SlackTarget, TargetBase
from skaldr.publish_block.target import JsonFields
from tests.factories import NOTION_PAGE_ID, make_jira_target, make_notion_target, make_slack_target
from tests.factories.jira_factory import SITE, FakeJira
from tests.factories.notion_factory import InMemoryNotion, numbered_id
from tests.factories.publish_factory import DOC_ID, FakeTransport
from tests.factories.slack_factory import TEAM_ID, WORKSPACE_URL, InMemorySlack

OTHER_PAGE_ID = "fedcba9876543210fedcba9876543210"
STAMP = Stamp(DOC_ID, None)
SECTION_STAMP = Stamp(DOC_ID, "tools")
CONTENT = ItemContent(
    title="Garden handbook",
    sections={"intro": "Welcome.\n", "planting": "Sow in spring.\n"},
    fields={"Area": "Shed", "Owner": "Rowan"},
)
COMPARABLE_FORM_IDEMPOTENCE_FIXTURE = ItemContent(
    title="Garden handbook",
    sections={
        "intro": '<span color="green">**Welcome.**</span>  \n\n',
        "planting": "- Sow in spring.\n\t- Water daily.\n",
    },
    fields={"Area": "Shed", "Labels": ["soil", "seeds"]},
)
JIRA_COMPARABLE_FORM_IDEMPOTENCE_FIXTURE = ItemContent(
    title="Garden handbook",
    sections={
        "intro": section_text(
            [
                {
                    "type": "paragraph",
                    "attrs": {"localId": "a1"},
                    "content": [
                        {
                            "type": "text",
                            "text": "Welcome.",
                            "marks": [{"type": "strong"}, {"type": "em"}],
                        },
                        {
                            "type": "mention",
                            "attrs": {"id": "5b10a2844c20165700ede21g", "text": "@Rowan", "accessLevel": ""},
                        },
                    ],
                }
            ]
        ),
        "tools": "[]\n",
        "planting": section_text(
            [{"type": "orderedList", "attrs": {"order": 1}, "content": []}, {"type": "rule"}]
        ),
    },
    fields={"Area": "Shed", "labels": ["soil", "seeds"]},
)
SLACK_COMPARABLE_FORM_IDEMPOTENCE_FIXTURE = ItemContent(
    title="Garden handbook",
    sections={
        "intro": "- Sow in spring.\n\n&nbsp;\n\n- [x] Water daily.\n",
        "beds": "| Bed | Crop |\n| --- | :---: |\n| North | ![](@U0EXAMPLE1) |\n",
        "spacer": "&nbsp;\n",
    },
)
NOTION_TARGET = NotionTarget.model_validate(make_notion_target())
SLACK_TARGET = SlackTarget.model_validate(make_slack_target())
JIRA_TARGET = JiraTarget.model_validate(make_jira_target())
SEEDLING = "🌱"
SUNFLOWER = "🌻"
COVER_URL = "https://example.com/garden.png"
LOOKING = CONTENT.model_copy(update={"icon": SEEDLING, "cover": COVER_URL})


def _issue_link(key: str) -> ShownLink:
    return ShownLink(service="jira", item_id=key, url=f"{SITE}/browse/{key}", title=key)


def _page_link(page_id: str, title: str) -> ShownLink:
    return ShownLink(service="notion", item_id=page_id, url=f"https://www.notion.so/{page_id}", title=title)


ISSUE_LINKS = (_issue_link("DEMO-12"), _issue_link("OPS-3"))
PAGE_LINKS = (_page_link(NOTION_PAGE_ID, "Garden handbook"), _page_link(OTHER_PAGE_ID, "Kitchen rota"))
MOVED_ADDRESS = "https://example.com/elsewhere"


@dataclass(frozen=True)
class Instance:
    transport: Transport
    empty_page_id: str | None
    edit_section_by_hand: Callable[[str, str, str], None]
    count_writes: Callable[[], int]
    unstamped_item_id: Callable[[], str]


def _as_written(text: str) -> str:
    return text


def _fake_link(item_id: str, title: str) -> ItemLink:
    return ItemLink(f"https://items.example.com/{item_id}", title)


def _fake_stamp_refusal(item_id: str, stamp: Stamp) -> str:
    return f"{item_id} is not stamped with {stamp.named}"


@dataclass(frozen=True)
class TransportUnderTest:
    make: Callable[[], Instance]
    target: TargetBase
    writes_into_pages: bool
    reports_edits: bool
    carries_look: bool = True
    carries_fields: bool = True
    spell: Callable[[str], str] = field(default=_as_written)
    form_fixture: ItemContent = COMPARABLE_FORM_IDEMPOTENCE_FIXTURE
    links: tuple[ShownLink, ...] = ISSUE_LINKS
    expected_link: Callable[[str, str], ItemLink] = field(default=_fake_link)
    reads_links_with_the_item: bool = True
    stamp_refusal: Callable[[str, Stamp], str] = field(default=_fake_stamp_refusal)


def _fake_instance(transport: FakeTransport) -> Instance:
    transport.seed("empty-page", "Blank page", None, fields={"Status": None})
    return Instance(
        transport,
        "empty-page",
        transport.edit_section_by_hand,
        lambda: len(transport.writes()),
        lambda: "empty-page",
    )


def _fake() -> Instance:
    return _fake_instance(FakeTransport(strips_trailing_whitespace=True, ignores_span_colors=True))


def _notion() -> Instance:
    notion = InMemoryNotion()
    notion.add_database(NOTION_PAGE_ID)
    empty_page = notion.add_row(numbered_id(900), "Blank page", NOTION_PAGE_ID)

    def edit_section_by_hand(item_id: str, key: str, text: str) -> None:
        notion.edit_by_hand(item_id, CONTENT.sections[key].rstrip("\n"), text.rstrip("\n"))

    return Instance(
        notion.transport(), empty_page, edit_section_by_hand, lambda: len(notion.writes()), lambda: empty_page
    )


def _notion_link(item_id: str, title: str) -> ItemLink:
    return ItemLink(f"https://www.notion.so/{item_id.replace('-', '')}", title)


def _notion_stamp_refusal(item_id: str, stamp: Stamp) -> str:
    return f"Notion page {item_id} is not stamped with {stamp.named}"


def _as_adf(text: str) -> str:
    return section_text([{"type": "paragraph", "content": [{"type": "text", "text": text.strip()}]}])


def _jira() -> Instance:
    jira = FakeJira()
    transport = JiraTransport(jira.client())
    outside_reader = JiraTransport(jira.client())

    def edit_section_by_hand(item_id: str, key: str, text: str) -> None:
        sections = {**outside_reader.read_item(item_id, ItemContent(title="")).raw_sections, key: text}
        blocks = [block for section in sections.values() for block in section_blocks(section)]
        jira.edit_by_hand(item_id, description=description_doc(blocks))

    def count_writes() -> int:
        return len([call for call in jira.calls() if call[0] != "GET"])

    def unstamped_item_id() -> str:
        created = transport.create_item(NewItem(JIRA_TARGET, STAMP, ItemContent(title="Blank issue")))
        del jira.issues[created.item_id].properties[STAMP_PROPERTY]
        return created.item_id

    return Instance(transport, None, edit_section_by_hand, count_writes, unstamped_item_id)


def _jira_link(item_id: str, _title: str) -> ItemLink:
    return ItemLink(f"{SITE}/browse/{item_id}", item_id)


def _jira_stamp_refusal(item_id: str, stamp: Stamp) -> str:
    return f"Jira issue {item_id} is not stamped with {stamp.named}"


def _slack() -> Instance:
    slack = InMemorySlack()
    empty_canvas = slack.add_canvas("Blank page")

    def edit_section_by_hand(item_id: str, key: str, text: str) -> None:
        slack.edit_by_hand(item_id, CONTENT.sections[key].rstrip("\n"), text.rstrip("\n"))

    return Instance(
        slack.transport(),
        empty_canvas,
        edit_section_by_hand,
        lambda: len(slack.writes()),
        lambda: slack.add_canvas("Blank canvas", "Welcome.\n"),
    )


def _slack_link(item_id: str, title: str) -> ItemLink:
    return ItemLink(f"{WORKSPACE_URL}docs/{TEAM_ID}/{item_id}", title)


def _slack_stamp_refusal(item_id: str, stamp: Stamp) -> str:
    return f"Slack canvas {item_id} is not stamped with {stamp.named}"


TRANSPORTS = [
    pytest.param(
        TransportUnderTest(_fake, NOTION_TARGET, writes_into_pages=True, reports_edits=True),
        id="fake",
    ),
    pytest.param(
        TransportUnderTest(
            _notion,
            NOTION_TARGET,
            writes_into_pages=True,
            reports_edits=False,
            expected_link=_notion_link,
            stamp_refusal=_notion_stamp_refusal,
        ),
        id="notion",
    ),
    pytest.param(
        TransportUnderTest(
            _jira,
            JIRA_TARGET,
            writes_into_pages=False,
            reports_edits=True,
            carries_look=False,
            spell=_as_adf,
            form_fixture=JIRA_COMPARABLE_FORM_IDEMPOTENCE_FIXTURE,
            links=PAGE_LINKS,
            expected_link=_jira_link,
            reads_links_with_the_item=False,
            stamp_refusal=_jira_stamp_refusal,
        ),
        id="jira",
    ),
    pytest.param(
        TransportUnderTest(
            _slack,
            SLACK_TARGET,
            writes_into_pages=True,
            reports_edits=False,
            carries_look=False,
            carries_fields=False,
            form_fixture=SLACK_COMPARABLE_FORM_IDEMPOTENCE_FIXTURE,
            expected_link=_slack_link,
            stamp_refusal=_slack_stamp_refusal,
        ),
        id="slack",
    ),
]


@pytest.fixture(params=TRANSPORTS)
def under_test(request: pytest.FixtureRequest) -> TransportUnderTest:
    chosen: TransportUnderTest = request.param
    return chosen


def _content(under_test: TransportUnderTest) -> ItemContent:
    sections = {key: under_test.spell(text) for key, text in CONTENT.sections.items()}
    fields = CONTENT.fields if under_test.carries_fields else {}
    return CONTENT.model_copy(update={"sections": sections, "fields": fields})


def _spelled(under_test: TransportUnderTest, sections: dict[str, str]) -> dict[str, str]:
    return {key: under_test.spell(text) for key, text in sections.items()}


def _created(under_test: TransportUnderTest, stamp: Stamp = STAMP) -> tuple[Instance, RemoteItem]:
    instance = under_test.make()
    return instance, instance.transport.create_item(NewItem(under_test.target, stamp, _content(under_test)))


def _sections(read: RemoteItem) -> list[tuple[str, str]]:
    return list(read.comparable.sections.items())


def _expected_sections(transport: Transport, sections: dict[str, str]) -> list[tuple[str, str]]:
    return list(transport.comparable_form(ItemContent(title="", sections=sections)).sections.items())


def test_a_created_item_reads_back_keyed_and_ordered_like_the_content_in_the_services_form(
    under_test: TransportUnderTest,
) -> None:
    instance, created = _created(under_test)
    transport = instance.transport

    read = transport.read_item(created.item_id, _content(under_test))

    assert (_sections(read), list(read.raw_sections), read.comparable.title, read.stamp) == (
        _expected_sections(transport, dict(_content(under_test).sections)),
        ["intro", "planting"],
        CONTENT.title,
        STAMP,
    )


def test_the_stamp_carries_the_section_the_item_holds(under_test: TransportUnderTest) -> None:
    instance, created = _created(under_test, SECTION_STAMP)

    assert instance.transport.read_item(created.item_id, _content(under_test)).stamp == SECTION_STAMP


def test_an_item_the_service_does_not_have_raises_item_not_found(under_test: TransportUnderTest) -> None:
    instance = under_test.make()

    with pytest.raises(ItemNotFoundError):
        instance.transport.read_item("no-such-item", _content(under_test))


def test_an_archived_item_reads_as_not_found_and_archiving_again_is_harmless(
    under_test: TransportUnderTest,
) -> None:
    instance, created = _created(under_test)

    instance.transport.archive_item(created.item_id)
    instance.transport.archive_item(created.item_id)

    with pytest.raises(ItemNotFoundError):
        instance.transport.read_item(created.item_id, _content(under_test))


def test_a_release_clears_the_sections_the_named_fields_and_the_stamp_and_can_be_repeated(
    under_test: TransportUnderTest,
) -> None:
    if not under_test.writes_into_pages:
        pytest.skip("only an item written into is released, and this transport never writes into one")
    instance, created = _created(under_test)
    transport = instance.transport

    transport.release_item(created.item_id, Release(created.raw_sections, ("Area",)))
    released = transport.read_item(created.item_id, _content(under_test))
    transport.release_item(created.item_id, Release(released.raw_sections, ("Area",)))

    assert (_sections(released), released.comparable.fields.get("Owner"), released.stamp) == (
        [],
        _content(under_test).fields.get("Owner"),
        None,
    )
    assert is_unset(released.comparable.fields.get("Area"))


def test_a_release_clears_the_icon_skaldr_set_and_keeps_a_cover_it_did_not(
    under_test: TransportUnderTest,
) -> None:
    if not under_test.carries_look:
        pytest.skip("this transport shows no icon or cover")
    instance = under_test.make()
    transport = instance.transport
    created = transport.create_item(NewItem(under_test.target, STAMP, LOOKING))

    transport.release_item(created.item_id, Release(created.raw_sections, (), clears_icon=True))
    released = transport.read_item(created.item_id, LOOKING)

    assert (released.comparable.icon, released.comparable.cover, released.stamp) == (None, COVER_URL, None)


def test_section_writes_add_replace_move_and_remove_by_key(under_test: TransportUnderTest) -> None:
    instance, created = _created(under_test)
    transport = instance.transport
    item_id = created.item_id

    def raw() -> dict[str, str]:
        return dict(transport.read_item(item_id, _content(under_test)).raw_sections)

    spade, sow_in_may = under_test.spell("Spade.\n"), under_test.spell("Sow in May.\n")
    transport.write_section(item_id, SectionRequest(AddSection("tools", spade, "intro"), raw(), STAMP))
    transport.write_section(
        item_id, SectionRequest(ReplaceSection("planting", raw()["planting"], sow_in_may, None), raw(), STAMP)
    )
    transport.write_section(item_id, SectionRequest(RemoveSection("intro", raw()["intro"]), raw(), STAMP))

    assert _sections(transport.read_item(item_id, _content(under_test))) == _expected_sections(
        transport, {"planting": sow_in_may, "tools": spade}
    )


def test_a_section_write_quoting_text_the_service_no_longer_holds_is_rejected_and_changes_nothing(
    under_test: TransportUnderTest,
) -> None:
    instance, created = _created(under_test)
    transport = instance.transport
    raw = dict(created.raw_sections)
    replace_quoting_old_text = ReplaceSection(
        "planting", under_test.spell("Sow in winter.\n"), under_test.spell("Sow in May.\n"), "intro"
    )

    with pytest.raises(WriteRejectedError):
        transport.write_section(created.item_id, SectionRequest(replace_quoting_old_text, raw, STAMP))
    assert list(transport.read_item(created.item_id, _content(under_test)).raw_sections.items()) == list(
        raw.items()
    )


def test_a_content_write_sent_with_a_stale_layout_is_rejected_and_changes_nothing(
    under_test: TransportUnderTest,
) -> None:
    instance, created = _created(under_test)
    transport = instance.transport
    stale = _spelled(under_test, {"intro": "Welcome.\n"})
    sections = _spelled(under_test, {"tools": "Spade.\n", "intro": "Hello.\n"})

    with pytest.raises(WriteRejectedError):
        transport.write_content(created.item_id, ContentWrite(sections, stale, STAMP))
    assert list(transport.read_item(created.item_id, _content(under_test)).raw_sections.items()) == list(
        created.raw_sections.items()
    )


def test_a_content_write_replaces_every_section_in_order(under_test: TransportUnderTest) -> None:
    instance, created = _created(under_test)
    transport = instance.transport
    sections = _spelled(under_test, {"tools": "Spade.\n", "planting": "Sow in May.\n"})

    transport.write_content(created.item_id, ContentWrite(sections, created.raw_sections, STAMP))

    assert _sections(transport.read_item(created.item_id, _content(under_test))) == _expected_sections(
        transport, sections
    )


def test_a_fields_write_sets_what_changed_and_leaves_a_cleared_field_unset_or_absent(
    under_test: TransportUnderTest,
) -> None:
    instance, created = _created(under_test)
    transport = instance.transport
    fields: JsonFields = {"Area": "Orchard"} if under_test.carries_fields else {}

    transport.write_fields(
        created.item_id,
        FieldsWrite("Garden guide", fields, CONTENT.title, _content(under_test).fields, STAMP),
    )
    read = transport.read_item(created.item_id, _content(under_test))

    assert (read.comparable.title, read.comparable.fields.get("Area"), read.stamp) == (
        "Garden guide",
        fields.get("Area"),
        STAMP,
    )
    assert is_unset(read.comparable.fields.get("Owner"))


def test_a_fields_write_for_another_section_of_the_document_is_rejected_and_changes_nothing(
    under_test: TransportUnderTest,
) -> None:
    instance, created = _created(under_test, SECTION_STAMP)
    transport = instance.transport

    with pytest.raises(WriteRejectedError):
        transport.write_fields(
            created.item_id,
            FieldsWrite("Garden guide", {}, CONTENT.title, _content(under_test).fields, STAMP),
        )
    read = transport.read_item(created.item_id, _content(under_test))

    assert (read.comparable.title, read.comparable.fields, read.stamp) == (
        CONTENT.title,
        created.comparable.fields,
        SECTION_STAMP,
    )


def test_the_icon_and_cover_an_item_is_created_with_read_back_and_a_fields_write_changes_and_clears_them(
    under_test: TransportUnderTest,
) -> None:
    if not under_test.carries_look:
        pytest.skip("this transport shows no icon or cover")
    instance = under_test.make()
    transport = instance.transport
    created = transport.create_item(NewItem(under_test.target, STAMP, LOOKING))

    transport.write_fields(
        created.item_id,
        FieldsWrite(
            LOOKING.title,
            LOOKING.fields,
            LOOKING.title,
            LOOKING.fields,
            STAMP,
            icon=SUNFLOWER,
            cover=None,
            previous_icon=SEEDLING,
            previous_cover=COVER_URL,
        ),
    )
    read = transport.read_item(created.item_id, LOOKING)

    assert (
        (created.comparable.icon, created.comparable.cover),
        (read.comparable.icon, read.comparable.cover),
    ) == (
        (SEEDLING, COVER_URL),
        (SUNFLOWER, None),
    )


def test_the_marker_a_write_returns_covers_that_write(under_test: TransportUnderTest) -> None:
    instance, created = _created(under_test)
    raw = dict(created.raw_sections)

    written = instance.transport.write_section(
        created.item_id,
        SectionRequest(AddSection("tools", under_test.spell("Spade.\n"), "planting"), raw, STAMP),
    )

    assert instance.transport.parts_edited_after(created.item_id, written.marker, _content(under_test)) == ()


def test_a_hand_edit_shows_in_the_comparable_text_a_read_returns(under_test: TransportUnderTest) -> None:
    instance, created = _created(under_test)

    instance.edit_section_by_hand(created.item_id, "planting", under_test.spell("Sow in June.\n"))
    read = instance.transport.read_item(created.item_id, _content(under_test))

    assert _sections(read) == _expected_sections(
        instance.transport, _spelled(under_test, {"intro": "Welcome.\n", "planting": "Sow in June.\n"})
    )


def test_a_hand_edit_after_a_marker_is_reported_or_shows_in_the_next_read(
    under_test: TransportUnderTest,
) -> None:
    instance, created = _created(under_test)

    instance.edit_section_by_hand(created.item_id, "planting", under_test.spell("Sow in June.\n"))
    reported = instance.transport.parts_edited_after(created.item_id, created.marker, _content(under_test))
    read = instance.transport.read_item(created.item_id, _content(under_test))

    planting = (section_part("planting"),)
    assert (reported, differing_parts(created.comparable, read.comparable)) == (
        planting if under_test.reports_edits else (),
        planting,
    )


def test_creating_into_an_empty_page_sets_its_title_and_the_requested_fields_and_keeps_the_others(
    under_test: TransportUnderTest,
) -> None:
    if not under_test.writes_into_pages:
        pytest.skip("this transport cannot write into an existing page")
    instance = under_test.make()
    transport = instance.transport
    page_id = instance.empty_page_id or ""
    raw = transport.read_item(page_id, ItemContent(title="")).raw_sections

    created = transport.create_item(
        NewItem(under_test.target, STAMP, _content(under_test), into_id=page_id, into_raw_sections=raw)
    )
    read = transport.read_item(page_id, _content(under_test))
    fields: JsonFields = {"Status": None, **CONTENT.fields} if under_test.carries_fields else {}

    assert (created.item_id, _sections(read), read.comparable.title, read.comparable.fields, read.stamp) == (
        page_id,
        _expected_sections(transport, dict(_content(under_test).sections)),
        CONTENT.title,
        fields,
        STAMP,
    )


def test_the_comparable_form_of_a_comparable_form_is_itself(under_test: TransportUnderTest) -> None:
    transport = under_test.make().transport
    once = transport.comparable_form(under_test.form_fixture)

    assert transport.comparable_form(once) == once


def _by_item(link: ShownLink) -> str:
    return link.item_id


def test_a_link_to_an_item_names_it_by_the_address_the_service_gives_it(
    under_test: TransportUnderTest,
) -> None:
    instance, created = _created(under_test)

    link = instance.transport.item_link(created.item_id, CONTENT.title)

    assert link == under_test.expected_link(created.item_id, CONTENT.title)


def test_links_written_to_an_item_read_back_and_writing_them_again_sends_nothing(
    under_test: TransportUnderTest,
) -> None:
    instance, created = _created(under_test)
    transport = instance.transport
    links = frozenset(under_test.links)

    written = transport.write_links(created.item_id, LinksWrite(STAMP, under_test.links))
    read = transport.read_links(created.item_id, STAMP)
    writes_before = instance.count_writes()
    again = transport.write_links(created.item_id, LinksWrite(STAMP, under_test.links, read))

    assert (frozenset(written), frozenset(read), frozenset(again), instance.count_writes()) == (
        links,
        links,
        links,
        writes_before,
    )


def test_an_item_read_carries_its_links_or_leaves_them_to_a_links_read(
    under_test: TransportUnderTest,
) -> None:
    instance, created = _created(under_test)
    transport = instance.transport
    transport.write_links(created.item_id, LinksWrite(STAMP, under_test.links))

    read = transport.read_item(created.item_id, _content(under_test))

    carried = None if read.links is None else frozenset(read.links)
    assert carried == (frozenset(under_test.links) if under_test.reads_links_with_the_item else None)


def test_writing_fewer_links_removes_the_others_and_writing_none_removes_every_link(
    under_test: TransportUnderTest,
) -> None:
    instance, created = _created(under_test)
    transport = instance.transport
    first, _ = under_test.links

    transport.write_links(created.item_id, LinksWrite(STAMP, under_test.links))
    transport.write_links(created.item_id, LinksWrite(STAMP, (first,), under_test.links))
    fewer = transport.read_links(created.item_id, STAMP)
    transport.write_links(created.item_id, LinksWrite(STAMP, (), fewer))

    assert (fewer, transport.read_links(created.item_id, STAMP)) == ((first,), ())


def test_a_link_whose_address_changed_is_replaced_in_place_and_not_doubled(
    under_test: TransportUnderTest,
) -> None:
    instance, created = _created(under_test)
    transport = instance.transport
    first, second = under_test.links
    transport.write_links(created.item_id, LinksWrite(STAMP, under_test.links))
    moved = first.model_copy(update={"url": MOVED_ADDRESS})

    transport.write_links(created.item_id, LinksWrite(STAMP, under_test.links, (moved, second)))

    assert sorted(transport.read_links(created.item_id, STAMP), key=_by_item) == sorted(
        under_test.links, key=_by_item
    )


def test_links_change_neither_the_content_nor_the_stamp_and_never_count_as_an_edit(
    under_test: TransportUnderTest,
) -> None:
    instance, created = _created(under_test)
    transport = instance.transport
    before = transport.read_item(created.item_id, _content(under_test))

    transport.write_links(created.item_id, LinksWrite(STAMP, under_test.links))
    after = transport.read_item(created.item_id, _content(under_test))

    assert (
        (after.comparable, dict(after.raw_sections), after.stamp),
        transport.parts_edited_after(created.item_id, created.marker, _content(under_test)),
    ) == ((before.comparable, dict(before.raw_sections), STAMP), ())


def test_a_section_write_after_links_keeps_them(under_test: TransportUnderTest) -> None:
    instance, created = _created(under_test)
    transport = instance.transport
    transport.write_links(created.item_id, LinksWrite(STAMP, under_test.links))
    raw = dict(transport.read_item(created.item_id, _content(under_test)).raw_sections)

    transport.write_section(
        created.item_id,
        SectionRequest(AddSection("tools", under_test.spell("Spade.\n"), "planting"), raw, STAMP),
    )

    assert frozenset(transport.read_links(created.item_id, STAMP)) == frozenset(under_test.links)


def test_a_links_write_for_another_section_of_the_document_is_rejected_and_changes_nothing(
    under_test: TransportUnderTest,
) -> None:
    instance, created = _created(under_test, SECTION_STAMP)
    transport = instance.transport
    refusal = under_test.stamp_refusal(created.item_id, STAMP)

    with pytest.raises(WriteRejectedError, match=f"^{re.escape(refusal)}$"):
        transport.write_links(created.item_id, LinksWrite(STAMP, under_test.links))
    assert (
        transport.read_links(created.item_id, SECTION_STAMP),
        transport.read_item(created.item_id, _content(under_test)).stamp,
    ) == ((), SECTION_STAMP)


def test_links_are_read_only_for_the_stamp_the_item_carries(under_test: TransportUnderTest) -> None:
    instance, created = _created(under_test, SECTION_STAMP)
    transport = instance.transport
    transport.write_links(created.item_id, LinksWrite(SECTION_STAMP, under_test.links))

    assert transport.read_links(created.item_id, STAMP) == ()


def test_a_links_write_to_an_unstamped_item_stamps_it_and_writes_the_links(
    under_test: TransportUnderTest,
) -> None:
    instance = under_test.make()
    transport = instance.transport
    item_id = instance.unstamped_item_id()

    written = transport.write_links(item_id, LinksWrite(STAMP, under_test.links))

    shown = frozenset(under_test.links)
    assert (
        frozenset(written),
        frozenset(transport.read_links(item_id, STAMP)),
        transport.read_item(item_id, ItemContent(title="")).stamp,
    ) == (shown, shown, STAMP)


class ReordersSections(FakeTransport):
    def read_item(self, item_id: str, keyed_like: ItemContent, /) -> RemoteItem:
        read = super().read_item(item_id, keyed_like)
        reordered = dict(reversed(read.comparable.sections.items()))
        return replace(read, comparable=read.comparable.model_copy(update={"sections": reordered}))


class HidesHandEdits(FakeTransport):
    def parts_edited_after(
        self, _item_id: str, _marker: str | None, _keyed_like: ItemContent, /
    ) -> tuple[Part, ...]:
        return ()


class ReadsWhatItLastWrote(FakeTransport):
    def edit_section_by_hand(self, item_id: str, key: str, text: str) -> None:  # noqa: ARG002
        self.report_an_edit_without_changing_content(item_id, section_part(key))


class DropsTheStampSection(FakeTransport):
    def create_item(self, request: NewItem, /) -> RemoteItem:
        return super().create_item(replace(request, stamp=Stamp(request.stamp.doc_id, None)))


class LandsBeforeRejecting(FakeTransport):
    def write_content(self, item_id: str, request: ContentWrite, /) -> RemoteItem:
        first_key, first_text = next(iter(request.sections.items()))
        self.items[item_id].raw_sections[first_key] = first_text
        return super().write_content(item_id, request)


class KeepsClearedFields(FakeTransport):
    def write_fields(self, item_id: str, request: FieldsWrite, /) -> RemoteItem:
        return super().write_fields(item_id, replace(request, previous_fields=dict(request.fields)))


class KeepsTheCover(FakeTransport):
    def write_fields(self, item_id: str, request: FieldsWrite, /) -> RemoteItem:
        return super().write_fields(item_id, replace(request, cover=request.previous_cover))


class ClosesEverySectionAgain(FakeTransport):
    def comparable_form(self, content: ItemContent, /) -> ItemContent:
        formed = super().comparable_form(content)
        closed = {key: text + "\n" for key, text in formed.sections.items()}
        return formed.model_copy(update={"sections": closed})


class NamesItemsByTitle(FakeTransport):
    def item_link(self, _item_id: str, title: str, /) -> ItemLink:
        return ItemLink(f"https://items.example.com/{title}", title)


class ForgetsLinks(FakeTransport):
    def write_links(self, _item_id: str, request: LinksWrite, /) -> tuple[ShownLink, ...]:
        return request.links


class AddsEachSentLinkBesideTheOthers(FakeTransport):
    def write_links(self, item_id: str, request: LinksWrite, /) -> tuple[ShownLink, ...]:
        item = self.items[item_id]
        item.links = (*(link for link in item.links if link not in request.dropped), *request.sent)
        item.stamp = request.stamp
        return item.links


class RewritesLinksEachTime(FakeTransport):
    def write_links(self, item_id: str, request: LinksWrite, /) -> tuple[ShownLink, ...]:
        self.calls.append(("write_links", item_id))
        return super().write_links(item_id, request)


class KeepsOldLinks(FakeTransport):
    def write_links(self, item_id: str, request: LinksWrite, /) -> tuple[ShownLink, ...]:
        kept = tuple(dict.fromkeys([*self.items[item_id].links, *request.links]))
        self.items[item_id].links = kept
        return kept


class ReportsLinksAsEdits(FakeTransport):
    def write_links(self, item_id: str, request: LinksWrite, /) -> tuple[ShownLink, ...]:
        self.report_an_edit_without_changing_content(item_id, section_part("intro"))
        return super().write_links(item_id, request)


class LinksBeforeCheckingTheStamp(FakeTransport):
    def write_links(self, item_id: str, request: LinksWrite, /) -> tuple[ShownLink, ...]:
        self.items[item_id].links = request.links
        return super().write_links(item_id, request)


class ReadsItemsWithoutTheirLinks(FakeTransport):
    def read_item(self, item_id: str, keyed_like: ItemContent, /) -> RemoteItem:
        return replace(super().read_item(item_id, keyed_like), links=())


class ReadsLinksOfAnyStamp(FakeTransport):
    def read_links(self, item_id: str, _stamp: Stamp, /) -> tuple[ShownLink, ...]:
        return self.items[item_id].links


class LinksWithoutStamping(FakeTransport):
    def write_links(self, item_id: str, request: LinksWrite, /) -> tuple[ShownLink, ...]:
        stamp = self.items[item_id].stamp
        written = super().write_links(item_id, request)
        self.items[item_id].stamp = stamp
        return written


class DropsLinksOnSectionWrites(FakeTransport):
    def write_section(self, item_id: str, request: SectionRequest, /) -> RemoteItem:
        self.items[item_id].links = ()
        return super().write_section(item_id, request)


def _mutant(transport_type: type[FakeTransport]) -> TransportUnderTest:
    return TransportUnderTest(
        lambda: _fake_instance(transport_type()), NOTION_TARGET, writes_into_pages=True, reports_edits=True
    )


PLANTING_EDIT = "(Part(kind='section', key='planting'),)"
BOTH_ISSUE_LINKS = f"({ISSUE_LINKS[0]!r}, {ISSUE_LINKS[1]!r})"
LINKS_NOT_READ_BACK = "At index 1 diff: frozenset() != frozenset({"
NO_LINKS_READ = "assert frozenset() == frozenset({"


@pytest.mark.parametrize(
    ("mutant", "check", "failing"),
    [
        pytest.param(
            ReordersSections,
            test_a_created_item_reads_back_keyed_and_ordered_like_the_content_in_the_services_form,
            "At index 0 diff: [('planting', 'Sow in spring.\\n'), ('intro', 'Welcome.\\n')]",
            id="reordered-sections",
        ),
        pytest.param(
            HidesHandEdits,
            test_a_hand_edit_after_a_marker_is_reported_or_shows_in_the_next_read,
            f"At index 0 diff: () != {PLANTING_EDIT}",
            id="hidden-hand-edits",
        ),
        pytest.param(
            ReadsWhatItLastWrote,
            test_a_hand_edit_after_a_marker_is_reported_or_shows_in_the_next_read,
            f"At index 1 diff: () != {PLANTING_EDIT}",
            id="hand-edits-missing-from-the-read",
        ),
        pytest.param(
            DropsTheStampSection,
            test_the_stamp_carries_the_section_the_item_holds,
            "section_id: None != 'tools'",
            id="stamp-without-section",
        ),
        pytest.param(
            LandsBeforeRejecting,
            test_a_content_write_sent_with_a_stale_layout_is_rejected_and_changes_nothing,
            "Left contains one more item: ('tools', 'Spade.\\n')",
            id="lands-before-rejecting",
        ),
        pytest.param(
            KeepsClearedFields,
            test_a_fields_write_sets_what_changed_and_leaves_a_cleared_field_unset_or_absent,
            "At index 1 diff: 'Shed' != 'Orchard'",
            id="keeps-cleared-fields",
        ),
        pytest.param(
            KeepsTheCover,
            test_the_icon_and_cover_an_item_is_created_with_read_back_and_a_fields_write_changes_and_clears_them,
            f"At index 1 diff: ('{SUNFLOWER}', 'https://example.com/garden.png') != ('{SUNFLOWER}', None)",
            id="keeps-the-cover",
        ),
        pytest.param(
            ClosesEverySectionAgain,
            test_the_comparable_form_of_a_comparable_form_is_itself,
            "assert ItemContent(",
            id="comparable-form-not-idempotent",
        ),
        pytest.param(
            NamesItemsByTitle,
            test_a_link_to_an_item_names_it_by_the_address_the_service_gives_it,
            "url: 'https://items.example.com/Garden handbook' != 'https://items.example.com/page-2'",
            id="link-by-title",
        ),
        pytest.param(
            ForgetsLinks,
            test_links_written_to_an_item_read_back_and_writing_them_again_sends_nothing,
            LINKS_NOT_READ_BACK,
            id="forgets-links",
        ),
        pytest.param(
            AddsEachSentLinkBesideTheOthers,
            test_a_link_whose_address_changed_is_replaced_in_place_and_not_doubled,
            f"Left contains one more item: {ISSUE_LINKS[1]!r}",
            id="doubles-a-moved-link",
        ),
        pytest.param(
            RewritesLinksEachTime,
            test_links_written_to_an_item_read_back_and_writing_them_again_sends_nothing,
            "At index 3 diff: 4 != 3",
            id="rewrites-unchanged-links",
        ),
        pytest.param(
            ReadsItemsWithoutTheirLinks,
            test_an_item_read_carries_its_links_or_leaves_them_to_a_links_read,
            NO_LINKS_READ,
            id="items-read-without-their-links",
        ),
        pytest.param(
            KeepsOldLinks,
            test_writing_fewer_links_removes_the_others_and_writing_none_removes_every_link,
            f"At index 0 diff: {BOTH_ISSUE_LINKS} != ({ISSUE_LINKS[0]!r},)",
            id="keeps-old-links",
        ),
        pytest.param(
            ReportsLinksAsEdits,
            test_links_change_neither_the_content_nor_the_stamp_and_never_count_as_an_edit,
            "At index 1 diff: (Part(kind='section', key='intro'),) != ()",
            id="links-reported-as-edits",
        ),
        pytest.param(
            DropsLinksOnSectionWrites,
            test_a_section_write_after_links_keeps_them,
            NO_LINKS_READ,
            id="section-write-drops-links",
        ),
        pytest.param(
            LinksBeforeCheckingTheStamp,
            test_a_links_write_for_another_section_of_the_document_is_rejected_and_changes_nothing,
            f"At index 0 diff: {BOTH_ISSUE_LINKS} != ()",
            id="links-before-checking-the-stamp",
        ),
        pytest.param(
            ReadsLinksOfAnyStamp,
            test_links_are_read_only_for_the_stamp_the_item_carries,
            f"Left contains 2 more items, first extra item: {ISSUE_LINKS[0]!r}",
            id="links-read-for-any-stamp",
        ),
        pytest.param(
            LinksWithoutStamping,
            test_a_links_write_to_an_unstamped_item_stamps_it_and_writes_the_links,
            LINKS_NOT_READ_BACK,
            id="links-without-stamping",
        ),
    ],
)
def test_each_contract_check_fails_on_a_transport_that_breaks_it(
    mutant: type[FakeTransport], check: Callable[[TransportUnderTest], None], failing: str
) -> None:
    with pytest.raises(AssertionError, match=re.escape(failing)):
        check(_mutant(mutant))
