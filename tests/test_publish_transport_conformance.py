from collections.abc import Callable
from dataclasses import dataclass, field, replace

import pytest

from skaldr.errors import ItemNotFoundError, WriteRejectedError
from skaldr.publish.content import ItemContent, Part, section_part
from skaldr.publish.jira.description import description_doc, section_blocks, section_text
from skaldr.publish.jira.transport import JiraTransport
from skaldr.publish.transport import (
    AddSection,
    ContentWrite,
    FieldsWrite,
    NewItem,
    Release,
    RemoteItem,
    RemoveSection,
    ReplaceSection,
    SectionRequest,
    Stamp,
    Transport,
    is_unset,
)
from skaldr.publish_block import JiraTarget, NotionTarget, TargetBase
from tests.factories import make_jira_target, make_notion_target
from tests.factories.jira_factory import FakeJira
from tests.factories.publish_factory import DOC_ID, FakeTransport

STAMP = Stamp(DOC_ID, None)
SECTION_STAMP = Stamp(DOC_ID, "tools")
CONTENT = ItemContent(
    title="Garden handbook",
    sections={"intro": "Welcome.\n", "planting": "Sow in spring.\n"},
    fields={"Area": "Shed", "Owner": "Rowan"},
)
NOTION_TARGET = NotionTarget.model_validate(make_notion_target())
JIRA_TARGET = JiraTarget.model_validate(make_jira_target())


@dataclass(frozen=True)
class Instance:
    transport: Transport
    empty_page_id: str | None
    edit_section_by_hand: Callable[[str, str, str], None]


def _as_written(text: str) -> str:
    return text


@dataclass(frozen=True)
class TransportUnderTest:
    make: Callable[[], Instance]
    target: TargetBase
    writes_into_pages: bool
    reports_edits: bool
    spell: Callable[[str], str] = field(default=_as_written)


def _fake_instance(transport: FakeTransport) -> Instance:
    transport.seed("empty-page", "Blank page", None, fields={"Status": None})
    return Instance(transport, "empty-page", transport.edit_section_by_hand)


def _fake() -> Instance:
    return _fake_instance(FakeTransport(strips_trailing_whitespace=True))


def _as_adf(text: str) -> str:
    return section_text([{"type": "paragraph", "content": [{"type": "text", "text": text.strip()}]}])


def _jira() -> Instance:
    jira = FakeJira()
    transport = JiraTransport(jira.client())

    def edit_section_by_hand(item_id: str, key: str, text: str) -> None:
        sections = {**transport.read_item(item_id, ItemContent(title="")).raw_sections, key: text}
        blocks = [block for section in sections.values() for block in section_blocks(section)]
        jira.edit_by_hand(item_id, description=description_doc(blocks))

    return Instance(transport, None, edit_section_by_hand)


TRANSPORTS = [
    pytest.param(
        TransportUnderTest(_fake, NOTION_TARGET, writes_into_pages=True, reports_edits=True),
        id="fake",
    ),
    pytest.param(
        TransportUnderTest(_jira, JIRA_TARGET, writes_into_pages=False, reports_edits=True, spell=_as_adf),
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


def test_section_writes_add_replace_move_and_remove_by_key(under_test: TransportUnderTest) -> None:
    instance, created = _created(under_test)
    transport = instance.transport
    item_id = created.item_id

    def raw() -> dict[str, str]:
        return dict(transport.read_item(item_id, _content(under_test)).raw_sections)

    spade, sow_in_may = under_test.spell("Spade.\n"), under_test.spell("Sow in May.\n")
    transport.write_section(item_id, SectionRequest(AddSection("tools", spade, "intro"), raw()))
    transport.write_section(
        item_id, SectionRequest(ReplaceSection("planting", raw()["planting"], sow_in_may, None), raw())
    )
    transport.write_section(item_id, SectionRequest(RemoveSection("intro", raw()["intro"]), raw()))

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
        transport.write_section(created.item_id, SectionRequest(replace_quoting_old_text, raw))
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
        transport.write_content(created.item_id, ContentWrite(sections, stale))
    assert list(transport.read_item(created.item_id, _content(under_test)).raw_sections.items()) == list(
        created.raw_sections.items()
    )


def test_a_content_write_replaces_every_section_in_order(under_test: TransportUnderTest) -> None:
    instance, created = _created(under_test)
    transport = instance.transport
    sections = _spelled(under_test, {"tools": "Spade.\n", "planting": "Sow in May.\n"})

    transport.write_content(created.item_id, ContentWrite(sections, created.raw_sections))

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


def test_the_marker_a_write_returns_covers_that_write(under_test: TransportUnderTest) -> None:
    instance, created = _created(under_test)
    raw = dict(created.raw_sections)

    written = instance.transport.write_section(
        created.item_id, SectionRequest(AddSection("tools", under_test.spell("Spade.\n"), "planting"), raw)
    )

    assert instance.transport.parts_edited_after(created.item_id, written.marker, _content(under_test)) == ()


def test_a_hand_edit_after_a_marker_is_reported(under_test: TransportUnderTest) -> None:
    if not under_test.reports_edits:
        pytest.skip("this transport reports no edits by marker")
    instance, created = _created(under_test)

    instance.edit_section_by_hand(created.item_id, "planting", under_test.spell("Sow in June.\n"))

    assert instance.transport.parts_edited_after(created.item_id, created.marker, _content(under_test)) == (
        section_part("planting"),
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
        pytest.param(HidesHandEdits, test_a_hand_edit_after_a_marker_is_reported, id="hidden-hand-edits"),
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
    ],
)
def test_each_contract_check_fails_on_a_transport_that_breaks_it(
    mutant: type[FakeTransport], check: Callable[[TransportUnderTest], None]
) -> None:
    with pytest.raises(AssertionError):
        check(_mutant(mutant))
