from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from skaldr.errors import PublishError
from skaldr.publish.applier import Applied, Applier, StepListener
from skaldr.publish.content import FIELDS, TITLE, ItemContent, Part, differing_parts, section_part
from skaldr.publish.drafts import ItemDraft, item_label
from skaldr.publish.plan import ItemRef, PublishPlan, plan_publish, published_item
from skaldr.publish.prepared import Prepared, Transports, prepare_publish, with_item
from skaldr.publish.reading import (
    MissingItem,
    Reading,
    RemoteEdit,
    missing_message,
    part_text,
    read_items_written_into,
    read_published,
    remote_edits,
    settle_interrupted_adoptions,
    shown_token,
)
from skaldr.publish.state import PendingCreate, PublishState, held_state_lock, save_state
from skaldr.publish.transport import RemoteItem

__all__ = [
    "Applied",
    "ApplyOutcome",
    "DryRun",
    "ItemStatus",
    "MissingItem",
    "Prepared",
    "PublishDiff",
    "Refused",
    "RemoteEdit",
    "YamlChange",
    "apply_publish",
    "diff_publish",
    "dry_run_publish",
    "prepare_publish",
    "publish_status",
    "refusal_message",
]

RefusalReason = Literal["edited", "changed since the diff"]
CREATE_INTERRUPTED = "create interrupted"
MISSING_REMOTELY = "missing remotely"


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
    missing_remotely: tuple[MissingItem, ...] = ()


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


@dataclass(frozen=True)
class _Count:
    parts: str
    were: str
    edits: str
    them: str

    @classmethod
    def of(cls, count: int) -> "_Count":
        if count == 1:
            return cls("1 part", "was", "edit", "it")
        return cls(f"{count} parts", "were", "edits", "them")


def refusal_message(refused: Refused) -> str:
    count = _Count.of(len(refused.edits))
    if refused.reason == "edited":
        return (
            f"{count.parts} {count.were} edited in the service since the last publish, so nothing was "
            f"written. To keep the {count.edits}, copy {count.them} into the YAML first; to replace "
            f"{count.them}, publish with --apply --overwrite."
        )
    return (
        f"{count.parts} edited in the service changed after the last diff showed {count.them}, or no diff "
        f"has shown {count.them} yet, so nothing was written. Read the diff above, then publish with "
        "--apply --overwrite again."
    )


@dataclass(frozen=True)
class _Preflight:
    prepared: Prepared
    readings: list[Reading]
    missing: list[MissingItem]
    written_into: dict[ItemRef, RemoteItem]

    @property
    def edited(self) -> list[Reading]:
        return [reading for reading in self.readings if reading.edited]


def _preflight(prepared: Prepared, transports: Transports) -> _Preflight:
    prepared = prepared.with_state(settle_interrupted_adoptions(prepared, transports))
    _refuse_an_interrupted_create(prepared)
    published = read_published(prepared, transports)
    settled = prepared.with_state(published.state)
    written_into = read_items_written_into(settled, settled.plan, transports, {})
    return _Preflight(settled, published.readings, published.missing, written_into)


def _refuse_missing_items(preflight: _Preflight) -> None:
    if preflight.missing:
        missing = preflight.missing[0]
        service = preflight.prepared.target_named(missing.item.target).service()
        raise PublishError(missing_message(missing, service))


def _ignore_step(_target: str, _described: str) -> None:
    return None


def apply_publish(
    prepared: Prepared, *, overwrite: bool = False, on_step: StepListener = _ignore_step
) -> ApplyOutcome:
    with held_state_lock(prepared.state_path, prepared.document_path, "publish --apply"):
        prepared = prepare_publish(prepared.document_path, prepared.registry)
        loaded = prepared.state
        transports = Transports(prepared)
        preflight = _preflight(prepared, transports)
        if not overwrite:
            _refuse_missing_items(preflight)
        edited = preflight.edited
        prepared = preflight.prepared
        refused, prepared = _refusal(prepared, edited, overwrite) if edited else (None, prepared)
        _save_if_changed(prepared, loaded)
        if refused is not None:
            return refused
        rewritten = {reading.item: reading.edited for reading in edited}
        missing = [missing.item for missing in preflight.missing]
        plan = plan_publish(prepared.drafts, prepared.state, prepared.registry, rewritten, missing)
        written_into = read_items_written_into(prepared, plan, transports, preflight.written_into)
        remote = {**written_into, **{reading.item: reading.remote for reading in preflight.readings}}
        return Applier(prepared, transports, remote, on_step, prepared.state).run(plan)


@dataclass(frozen=True)
class DryRun:
    plan: PublishPlan
    edits: tuple[RemoteEdit, ...]
    refusal: str | None


def dry_run_publish(prepared: Prepared) -> DryRun:
    try:
        preflight = _preflight(prepared, Transports(prepared))
        _refuse_missing_items(preflight)
    except PublishError as exc:
        return DryRun(prepared.plan, (), str(exc))
    if preflight.edited:
        edits = remote_edits(preflight.prepared, preflight.edited)
        return DryRun(prepared.plan, edits, refusal_message(Refused(edits, "edited")))
    settled = preflight.prepared
    return DryRun(plan_publish(settled.drafts, settled.state, settled.registry), (), None)


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
    with held_state_lock(prepared.state_path, prepared.document_path, "diff"):
        prepared = prepare_publish(prepared.document_path, prepared.registry)
        loaded = prepared.state
        published = read_published(prepared, Transports(prepared))
        prepared = prepared.with_state(published.state)
        edited = [reading for reading in published.readings if reading.edited]
        prepared = prepared.with_state(_with_shown(prepared, edited))
        _save_if_changed(prepared, loaded)
        return PublishDiff(remote_edits(prepared, edited), _yaml_changes(prepared), tuple(published.missing))


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


@dataclass(frozen=True)
class _StatusFacts:
    readings: dict[ItemRef, Reading]
    missing: dict[ItemRef, str]


def _status_of(ref: ItemRef, draft: ItemDraft | None, prepared: Prepared, facts: _StatusFacts) -> ItemStatus:
    if ref in facts.missing:
        return ItemStatus(ref, facts.missing[ref], (MISSING_REMOTELY,))
    reading = facts.readings.get(ref)
    if reading is None:
        return ItemStatus(ref, None, (_unpublished_state(prepared, ref),))
    states = ("removed",) if draft is None else _item_states(reading, draft)
    return ItemStatus(ref, reading.published.item_id, states)


def publish_status(prepared: Prepared) -> tuple[ItemStatus, ...]:
    published = read_published(prepared, Transports(prepared))
    facts = _StatusFacts(
        {reading.item: reading for reading in published.readings},
        {missing.item: missing.item_id for missing in published.missing},
    )
    drafted = [
        (ItemRef(target.label, draft.section_id), draft)
        for target in prepared.drafts
        for draft in target.items
    ]
    drafted_refs = {ref for ref, _ in drafted}
    held = [ref for ref in (*facts.readings, *facts.missing) if ref not in drafted_refs]
    return (
        *(_status_of(ref, draft, prepared, facts) for ref, draft in drafted),
        *(_status_of(ref, None, prepared, facts) for ref in held),
    )
