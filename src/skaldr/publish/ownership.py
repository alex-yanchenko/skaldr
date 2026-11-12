from collections.abc import Mapping
from dataclasses import dataclass, field

from pydantic import JsonValue

from skaldr.errors import WriteRejectedError
from skaldr.publish.content import ItemContent, same_value


@dataclass(frozen=True)
class HeldContent:
    title: str
    sections: Mapping[str, str]
    child_ids: tuple[str, ...] = ()
    fields: Mapping[str, JsonValue] = field(default_factory=dict[str, JsonValue])
    icon: str | None = None
    cover: str | None = None
    labelled_for: frozenset[str] | None = None


@dataclass(frozen=True)
class Ownership:
    copies: tuple[ItemContent, ...] = ()
    own_child_ids: frozenset[str] = frozenset()
    doc_id: str | None = None
    judges_the_title_and_look: bool = True
    judges_properties: bool = True


NOTHING_WRITTEN = Ownership()
NOTHING_HELD = HeldContent(title="", sections={})
EMPTY_BODY = Ownership(judges_the_title_and_look=False, judges_properties=False)
NO_CONTENT = Ownership(judges_the_title_and_look=False)


def _title_is_unwritten(held: HeldContent, ownership: Ownership) -> bool:
    return (
        ownership.judges_the_title_and_look
        and bool(held.title.strip())
        and all(copy.title != held.title for copy in ownership.copies)
    )


def _look_is_unwritten(held: str | None, written: list[str | None], ownership: Ownership) -> bool:
    return ownership.judges_the_title_and_look and held is not None and all(look is None for look in written)


def _section_is_unwritten(key: str, text: str, ownership: Ownership) -> bool:
    return bool(text.strip()) and all(copy.sections.get(key) != text for copy in ownership.copies)


def _property_is_unwritten(name: str, value: JsonValue, ownership: Ownership) -> bool:
    return ownership.judges_properties and not any(
        name in copy.fields and same_value(copy.fields[name], value) for copy in ownership.copies
    )


def _labels_are_unwritten(held: HeldContent, ownership: Ownership) -> bool:
    return (
        held.labelled_for is not None
        and ownership.doc_id is not None
        and ownership.doc_id not in held.labelled_for
    )


def unwritten_parts(held: HeldContent, ownership: Ownership) -> tuple[str, ...]:
    title = ("the title",) if _title_is_unwritten(held, ownership) else ()
    icon = (
        ("the icon",)
        if _look_is_unwritten(held.icon, [copy.icon for copy in ownership.copies], ownership)
        else ()
    )
    cover = (
        ("the cover",)
        if _look_is_unwritten(held.cover, [copy.cover for copy in ownership.copies], ownership)
        else ()
    )
    labels = ("the labels",) if _labels_are_unwritten(held, ownership) else ()
    sections = tuple(
        f"section {key}" for key, text in held.sections.items() if _section_is_unwritten(key, text, ownership)
    )
    properties = tuple(
        f"property {name}"
        for name, value in held.fields.items()
        if _property_is_unwritten(name, value, ownership)
    )
    children = tuple(
        f"child page {child}" for child in held.child_ids if child not in ownership.own_child_ids
    )
    return (*title, *icon, *cover, *labels, *sections, *properties, *children)


def refuse_unstamped_content_skaldr_did_not_write(
    item: str, held: HeldContent, ownership: Ownership, verb: str
) -> None:
    parts = unwritten_parts(held, ownership)
    if parts:
        raise WriteRejectedError(
            f"{item} carries no skaldr stamp and holds content skaldr did not write ({', '.join(parts)}), so "
            f"skaldr will not {verb} it"
        )


def refuse_to_archive_an_item_skaldr_does_not_own(
    item: str, stamped_doc_id: str | None, held: HeldContent, doc_id: str, ownership: Ownership
) -> None:
    if stamped_doc_id is not None and stamped_doc_id != doc_id:
        raise WriteRejectedError(
            f"{item} is not stamped with doc_id '{doc_id}', so skaldr will not archive it"
        )
    if stamped_doc_id is None:
        refuse_unstamped_content_skaldr_did_not_write(item, held, ownership, "archive")


def holds_content(held: HeldContent) -> bool:
    return bool(unwritten_parts(held, NO_CONTENT))


def holds_no_body(held: HeldContent) -> bool:
    return not unwritten_parts(held, EMPTY_BODY)
