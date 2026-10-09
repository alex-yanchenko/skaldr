import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from pydantic import JsonValue
from typing_extensions import assert_never

from skaldr.errors import ItemNotFoundError, PublishError
from skaldr.publish.content import ItemContent, Part, comparable, differing_parts, placed_section
from skaldr.publish.plan import CreateStep, ItemRef, PublishPlan
from skaldr.publish.prepared import Prepared, Transports, with_item
from skaldr.publish.state import PublishedItem, PublishState
from skaldr.publish.transport import RemoteItem, Transport
from skaldr.services import SERVICE_NAMES, Service

NOT_YET_PUBLISHED = ItemContent(title="")


@dataclass(frozen=True)
class Reading:
    item: ItemRef
    published: PublishedItem
    remote: RemoteItem
    edited: tuple[Part, ...]
    reported: tuple[Part, ...]


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
            return json.dumps(comparable(dict(content.fields)), indent=2, ensure_ascii=False) + "\n"
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


def _is_set(value: JsonValue) -> bool:
    return value not in (None, "", [], {})


def _has_content(remote: RemoteItem) -> bool:
    return (
        any(text.strip() for text in remote.comparable.sections.values())
        or bool(remote.child_ids)
        or any(_is_set(value) for value in remote.comparable.fields.values())
    )


def _with_parts(before: ItemContent, after: ItemContent, parts: Sequence[Part]) -> ItemContent:
    content = before
    order = list(after.sections)
    for part in parts:
        match part.kind:
            case "title":
                content = content.model_copy(update={"title": after.title})
            case "fields":
                content = content.model_copy(update={"fields": after.fields})
            case "section":
                text = after.sections.get(part.key)
                follows = order[order.index(part.key) - 1] if part.key in order[1:] else None
                sections = placed_section(content.sections, part.key, text, follows)
                content = content.model_copy(update={"sections": sections})
            case _:
                assert_never(part.kind)
    return content


def _settled(
    item: PublishedItem, remote: RemoteItem, edited: tuple[Part, ...], transport: Transport
) -> tuple[PublishedItem, tuple[Part, ...]]:
    if item.writing is None:
        return item, edited
    expected = transport.comparable_form(item.writing.rendered)
    landed = [
        part.part
        for part in item.writing.parts
        if part.part in edited and part_text(remote.comparable, part.part) == part_text(expected, part.part)
    ]
    if any(part not in landed for part in edited):
        return item, edited
    settled = item.model_copy(
        update={
            "rendered": _with_parts(item.rendered, item.writing.rendered, landed),
            "remote": remote.comparable,
            "marker": remote.marker,
            "writing": None,
        }
    )
    return settled, ()


def _retired_already(item: PublishedItem, remote: RemoteItem | None) -> bool:
    if item.retiring is None:
        return False
    if remote is None:
        return True
    return item.retiring == "release" and remote.doc_id is None and not _has_content(remote)


def _read_or_none(transport: Transport, item_id: str, keyed_like: ItemContent) -> RemoteItem | None:
    try:
        return transport.read_item(item_id, keyed_like)
    except ItemNotFoundError:
        return None


def _adopted(remote: RemoteItem) -> PublishedItem:
    return PublishedItem(
        item_id=remote.item_id,
        origin="adopted",
        rendered=remote.comparable,
        remote=remote.comparable,
        marker=remote.marker,
    )


def settle_interrupted_adoptions(prepared: Prepared, transports: Transports) -> PublishState:
    state = prepared.state
    for pending in prepared.state.pending_creates:
        if pending.into_id is None:
            continue
        transport = transports.for_target(pending.target)
        remote = _read_or_none(transport, pending.into_id, NOT_YET_PUBLISHED)
        remaining = [held for held in state.pending_creates if held != pending]
        state = state.model_copy(update={"pending_creates": remaining})
        if remote is not None and remote.doc_id == prepared.doc_id:
            ref = ItemRef(pending.target, pending.section_id)
            state = with_item(state, ref, prepared.target_named(pending.target), _adopted(remote))
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
        for section_id, item in published_target.held_items():
            ref = ItemRef(label, section_id)
            remote = _read_or_none(transport, item.item_id, item.remote)
            if _retired_already(item, remote):
                state = with_item(state, ref, prepared.target_named(label), None)
                continue
            if remote is None:
                missing.append(MissingItem(ref, item.item_id))
                continue
            refuse_another_documents_item(ref, remote, prepared.doc_id)
            reported = tuple(transport.remote_edits_since(item.item_id, item.marker))
            edited = tuple(dict.fromkeys([*differing_parts(item.remote, remote.comparable), *reported]))
            settled, edited = _settled(item, remote, edited, transport)
            if settled != item:
                state = with_item(state, ref, prepared.target_named(label), settled)
            readings.append(Reading(ref, settled, remote, edited, reported))
    return PublishedReadings(readings, state, missing)


def _read_written_into(
    prepared: Prepared, transports: Transports, label: str, step: CreateStep
) -> RemoteItem:
    into_id = step.into_id or ""
    service = prepared.target_named(label).service()
    try:
        remote = transports.for_target(label).read_item(into_id, NOT_YET_PUBLISHED)
    except ItemNotFoundError as exc:
        raise PublishError(
            f"{step.item.label}: the page {into_id} the target names is not in {SERVICE_NAMES[service]}; "
            "name an existing empty page, or publish under one with `parent_page` instead"
        ) from exc
    refuse_another_documents_item(step.item, remote, prepared.doc_id)
    if remote.doc_id is None and _has_content(remote):
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
            part_text(reading.published.remote, part),
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
