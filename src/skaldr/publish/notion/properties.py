import json
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Literal, NamedTuple, TypeGuard, assert_never

from pydantic import JsonValue

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

SettableKind = Literal[
    "rich_text",
    "number",
    "select",
    "status",
    "multi_select",
    "date",
    "checkbox",
    "url",
    "email",
    "phone_number",
    "people",
    "relation",
]


@dataclass(frozen=True)
class _Sent:
    value: JsonValue


def _plain(items: Sequence[RichTextItem]) -> str:
    return "".join(item.plain_text for item in items)


def title_text(page: Page) -> str:
    return next(
        (_plain(value.title) for value in page.properties.values() if isinstance(value, TitleValue)), ""
    )


def _read_value(value: PropertyValue) -> _Sent | None:
    match value:
        case TitleValue() | OtherValue():
            return None
        case RichTextValue():
            return _Sent(_plain(value.rich_text))
        case NumberValue():
            return _Sent(value.number)
        case SelectValue() | StatusValue():
            option = value.select if isinstance(value, SelectValue) else value.status
            return _Sent(None if option is None else option.name)
        case MultiSelectValue():
            return _Sent([option.name for option in value.multi_select])
        case DateValue():
            if value.date is None or value.date.end is None:
                return _Sent(None if value.date is None else value.date.start)
            return _Sent({"start": value.date.start, "end": value.date.end})
        case CheckboxValue():
            return _Sent(value.checkbox)
        case UrlValue():
            return _Sent(value.url)
        case EmailValue():
            return _Sent(value.email)
        case PhoneNumberValue():
            return _Sent(value.phone_number)
        case PeopleValue() | RelationValue():
            references = value.people if isinstance(value, PeopleValue) else value.relation
            return _Sent([reference.id for reference in references])
        case FilesValue():
            return _Sent([file.name for file in value.files])
        case _:
            assert_never(value)


def property_fields(page: Page) -> JsonFields:
    return {
        name: read.value
        for name, value in page.properties.items()
        if (read := _read_value(value)) is not None
    }


def set_property_names(page: Page) -> tuple[str, ...]:
    return tuple(
        name for name, value in property_fields(page).items() if not is_unset(value) and value is not False
    )


def rich_text_request(text: str) -> list[JsonValue]:
    return [
        {"type": "text", "text": {"content": text[start : start + RICH_TEXT_PIECE_CHARACTERS]}}
        for start in range(0, len(text), RICH_TEXT_PIECE_CHARACTERS)
    ]


def title_property_name(page: Page) -> str:
    return next(
        (name for name, value in page.properties.items() if isinstance(value, TitleValue)), TITLE_PROPERTY_ID
    )


def title_request(title: str, name: str = TITLE_PROPERTY_ID) -> JsonFields:
    return {name: {"title": rich_text_request(title)}}


def _text_list(value: JsonValue) -> list[str] | None:
    if not isinstance(value, list) or not all(isinstance(member, str) for member in value):
        return None
    return [member for member in value if isinstance(member, str)]


def _date(value: JsonValue) -> _Sent | None:
    if isinstance(value, str):
        return _Sent({"start": value})
    if not isinstance(value, dict) or not isinstance(value.get("start"), str):
        return None
    if "end" in value and not isinstance(value["end"], str):
        return None
    return _Sent({key: member for key, member in value.items() if key in ("start", "end")})


def _text_value(value: JsonValue) -> _Sent | None:
    return _Sent(value) if isinstance(value, str) else None


def _number(value: JsonValue) -> _Sent | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return _Sent(value) if math.isfinite(value) else None


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


class _Encoding(NamedTuple):
    encode: Callable[[JsonValue], _Sent | None]
    cleared: JsonValue
    expectation: str


_ENCODINGS: Final[Mapping[SettableKind, _Encoding]] = {
    "rich_text": _Encoding(_rich_text, [], "a text"),
    "number": _Encoding(_number, None, "a number"),
    "select": _Encoding(_named, None, "a text"),
    "status": _Encoding(_named, None, "a text"),
    "multi_select": _Encoding(_names, [], "a list of texts"),
    "date": _Encoding(_date, None, "a date text or a start and end"),
    "checkbox": _Encoding(_checkbox, False, "true or false"),
    "url": _Encoding(_text_value, None, "a text"),
    "email": _Encoding(_text_value, None, "a text"),
    "phone_number": _Encoding(_text_value, None, "a text"),
    "people": _Encoding(_ids, [], "a list of user ids"),
    "relation": _Encoding(_ids, [], "a list of page ids"),
}


def _is_settable(kind: str) -> TypeGuard[SettableKind]:
    return kind in _ENCODINGS


def property_request(name: str, kind: str, value: JsonValue) -> JsonFields:
    if not _is_settable(kind):
        raise WriteRejectedError(
            f"the Notion property '{name}' is a {kind} property, which skaldr cannot set"
        )
    encoding = _ENCODINGS[kind]
    if is_unset(value):
        return {kind: encoding.cleared}
    sent = encoding.encode(value)
    if sent is None:
        shown = json.dumps(value, ensure_ascii=False)
        raise WriteRejectedError(
            f"the Notion property '{name}' is a {kind} property, so skaldr sends it {encoding.expectation}, "
            f"not {shown}"
        )
    return {kind: sent.value}
