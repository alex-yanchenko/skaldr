from collections.abc import Callable
from dataclasses import dataclass

import pytest

from skaldr.errors import ItemNotFoundError, WriteRejectedError
from skaldr.publish.content import ItemContent
from skaldr.publish.transport import (
    AddSection,
    ContentWrite,
    FieldsWrite,
    NewItem,
    Release,
    RemoveSection,
    ReplaceSection,
    SectionRequest,
    Stamp,
    Transport,
)
from skaldr.publish_block import NotionTarget, TargetBase
from tests.factories import make_notion_target
from tests.factories.publish_factory import DOC_ID, FakeTransport

STAMP = Stamp(DOC_ID, None)
CONTENT = ItemContent(
    title="Garden handbook",
    sections={"intro": "Welcome.\n", "planting": "Sow in spring.\n"},
    fields={"Area": "Shed", "Owner": "Rowan"},
)


@dataclass(frozen=True)
class TransportUnderTest:
    make: Callable[[], tuple[Transport, str]]
    target: TargetBase


def _fake_with_an_empty_page() -> tuple[Transport, str]:
    transport = FakeTransport(strips_trailing_whitespace=True)
    transport.seed("empty-page", "Blank page", None, fields={"Status": None})
    return transport, "empty-page"


TRANSPORTS = [
    pytest.param(
        TransportUnderTest(_fake_with_an_empty_page, NotionTarget.model_validate(make_notion_target())),
        id="fake",
    )
]


@pytest.fixture(params=TRANSPORTS)
def under_test(request: pytest.FixtureRequest) -> TransportUnderTest:
    chosen: TransportUnderTest = request.param
    return chosen


def _created(under_test: TransportUnderTest) -> tuple[Transport, str]:
    transport, _ = under_test.make()
    return transport, transport.create_item(NewItem(under_test.target, STAMP, CONTENT)).item_id


def test_a_created_item_reads_back_keyed_like_the_content_in_the_services_form(
    under_test: TransportUnderTest,
) -> None:
    transport, item_id = _created(under_test)

    read = transport.read_item(item_id, CONTENT)

    assert (read.comparable, list(read.raw_sections), read.doc_id) == (
        transport.comparable_form(CONTENT),
        ["intro", "planting"],
        DOC_ID,
    )


def test_an_item_the_service_does_not_have_raises_item_not_found(under_test: TransportUnderTest) -> None:
    transport, _ = under_test.make()

    with pytest.raises(ItemNotFoundError):
        transport.read_item("no-such-item", CONTENT)


def test_an_archived_item_reads_as_not_found_and_archiving_again_is_harmless(
    under_test: TransportUnderTest,
) -> None:
    transport, item_id = _created(under_test)

    transport.archive_item(item_id)
    transport.archive_item(item_id)

    with pytest.raises(ItemNotFoundError):
        transport.read_item(item_id, CONTENT)


def test_a_release_clears_the_sections_the_named_fields_and_the_stamp_and_can_be_repeated(
    under_test: TransportUnderTest,
) -> None:
    transport, item_id = _created(under_test)
    raw = transport.read_item(item_id, CONTENT).raw_sections

    transport.release_item(item_id, Release(raw, ("Area",)))
    released = transport.read_item(item_id, CONTENT)
    transport.release_item(item_id, Release(released.raw_sections, ("Area",)))

    assert (released.comparable.sections, released.comparable.fields, released.doc_id) == (
        {},
        {"Owner": "Rowan"},
        None,
    )


def test_section_writes_add_replace_move_and_remove_by_key(under_test: TransportUnderTest) -> None:
    transport, item_id = _created(under_test)

    def raw() -> dict[str, str]:
        return dict(transport.read_item(item_id, CONTENT).raw_sections)

    transport.write_section(item_id, SectionRequest(AddSection("tools", "Spade.\n", "intro"), raw()))
    transport.write_section(
        item_id, SectionRequest(ReplaceSection("planting", raw()["planting"], "Sow in May.\n", None), raw())
    )
    transport.write_section(item_id, SectionRequest(RemoveSection("intro", raw()["intro"]), raw()))

    assert (
        transport.read_item(item_id, CONTENT).comparable.sections
        == transport.comparable_form(
            ItemContent(title="", sections={"planting": "Sow in May.\n", "tools": "Spade.\n"})
        ).sections
    )


def test_a_section_write_quoting_text_the_service_no_longer_holds_is_rejected_and_changes_nothing(
    under_test: TransportUnderTest,
) -> None:
    transport, item_id = _created(under_test)
    raw = dict(transport.read_item(item_id, CONTENT).raw_sections)

    with pytest.raises(WriteRejectedError):
        transport.write_section(
            item_id,
            SectionRequest(ReplaceSection("planting", "Sow in winter.\n", "Sow in May.\n", "intro"), raw),
        )
    assert transport.read_item(item_id, CONTENT).raw_sections == raw


def test_a_content_write_replaces_every_section(under_test: TransportUnderTest) -> None:
    transport, item_id = _created(under_test)
    sections = {"planting": "Sow in May.\n", "tools": "Spade.\n"}

    transport.write_content(
        item_id, ContentWrite(sections, transport.read_item(item_id, CONTENT).raw_sections)
    )

    assert (
        transport.read_item(item_id, CONTENT).comparable.sections
        == transport.comparable_form(ItemContent(title="", sections=sections)).sections
    )


def test_a_fields_write_sets_what_changed_and_clears_only_what_it_names(
    under_test: TransportUnderTest,
) -> None:
    transport, item_id = _created(under_test)

    transport.write_fields(
        item_id,
        FieldsWrite(
            "Garden guide", {"Area": "Orchard"}, CONTENT.title, {"Area": "Shed", "Owner": "Rowan"}, STAMP
        ),
    )
    read = transport.read_item(item_id, CONTENT)

    assert (read.comparable.title, read.comparable.fields, read.doc_id) == (
        "Garden guide",
        {"Area": "Orchard"},
        DOC_ID,
    )


def test_the_marker_a_write_returns_covers_that_write(under_test: TransportUnderTest) -> None:
    transport, item_id = _created(under_test)
    raw = dict(transport.read_item(item_id, CONTENT).raw_sections)

    written = transport.write_section(
        item_id, SectionRequest(AddSection("tools", "Spade.\n", "planting"), raw)
    )

    assert transport.parts_edited_after(item_id, written.marker, CONTENT) == ()


def test_creating_into_an_empty_page_sets_its_title_and_the_requested_fields_and_keeps_the_others(
    under_test: TransportUnderTest,
) -> None:
    transport, page_id = under_test.make()
    raw = transport.read_item(page_id, ItemContent(title="")).raw_sections

    created = transport.create_item(
        NewItem(under_test.target, STAMP, CONTENT, into_id=page_id, into_raw_sections=raw)
    )
    read = transport.read_item(page_id, CONTENT)

    assert (created.item_id, read.comparable, read.doc_id) == (
        page_id,
        transport.comparable_form(CONTENT.model_copy(update={"fields": {"Status": None, **CONTENT.fields}})),
        DOC_ID,
    )
