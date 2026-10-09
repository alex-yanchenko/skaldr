import hashlib
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from typing_extensions import assert_never

from skaldr.errors import PublishError
from skaldr.models import load_report
from skaldr.publish.connector import ConnectorRegistry
from skaldr.publish.content import (
    FIELDS,
    TITLE,
    ItemContent,
    Part,
    comparable,
    content_digest,
    differing_parts,
    placed_section,
    section_part,
)
from skaldr.publish.drafts import ItemDraft, TargetDraft, draft_targets, published_targets
from skaldr.publish.plan import (
    ArchiveStep,
    CreateStep,
    ItemRef,
    PublishPlan,
    RemoveSectionStep,
    Step,
    TargetPlan,
    WriteContentStep,
    WriteFieldsStep,
    WriteSectionStep,
    describe_step,
    plan_publish,
    published_item,
)
from skaldr.publish.state import (
    PublishedItem,
    PublishedTarget,
    PublishState,
    load_state,
    save_state,
    state_path_for,
)
from skaldr.publish.transport import (
    NO_SECTIONS,
    AddSection,
    FieldsWrite,
    NewItem,
    RawSections,
    RemoteItem,
    RemoveSection,
    ReplaceSection,
    SectionWrite,
    Stamp,
    Transport,
)
from skaldr.publish_block import TargetBase

RefusalReason = Literal["edited", "changed since the diff"]
StepListener = Callable[[str, str], None]
NOT_YET_PUBLISHED = ItemContent(title="")


@dataclass(frozen=True)
class Prepared:
    state_path: Path
    doc_id: str
    state: PublishState
    drafts: tuple[TargetDraft, ...]
    plan: PublishPlan
    registry: ConnectorRegistry

    def target_named(self, label: str) -> TargetBase:
        return next(target_plan.target for target_plan in self.plan.targets if target_plan.label == label)

    def draft_of(self, ref: ItemRef) -> ItemDraft | None:
        drafts = (draft for target in self.drafts if target.label == ref.target for draft in target.items)
        return next((draft for draft in drafts if draft.section_id == ref.section_id), None)


@dataclass(frozen=True)
class RemoteEdit:
    item: ItemRef
    part: Part
    path: str | None
    published: str | None
    current: str | None
    edited_by: str | None
    edited_at: str | None


@dataclass(frozen=True)
class YamlChange:
    item: ItemRef
    part: Part
    path: str | None
    published: str | None
    next: str | None


@dataclass(frozen=True)
class Applied:
    steps: tuple[str, ...]


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


@dataclass(frozen=True)
class _Reading:
    item: ItemRef
    published: PublishedItem
    remote: RemoteItem
    edited: tuple[Part, ...]


@dataclass
class _Transports:
    prepared: Prepared
    opened: dict[str, Transport] = field(default_factory=dict[str, Transport])

    def for_target(self, label: str) -> Transport:
        if label not in self.opened:
            target = self.prepared.target_named(label)
            self.opened[label] = self.prepared.registry.for_target(target).open_transport(target)
        return self.opened[label]


def prepare_publish(document_path: Path, registry: ConnectorRegistry) -> Prepared:
    report = load_report(document_path)
    doc_id = published_targets(report).doc_id
    state_path = state_path_for(document_path)
    state = load_state(state_path, doc_id)
    drafts = draft_targets(report, registry)
    return Prepared(state_path, doc_id, state, drafts, plan_publish(drafts, state, registry), registry)


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


def _part_path(prepared: Prepared, ref: ItemRef, part: Part) -> str | None:
    draft = prepared.draft_of(ref)
    return None if draft is None else draft.paths.get(part)


def _refuse_another_documents_item(ref: ItemRef, remote: RemoteItem, doc_id: str) -> None:
    if remote.doc_id is not None and remote.doc_id != doc_id:
        raise PublishError(
            f"{ref.label} ({remote.item_id}) is stamped with doc_id '{remote.doc_id}', so it belongs to that "
            f"document and not to '{doc_id}'; skaldr writes only to items of the document it publishes"
        )


def _read_published(prepared: Prepared, transports: _Transports) -> list[_Reading]:
    readings: list[_Reading] = []
    for label, published_target in prepared.state.targets.items():
        transport = transports.for_target(label)
        for section_id, item in published_target.held_items():
            ref = ItemRef(label, section_id)
            remote = transport.read_item(item.item_id, item.remote)
            _refuse_another_documents_item(ref, remote, prepared.doc_id)
            reported = transport.remote_edits_since(item.item_id, item.marker)
            edited = tuple(dict.fromkeys([*differing_parts(item.remote, remote.comparable), *reported]))
            readings.append(_Reading(ref, item, remote, edited))
    return readings


def _read_items_written_into(prepared: Prepared, transports: _Transports) -> dict[ItemRef, RemoteItem]:
    read: dict[ItemRef, RemoteItem] = {}
    for target_plan in prepared.plan.targets:
        for step in target_plan.steps:
            if isinstance(step, CreateStep) and step.into_id is not None:
                remote = transports.for_target(target_plan.label).read_item(step.into_id, NOT_YET_PUBLISHED)
                _refuse_another_documents_item(step.item, remote, prepared.doc_id)
                read[step.item] = remote
    return read


def _remote_edits(prepared: Prepared, readings: Sequence[_Reading]) -> tuple[RemoteEdit, ...]:
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


def _shown_token(remote: RemoteItem) -> str:
    seen = f"{content_digest(remote.comparable)}:{remote.marker or ''}"
    return hashlib.sha256(seen.encode("utf-8")).hexdigest()


def _with_item(
    state: PublishState, ref: ItemRef, target: TargetBase, item: PublishedItem | None
) -> PublishState:
    published = state.targets.get(ref.target) or PublishedTarget(
        service=target.service(), target=target.model_dump(mode="json")
    )
    if ref.section_id is None:
        published = published.model_copy(update={"document": item})
    else:
        sections = {key: held for key, held in published.sections.items() if key != ref.section_id}
        if item is not None:
            sections = {**published.sections, ref.section_id: item}
        published = published.model_copy(update={"sections": sections})
    targets = dict(state.targets)
    if published.held_items():
        targets[ref.target] = published
    else:
        targets.pop(ref.target, None)
    return state.model_copy(update={"targets": targets})


def _with_shown(prepared: Prepared, readings: Sequence[_Reading]) -> PublishState:
    state = prepared.state
    for reading in readings:
        shown = reading.published.model_copy(update={"shown_remote": _shown_token(reading.remote)})
        state = _with_item(state, reading.item, prepared.target_named(reading.item.target), shown)
    return state


def _record_shown(prepared: Prepared, readings: Sequence[_Reading]) -> None:
    state = _with_shown(prepared, readings)
    if state != prepared.state:
        save_state(prepared.state_path, state)


def _refusal(prepared: Prepared, edited: Sequence[_Reading], overwrite: bool) -> Refused | None:
    if not overwrite:
        _record_shown(prepared, edited)
        return Refused(_remote_edits(prepared, edited), "edited")
    unseen = [reading for reading in edited if reading.published.shown_remote != _shown_token(reading.remote)]
    if not unseen:
        return None
    _record_shown(prepared, unseen)
    return Refused(_remote_edits(prepared, unseen), "changed since the diff")


@dataclass
class _Applier:
    prepared: Prepared
    transports: _Transports
    remote: dict[ItemRef, RemoteItem]
    on_step: StepListener
    state: PublishState
    done: list[str] = field(default_factory=list[str])

    def run(self, plan: PublishPlan) -> Applied:
        for target_plan in plan.targets:
            for step in target_plan.steps:
                self.state = self._applied(target_plan, step)
                save_state(self.prepared.state_path, self.state)
                described = describe_step(step)
                self.done.append(described)
                self.on_step(target_plan.label, described)
        self._keep_each_target_as_written()
        return Applied(tuple(self.done))

    def _keep_each_target_as_written(self) -> None:
        targets = dict(self.state.targets)
        for draft in self.prepared.drafts:
            published = targets.get(draft.label)
            if published is not None:
                targets[draft.label] = published.model_copy(
                    update={"target": draft.target.model_dump(mode="json")}
                )
        state = self.state.model_copy(update={"targets": targets})
        if state != self.state:
            self.state = state
            save_state(self.prepared.state_path, state)

    def _item(self, ref: ItemRef) -> PublishedItem:
        item = published_item(self.state.targets.get(ref.target), ref.section_id)
        if item is None:
            raise PublishError(f"{ref.label} is not in the state file, so skaldr cannot write to it")
        return item

    def _after_write(
        self, step_plan: TargetPlan, ref: ItemRef, rendered: ItemContent, remote: RemoteItem
    ) -> PublishState:
        self.remote[ref] = remote
        written = self._item(ref).model_copy(
            update={
                "rendered": rendered,
                "remote": remote.comparable,
                "marker": remote.marker,
                "shown_remote": None,
            }
        )
        return _with_item(self.state, ref, step_plan.target, written)

    def _raw_sections(self, ref: ItemRef) -> RawSections:
        return self.remote[ref].raw_sections if ref in self.remote else NO_SECTIONS

    def _write_section(
        self, target_plan: TargetPlan, ref: ItemRef, key: str, text: str | None, follows: str | None
    ) -> PublishState:
        item = self._item(ref)
        rendered = item.rendered.model_copy(
            update={"sections": placed_section(item.rendered.sections, key, text, follows)}
        )
        raw_sections = self._raw_sections(ref)
        write = _section_write(key, raw_sections.get(key), text, follows)
        if write is None:
            return _with_item(
                self.state, ref, target_plan.target, item.model_copy(update={"rendered": rendered})
            )
        transport = self.transports.for_target(ref.target)
        remote = transport.write_section(item.item_id, write, raw_sections)
        return self._after_write(target_plan, ref, rendered, remote)

    def _write_content(self, target_plan: TargetPlan, step: WriteContentStep) -> PublishState:
        item = self._item(step.item)
        transport = self.transports.for_target(step.item.target)
        remote = transport.write_content(item.item_id, step.content.sections, self._raw_sections(step.item))
        rendered = item.rendered.model_copy(update={"sections": step.content.sections})
        return self._after_write(target_plan, step.item, rendered, remote)

    def _write_fields(self, target_plan: TargetPlan, step: WriteFieldsStep) -> PublishState:
        item = self._item(step.item)
        now = self.remote[step.item].comparable if step.item in self.remote else item.remote
        write = FieldsWrite(
            step.content.title,
            step.content.fields,
            now.title,
            now.fields,
            Stamp(self.prepared.doc_id, step.item.section_id),
        )
        remote = self.transports.for_target(step.item.target).write_fields(item.item_id, write)
        rendered = item.rendered.model_copy(
            update={"title": step.content.title, "fields": step.content.fields}
        )
        return self._after_write(target_plan, step.item, rendered, remote)

    def _applied(self, target_plan: TargetPlan, step: Step) -> PublishState:
        match step:
            case CreateStep():
                return self._created(target_plan, step)
            case WriteFieldsStep():
                return self._write_fields(target_plan, step)
            case WriteSectionStep():
                return self._write_section(target_plan, step.item, step.key, step.text, step.follows)
            case RemoveSectionStep():
                return self._write_section(target_plan, step.item, step.key, None, None)
            case WriteContentStep():
                return self._write_content(target_plan, step)
            case ArchiveStep():
                self.transports.for_target(target_plan.label).archive_item(step.item_id)
                return _with_item(self.state, step.item, target_plan.target, None)
            case _:
                assert_never(step)

    def _created(self, target_plan: TargetPlan, step: CreateStep) -> PublishState:
        parent = None if step.item.section_id is None else self._item(ItemRef(step.item.target, None))
        written_into = self.remote.get(step.item)
        remote = self.transports.for_target(target_plan.label).create_item(
            NewItem(
                target_plan.target,
                Stamp(self.prepared.doc_id, step.item.section_id),
                step.draft.content,
                parent_id=None if parent is None else parent.item_id,
                into_id=step.into_id,
                into_raw_sections=NO_SECTIONS if written_into is None else written_into.raw_sections,
            )
        )
        self.remote[step.item] = remote
        created = PublishedItem(
            item_id=remote.item_id,
            rendered=step.draft.content,
            remote=remote.comparable,
            marker=remote.marker,
        )
        return _with_item(self.state, step.item, target_plan.target, created)


def _section_write(
    key: str, raw_current: str | None, text: str | None, follows: str | None
) -> SectionWrite | None:
    if text is None:
        return None if raw_current is None else RemoveSection(key, raw_current)
    if raw_current is None:
        return AddSection(key, text, follows)
    return ReplaceSection(key, raw_current, text, follows)


def _ignore_step(_target: str, _described: str) -> None:
    return None


def apply_publish(
    prepared: Prepared, *, overwrite: bool = False, on_step: StepListener = _ignore_step
) -> ApplyOutcome:
    transports = _Transports(prepared)
    readings = _read_published(prepared, transports)
    written_into = _read_items_written_into(prepared, transports)
    edited = [reading for reading in readings if reading.edited]
    refusal = _refusal(prepared, edited, overwrite) if edited else None
    if refusal is not None:
        return refusal
    plan = plan_publish(
        prepared.drafts,
        prepared.state,
        prepared.registry,
        {reading.item: reading.edited for reading in edited},
    )
    remote = {**written_into, **{reading.item: reading.remote for reading in readings}}
    return _Applier(prepared, transports, remote, on_step, prepared.state).run(plan)


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
    readings = _read_published(prepared, _Transports(prepared))
    edited = [reading for reading in readings if reading.edited]
    _record_shown(prepared, edited)
    return PublishDiff(_remote_edits(prepared, edited), _yaml_changes(prepared))


def _item_states(reading: _Reading, draft: ItemDraft | None) -> tuple[str, ...]:
    if draft is None:
        return ("removed",)
    states = [
        *(("edited remotely",) if reading.edited else ()),
        *(("changed in the YAML",) if differing_parts(reading.published.rendered, draft.content) else ()),
    ]
    return tuple(states) or ("in sync",)


def publish_status(prepared: Prepared) -> tuple[ItemStatus, ...]:
    readings = {reading.item: reading for reading in _read_published(prepared, _Transports(prepared))}
    statuses: list[ItemStatus] = []
    for target in prepared.drafts:
        for draft in target.items:
            ref = ItemRef(target.label, draft.section_id)
            reading = readings.pop(ref, None)
            if reading is None:
                statuses.append(ItemStatus(ref, None, ("never published",)))
            else:
                statuses.append(ItemStatus(ref, reading.published.item_id, _item_states(reading, draft)))
    statuses += [
        ItemStatus(ref, reading.published.item_id, ("removed",)) for ref, reading in readings.items()
    ]
    return tuple(statuses)
