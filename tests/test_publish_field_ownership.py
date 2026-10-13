from pathlib import Path
from typing import Any

import pytest

from skaldr.errors import ConnectorError
from skaldr.publish.engine import Applied, ApplyOutcome, apply_publish, prepare_publish
from skaldr.publish.state import load_state, state_path_for
from skaldr.publish_block.target import JsonFields
from tests.factories.publish_factory import (
    DOC_ID,
    DROPPED_AFTER_WRITE,
    INTO_LABEL,
    TARGET_LABEL,
    FakeTransport,
    fake_registry,
    make_notion_publish,
    write_garden_report,
)
from tests.factories.report_factory import NOTION_PAGE_ID


def _publish(path: Path, transport: FakeTransport) -> ApplyOutcome:
    return apply_publish(prepare_publish(path, fake_registry(transport)))


def _with_fields(fields: JsonFields) -> dict[str, Any]:
    return {"publish": make_notion_publish(where={"parent_page": NOTION_PAGE_ID, "fields": fields})}


def test_adding_a_field_the_service_already_holds_is_not_a_remote_edit(tmp_path: Path) -> None:
    transport = FakeTransport(service_fields={"Status": "Open"})
    path = write_garden_report(tmp_path, **_with_fields({"Area": "Shed"}))
    _publish(path, transport)
    write_garden_report(tmp_path, **_with_fields({"Area": "Shed", "Status": "Open"}))
    transport.forget_calls()

    outcome = _publish(path, transport)

    assert (outcome, transport.writes(), transport.items["page-1"].fields) == (
        Applied(("update   document: fields",)),
        [("write_fields", "page-1")],
        {"Status": "Open", "Area": "Shed"},
    )


def test_after_a_write_skaldr_owns_only_the_fields_it_rendered(tmp_path: Path) -> None:
    transport = FakeTransport(reads_cleared_fields_as_null=True)
    path = write_garden_report(tmp_path, **_with_fields({"Area": "Shed", "Owner": "Rowan"}))
    _publish(path, transport)
    write_garden_report(tmp_path, **_with_fields({"Area": "Shed"}))
    _publish(path, transport)

    document = load_state(state_path_for(path), DOC_ID).targets[TARGET_LABEL].document

    assert (document and document.remote.fields, transport.items["page-1"].fields) == (
        {"Area": "Shed"},
        {"Area": "Shed", "Owner": None},
    )


def test_an_interrupted_fields_write_whose_empty_value_the_service_dropped_is_recognised(
    tmp_path: Path,
) -> None:
    transport = FakeTransport(drops_unset_fields=True)
    path = write_garden_report(tmp_path, **_with_fields({"Area": "Shed"}))
    _publish(path, transport)
    write_garden_report(tmp_path, **_with_fields({"Area": "Orchard", "Notes": ""}))
    transport.drop_the_connection_after_write(1)
    with pytest.raises(ConnectorError, match=f"^{DROPPED_AFTER_WRITE}$"):
        _publish(path, transport)
    transport.stop_failing()
    transport.forget_calls()

    assert (_publish(path, transport), transport.writes()) == (Applied(()), [])


def test_a_page_whose_properties_the_service_reports_as_unset_is_empty(tmp_path: Path) -> None:
    transport = FakeTransport()
    transport.seed(NOTION_PAGE_ID, "Blank page", None, fields={"Done": False, "Count": 0}, set_properties=())
    path = write_garden_report(tmp_path, publish=make_notion_publish(where={"page": NOTION_PAGE_ID}))

    outcome = _publish(path, transport)

    assert (outcome, list(load_state(state_path_for(path), DOC_ID).targets)) == (
        Applied((f'create   document "Garden handbook" into {NOTION_PAGE_ID}',)),
        [INTO_LABEL],
    )
