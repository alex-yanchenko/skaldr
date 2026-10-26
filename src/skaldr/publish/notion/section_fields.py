from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass
from typing import Final, Literal
from uuid import UUID

from pydantic import JsonValue

from skaldr.errors import WriteRejectedError
from skaldr.models import FieldList, FieldScalar, Report, Section, SectionFields
from skaldr.publish.connector import NO_SECTION_DEFAULTS, SectionDefaults
from skaldr.publish.notion.parents import ParentLookup
from skaldr.publish.notion.responses import DataSource, PropertySchema
from skaldr.publish_block import NotionTarget, TargetBase
from skaldr.publish_block.target import JsonFields

Shape = Literal["text", "texts", "number", "date", "person"]

USER_URI_SCHEME: Final = "user://"
TITLE_KIND: Final = "title"
SELECT_KIND: Final = "select"
STATUS_KIND: Final = "status"
MULTI_SELECT_KIND: Final = "multi_select"
OPTION_KINDS: Final = (SELECT_KIND, STATUS_KIND, MULTI_SELECT_KIND)
KINDS_A_SHAPE_GOES_TO: Final[Mapping[Shape, tuple[str, ...]]] = {
    "text": ("select", STATUS_KIND, MULTI_SELECT_KIND, "rich_text"),
    "texts": (MULTI_SELECT_KIND,),
    "number": ("number",),
    "date": ("date",),
    "person": ("people",),
}
SHAPE_IN_WORDS: Final[Mapping[Shape, str]] = {
    "text": "a text",
    "texts": "a list of texts",
    "number": "a number",
    "date": "a date",
    "person": "a person",
}


@dataclass(frozen=True)
class _Field:
    key: str
    shape: Shape
    value: JsonValue
    matches_in_any_capitalisation: bool


@dataclass(frozen=True)
class _Property:
    name: str
    schema: PropertySchema


@dataclass(frozen=True)
class _Outcome:
    name: str | None = None
    value: JsonValue = None
    refusals: tuple[str, ...] = ()


def _in_words(names: tuple[str, ...]) -> str:
    *earlier, last = names
    return f"{', '.join(earlier)} or {last}" if earlier else last


def _quoted(names: list[str]) -> str:
    return ", ".join(f"'{name}'" for name in names)


def _notion_user_id(report: Report, person_key: str) -> str | None:
    person = report.meta.people.get(person_key)
    if person is None or person.notion is None:
        return None
    try:
        return str(UUID(person.notion.removeprefix(USER_URI_SCHEME)))
    except ValueError:
        return None


def _person_refusals(
    report: Report, person_key: str | None, fields: list[_Field], authored_path: str
) -> tuple[str, ...]:
    if person_key is None or all(field.key != "assignee" for field in fields):
        return ()
    if _notion_user_id(report, person_key) is not None:
        return ()
    person = report.meta.people.get(person_key)
    if person is not None and person.notion is not None:
        return (
            f"{authored_path}.assignee is '{person_key}', but meta.people.{person_key}.notion is not a "
            "Notion user id (a UUID); fix it, or remove the assignee",
        )
    return (
        f"{authored_path}.assignee is '{person_key}', but that person has no notion user id in meta.people; "
        f"add one under meta.people.{person_key}.notion, or remove the assignee",
    )


def _extra_field(key: str, value: FieldScalar | FieldList) -> _Field:
    if isinstance(value, list):
        return _Field(key, "texts", [str(member) for member in value], False)
    if isinstance(value, str):
        return _Field(key, "text", value, False)
    return _Field(key, "number", value, False)


def _authored_fields(report: Report, authored: SectionFields) -> list[_Field]:
    fields: list[_Field] = []
    if authored.status is not None:
        fields.append(_Field("status", "text", authored.status, True))
    if authored.priority is not None:
        fields.append(_Field("priority", "text", authored.priority, True))
    if authored.assignee is not None:
        fields.append(_Field("assignee", "person", _notion_user_id(report, authored.assignee) or "", True))
    if authored.due is not None:
        fields.append(_Field("due", "date", authored.due.isoformat(), True))
    if authored.labels is not None:
        fields.append(_Field("labels", "texts", list(authored.labels), True))
    if authored.estimate is not None:
        fields.append(_Field("estimate", "number", authored.estimate, True))
    fields.extend(_extra_field(key, value) for key, value in authored.extras.items())
    return fields


def _left_to_the_section(fields: list[_Field], taken_by_the_target: Collection[str]) -> list[_Field]:
    folded = {name.casefold() for name in taken_by_the_target}
    return [
        field
        for field in fields
        if field.key not in taken_by_the_target
        and not (field.matches_in_any_capitalisation and field.key.casefold() in folded)
    ]


def _property_named(field: _Field, source: DataSource, database_id: str, field_path: str) -> _Property | str:
    properties = source.properties
    if field.key in properties:
        return _Property(field.key, properties[field.key])
    matches = (
        sorted(name for name in properties if name.casefold() == field.key.casefold())
        if field.matches_in_any_capitalisation
        else []
    )
    if len(matches) == 1:
        return _Property(matches[0], properties[matches[0]])
    if matches:
        return (
            f"{field_path} matches the properties {_quoted(matches)} of Notion database {database_id}, which "
            "differ only in capitalisation; rename one of them in Notion"
        )
    capitalisation = ", in any capitalisation," if field.matches_in_any_capitalisation else ""
    return (
        f"{field_path} has no property named '{field.key}'{capitalisation} in Notion database {database_id}; "
        "add one there, or remove the field from the section"
    )


def _refusal_for_the_kind(field: _Field, held: _Property, database_id: str, field_path: str) -> str | None:
    if held.schema.type == TITLE_KIND:
        return (
            f"{field_path} would set '{held.name}', the title of Notion database {database_id}; skaldr sets "
            "the title from the section's title"
        )
    accepted = KINDS_A_SHAPE_GOES_TO[field.shape]
    if held.schema.type in accepted:
        return None
    return (
        f"{field_path} is {SHAPE_IN_WORDS[field.shape]}, but '{held.name}' in Notion database {database_id} "
        f"is a {held.schema.type} property; skaldr writes {SHAPE_IN_WORDS[field.shape]} to a "
        f"{_in_words(accepted)} property"
    )


def _texts_of(field: _Field) -> list[str]:
    value = field.value
    if isinstance(value, list):
        return [member for member in value if isinstance(member, str)]
    return [value] if isinstance(value, str) else []


def _refusals_for_the_options(
    field: _Field, held: _Property, database_id: str, field_path: str
) -> tuple[str, ...]:
    kind = held.schema.type
    texts = _texts_of(field)
    if kind in (SELECT_KIND, MULTI_SELECT_KIND):
        return tuple(
            f"{field_path}{f'.{position}' if field.shape == 'texts' else ''} is '{text}', but a Notion "
            "select or multi-select option cannot hold a comma; remove the comma"
            for position, text in enumerate(texts)
            if "," in text
        )
    if kind != STATUS_KIND:
        return ()
    options = held.schema.option_names
    known = {option.casefold() for option in options}
    listed = _quoted(list(options)) if options else "it has no options"
    return tuple(
        f"{field_path} is '{text}', but the status property '{held.name}' in Notion database "
        f"{database_id} has no option '{text}'; {'its options are ' if options else ''}{listed}"
        for text in texts
        if text.casefold() not in known
    )


def _as_the_database_holds_it(text: str, options: tuple[str, ...]) -> str:
    return next((option for option in options if option.casefold() == text.casefold()), text)


def _once_each_ignoring_case(names: list[str]) -> list[JsonValue]:
    first_of_each = {name.casefold(): name for name in reversed(names)}
    return [first_of_each[name.casefold()] for name in dict.fromkeys(name.casefold() for name in names)]


def _value_for(field: _Field, held: _Property) -> JsonValue:
    kind = held.schema.type
    if field.shape == "person":
        return [field.value]
    if kind not in OPTION_KINDS:
        return field.value
    options = held.schema.option_names
    names = _once_each_ignoring_case([_as_the_database_holds_it(text, options) for text in _texts_of(field)])
    return names if kind == MULTI_SELECT_KIND else names[0]


def _outcome_of(field: _Field, source: DataSource, database_id: str, authored_path: str) -> _Outcome:
    field_path = f"{authored_path}.{field.key}"
    held = _property_named(field, source, database_id, field_path)
    if isinstance(held, str):
        return _Outcome(refusals=(held,))
    kind_refusal = _refusal_for_the_kind(field, held, database_id, field_path)
    if kind_refusal is not None:
        return _Outcome(refusals=(kind_refusal,))
    option_refusals = _refusals_for_the_options(field, held, database_id, field_path)
    if option_refusals:
        return _Outcome(refusals=option_refusals)
    return _Outcome(held.name, _value_for(field, held))


def _mapped(
    fields: list[_Field], source: DataSource, database_id: str, authored_path: str
) -> tuple[JsonFields, tuple[str, ...]]:
    values: JsonFields = {}
    refusals: list[str] = []
    for field in fields:
        outcome = _outcome_of(field, source, database_id, authored_path)
        refusals.extend(outcome.refusals)
        if outcome.name is not None:
            values[outcome.name] = outcome.value
    return values, tuple(refusals)


def _page_parent_refusal(fields: list[_Field], database_id: str, authored_path: str) -> str:
    return (
        f"{authored_path}.{fields[0].key} has no property to go to: the target's `parent_page` {database_id} "
        "is a page, not a database; point `parent_page` at a database, or remove `fields_from_sections`"
    )


def notion_section_defaults(
    report: Report,
    section: Section,
    source_index: int,
    target: TargetBase,
    look_up_parent: Callable[[str], ParentLookup],
) -> SectionDefaults:
    authored = section.fields
    if authored is None or not isinstance(target, NotionTarget) or not target.where.fields_from_sections:
        return NO_SECTION_DEFAULTS
    authored_path = f"blocks[{source_index}].fields"
    taken = target.fields_for(section.id).keys()
    fields = _left_to_the_section(_authored_fields(report, authored), taken)
    if not fields:
        return NO_SECTION_DEFAULTS
    person_refusals = _person_refusals(report, authored.assignee, fields, authored_path)
    if person_refusals:
        return SectionDefaults({}, authored_path, person_refusals)
    database_id = target.where.page_id
    try:
        parent = look_up_parent(database_id)
    except WriteRejectedError as refused:
        return SectionDefaults({}, authored_path, (str(refused),))
    if parent.data_source is None:
        return SectionDefaults({}, authored_path, (_page_parent_refusal(fields, database_id, authored_path),))
    values, refusals = _mapped(fields, parent.data_source, database_id, authored_path)
    return SectionDefaults(values, authored_path, refusals)
