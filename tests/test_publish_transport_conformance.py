from collections.abc import Callable
from dataclasses import dataclass, field, replace

import pytest

from skaldr.errors import ItemNotFoundError, WriteRejectedError
from skaldr.publish.content import ItemContent, Part, differing_parts, section_part
from skaldr.publish.jira.description import description_doc, section_blocks, section_text
from skaldr.publish.jira.transport import JiraTransport
from skaldr.publish.transport import (
    AddSection,
    ContentWrite,
    FieldsWrite,
    ItemLink,
    LinksWrite,
    NewItem,
    PairedLink,
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
from skaldr.publish_block import JiraTarget, NotionTarget, TargetBase
from tests.factories import NOTION_PAGE_ID, make_jira_target, make_notion_target
from tests.factories.jira_factory import SITE, FakeJira
from tests.factories.notion_factory import InMemoryNotion, numbered_id
from tests.factories.publish_factory import DOC_ID, FakeTransport

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
NOTION_TARGET = NotionTarget.model_validate(make_notion_target())
JIRA_TARGET = JiraTarget.model_validate(make_jira_target())
SEEDLING = "🌱"
SUNFLOWER = "🌻"
COVER_URL = "https://example.com/garden.png"
LOOKING = CONTENT.model_copy(update={"icon": SEEDLING, "cover": COVER_URL})


ISSUE_LINKS = (
    PairedLink("jira", "DEMO-12", f"{SITE}/browse/DEMO-12", "DEMO-12"),
    PairedLink("jira", "OPS-3", f"{SITE}/browse/OPS-3", "OPS-3"),
)
PAGE_LINKS = (
    PairedLink("notion", NOTION_PAGE_ID, f"https://www.notion.so/{NOTION_PAGE_ID}", "Garden handbook"),
    PairedLink("notion", OTHER_PAGE_ID, f"https://www.notion.so/{OTHER_PAGE_ID}", "Kitchen rota"),
)


@dataclass(frozen=True)
class Instance:
    transport: Transport
    empty_page_id: str | None
    edit_section_by_hand: Callable[[str, str, str], None]
    count_writes: Callable[[], int]


def _as_written(text: str) -> str:
    return text


def _fake_link(item_id: str, title: str) -> ItemLink:
    return ItemLink(f"https://items.example.com/{item_id}", title)


@dataclass(frozen=True)
class TransportUnderTest:
    make: Callable[[], Instance]
    target: TargetBase
    writes_into_pages: bool
    reports_edits: bool
    carries_look: bool = True
    spell: Callable[[str], str] = field(default=_as_written)
    form_fixture: ItemContent = COMPARABLE_FORM_IDEMPOTENCE_FIXTURE
    links: tuple[PairedLink, ...] = ISSUE_LINKS
    expected_link: Callable[[str, str], ItemLink] = field(default=_fake_link)


def _fake_instance(transport: FakeTransport) -> Instance:
    transport.seed("empty-page", "Blank page", None, fields={"Status": None})
    return Instance(transport, "empty-page", transport.edit_section_by_hand, lambda: len(transport.writes()))


def _fake() -> Instance:
    return _fake_instance(FakeTransport(strips_trailing_whitespace=True, ignores_span_colors=True))


def _notion() -> Instance:
    notion = InMemoryNotion()
    notion.add_database(NOTION_PAGE_ID)
    empty_page = notion.add_row(numbered_id(900), "Blank page", NOTION_PAGE_ID)

    def edit_section_by_hand(item_id: str, key: str, text: str) -> None:
        notion.edit_by_hand(item_id, CONTENT.sections[key].rstrip("\n"), text.rstrip("\n"))

    return Instance(notion.transport(), empty_page, edit_section_by_hand, lambda: len(notion.writes()))


def _notion_link(item_id: str, title: str) -> ItemLink:
    return ItemLink(f"https://www.notion.so/{item_id.replace('-', '')}", title)


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

    return Instance(transport, None, edit_section_by_hand, count_writes)


def _jira_link(item_id: str, _title: str) -> ItemLink:
    return ItemLink(f"{SITE}/browse/{item_id}", item_id)


TRANSPORTS = [
    pytest.param(
        TransportUnderTest(_fake, NOTION_TARGET, writes_into_pages=True, reports_edits=True),
        id="fake",
    ),
    pytest.param(
        TransportUnderTest(
            _notion, NOTION_TARGET, writes_into_pages=True, reports_edits=False, expected_link=_notion_link
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
        ),
        id="jira",
    ),
]


@pytest.fixture(params=TRANSPORTS)
def under_test(request: pytest.FixtureRequest) -> TransportUnderTest:
    chosen: TransportUnderTest = request.param
    return chosen


def _content(under_test: TransportUnderTest) -> ItemContent:
    sections = {key: under_test.spell(text) for key, text in CONTENT.sections.items()}
    return CONTENT.model_copy(update={"sections": sections})


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
        "Rowan",
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

    transport.write_fields(
        created.item_id,
        FieldsWrite(
            "Garden guide", {"Area": "Orchard"}, CONTENT.title, {"Area": "Shed", "Owner": "Rowan"}, STAMP
        ),
    )
    read = transport.read_item(created.item_id, _content(under_test))

    assert (read.comparable.title, read.comparable.fields.get("Area"), read.stamp) == (
        "Garden guide",
        "Orchard",
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
            created.item_id, FieldsWrite("Garden guide", {}, CONTENT.title, CONTENT.fields, STAMP)
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

    assert (created.item_id, _sections(read), read.comparable.title, read.comparable.fields, read.stamp) == (
        page_id,
        _expected_sections(transport, dict(_content(under_test).sections)),
        CONTENT.title,
        {"Status": None, **CONTENT.fields},
        STAMP,
    )


def test_the_comparable_form_of_a_comparable_form_is_itself(under_test: TransportUnderTest) -> None:
    transport = under_test.make().transport
    once = transport.comparable_form(under_test.form_fixture)

    assert transport.comparable_form(once) == once


def _shown(links: tuple[PairedLink, ...]) -> tuple[ShownLink, ...]:
    return tuple(link.shown for link in links)


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
    request = LinksWrite(STAMP, under_test.links)

    written = transport.write_links(created.item_id, request)
    read = transport.read_links(created.item_id, STAMP)
    writes_before = instance.count_writes()
    again = transport.write_links(created.item_id, request)

    assert (frozenset(written), frozenset(read), frozenset(again), instance.count_writes()) == (
        frozenset(request.shown),
        frozenset(request.shown),
        frozenset(request.shown),
        writes_before,
    )


def test_writing_fewer_links_removes_the_others_and_writing_none_removes_every_link(
    under_test: TransportUnderTest,
) -> None:
    instance, created = _created(under_test)
    transport = instance.transport
    first, _ = under_test.links

    transport.write_links(created.item_id, LinksWrite(STAMP, under_test.links))
    transport.write_links(created.item_id, LinksWrite(STAMP, (first,)))
    fewer = transport.read_links(created.item_id, STAMP)
    transport.write_links(created.item_id, LinksWrite(STAMP, ()))

    assert (fewer, transport.read_links(created.item_id, STAMP)) == ((first.shown,), ())


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

    assert frozenset(transport.read_links(created.item_id, STAMP)) == frozenset(_shown(under_test.links))


def test_a_links_write_for_another_section_of_the_document_is_rejected_and_changes_nothing(
    under_test: TransportUnderTest,
) -> None:
    instance, created = _created(under_test, SECTION_STAMP)
    transport = instance.transport

    with pytest.raises(WriteRejectedError):
        transport.write_links(created.item_id, LinksWrite(STAMP, under_test.links))
    assert (
        transport.read_links(created.item_id, SECTION_STAMP),
        transport.read_item(created.item_id, _content(under_test)).stamp,
    ) == ((), SECTION_STAMP)


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
    def item_link(self, item_id: str, title: str, /) -> ItemLink:  # noqa: ARG002
        return ItemLink(f"https://items.example.com/{title}", title)


class ForgetsLinks(FakeTransport):
    def write_links(self, _item_id: str, request: LinksWrite, /) -> tuple[ShownLink, ...]:
        return request.shown


class RewritesLinksEachTime(FakeTransport):
    def write_links(self, item_id: str, request: LinksWrite, /) -> tuple[ShownLink, ...]:
        self.calls.append(("write_links", item_id))
        return super().write_links(item_id, request)


class KeepsOldLinks(FakeTransport):
    def write_links(self, item_id: str, request: LinksWrite, /) -> tuple[ShownLink, ...]:
        kept = tuple(dict.fromkeys([*self.items[item_id].links, *request.shown]))
        self.items[item_id].links = kept
        return kept


class ReportsLinksAsEdits(FakeTransport):
    def write_links(self, item_id: str, request: LinksWrite, /) -> tuple[ShownLink, ...]:
        self.report_an_edit_without_changing_content(item_id, section_part("intro"))
        return super().write_links(item_id, request)


class LinksBeforeCheckingTheStamp(FakeTransport):
    def write_links(self, item_id: str, request: LinksWrite, /) -> tuple[ShownLink, ...]:
        self.items[item_id].links = request.shown
        return super().write_links(item_id, request)


class DropsLinksOnSectionWrites(FakeTransport):
    def write_section(self, item_id: str, request: SectionRequest, /) -> RemoteItem:
        self.items[item_id].links = ()
        return super().write_section(item_id, request)


def _mutant(transport_type: type[FakeTransport]) -> TransportUnderTest:
    return TransportUnderTest(
        lambda: _fake_instance(transport_type()), NOTION_TARGET, writes_into_pages=True, reports_edits=True
    )


@pytest.mark.parametrize(
    ("mutant", "check"),
    [
        pytest.param(
            ReordersSections,
            test_a_created_item_reads_back_keyed_and_ordered_like_the_content_in_the_services_form,
            id="reordered-sections",
        ),
        pytest.param(
            HidesHandEdits,
            test_a_hand_edit_after_a_marker_is_reported_or_shows_in_the_next_read,
            id="hidden-hand-edits",
        ),
        pytest.param(
            ReadsWhatItLastWrote,
            test_a_hand_edit_after_a_marker_is_reported_or_shows_in_the_next_read,
            id="hand-edits-missing-from-the-read",
        ),
        pytest.param(
            DropsTheStampSection,
            test_the_stamp_carries_the_section_the_item_holds,
            id="stamp-without-section",
        ),
        pytest.param(
            LandsBeforeRejecting,
            test_a_content_write_sent_with_a_stale_layout_is_rejected_and_changes_nothing,
            id="lands-before-rejecting",
        ),
        pytest.param(
            KeepsClearedFields,
            test_a_fields_write_sets_what_changed_and_leaves_a_cleared_field_unset_or_absent,
            id="keeps-cleared-fields",
        ),
        pytest.param(
            KeepsTheCover,
            test_the_icon_and_cover_an_item_is_created_with_read_back_and_a_fields_write_changes_and_clears_them,
            id="keeps-the-cover",
        ),
        pytest.param(
            ClosesEverySectionAgain,
            test_the_comparable_form_of_a_comparable_form_is_itself,
            id="comparable-form-not-idempotent",
        ),
        pytest.param(
            NamesItemsByTitle,
            test_a_link_to_an_item_names_it_by_the_address_the_service_gives_it,
            id="link-by-title",
        ),
        pytest.param(
            ForgetsLinks,
            test_links_written_to_an_item_read_back_and_writing_them_again_sends_nothing,
            id="forgets-links",
        ),
        pytest.param(
            RewritesLinksEachTime,
            test_links_written_to_an_item_read_back_and_writing_them_again_sends_nothing,
            id="rewrites-unchanged-links",
        ),
        pytest.param(
            KeepsOldLinks,
            test_writing_fewer_links_removes_the_others_and_writing_none_removes_every_link,
            id="keeps-old-links",
        ),
        pytest.param(
            ReportsLinksAsEdits,
            test_links_change_neither_the_content_nor_the_stamp_and_never_count_as_an_edit,
            id="links-reported-as-edits",
        ),
        pytest.param(
            DropsLinksOnSectionWrites,
            test_a_section_write_after_links_keeps_them,
            id="section-write-drops-links",
        ),
        pytest.param(
            LinksBeforeCheckingTheStamp,
            test_a_links_write_for_another_section_of_the_document_is_rejected_and_changes_nothing,
            id="links-before-checking-the-stamp",
        ),
    ],
)
def test_each_contract_check_fails_on_a_transport_that_breaks_it(
    mutant: type[FakeTransport], check: Callable[[TransportUnderTest], None]
) -> None:
    with pytest.raises(AssertionError):
        check(_mutant(mutant))
