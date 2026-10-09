import re
from typing import Any

import pytest
from pydantic import JsonValue

from skaldr.errors import WriteRejectedError
from skaldr.publish.notion.properties import (
    property_fields,
    property_request,
    rich_text_request,
    set_property_names,
    title_request,
    title_text,
)
from skaldr.publish.notion.responses import Page


def _text(content: str) -> dict[str, Any]:
    return {"type": "text", "plain_text": content, "text": {"content": content}}


def _page(**properties: dict[str, Any]) -> Page:
    return Page.model_validate(
        {
            "object": "page",
            "id": "11111111-2222-4333-8444-555555555555",
            "last_edited_time": "2026-10-09T12:00:00.000Z",
            "last_edited_by": {"object": "user", "id": "bot-1"},
            "in_trash": False,
            "properties": {
                "Name": {"id": "title", "type": "title", "title": [_text("Garden "), _text("handbook")]},
                **properties,
            },
        }
    )


EVERY_KIND = _page(
    Notes={"id": "a", "type": "rich_text", "rich_text": [_text("Sow "), _text("early")]},
    Beds={"id": "b", "type": "number", "number": 4},
    Area={"id": "c", "type": "select", "select": {"id": "s", "name": "Shed", "color": "red"}},
    Stage={"id": "d", "type": "status", "status": None},
    Tags={"id": "e", "type": "multi_select", "multi_select": [{"id": "1", "name": "soil", "color": "red"}]},
    Due={"id": "f", "type": "date", "date": {"start": "2026-10-01", "end": None, "time_zone": None}},
    Season={
        "id": "g",
        "type": "date",
        "date": {"start": "2026-03-01", "end": "2026-05-31", "time_zone": None},
    },
    Done={"id": "h", "type": "checkbox", "checkbox": False},
    Site={"id": "i", "type": "url", "url": "https://example.com/garden"},
    Mail={"id": "j", "type": "email", "email": None},
    Phone={"id": "k", "type": "phone_number", "phone_number": "555 0100"},
    Owners={"id": "l", "type": "people", "people": [{"object": "user", "id": "user-1"}]},
    Plots={"id": "m", "type": "relation", "relation": [{"id": "plot-1"}], "has_more": False},
    Photos={"id": "n", "type": "files", "files": [{"name": "bed.png", "type": "external"}]},
    Made={"id": "o", "type": "created_time", "created_time": "2026-10-01T00:00:00.000Z"},
    Score={"id": "p", "type": "formula", "formula": {"type": "number", "number": 3}},
)


def test_the_title_reads_as_its_plain_text() -> None:
    assert title_text(EVERY_KIND) == "Garden handbook"


def test_each_property_a_person_can_set_reads_as_a_plain_value_and_computed_ones_are_left_out() -> None:
    assert property_fields(EVERY_KIND) == {
        "Notes": "Sow early",
        "Beds": 4,
        "Area": "Shed",
        "Stage": None,
        "Tags": ["soil"],
        "Due": "2026-10-01",
        "Season": {"start": "2026-03-01", "end": "2026-05-31"},
        "Done": False,
        "Site": "https://example.com/garden",
        "Mail": None,
        "Phone": "555 0100",
        "Owners": ["user-1"],
        "Plots": ["plot-1"],
        "Photos": ["bed.png"],
    }


def test_the_set_properties_are_those_holding_a_value_and_an_unticked_checkbox_holds_none() -> None:
    assert set_property_names(EVERY_KIND) == (
        "Notes",
        "Beds",
        "Area",
        "Tags",
        "Due",
        "Season",
        "Site",
        "Phone",
        "Owners",
        "Plots",
        "Photos",
    )


def test_a_page_with_only_a_title_has_no_fields() -> None:
    assert (property_fields(_page()), set_property_names(_page())) == ({}, ())


def test_text_longer_than_one_notion_text_object_is_sent_in_pieces() -> None:
    assert rich_text_request("a" * 2001) == [
        {"type": "text", "text": {"content": "a" * 2000}},
        {"type": "text", "text": {"content": "a"}},
    ]


def test_the_title_is_sent_under_the_title_property_id() -> None:
    assert title_request("Garden guide") == {
        "title": {"title": [{"type": "text", "text": {"content": "Garden guide"}}]}
    }


@pytest.mark.parametrize(
    ("kind", "value", "request_value"),
    [
        pytest.param(
            "rich_text", "Sow", {"rich_text": [{"type": "text", "text": {"content": "Sow"}}]}, id="text"
        ),
        pytest.param("rich_text", None, {"rich_text": []}, id="text-cleared"),
        pytest.param("number", 4.5, {"number": 4.5}, id="number"),
        pytest.param("number", None, {"number": None}, id="number-cleared"),
        pytest.param("select", "Shed", {"select": {"name": "Shed"}}, id="select"),
        pytest.param("select", "", {"select": None}, id="select-cleared"),
        pytest.param("status", "Done", {"status": {"name": "Done"}}, id="status"),
        pytest.param(
            "multi_select", ["soil", "seeds"], {"multi_select": [{"name": "soil"}, {"name": "seeds"}]}
        ),
        pytest.param("multi_select", None, {"multi_select": []}, id="multi-select-cleared"),
        pytest.param("date", "2026-10-01", {"date": {"start": "2026-10-01"}}, id="date"),
        pytest.param(
            "date",
            {"start": "2026-03-01", "end": "2026-05-31"},
            {"date": {"start": "2026-03-01", "end": "2026-05-31"}},
            id="date-range",
        ),
        pytest.param("date", None, {"date": None}, id="date-cleared"),
        pytest.param("checkbox", True, {"checkbox": True}, id="checkbox"),
        pytest.param("checkbox", None, {"checkbox": False}, id="checkbox-cleared"),
        pytest.param("url", "https://example.com", {"url": "https://example.com"}, id="url"),
        pytest.param("email", "", {"email": None}, id="email-cleared"),
        pytest.param("phone_number", "555 0100", {"phone_number": "555 0100"}, id="phone"),
        pytest.param("people", ["user-1"], {"people": [{"id": "user-1"}]}, id="people"),
        pytest.param("relation", [], {"relation": []}, id="relation-cleared"),
    ],
)
def test_a_field_value_is_sent_in_the_shape_its_property_kind_takes(
    kind: str, value: JsonValue, request_value: JsonValue
) -> None:
    assert property_request("Area", kind, value) == request_value


@pytest.mark.parametrize(
    ("kind", "value", "message"),
    [
        pytest.param(
            "number",
            "four",
            "the Notion property 'Area' is a number property, so skaldr sends it a number, not \"four\"",
            id="text-for-a-number",
        ),
        pytest.param(
            "number",
            True,
            "the Notion property 'Area' is a number property, so skaldr sends it a number, not true",
            id="boolean-for-a-number",
        ),
        pytest.param(
            "multi_select",
            "soil",
            "the Notion property 'Area' is a multi_select property, so skaldr sends it a list of texts, "
            'not "soil"',
            id="text-for-a-list",
        ),
        pytest.param(
            "date",
            {"end": "2026-05-31"},
            "the Notion property 'Area' is a date property, so skaldr sends it a date text or a start and "
            'end, not {"end": "2026-05-31"}',
            id="date-without-start",
        ),
        pytest.param(
            "checkbox",
            "yes",
            "the Notion property 'Area' is a checkbox property, so skaldr sends it true or false, "
            'not "yes"',
            id="text-for-a-checkbox",
        ),
        pytest.param(
            "files",
            ["bed.png"],
            "the Notion property 'Area' is a files property, which skaldr cannot set",
            id="files",
        ),
        pytest.param(
            "formula",
            1,
            "the Notion property 'Area' is a formula property, which skaldr cannot set",
            id="computed",
        ),
    ],
)
def test_a_value_its_property_kind_cannot_take_is_refused_before_anything_is_sent(
    kind: str, value: JsonValue, message: str
) -> None:
    with pytest.raises(WriteRejectedError, match=f"^{re.escape(message)}$"):
        property_request("Area", kind, value)
