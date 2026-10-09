from dataclasses import dataclass, field, replace
from pathlib import Path

from skaldr.errors import PublishError
from skaldr.models import load_report
from skaldr.publish.connector import ConnectorRegistry
from skaldr.publish.drafts import ItemDraft, TargetDraft, draft_targets, published_targets
from skaldr.publish.plan import ItemRef, PublishPlan, plan_publish
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
        return replace(self, state=state)


def prepare_publish(document_path: Path, registry: ConnectorRegistry) -> Prepared:
    report = load_report(document_path)
    doc_id = published_targets(report).doc_id
    state_path = state_path_for(document_path)
    state = load_state(state_path, doc_id)
    drafts = draft_targets(report, registry)
    plan = plan_publish(drafts, state, registry)
    return Prepared(document_path, state_path, doc_id, state, drafts, plan, registry)


@dataclass
class Transports:
    prepared: Prepared
    opened: dict[str, Transport] = field(default_factory=dict[str, Transport])

    def for_target(self, label: str) -> Transport:
        if label not in self.opened:
            target = self.prepared.target_named(label)
            self.opened[label] = self.prepared.registry.for_target(target).open_transport(target)
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
