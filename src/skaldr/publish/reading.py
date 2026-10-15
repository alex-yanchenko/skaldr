import hashlib
import json
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace

from typing_extensions import assert_never

from skaldr.errors import ItemNotFoundError, PublishError
from skaldr.publish.content import (
    ItemContent,
    Part,
    comparable,
    differing_parts,
    same_fields,
    set_fields,
    with_fields_named,
    with_look_owned_by,
    with_parts,
)
from skaldr.publish.drafts import ItemDraft
from skaldr.publish.plan import CreateStep, ItemRef, PublishPlan
from skaldr.publish.prepared import Prepared, Transports, with_item
from skaldr.publish.state import ItemOrigin, PendingCreate, PublishedItem, PublishState
from skaldr.publish.transport import RemoteItem, Transport
from skaldr.publish_block import TargetBase
from skaldr.services import SERVICE_NAMES, Service

NOT_YET_PUBLISHED = ItemContent(title="")


@dataclass(frozen=True)
class Reading:
    item: ItemRef
    published: PublishedItem
    remote: RemoteItem
    edited: tuple[Part, ...]
    reported: tuple[Part, ...]
    saved_copy: ItemContent = field(default_factory=lambda: NOT_YET_PUBLISHED)


@dataclass(frozen=True)
class RemoteEdit:
    item: ItemRef
    part: Part
    path: str | None
    published: str | None
    current: str | None
    edited_by: str | None
    edited_at: str | None


def part_text(content: ItemContent | None, part: Part) -> str | None:
    if content is None:
        return None
    match part.kind:
        case "title":
            return content.title + "\n"
        case "fields":
            return json.dumps(comparable(set_fields(content.fields)), indent=2, ensure_ascii=False) + "\n"
        case "icon":
            return None if content.icon is None else f"{content.icon}\n"
        case "cover":
            return None if content.cover is None else f"{content.cover}\n"
        case "section":
            return content.sections.get(part.key)
        case _:
            assert_never(part.kind)


def refuse_another_documents_item(ref: ItemRef, remote: RemoteItem, doc_id: str) -> None:
    if remote.doc_id is not None and remote.doc_id != doc_id:
        raise PublishError(
            f"{ref.label} ({remote.item_id}) is stamped with doc_id '{remote.doc_id}', so it belongs to that "
            f"document and not to '{doc_id}'; skaldr writes only to items of the document it publishes"
        )


@dataclass(frozen=True)
class MissingItem:
    item: ItemRef
    item_id: str


def missing_message(missing: MissingItem, service: Service) -> str:
    return (
        f"{missing.item.label} ({missing.item_id}) is no longer in {SERVICE_NAMES[service]}; publish with "
        "--apply --overwrite to create it again, or to forget it if the YAML no longer has it"
    )


def _has_content(remote: RemoteItem) -> bool:
    return (
        any(text.strip() for text in remote.comparable.sections.values())
        or bool(remote.child_ids)
        or bool(remote.set_properties)
    )


def _lines_held(text: str | None) -> Counter[str]:
    return Counter(line for line in (text or "").split("\n") if line.strip())


def _holds_only_what_skaldr_wrote(current: str | None, published: str | None, expected: str | None) -> bool:
    return not _lines_held(current) - (_lines_held(published) + _lines_held(expected))


def _left_by_the_interrupted_write(
    item: PublishedItem, remote: RemoteItem, parts: Sequence[Part], transport: Transport
) -> list[Part]:
    if item.writing is None:
        return []
    saved = transport.comparable_form(item.remote)
    expected = transport.comparable_form(item.writing.rendered)
    return [
        part
        for part in parts
        if _holds_only_what_skaldr_wrote(
            part_text(remote.comparable, part), part_text(saved, part), part_text(expected, part)
        )
    ]


def _settled(
    item: PublishedItem, remote: RemoteItem, edited: tuple[Part, ...], transport: Transport
) -> tuple[PublishedItem, tuple[Part, ...]]:
    if item.writing is None:
        return item, edited
    expected = transport.comparable_form(item.writing.rendered)
    written = [part.part for part in item.writing.parts if part.part in edited]
    landed = [part for part in written if part_text(remote.comparable, part) == part_text(expected, part)]
    half_written = _left_by_the_interrupted_write(
        item, remote, [part for part in written if part not in landed], transport
    )
    rest = tuple(part for part in edited if part not in landed and part not in half_written)
    rendered = with_parts(
        with_parts(item.rendered, item.writing.rendered, landed), remote.comparable, half_written
    )
    if not rest:
        settled = item.model_copy(
            update={
                "rendered": rendered,
                "remote": remote.comparable,
                "marker": remote.marker,
                "writing": None,
            }
        )
        return settled, ()
    still_writing = item.writing.model_copy(
        update={"parts": [part for part in item.writing.parts if part.part in landed]}
    )
    settled = item.model_copy(
        update={
            "rendered": rendered,
            "remote": with_parts(item.remote, remote.comparable, [*landed, *half_written]),
            "writing": still_writing if landed else item.writing,
        }
    )
    return settled, rest


def _released(remote: RemoteItem, item: PublishedItem) -> bool:
    owned_set = any(name in remote.set_properties for name in item.rendered.fields)
    owned_icon = item.rendered.icon is not None and remote.comparable.icon is not None
    owned_cover = item.rendered.cover is not None and remote.comparable.cover is not None
    blank = not any(text.strip() for text in remote.comparable.sections.values())
    return remote.doc_id is None and blank and not (owned_set or owned_icon or owned_cover)


def _retired_already(item: PublishedItem, remote: RemoteItem | None) -> bool:
    if item.retiring is None:
        return False
    if remote is None:
        return True
    return item.retiring == "release" and _released(remote, item)


def _owners(item: PublishedItem, draft: ItemDraft | None) -> list[ItemContent]:
    return [item.rendered] if draft is None else [item.rendered, draft.content]


def _owned_field_names(owners: Sequence[ItemContent]) -> list[str]:
    return [name for owner in owners for name in owner.fields]


def _owned_part_of(read: ItemContent, owners: Sequence[ItemContent]) -> ItemContent:
    return with_look_owned_by(with_fields_named(read, _owned_field_names(owners)), *owners)


def _keyed_view(content: ItemContent, owners: Sequence[ItemContent]) -> ItemContent:
    keyed = content.model_copy(
        update={"fields": {name: content.fields.get(name) for name in _owned_field_names(owners)}}
    )
    return with_look_owned_by(keyed, *owners)


def _read_or_none(transport: Transport, item_id: str, keyed_like: ItemContent) -> RemoteItem | None:
    try:
        return transport.read_item(item_id, keyed_like)
    except ItemNotFoundError:
        return None


def _rendered_where_it_matches(remote: ItemContent, draft: ItemContent, transport: Transport) -> ItemContent:
    expected = transport.comparable_form(draft)
    title = draft.title if expected.title == remote.title else remote.title
    fields = draft.fields if same_fields(expected.fields, remote.fields) else remote.fields
    sections = {
        key: draft.sections[key] if expected.sections.get(key) == text else text
        for key, text in remote.sections.items()
    }
    icon = remote.icon if draft.icon is not None and expected.icon != remote.icon else draft.icon
    cover = remote.cover if draft.cover is not None and expected.cover != remote.cover else draft.cover
    return ItemContent(title=title, sections=sections, fields=fields, icon=icon, cover=cover)


def _adopted(remote: RemoteItem, draft: ItemDraft | None, transport: Transport) -> PublishedItem:
    rendered = (
        remote.comparable
        if draft is None
        else _rendered_where_it_matches(remote.comparable, draft.content, transport)
    )
    return PublishedItem(
        item_id=remote.item_id,
        origin="adopted",
        rendered=rendered,
        remote=remote.comparable,
        marker=remote.marker,
    )


def _pending_target(prepared: Prepared, pending: PendingCreate) -> TargetBase:
    if pending.service is None or pending.target_as_written is None:
        return prepared.target_named(pending.target)
    target_type = prepared.registry.for_service(pending.service).target_type
    return target_type.model_validate(pending.target_as_written)


def settle_interrupted_creates(prepared: Prepared, transports: Transports) -> PublishState:
    state = prepared.state
    for pending in prepared.state.pending_creates:
        item_id = pending.into_id or pending.created_id
        if item_id is None:
            continue
        target = _pending_target(prepared, pending)
        transport = transports.for_target(pending.target, target)
        remote = _read_or_none(transport, item_id, NOT_YET_PUBLISHED)
        ref = ItemRef(pending.target, pending.section_id)
        created_by_skaldr = pending.into_id is None
        if remote is not None and created_by_skaldr:
            refuse_another_documents_item(ref, remote, prepared.doc_id)
        remaining = [held for held in state.pending_creates if held != pending]
        state = state.model_copy(update={"pending_creates": remaining})
        if remote is not None and (created_by_skaldr or remote.doc_id == prepared.doc_id):
            held = _adopted(remote, prepared.draft_of(ref), transport)
            origin: ItemOrigin = "created" if created_by_skaldr else "adopted"
            state = with_item(state, ref, target, held.model_copy(update={"origin": origin}))
    return state


@dataclass(frozen=True)
class PublishedReadings:
    readings: list[Reading]
    state: PublishState
    missing: list[MissingItem]


def read_published(prepared: Prepared, transports: Transports) -> PublishedReadings:
    readings: list[Reading] = []
    missing: list[MissingItem] = []
    state = prepared.state
    for label, published_target in prepared.state.targets.items():
        transport = transports.for_target(label)
        for section_id, held in published_target.held_items():
            ref = ItemRef(label, section_id)
            draft = prepared.draft_of(ref)
            item = held.model_copy(update={"retiring": None}) if draft is not None else held
            if item != held:
                state = with_item(state, ref, prepared.target_named(label), item)
            owners = _owners(item, draft)
            read = _read_or_none(transport, item.item_id, _keyed_view(item.remote, owners))
            if _retired_already(item, read):
                state = with_item(state, ref, prepared.target_named(label), None)
                continue
            if read is None:
                missing.append(MissingItem(ref, item.item_id))
                continue
            refuse_another_documents_item(ref, read, prepared.doc_id)
            remote = replace(read, comparable=_owned_part_of(read.comparable, owners))
            if item.retiring is not None:
                readings.append(Reading(ref, item, remote, (), ()))
                continue
            saved_copy = transport.comparable_form(item.remote)
            published = _keyed_view(saved_copy, [item.rendered])
            reported = tuple(transport.parts_edited_after(item.item_id, item.marker, published))
            compared = _owned_part_of(read.comparable, [item.rendered])
            unsettled = tuple(dict.fromkeys([*differing_parts(published, compared), *reported]))
            settled, edited = _settled(item, remote, unsettled, transport)
            if settled != item:
                state = with_item(state, ref, prepared.target_named(label), settled)
            landed = set(unsettled) - set(edited)
            still_reported = tuple(part for part in reported if part not in landed)
            if settled.remote != item.remote:
                saved_copy = transport.comparable_form(settled.remote)
            if (edited or still_reported) and remote.edited_by is not None:
                remote = replace(remote, edited_by=transport.editor_name(remote.edited_by))
            readings.append(Reading(ref, settled, remote, edited, still_reported, saved_copy))
    return PublishedReadings(readings, state, missing)


def _read_written_into(
    prepared: Prepared, transports: Transports, label: str, step: CreateStep
) -> RemoteItem:
    into_id = step.into_id or ""
    service = prepared.target_named(label).service()
    transport = transports.for_target(label)
    try:
        remote = transport.read_item(into_id, NOT_YET_PUBLISHED)
    except ItemNotFoundError as exc:
        raise PublishError(
            f"{step.item.label}: the page {into_id} the target names is not in {SERVICE_NAMES[service]}; "
            "name an existing empty page, or publish under one with `parent_page` instead"
        ) from exc
    refuse_another_documents_item(step.item, remote, prepared.doc_id)
    holds_this_draft = not differing_parts(
        transport.comparable_form(step.draft.content), _owned_part_of(remote.comparable, [step.draft.content])
    )
    if remote.doc_id is None and _has_content(remote) and not holds_this_draft:
        raise PublishError(
            f"{step.item.label}: {into_id} already holds content and carries no skaldr stamp, so skaldr will "
            "not write into it; empty the page, or publish under it with `parent_page` instead"
        )
    return remote


def read_items_written_into(
    prepared: Prepared, plan: PublishPlan, transports: Transports, already: Mapping[ItemRef, RemoteItem]
) -> dict[ItemRef, RemoteItem]:
    read = dict(already)
    for target_plan in plan.targets:
        for step in target_plan.steps:
            if isinstance(step, CreateStep) and step.into_id is not None and step.item not in read:
                read[step.item] = _read_written_into(prepared, transports, target_plan.label, step)
    return read


def _part_path(prepared: Prepared, ref: ItemRef, part: Part) -> str | None:
    draft = prepared.draft_of(ref)
    return None if draft is None else draft.paths.get(part)


def remote_edits(prepared: Prepared, readings: Sequence[Reading]) -> tuple[RemoteEdit, ...]:
    return tuple(
        RemoteEdit(
            reading.item,
            part,
            _part_path(prepared, reading.item, part),
            part_text(reading.saved_copy, part),
            part_text(reading.remote.comparable, part),
            reading.remote.edited_by,
            reading.remote.edited_at,
        )
        for reading in readings
        for part in reading.edited
    )


def shown_token(reading: Reading) -> str:
    seen = {
        "edited": [
            [part.kind, part.key, part_text(reading.remote.comparable, part)] for part in reading.edited
        ],
        "reported": sorted({(part.kind, part.key) for part in reading.reported}),
    }
    return hashlib.sha256(json.dumps(seen, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
