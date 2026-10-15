from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from typing_extensions import Self

from skaldr.errors import PublishError
from skaldr.publish.applier import StepListener
from skaldr.publish.drafts import ItemDraft, TargetDraft, item_label
from skaldr.publish.jira.transport import global_id_refusal
from skaldr.publish.plan import ItemRef, published_item
from skaldr.publish.prepared import Prepared, Transports, with_item
from skaldr.publish.state import PublishedItem, PublishState, save_state
from skaldr.publish.transport import LinksWrite, RemoteItem, ShownLink, Stamp
from skaldr.publish_block import TargetBase
from skaldr.publish_block.notion import DASHLESS_PAGE_ID_LENGTH
from skaldr.services import SERVICE_NAMES

LinkAction = Literal["link", "unlink"]
STEP_VERB_WIDTH = 9


@dataclass(frozen=True)
class LinkStep:
    item: ItemRef
    action: LinkAction
    other: str


@dataclass(frozen=True)
class ItemLinkPlan:
    item: ItemRef
    held: PublishedItem | None
    write: LinksWrite
    steps: tuple[LinkStep, ...]

    @property
    def held_matches_planned(self) -> bool:
        return self.held is None or frozenset(self.held.links) == frozenset(self.write.links)


def paired_items(drafts: Sequence[TargetDraft]) -> dict[ItemRef, tuple[ItemRef, ...]]:
    drafted = [
        (draft.target.service(), ItemRef(draft.label, item.section_id))
        for draft in drafts
        for item in draft.items
    ]
    by_section: defaultdict[str | None, list[tuple[str, ItemRef]]] = defaultdict(list[tuple[str, ItemRef]])
    for service, ref in drafted:
        by_section[ref.section_id].append((service, ref))
    pairs = {
        ref: tuple(other for other_service, other in by_section[ref.section_id] if other_service != service)
        for service, ref in drafted
    }
    for draft in drafts:
        document = ItemRef(draft.label, None)
        if draft.target.links_its_sections_from_the_document() and document in pairs:
            sections = (ItemRef(draft.label, item.section_id) for item in draft.sections)
            pairs[document] = (*pairs[document], *sections)
    return pairs


def _service_and_title(link: ShownLink) -> str:
    return f"{SERVICE_NAMES[link.service]} {link.title}"


@dataclass(frozen=True)
class _LinkPlanner:
    prepared: Prepared
    state: PublishState
    transports: Transports
    remote: Mapping[ItemRef, RemoteItem]
    targets: Mapping[str, TargetDraft]
    drafted: Mapping[ItemRef, ItemDraft]

    @classmethod
    def of(
        cls,
        prepared: Prepared,
        state: PublishState,
        transports: Transports,
        remote: Mapping[ItemRef, RemoteItem],
    ) -> Self:
        return cls(
            prepared,
            state,
            transports,
            remote,
            {draft.label: draft for draft in prepared.drafts},
            {
                ItemRef(draft.label, item.section_id): item
                for draft in prepared.drafts
                for item in draft.items
            },
        )

    def plan(self) -> tuple[ItemLinkPlan, ...]:
        return tuple(
            self.item_links(ref, partners)
            for ref, partners in paired_items(self.prepared.drafts).items()
            if partners or self.holds_links(ref)
        )

    def held(self, ref: ItemRef) -> PublishedItem | None:
        return published_item(self.state.targets.get(ref.target), ref.section_id)

    def holds_links(self, ref: ItemRef) -> bool:
        held = self.held(ref)
        return held is not None and bool(held.links)

    def stamp(self, ref: ItemRef) -> Stamp:
        return Stamp(self.prepared.doc_id, ref.section_id)

    def paired_link(self, partner: ItemRef) -> ShownLink | None:
        held = self.held(partner)
        if held is None:
            return None
        title = self.drafted[partner].content.title
        shown = self.transports.for_target(partner.target).item_link(held.item_id, title)
        return ShownLink(
            service=self.targets[partner.target].target.service(),
            item_id=held.item_id,
            url=shown.url,
            title=shown.title if shown.title.strip() else held.item_id,
        )

    def current_links(self, ref: ItemRef, held: PublishedItem) -> tuple[ShownLink, ...]:
        stamp = self.stamp(ref)
        remote = self.remote.get(ref)
        if remote is None or remote.links is None:
            return self.transports.for_target(ref.target).read_links(held.item_id, stamp)
        return remote.links if remote.stamp == stamp else ()

    def item_links(self, ref: ItemRef, partners: Sequence[ItemRef]) -> ItemLinkPlan:
        held = self.held(ref)
        wanted = [(partner, self.paired_link(partner)) for partner in partners]
        links = tuple(link for _, link in wanted if link is not None)
        current = () if held is None else self.current_links(ref, held)
        write = LinksWrite(self.stamp(ref), links, current)
        sent = set(write.sent)
        linked = [
            LinkStep(ref, "link", partner.label) for partner, link in wanted if link is None or link in sent
        ]
        unlinked = [LinkStep(ref, "unlink", _service_and_title(link)) for link in write.dropped]
        return ItemLinkPlan(ref, held, write, (*linked, *unlinked))


def plan_links(
    prepared: Prepared, state: PublishState, transports: Transports, remote: Mapping[ItemRef, RemoteItem]
) -> tuple[ItemLinkPlan, ...]:
    return _LinkPlanner.of(prepared, state, transports, remote).plan()


def refuse_overlong_link_ids(prepared: Prepared) -> None:
    jira_targets = {draft.label for draft in prepared.drafts if draft.target.service() == "jira"}
    for ref, partners in paired_items(prepared.drafts).items():
        if ref.target not in jira_targets or not partners:
            continue
        stamp = Stamp(prepared.doc_id, ref.section_id)
        refusal = global_id_refusal(stamp, "notion", "0" * DASHLESS_PAGE_ID_LENGTH)
        if refusal is not None:
            raise PublishError(f"{ref.label}: {refusal}")


def link_steps(planned: Sequence[ItemLinkPlan]) -> tuple[LinkStep, ...]:
    return tuple(step for item in planned for step in item.steps)


def describe_link_step(step: LinkStep) -> str:
    preposition = "to" if step.action == "link" else "from"
    return f"{step.action:<{STEP_VERB_WIDTH}}{item_label(step.item.section_id)} {preposition} {step.other}"


def describe_links(steps: Sequence[LinkStep]) -> list[str]:
    if not steps:
        return []
    linked = sum(step.action == "link" for step in steps)
    return [
        f"links: {linked} to link, {len(steps) - linked} to unlink",
        *(f"  {step.item.target}: {describe_link_step(step)}" for step in steps),
    ]


def _noted(
    prepared: Prepared, state: PublishState, ref: ItemRef, target: TargetBase, item: PublishedItem
) -> PublishState:
    noted = with_item(state, ref, target, item)
    save_state(prepared.state_path, noted)
    return noted


def apply_links(
    prepared: Prepared,
    state: PublishState,
    transports: Transports,
    remote: Mapping[ItemRef, RemoteItem],
    on_step: StepListener,
) -> tuple[str, ...]:
    planner = _LinkPlanner.of(prepared, state, transports, remote)
    noted = state
    done: list[str] = []
    for planned in planner.plan():
        held = planned.held
        if held is None or (not planned.steps and planned.held_matches_planned):
            continue
        ref = planned.item
        target = planner.targets[ref.target].target
        written = planned.write.links
        if planned.steps:
            sending = tuple(dict.fromkeys([*held.links, *planned.write.links]))
            noted = _noted(prepared, noted, ref, target, held.model_copy(update={"links": sending}))
            written = transports.for_target(ref.target).write_links(held.item_id, planned.write)
        noted = _noted(prepared, noted, ref, target, held.model_copy(update={"links": written}))
        for step in planned.steps:
            described = describe_link_step(step)
            done.append(described)
            on_step(ref.target, described)
    return tuple(done)
