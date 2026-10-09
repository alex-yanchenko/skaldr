from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

from typing_extensions import assert_never

from skaldr.errors import PublishError
from skaldr.publish.connector import Connector, ConnectorRegistry, WriteGranularity
from skaldr.publish.content import (
    FIELDS,
    TITLE,
    ItemContent,
    Part,
    same_fields,
    section_changes,
    section_part,
)
from skaldr.publish.drafts import ItemDraft, TargetDraft, item_label, section_label
from skaldr.publish.state import PublishedItem, PublishedTarget, PublishState
from skaldr.publish_block import TargetBase


@dataclass(frozen=True)
class ItemRef:
    target: str
    section_id: str | None

    @property
    def label(self) -> str:
        return f"{self.target}, {item_label(self.section_id)}"


@dataclass(frozen=True)
class CreateStep:
    item: ItemRef
    draft: ItemDraft
    into_id: str | None = None


@dataclass(frozen=True)
class WriteFieldsStep:
    item: ItemRef
    parts: tuple[Part, ...]
    content: ItemContent


@dataclass(frozen=True)
class WriteSectionStep:
    item: ItemRef
    key: str
    text: str
    follows: str | None
    path: str


@dataclass(frozen=True)
class ArchiveStep:
    item: ItemRef
    item_id: str


@dataclass(frozen=True)
class RemoveSectionStep:
    item: ItemRef
    key: str


@dataclass(frozen=True)
class WriteContentStep:
    item: ItemRef
    written: tuple[str, ...]
    removed: tuple[str, ...]
    content: ItemContent
    paths: Mapping[Part, str]


Step = CreateStep | WriteFieldsStep | WriteSectionStep | RemoveSectionStep | WriteContentStep | ArchiveStep
ItemUpdate = WriteFieldsStep | WriteSectionStep | RemoveSectionStep | WriteContentStep


@dataclass(frozen=True)
class TargetPlan:
    label: str
    target: TargetBase
    steps: tuple[Step, ...]


@dataclass(frozen=True)
class PublishPlan:
    targets: tuple[TargetPlan, ...]


def published_item(published: PublishedTarget | None, section_id: str | None) -> PublishedItem | None:
    if published is None:
        return None
    return published.document if section_id is None else published.sections.get(section_id)


def _field_parts(last: ItemContent, content: ItemContent, rewritten: Collection[Part]) -> tuple[Part, ...]:
    differs = {TITLE: last.title != content.title, FIELDS: not same_fields(last.fields, content.fields)}
    return tuple(part for part, changed in differs.items() if changed or part in rewritten)


def _section_updates(
    item: ItemRef, draft: ItemDraft, written: Collection[str], removed: Sequence[str]
) -> list[ItemUpdate]:
    updates: list[ItemUpdate] = []
    previous: str | None = None
    for key, text in draft.content.sections.items():
        if key in written:
            updates.append(WriteSectionStep(item, key, text, previous, draft.paths[section_part(key)]))
        previous = key
    return [*updates, *(RemoveSectionStep(item, key) for key in removed)]


def item_steps(
    item: ItemRef,
    last: ItemContent,
    draft: ItemDraft,
    writes: WriteGranularity,
    rewritten: Collection[Part] = (),
) -> tuple[ItemUpdate, ...]:
    content = draft.content
    changes = section_changes(last.sections, content.sections)
    rewritten_keys = [part.key for part in rewritten if part.kind == "section"]
    written = {*changes.written, *(key for key in rewritten_keys if key in content.sections)}
    removed = list(
        dict.fromkeys([*changes.removed, *(key for key in rewritten_keys if key not in content.sections)])
    )
    field_parts = _field_parts(last, content, rewritten)
    fields: list[ItemUpdate] = [WriteFieldsStep(item, field_parts, content)] if field_parts else []
    if not written and not removed:
        return tuple(fields)
    if writes == "content":
        ordered = tuple(key for key in content.sections if key in written)
        return (*fields, WriteContentStep(item, ordered, tuple(removed), content, draft.paths))
    return (*fields, *_section_updates(item, draft, written, removed))


def _target_plan(
    draft: TargetDraft,
    published: PublishedTarget | None,
    connector: Connector,
    rewritten: Mapping[ItemRef, Collection[Part]],
) -> TargetPlan:
    creates: list[Step] = []
    updates: list[Step] = []
    for item in draft.items:
        ref = ItemRef(draft.label, item.section_id)
        existing = published_item(published, item.section_id)
        if existing is None:
            into_id = connector.existing_item_id(draft.target) if item.section_id is None else None
            creates.append(CreateStep(ref, item, into_id))
            continue
        updates += item_steps(ref, existing.rendered, item, connector.writes, rewritten.get(ref, ()))
    drafted = {item.section_id for item in draft.sections}
    archives: list[Step] = [
        ArchiveStep(ItemRef(draft.label, section_id), item.item_id)
        for section_id, item in (published.sections.items() if published is not None else ())
        if section_id not in drafted
    ]
    return TargetPlan(draft.label, draft.target, (*creates, *updates, *archives))


def _removed_target_plan(label: str, published: PublishedTarget, registry: ConnectorRegistry) -> TargetPlan:
    target = registry.for_service(published.service).target_type.model_validate(published.target)
    archives = [
        ArchiveStep(ItemRef(label, section_id), item.item_id)
        for section_id, item in published.sections.items()
    ]
    if published.document is not None:
        archives.append(ArchiveStep(ItemRef(label, None), published.document.item_id))
    return TargetPlan(label, target, tuple(archives))


def _refuse_shared_items(state: PublishState) -> None:
    first_holder: dict[tuple[str, str], ItemRef] = {}
    for label, published in state.targets.items():
        for section_id, item in published.held_items():
            ref = ItemRef(label, section_id)
            holder = first_holder.setdefault((published.service, item.item_id), ref)
            if holder != ref:
                raise PublishError(
                    f"the state file lists {item.item_id} as both {holder.label} and {ref.label}; two items "
                    "may not write to one place, so restore the state file"
                )


def plan_publish(
    drafts: Sequence[TargetDraft],
    state: PublishState,
    registry: ConnectorRegistry,
    rewritten: Mapping[ItemRef, Collection[Part]] = MappingProxyType({}),
) -> PublishPlan:
    _refuse_shared_items(state)
    drafted = {draft.label for draft in drafts}
    return PublishPlan(
        (
            *(
                _target_plan(
                    draft, state.targets.get(draft.label), registry.for_target(draft.target), rewritten
                )
                for draft in drafts
            ),
            *(
                _removed_target_plan(label, published, registry)
                for label, published in state.targets.items()
                if label not in drafted
            ),
        )
    )


def describe_step(step: Step) -> str:
    match step:
        case CreateStep():
            into = f" into {step.into_id}" if step.into_id else ""
            return f'create   {item_label(step.item.section_id)} "{step.draft.content.title}"{into}'
        case WriteFieldsStep():
            return (
                f"update   {item_label(step.item.section_id)}: {', '.join(part.label for part in step.parts)}"
            )
        case WriteSectionStep():
            return f"update   {item_label(step.item.section_id)}: {section_label(step.key, step.path)}"
        case RemoveSectionStep():
            return f"remove   {item_label(step.item.section_id)}: {step.key}"
        case WriteContentStep():
            written = [section_label(key, step.paths.get(section_part(key))) for key in step.written]
            removed = [f"remove {key}" for key in step.removed]
            return f"update   {item_label(step.item.section_id)}: {', '.join([*written, *removed])}"
        case ArchiveStep():
            return f"archive  {item_label(step.item.section_id)} ({step.item_id})"
        case _:
            assert_never(step)


def _counts(steps: Sequence[Step]) -> str:
    creates = sum(isinstance(step, CreateStep) for step in steps)
    archives = sum(isinstance(step, ArchiveStep) for step in steps)
    updates = len(steps) - creates - archives
    return f"{creates} to create, {updates} to update, {archives} to archive"


def describe_plan(plan: PublishPlan) -> list[str]:
    lines: list[str] = []
    for target in plan.targets:
        if not target.steps:
            lines.append(f"{target.label}: nothing to change")
            continue
        lines.append(f"{target.label}: {_counts(target.steps)}")
        lines += [f"  {describe_step(step)}" for step in target.steps]
    return lines
