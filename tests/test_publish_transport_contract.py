import re
from pathlib import Path
from typing import Any

import pytest

from skaldr.errors import PublishError
from skaldr.publish.connector import WriteGranularity
from skaldr.publish.content import ItemContent
from skaldr.publish.drafts import draft_targets, load_authored
from skaldr.publish.engine import Applied, ApplyOutcome, Refused, apply_publish, prepare_publish
from skaldr.publish.transport import FieldsWrite, ReplaceSection, Stamp
from skaldr.publish_block.target import JsonFields
from tests.factories.publish_factory import (
    DOC_ID,
    INTO_LABEL,
    FakeTransport,
    fake_registry,
    make_garden_blocks,
    make_notion_publish,
    write_garden_report,
)
from tests.factories.report_factory import NOTION_PAGE_ID

SHED: JsonFields = {"Area": "Shed", "Tags": ["soil", "seeds"]}


def _publish(
    path: Path, transport: FakeTransport, *, overwrite: bool = False, writes: WriteGranularity = "section"
) -> ApplyOutcome:
    return apply_publish(prepare_publish(path, fake_registry(transport, writes=writes)), overwrite=overwrite)


def _drafted(path: Path, section_id: str | None = None) -> ItemContent:
    (target,) = draft_targets(load_authored(path), fake_registry(FakeTransport()))
    return next(item.content for item in target.items if item.section_id == section_id)


def _republished(
    tmp_path: Path,
    transport: FakeTransport,
    first: dict[str, Any],
    then: dict[str, Any],
    writes: WriteGranularity = "section",
) -> Path:
    path = write_garden_report(tmp_path, **first)
    _publish(path, transport, writes=writes)
    write_garden_report(tmp_path, **then)
    transport.forget_calls()
    return path


def _with_fields(fields: JsonFields, **report: Any) -> dict[str, Any]:
    return {"publish": make_notion_publish(where={"parent_page": NOTION_PAGE_ID, "fields": fields}), **report}


def test_comment_markers_are_not_an_edit_and_the_write_quotes_the_marked_text(tmp_path: Path) -> None:
    transport = FakeTransport()
    path = _republished(tmp_path, transport, {}, {"blocks": make_garden_blocks(planting="Sow in May.")})
    transport.comment_on("page-1", "planting")

    outcome = _publish(path, transport)

    assert (outcome, transport.writes(), transport.items["page-1"].content) == (
        Applied(("update   document: planting (blocks[2])",)),
        [("write_section", "page-1", "planting")],
        _drafted(path),
    )


def test_a_whole_content_connector_gets_one_content_write_per_item(tmp_path: Path) -> None:
    transport = FakeTransport()
    path = _republished(
        tmp_path,
        transport,
        {},
        {"blocks": make_garden_blocks(intro="Welcome, new members.", planting="Sow in May.")},
        writes="content",
    )

    outcome = _publish(path, transport, writes="content")

    assert (outcome, transport.writes(), transport.items["page-1"].content) == (
        Applied(
            ("update   document: block e976d1ce (blocks[0]), planting (blocks[2]), remove block 2c7116fc",)
        ),
        [("write_content", "page-1")],
        _drafted(path),
    )


def test_a_moved_section_is_written_at_its_new_place(tmp_path: Path) -> None:
    transport = FakeTransport()
    tools, planting = make_garden_blocks()[1:]
    path = _republished(
        tmp_path,
        transport,
        {"publish": make_notion_publish()},
        {"publish": make_notion_publish(), "blocks": [make_garden_blocks()[0], planting, tools]},
    )

    outcome = _publish(path, transport)

    assert (outcome, transport.writes(), list(transport.items["page-1"].raw_sections)) == (
        Applied(("update   document: planting (blocks[1])",)),
        [("write_section", "page-1", "planting")],
        list(_drafted(path).sections),
    )


def test_a_replace_whose_place_differs_from_where_the_section_sits_is_a_move() -> None:
    sections = {"a": "A\n", "b": "B\n", "c": "C\n"}

    moves = [
        ReplaceSection("c", "C\n", "C\n", "a").moves_within(sections),
        ReplaceSection("b", "B\n", "B2\n", "a").moves_within(sections),
        ReplaceSection("a", "A\n", "A\n", None).moves_within(sections),
    ]

    assert moves == [True, False, False]


@pytest.mark.parametrize(
    ("then", "write", "fields"),
    [
        pytest.param(
            _with_fields(SHED, meta={"title": "Garden guide", "subtitle": ["For new members"], "toc": True}),
            ("write_fields", "page-1", "title"),
            SHED,
            id="title",
        ),
        pytest.param(
            _with_fields({**SHED, "Area": "Orchard"}),
            ("write_fields", "page-1", "set Area"),
            {**SHED, "Area": "Orchard"},
            id="changed-field",
        ),
        pytest.param(
            _with_fields({"Area": "Shed"}),
            ("write_fields", "page-1", "clear Tags"),
            {"Area": "Shed"},
            id="removed-field",
        ),
        pytest.param(
            _with_fields({**SHED, "Tags": ["seeds", "soil", "tools"]}),
            ("write_fields", "page-1", "set Tags"),
            {**SHED, "Tags": ["seeds", "soil", "tools"]},
            id="added-label",
        ),
    ],
)
def test_a_fields_write_names_only_what_changed_and_clears_what_was_removed(
    tmp_path: Path, then: dict[str, Any], write: tuple[str, ...], fields: JsonFields
) -> None:
    transport = FakeTransport()
    path = _republished(tmp_path, transport, _with_fields(SHED), then)

    _publish(path, transport)

    assert (transport.writes(), transport.items["page-1"].fields) == ([write], fields)


def test_overwriting_a_field_edit_writes_that_field_back(tmp_path: Path) -> None:
    transport = FakeTransport()
    path = _republished(tmp_path, transport, _with_fields(SHED), _with_fields(SHED))
    transport.edit_fields_by_hand("page-1", {**SHED, "Area": "Barn"})

    refused = _publish(path, transport)
    overwritten = _publish(path, transport, overwrite=True)

    assert (
        type(refused),
        overwritten,
        transport.writes(),
        transport.items["page-1"].fields,
    ) == (
        Refused,
        Applied(("update   document: fields",)),
        [("write_fields", "page-1", "set Area")],
        SHED,
    )


def test_a_field_skaldr_does_not_own_changing_in_the_service_is_not_an_edit(tmp_path: Path) -> None:
    transport = FakeTransport(service_fields={"Board": "Sprint 4"})
    path = _republished(tmp_path, transport, _with_fields(SHED), _with_fields(SHED))
    transport.edit_fields_by_hand("page-1", {**SHED, "Board": "Sprint 5"})

    assert (_publish(path, transport), transport.writes()) == (Applied(()), [])


def test_overwriting_a_field_edit_never_clears_a_field_skaldr_does_not_own(tmp_path: Path) -> None:
    transport = FakeTransport(service_fields={"Board": "Sprint 4"})
    path = _republished(tmp_path, transport, _with_fields(SHED), _with_fields(SHED))
    transport.edit_fields_by_hand("page-1", {**SHED, "Area": "Barn", "Board": "Sprint 5"})

    refused = _publish(path, transport)
    overwritten = _publish(path, transport, overwrite=True)

    assert (type(refused), overwritten, transport.writes(), transport.items["page-1"].fields) == (
        Refused,
        Applied(("update   document: fields",)),
        [("write_fields", "page-1", "set Area")],
        {**SHED, "Board": "Sprint 5"},
    )


def test_overwrite_cannot_bring_back_a_page_written_into_that_is_gone(tmp_path: Path) -> None:
    transport = FakeTransport()
    transport.seed(NOTION_PAGE_ID, "Blank page", None)
    into = {"publish": make_notion_publish(where={"page": NOTION_PAGE_ID})}
    path = _republished(tmp_path, transport, into, into)
    transport.delete_item_by_hand(NOTION_PAGE_ID)
    expected = (
        f"{INTO_LABEL}, document: the page {NOTION_PAGE_ID} the target names is not in Notion; name an "
        "existing empty page, or publish under one with `parent_page` instead"
    )

    with pytest.raises(PublishError, match=f"^{re.escape(expected)}$"):
        _publish(path, transport, overwrite=True)
    assert transport.writes() == []


def test_the_doc_id_stamp_survives_an_override_of_the_labels(tmp_path: Path) -> None:
    transport = FakeTransport()
    labelled = {"parent_page": NOTION_PAGE_ID, "fields": {"labels": ["garden"]}}

    def publish_block(labels: list[str]) -> dict[str, Any]:
        return make_notion_publish(
            split=["tools"], where=labelled, overrides={"tools": {"fields": {"labels": labels}}}
        )

    path = _republished(
        tmp_path, transport, {"publish": publish_block(["shed"])}, {"publish": publish_block(["tools"])}
    )
    created = (transport.items["page-2"].stamp, transport.items["page-2"].fields)

    _publish(path, transport)

    assert (
        created,
        transport.writes(),
        transport.items["page-2"].stamp,
        transport.items["page-2"].fields,
    ) == (
        (Stamp(DOC_ID, "tools"), {"labels": ["shed"]}),
        [("write_fields", "page-2", "set labels")],
        Stamp(DOC_ID, "tools"),
        {"labels": ["tools"]},
    )


def test_the_fields_write_lists_changed_and_cleared_fields_compared_as_sorted_sets() -> None:
    write = FieldsWrite(
        "Tools",
        {"Tags": ["b", "a"], "Area": "Shed", "Owner": "Rowan"},
        "Tools",
        {"Tags": ["a", "b"], "Area": "Barn", "Due": "Friday"},
        Stamp(DOC_ID, "tools"),
    )

    assert (write.changed_fields, write.cleared_fields, write.changes_the_title) == (
        {"Area": "Shed", "Owner": "Rowan"},
        ("Due",),
        False,
    )
