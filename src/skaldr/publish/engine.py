from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from skaldr.errors import PublishError
from skaldr.publish.applier import Applied, Applier, StepListener
from skaldr.publish.content import FIELDS, TITLE, ItemContent, Part, differing_parts, section_part
from skaldr.publish.drafts import ItemDraft, item_label
from skaldr.publish.plan import ItemRef, plan_publish, published_item
from skaldr.publish.prepared import Prepared, Transports, prepare_publish, with_item
from skaldr.publish.reading import (
    Reading,
    RemoteEdit,
    part_text,
    read_items_written_into,
    read_published,
    remote_edits,
    shown_token,
)
from skaldr.publish.state import PendingCreate, PublishState, held_state_lock, save_state

__all__ = [
    "Applied",
    "ApplyOutcome",
    "ItemStatus",
    "Prepared",
    "PublishDiff",
    "Refused",
    "RemoteEdit",
    "YamlChange",
    "apply_publish",
    "diff_publish",
    "prepare_publish",
    "publish_status",
]

RefusalReason = Literal["edited", "changed since the diff"]
CREATE_INTERRUPTED = "create interrupted"


@dataclass(frozen=True)
class YamlChange:
    item: ItemRef
    part: Part
    path: str | None
    published: str | None
    next: str | None


@dataclass(frozen=True)
class Refused:
    edits: tuple[RemoteEdit, ...]
    reason: RefusalReason


ApplyOutcome = Applied | Refused


@dataclass(frozen=True)
class PublishDiff:
    remote_edits: tuple[RemoteEdit, ...]
    yaml_changes: tuple[YamlChange, ...]


@dataclass(frozen=True)
class ItemStatus:
    item: ItemRef
    item_id: str | None
    states: tuple[str, ...]


def _with_shown(prepared: Prepared, readings: Sequence[Reading]) -> PublishState:
    state = prepared.state
    for reading in readings:
        shown = reading.published.model_copy(update={"shown_remote": shown_token(reading)})
        state = with_item(state, reading.item, prepared.target_named(reading.item.target), shown)
    return state


def _save_if_changed(prepared: Prepared, loaded: PublishState) -> None:
    if prepared.state != loaded:
        save_state(prepared.state_path, prepared.state)


def _refusal(
    prepared: Prepared, edited: Sequence[Reading], overwrite: bool
) -> tuple[Refused | None, Prepared]:
    if not overwrite:
        return Refused(remote_edits(prepared, edited), "edited"), prepared.with_state(
            _with_shown(prepared, edited)
        )
    unseen = [reading for reading in edited if reading.published.shown_remote != shown_token(reading)]
    if not unseen:
        return None, prepared
    refused = Refused(remote_edits(prepared, unseen), "changed since the diff")
    return refused, prepared.with_state(_with_shown(prepared, unseen))


def _interrupted_create_message(prepared: Prepared, pending: PendingCreate) -> str:
    parent = pending.parent_id or pending.target
    return (
        f"{pending.target}, {item_label(pending.section_id)}: skaldr stopped while creating "
        f'"{pending.title}" under {parent}, so it cannot tell whether that item exists. Look under {parent} '
        f"for an item titled \"{pending.title}\" stamped with doc_id '{prepared.doc_id}' and archive it if "
        f"it is there; then delete its entry from `pending_creates` in {prepared.state_path} and publish "
        "again"
    )


def _refuse_an_interrupted_create(prepared: Prepared) -> None:
    if prepared.state.pending_creates:
        raise PublishError(_interrupted_create_message(prepared, prepared.state.pending_creates[0]))


def _ignore_step(_target: str, _described: str) -> None:
    return None


def apply_publish(
    prepared: Prepared, *, overwrite: bool = False, on_step: StepListener = _ignore_step
) -> ApplyOutcome:
    with held_state_lock(prepared.state_path, prepared.document_path):
        _refuse_an_interrupted_create(prepared)
        loaded = prepared.state
        transports = Transports(prepared)
        readings, settled = read_published(prepared, transports)
        prepared = prepared.with_state(settled)
        written_into = read_items_written_into(prepared, transports)
        edited = [reading for reading in readings if reading.edited]
        refused, prepared = _refusal(prepared, edited, overwrite) if edited else (None, prepared)
        _save_if_changed(prepared, loaded)
        if refused is not None:
            return refused
        rewritten = {reading.item: reading.edited for reading in edited}
        plan = plan_publish(prepared.drafts, prepared.state, prepared.registry, rewritten)
        remote = {**written_into, **{reading.item: reading.remote for reading in readings}}
        return Applier(prepared, transports, remote, on_step, prepared.state).run(plan)


def _changes_of_item(
    ref: ItemRef, published: ItemContent | None, draft: ItemDraft | None, parts: Sequence[Part]
) -> list[YamlChange]:
    drafted = None if draft is None else draft.content
    return [
        YamlChange(
            ref,
            part,
            None if draft is None else draft.paths.get(part),
            part_text(published, part),
            part_text(drafted, part),
        )
        for part in parts
    ]


def _whole_item_parts(content: ItemContent) -> list[Part]:
    fields: list[Part] = [FIELDS] if content.fields else []
    return [TITLE, *fields, *(section_part(key) for key in content.sections)]


def _yaml_changes(prepared: Prepared) -> tuple[YamlChange, ...]:
    changes: list[YamlChange] = []
    drafted: set[ItemRef] = set()
    for target in prepared.drafts:
        for draft in target.items:
            ref = ItemRef(target.label, draft.section_id)
            drafted.add(ref)
            published = published_item(prepared.state.targets.get(target.label), draft.section_id)
            parts = (
                _whole_item_parts(draft.content)
                if published is None
                else list(differing_parts(published.rendered, draft.content))
            )
            changes += _changes_of_item(ref, None if published is None else published.rendered, draft, parts)
    for label, published_target in prepared.state.targets.items():
        for section_id, item in published_target.held_items():
            ref = ItemRef(label, section_id)
            if ref not in drafted:
                changes += _changes_of_item(ref, item.rendered, None, _whole_item_parts(item.rendered))
    return tuple(changes)


def diff_publish(prepared: Prepared) -> PublishDiff:
    with held_state_lock(prepared.state_path, prepared.document_path):
        loaded = prepared.state
        readings, settled = read_published(prepared, Transports(prepared))
        prepared = prepared.with_state(settled)
        edited = [reading for reading in readings if reading.edited]
        prepared = prepared.with_state(_with_shown(prepared, edited))
        _save_if_changed(prepared, loaded)
        return PublishDiff(remote_edits(prepared, edited), _yaml_changes(prepared))


def _item_states(reading: Reading, draft: ItemDraft) -> tuple[str, ...]:
    states = [
        *(("edited remotely",) if reading.edited else ()),
        *(("changed in the YAML",) if differing_parts(reading.published.rendered, draft.content) else ()),
    ]
    return tuple(states) or ("in sync",)


def _unpublished_state(prepared: Prepared, ref: ItemRef) -> str:
    interrupted = any(
        pending.target == ref.target and pending.section_id == ref.section_id
        for pending in prepared.state.pending_creates
    )
    return CREATE_INTERRUPTED if interrupted else "never published"


def publish_status(prepared: Prepared) -> tuple[ItemStatus, ...]:
    readings, _ = read_published(prepared, Transports(prepared))
    by_item = {reading.item: reading for reading in readings}
    statuses: list[ItemStatus] = []
    for target in prepared.drafts:
        for draft in target.items:
            ref = ItemRef(target.label, draft.section_id)
            reading = by_item.pop(ref, None)
            if reading is None:
                statuses.append(ItemStatus(ref, None, (_unpublished_state(prepared, ref),)))
            else:
                statuses.append(ItemStatus(ref, reading.published.item_id, _item_states(reading, draft)))
    statuses += [ItemStatus(ref, reading.published.item_id, ("removed",)) for ref, reading in by_item.items()]
    return tuple(statuses)
