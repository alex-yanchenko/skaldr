from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace

from typing_extensions import assert_never

from skaldr.errors import PublishError, WriteRejectedError
from skaldr.publish.content import (
    ItemContent,
    Part,
    placed_section,
    section_part,
    with_fields_named,
    with_parts,
)
from skaldr.publish.plan import (
    ArchiveStep,
    CreateStep,
    ItemRef,
    PublishPlan,
    ReleaseStep,
    RemoveSectionStep,
    Step,
    TargetPlan,
    WriteContentStep,
    WriteFieldsStep,
    WriteSectionStep,
    describe_step,
    published_item,
)
from skaldr.publish.prepared import Prepared, Transports, with_item
from skaldr.publish.state import (
    InFlightWrite,
    PendingCreate,
    PublishedItem,
    PublishState,
    Retirement,
    WritingPart,
    save_state,
)
from skaldr.publish.transport import (
    NO_SECTIONS,
    AddSection,
    ContentWrite,
    FieldsWrite,
    NewItem,
    RawSections,
    Release,
    RemoteItem,
    RemoveSection,
    ReplaceSection,
    SectionRequest,
    SectionWrite,
    Stamp,
)

StepListener = Callable[[str, str], None]


@dataclass(frozen=True)
class Applied:
    steps: tuple[str, ...]


def _section_write(
    key: str, raw_current: str | None, text: str | None, follows: str | None
) -> SectionWrite | None:
    if text is None:
        return None if raw_current is None else RemoveSection(key, raw_current)
    if raw_current is None:
        return AddSection(key, text, follows)
    return ReplaceSection(key, raw_current, text, follows)


def _raw_with_written_parts(read: RawSections, read_back: RawSections, parts: Sequence[Part]) -> RawSections:
    written = {part.key for part in parts if part.kind == "section"}
    return {key: text if key in written or key not in read else read[key] for key, text in read_back.items()}


@dataclass
class Applier:
    prepared: Prepared
    transports: Transports
    remote: dict[ItemRef, RemoteItem]
    on_step: StepListener
    state: PublishState
    done: list[str] = field(default_factory=list[str])

    def run(self, plan: PublishPlan) -> Applied:
        for target_plan in plan.targets:
            for step in target_plan.steps:
                self._save(self._applied(target_plan, step))
                described = describe_step(step)
                self.done.append(described)
                self.on_step(target_plan.label, described)
        self._keep_each_target_as_written()
        return Applied(tuple(self.done))

    def _save(self, state: PublishState) -> None:
        self.state = state
        save_state(self.prepared.state_path, state)

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
            self._save(state)

    def _item(self, ref: ItemRef) -> PublishedItem:
        item = published_item(self.state.targets.get(ref.target), ref.section_id)
        if item is None:
            raise PublishError(f"{ref.label} is not in the state file, so skaldr cannot write to it")
        return item

    def _start_writing(
        self, target_plan: TargetPlan, ref: ItemRef, parts: Sequence[Part], rendered: ItemContent
    ) -> PublishedItem:
        writing = InFlightWrite(
            parts=[WritingPart(kind=part.kind, key=part.key) for part in parts], rendered=rendered
        )
        item = self._item(ref).model_copy(update={"writing": writing})
        self._save(with_item(self.state, ref, target_plan.target, item))
        return item

    def _after_write(
        self,
        target_plan: TargetPlan,
        ref: ItemRef,
        intent: tuple[Sequence[Part], ItemContent],
        remote: RemoteItem,
    ) -> PublishState:
        parts, rendered = intent
        item = self._item(ref)
        owned = list(rendered.fields)
        read_back = with_fields_named(remote.comparable, owned)
        self.remote[ref] = replace(
            remote,
            comparable=with_parts(self._comparable(ref, item), read_back, parts),
            raw_sections=_raw_with_written_parts(self._raw_sections(ref), remote.raw_sections, parts),
        )
        written = item.model_copy(
            update={
                "rendered": rendered,
                "remote": with_parts(item.remote, read_back, parts),
                "marker": remote.marker,
                "shown_remote": None,
                "writing": None,
            }
        )
        return with_item(self.state, ref, target_plan.target, written)

    def _raw_sections(self, ref: ItemRef) -> RawSections:
        return self.remote[ref].raw_sections if ref in self.remote else NO_SECTIONS

    def _comparable(self, ref: ItemRef, item: PublishedItem) -> ItemContent:
        return self.remote[ref].comparable if ref in self.remote else item.remote

    def _written(
        self,
        target_plan: TargetPlan,
        ref: ItemRef,
        intent: tuple[Sequence[Part], ItemContent],
        send: Callable[[str], RemoteItem],
    ) -> PublishState:
        parts, rendered = intent
        item = self._start_writing(target_plan, ref, parts, rendered)
        try:
            remote = send(item.item_id)
        except WriteRejectedError:
            self._save(
                with_item(self.state, ref, target_plan.target, item.model_copy(update={"writing": None}))
            )
            raise
        return self._after_write(target_plan, ref, intent, remote)

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
            return with_item(
                self.state, ref, target_plan.target, item.model_copy(update={"rendered": rendered})
            )
        transport = self.transports.for_target(ref.target)
        return self._written(
            target_plan,
            ref,
            ([section_part(key)], rendered),
            lambda item_id: transport.write_section(item_id, SectionRequest(write, raw_sections)),
        )

    def _write_content(self, target_plan: TargetPlan, step: WriteContentStep) -> PublishState:
        item = self._item(step.item)
        rendered = item.rendered.model_copy(update={"sections": step.content.sections})
        parts = [section_part(key) for key in (*step.written, *step.removed)]
        transport = self.transports.for_target(step.item.target)
        raw_sections = self._raw_sections(step.item)
        return self._written(
            target_plan,
            step.item,
            (parts, rendered),
            lambda item_id: transport.write_content(
                item_id, ContentWrite(step.content.sections, raw_sections)
            ),
        )

    def _write_fields(self, target_plan: TargetPlan, step: WriteFieldsStep) -> PublishState:
        item = self._item(step.item)
        now = self.remote[step.item].comparable if step.item in self.remote else item.remote
        write = FieldsWrite(
            step.content.title,
            step.content.fields,
            now.title,
            with_fields_named(now, [*item.rendered.fields, *step.content.fields]).fields,
            Stamp(self.prepared.doc_id, step.item.section_id),
        )
        rendered = item.rendered.model_copy(
            update={"title": step.content.title, "fields": step.content.fields}
        )
        transport = self.transports.for_target(step.item.target)
        return self._written(
            target_plan,
            step.item,
            (step.parts, rendered),
            lambda item_id: transport.write_fields(item_id, write),
        )

    def _retired(
        self, target_plan: TargetPlan, ref: ItemRef, retirement: Retirement, send: Callable[[], None]
    ) -> PublishState:
        if ref not in self.remote:
            return with_item(self.state, ref, target_plan.target, None)
        item = self._item(ref).model_copy(update={"retiring": retirement})
        self._save(with_item(self.state, ref, target_plan.target, item))
        try:
            send()
        except WriteRejectedError:
            self._save(
                with_item(self.state, ref, target_plan.target, item.model_copy(update={"retiring": None}))
            )
            raise
        return with_item(self.state, ref, target_plan.target, None)

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
                transport = self.transports.for_target(target_plan.label)
                return self._retired(
                    target_plan, step.item, "archive", lambda: transport.archive_item(step.item_id)
                )
            case ReleaseStep():
                transport = self.transports.for_target(target_plan.label)
                release = Release(self._raw_sections(step.item), tuple(self._item(step.item).rendered.fields))
                return self._retired(
                    target_plan, step.item, "release", lambda: transport.release_item(step.item_id, release)
                )
            case _:
                assert_never(step)

    def _created(self, target_plan: TargetPlan, step: CreateStep) -> PublishState:
        parent = None if step.item.section_id is None else self._item(ItemRef(step.item.target, None))
        parent_id = None if parent is None else parent.item_id
        pending = PendingCreate(
            target=target_plan.label,
            section_id=step.item.section_id,
            parent_id=parent_id,
            title=step.draft.content.title,
            into_id=step.into_id,
            service=target_plan.target.service(),
            target_as_written=target_plan.target.model_dump(mode="json"),
        )
        transport = self.transports.for_target(target_plan.label)
        before = self.state
        self._save(before.model_copy(update={"pending_creates": [*before.pending_creates, pending]}))
        written_into = self.remote.get(step.item)
        try:
            remote = transport.create_item(
                NewItem(
                    target_plan.target,
                    Stamp(self.prepared.doc_id, step.item.section_id),
                    step.draft.content,
                    parent_id=parent_id,
                    into_id=step.into_id,
                    into_raw_sections=NO_SECTIONS if written_into is None else written_into.raw_sections,
                )
            )
        except WriteRejectedError:
            self._save(before)
            raise
        remote = replace(remote, comparable=with_fields_named(remote.comparable, step.draft.content.fields))
        self.remote[step.item] = remote
        created = PublishedItem(
            item_id=remote.item_id,
            origin="created" if step.into_id is None else "adopted",
            rendered=step.draft.content,
            remote=remote.comparable,
            marker=remote.marker,
        )
        state = with_item(self.state, step.item, target_plan.target, created)
        remaining = [held for held in state.pending_creates if held != pending]
        return state.model_copy(update={"pending_creates": remaining})
