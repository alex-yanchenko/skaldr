from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from skaldr.publish.applier import StepListener
from skaldr.publish.drafts import TargetDraft, item_label
from skaldr.publish.plan import ItemRef, published_item
from skaldr.publish.prepared import Prepared, Transports, with_item
from skaldr.publish.state import PublishedItem, PublishState, save_state
from skaldr.publish.transport import LinksWrite, PairedLink, RemoteItem, ShownLink, Stamp
from skaldr.publish_block import TargetBase

LinkAction = Literal["link", "unlink"]
STEP_VERB_WIDTH = 9


@dataclass(frozen=True)
class LinkStep:
    item: ItemRef
    action: LinkAction
    other: str


@dataclass(frozen=True)
class ItemLinks:
    item: ItemRef
    held: PublishedItem | None
    links: tuple[PairedLink, ...]
    steps: tuple[LinkStep, ...]

    @property
    def shown(self) -> tuple[ShownLink, ...]:
        return tuple(link.shown for link in self.links)

    @property
    def held_matches_shown(self) -> bool:
        return self.held is None or tuple(self.held.links) == self.shown


def paired_items(drafts: Sequence[TargetDraft]) -> dict[ItemRef, tuple[ItemRef, ...]]:
    drafted = [
        (draft.target.service(), ItemRef(draft.label, item.section_id))
        for draft in drafts
        for item in draft.items
    ]
    return {
        ref: tuple(
            other
            for other_service, other in drafted
            if other_service != service and other.section_id == ref.section_id
        )
        for service, ref in drafted
    }


@dataclass(frozen=True)
class _Linking:
    prepared: Prepared
    state: PublishState
    transports: Transports
    remote: Mapping[ItemRef, RemoteItem]
    targets: Mapping[str, TargetDraft]

    def held(self, ref: ItemRef) -> PublishedItem | None:
        return published_item(self.state.targets.get(ref.target), ref.section_id)

    def stamp(self, ref: ItemRef) -> Stamp:
        return Stamp(self.prepared.doc_id, ref.section_id)

    def paired_link(self, partner: ItemRef) -> PairedLink | None:
        held = self.held(partner)
        draft = self.prepared.draft_of(partner)
        if held is None or draft is None:
            return None
        shown = self.transports.for_target(partner.target).item_link(held.item_id, draft.content.title)
        service = self.targets[partner.target].target.service()
        return PairedLink(service, held.item_id, shown.url, shown.title)

    def current_links(self, ref: ItemRef, held: PublishedItem) -> tuple[ShownLink, ...]:
        stamp = self.stamp(ref)
        remote = self.remote.get(ref)
        if remote is None or remote.links is None:
            return self.transports.for_target(ref.target).read_links(held.item_id, stamp)
        return remote.links if remote.stamp == stamp else ()

    def item_links(self, ref: ItemRef, partners: Sequence[ItemRef]) -> ItemLinks:
        held = self.held(ref)
        wanted = [(partner, self.paired_link(partner)) for partner in partners]
        links = tuple(link for _, link in wanted if link is not None)
        if held is None:
            return ItemLinks(
                ref, None, links, tuple(LinkStep(ref, "link", partner.label) for partner in partners)
            )
        current = self.current_links(ref, held)
        addresses = {link.url for link in links}
        linked = [
            LinkStep(ref, "link", partner.label)
            for partner, link in wanted
            if link is None or link.shown not in current
        ]
        unlinked = [LinkStep(ref, "unlink", link.title) for link in current if link.url not in addresses]
        return ItemLinks(ref, held, links, (*linked, *unlinked))


def _linking(
    prepared: Prepared, state: PublishState, transports: Transports, remote: Mapping[ItemRef, RemoteItem]
) -> _Linking:
    return _Linking(prepared, state, transports, remote, {draft.label: draft for draft in prepared.drafts})


def plan_links(
    prepared: Prepared, state: PublishState, transports: Transports, remote: Mapping[ItemRef, RemoteItem]
) -> tuple[ItemLinks, ...]:
    linking = _linking(prepared, state, transports, remote)
    planned: list[ItemLinks] = []
    for ref, partners in paired_items(prepared.drafts).items():
        held = linking.held(ref)
        if partners or (held is not None and held.links):
            planned.append(linking.item_links(ref, partners))
    return tuple(planned)


def link_steps(planned: Sequence[ItemLinks]) -> tuple[LinkStep, ...]:
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
    linking = _linking(prepared, state, transports, remote)
    noted = state
    done: list[str] = []
    for planned in plan_links(prepared, state, transports, remote):
        held = planned.held
        if held is None or (not planned.steps and planned.held_matches_shown):
            continue
        ref = planned.item
        target = linking.targets[ref.target].target
        written = planned.shown
        if planned.steps:
            sending = list(dict.fromkeys([*held.links, *planned.shown]))
            noted = _noted(prepared, noted, ref, target, held.model_copy(update={"links": sending}))
            transport = transports.for_target(ref.target)
            written = transport.write_links(held.item_id, LinksWrite(linking.stamp(ref), planned.links))
        noted = _noted(prepared, noted, ref, target, held.model_copy(update={"links": list(written)}))
        for step in planned.steps:
            described = describe_link_step(step)
            done.append(described)
            on_step(ref.target, described)
    return tuple(done)
