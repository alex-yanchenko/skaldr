import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass

from typing_extensions import assert_never

from skaldr.errors import ItemNotFoundError, PublishError
from skaldr.publish.content import ItemContent, Part, comparable, differing_parts
from skaldr.publish.plan import CreateStep, ItemRef
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


def _read(transport: Transport, ref: ItemRef, item: PublishedItem, service: Service) -> RemoteItem:
    try:
        return transport.read_item(item.item_id, item.remote)
    except ItemNotFoundError as exc:
        raise PublishError(
            f"{ref.label} ({item.item_id}) is no longer in {SERVICE_NAMES[service]}, so skaldr stops here "
            "and changes nothing: it cannot tell whether the item was deleted on purpose"
        ) from exc


def _the_interrupted_write_landed(item: PublishedItem, remote: RemoteItem, edited: Sequence[Part]) -> bool:
    if item.writing is None:
        return False
    written = {part.part for part in item.writing.parts}
    return all(
        part in written and part_text(remote.comparable, part) == part_text(item.writing.rendered, part)
        for part in edited
    )


def _settled(
    item: PublishedItem, remote: RemoteItem, edited: tuple[Part, ...]
) -> tuple[PublishedItem, tuple[Part, ...]]:
    if item.writing is None:
        return item, edited
    if not edited:
        return item.model_copy(update={"writing": None}), ()
    if not _the_interrupted_write_landed(item, remote, edited):
        return item, edited
    landed = item.model_copy(
        update={
            "rendered": item.writing.rendered,
            "remote": remote.comparable,
            "marker": remote.marker,
            "writing": None,
        }
    )
    return landed, ()


def read_published(prepared: Prepared, transports: Transports) -> tuple[list[Reading], PublishState]:
    readings: list[Reading] = []
    state = prepared.state
    for label, published_target in prepared.state.targets.items():
        transport = transports.for_target(label)
        for section_id, item in published_target.held_items():
            ref = ItemRef(label, section_id)
            remote = _read(transport, ref, item, published_target.service)
            refuse_another_documents_item(ref, remote, prepared.doc_id)
            reported = tuple(transport.remote_edits_since(item.item_id, item.marker))
            edited = tuple(dict.fromkeys([*differing_parts(item.remote, remote.comparable), *reported]))
            settled, edited = _settled(item, remote, edited)
            if settled != item:
                state = with_item(state, ref, prepared.target_named(label), settled)
            readings.append(Reading(ref, settled, remote, edited, reported))
    return readings, state


def read_items_written_into(prepared: Prepared, transports: Transports) -> dict[ItemRef, RemoteItem]:
    read: dict[ItemRef, RemoteItem] = {}
    for target_plan in prepared.plan.targets:
        for step in target_plan.steps:
            if isinstance(step, CreateStep) and step.into_id is not None:
                remote = transports.for_target(target_plan.label).read_item(step.into_id, NOT_YET_PUBLISHED)
                refuse_another_documents_item(step.item, remote, prepared.doc_id)
                read[step.item] = remote
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
