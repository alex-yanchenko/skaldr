from contextlib import ExitStack
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import TracebackType

from typing_extensions import Self

from skaldr.errors import PublishError
from skaldr.publish.connector import ConnectorRegistry
from skaldr.publish.drafts import ItemDraft, TargetDraft, draft_targets, load_authored, published_targets
from skaldr.publish.plan import ItemRef, PublishPlan, plan_publish, published_item
from skaldr.publish.state import PublishedItem, PublishedTarget, PublishState, load_state, state_path_for
from skaldr.publish.transport import Transport
from skaldr.publish_block import TargetBase


@dataclass(frozen=True)
class Prepared:
    document_path: Path
    state_path: Path
    doc_id: str
    state: PublishState
    drafts: tuple[TargetDraft, ...]
    plan: PublishPlan
    registry: ConnectorRegistry

    def target_named(self, label: str) -> TargetBase:
        found = next((target.target for target in self.plan.targets if target.label == label), None)
        if found is None:
            raise PublishError(f"neither the publish block nor the state file names the target '{label}'")
        return found

    def draft_of(self, ref: ItemRef) -> ItemDraft | None:
        drafts = (draft for target in self.drafts if target.label == ref.target for draft in target.items)
        return next((draft for draft in drafts if draft.section_id == ref.section_id), None)

    def with_state(self, state: PublishState) -> "Prepared":
        if state == self.state:
            return self
        return replace(self, state=state, plan=plan_publish(self.drafts, state, self.registry))


def _keeping_what_was_left_alone(draft: ItemDraft, published: PublishedItem | None) -> ItemDraft:
    if published is None:
        return draft
    kept = {
        name: published.rendered.fields[name]
        for name in draft.left_alone
        if name in published.rendered.fields and name not in draft.content.fields
    }
    if not kept:
        return draft
    fields = {**draft.content.fields, **kept}
    return replace(draft, content=draft.content.model_copy(update={"fields": fields}))


def _keeping_what_the_drafts_leave_alone(
    drafts: tuple[TargetDraft, ...], state: PublishState
) -> tuple[TargetDraft, ...]:
    return tuple(
        replace(
            target,
            document=_keeping_what_was_left_alone(
                target.document, published_item(state.targets.get(target.label), None)
            ),
            sections=tuple(
                _keeping_what_was_left_alone(
                    section, published_item(state.targets.get(target.label), section.section_id)
                )
                for section in target.sections
            ),
        )
        for target in drafts
    )


def prepare_publish(document_path: Path, registry: ConnectorRegistry) -> Prepared:
    authored = load_authored(document_path)
    doc_id = published_targets(authored.report).doc_id
    state_path = state_path_for(document_path)
    state = load_state(state_path, doc_id)
    drafts = _keeping_what_the_drafts_leave_alone(draft_targets(authored, registry), state)
    plan = plan_publish(drafts, state, registry)
    return Prepared(document_path, state_path, doc_id, state, drafts, plan, registry)


@dataclass
class Transports:
    prepared: Prepared
    opened: dict[str, Transport] = field(default_factory=dict[str, Transport])
    _closing: ExitStack = field(default_factory=ExitStack)

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._closing.close()

    def for_target(self, label: str, target: TargetBase | None = None) -> Transport:
        if label not in self.opened:
            named = target if target is not None else self.prepared.target_named(label)
            opened = self.prepared.registry.for_target(named).open_transport(named)
            self._closing.callback(opened.close)
            self.opened[label] = opened
        return self.opened[label]


def with_item(
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
