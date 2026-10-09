import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Final

from pydantic import JsonValue
from typing_extensions import assert_never

from skaldr.errors import WriteRejectedError
from skaldr.publish.content import is_unset
from skaldr.publish.notion.responses import (
    CheckboxValue,
    DateValue,
    EmailValue,
    FilesValue,
    MultiSelectValue,
    NumberValue,
    OtherValue,
    Page,
    PeopleValue,
    PhoneNumberValue,
    PropertyValue,
    RelationValue,
    RichTextItem,
    RichTextValue,
    SelectValue,
    StatusValue,
    TitleValue,
    UrlValue,
)
from skaldr.publish_block.target import JsonFields

TITLE_PROPERTY_ID: Final = "title"
RICH_TEXT_PIECE_CHARACTERS: Final = 2000


def _plain(items: list[RichTextItem]) -> str:
    return "".join(item.plain_text for item in items)


def title_text(page: Page) -> str:
    return next(
        (_plain(value.title) for value in page.properties.values() if isinstance(value, TitleValue)), ""
    )


def _read_value(value: PropertyValue) -> tuple[bool, JsonValue]:
    match value:
        case TitleValue() | OtherValue():
            return False, None
        case RichTextValue():
            return True, _plain(value.rich_text)
        case NumberValue():
            return True, value.number
        case SelectValue() | StatusValue():
            option = value.select if isinstance(value, SelectValue) else value.status
            return True, None if option is None else option.name
        case MultiSelectValue():
            return True, [option.name for option in value.multi_select]
        case DateValue():
            if value.date is None or value.date.end is None:
                return True, None if value.date is None else value.date.start
            return True, {"start": value.date.start, "end": value.date.end}
        case CheckboxValue():
            return True, value.checkbox
        case UrlValue():
            return True, value.url
        case EmailValue():
            return True, value.email
        case PhoneNumberValue():
            return True, value.phone_number
        case PeopleValue() | RelationValue():
            references = value.people if isinstance(value, PeopleValue) else value.relation
            return True, [reference.id for reference in references]
        case FilesValue():
            return True, [file.name for file in value.files]
        case _:
            assert_never(value)


def property_fields(page: Page) -> JsonFields:
    fields: JsonFields = {}
    for name, value in page.properties.items():
        readable, read = _read_value(value)
        if readable:
            fields[name] = read
    return fields


def set_property_names(page: Page) -> tuple[str, ...]:
    return tuple(
        name for name, value in property_fields(page).items() if not is_unset(value) and value is not False
    )


def rich_text_request(text: str) -> list[JsonValue]:
    return [
        {"type": "text", "text": {"content": text[start : start + RICH_TEXT_PIECE_CHARACTERS]}}
        for start in range(0, len(text), RICH_TEXT_PIECE_CHARACTERS)
    ]


def title_request(title: str) -> JsonFields:
    return {TITLE_PROPERTY_ID: {"title": rich_text_request(title)}}


@dataclass(frozen=True)
class _Sent:
    value: JsonValue


def _text_list(value: JsonValue) -> list[str] | None:
    if not isinstance(value, list) or not all(isinstance(member, str) for member in value):
        return None
    return [member for member in value if isinstance(member, str)]


def _date(value: JsonValue) -> _Sent | None:
    if isinstance(value, str):
        return _Sent({"start": value})
    if isinstance(value, dict) and isinstance(value.get("start"), str):
        return _Sent({key: member for key, member in value.items() if key in ("start", "end")})
    return None


def _text_value(value: JsonValue) -> _Sent | None:
    return _Sent(value) if isinstance(value, str) else None


def _number(value: JsonValue) -> _Sent | None:
    return _Sent(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _named(value: JsonValue) -> _Sent | None:
    return _Sent({"name": value}) if isinstance(value, str) else None


def _names(value: JsonValue) -> _Sent | None:
    texts = _text_list(value)
    return None if texts is None else _Sent([{"name": text} for text in texts])


def _ids(value: JsonValue) -> _Sent | None:
    texts = _text_list(value)
    return None if texts is None else _Sent([{"id": text} for text in texts])


def _checkbox(value: JsonValue) -> _Sent | None:
    return _Sent(value) if isinstance(value, bool) else None


def _rich_text(value: JsonValue) -> _Sent | None:
    return _Sent(rich_text_request(value)) if isinstance(value, str) else None


_Encoding = tuple[Callable[[JsonValue], _Sent | None], JsonValue, str]

_ENCODINGS: Final[Mapping[str, _Encoding]] = {
    "rich_text": (_rich_text, [], "a text"),
    "number": (_number, None, "a number"),
    "select": (_named, None, "a text"),
    "status": (_named, None, "a text"),
    "multi_select": (_names, [], "a list of texts"),
    "date": (_date, None, "a date text or a start and end"),
    "checkbox": (_checkbox, False, "true or false"),
    "url": (_text_value, None, "a text"),
    "email": (_text_value, None, "a text"),
    "phone_number": (_text_value, None, "a text"),
    "people": (_ids, [], "a list of user ids"),
    "relation": (_ids, [], "a list of page ids"),
}


def property_request(name: str, kind: str, value: JsonValue) -> JsonFields:
    encoding = _ENCODINGS.get(kind)
    if encoding is None:
        raise WriteRejectedError(
            f"the Notion property '{name}' is a {kind} property, which skaldr cannot set"
        )
    encode, cleared, expectation = encoding
    if is_unset(value):
        return {kind: cleared}
    sent = encode(value)
    if sent is None:
        shown = json.dumps(value, ensure_ascii=False)
        raise WriteRejectedError(
            f"the Notion property '{name}' is a {kind} property, so skaldr sends it {expectation}, "
            f"not {shown}"
        )
    return {kind: sent.value}
