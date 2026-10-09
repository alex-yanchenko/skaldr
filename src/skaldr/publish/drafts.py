from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from typing_extensions import assert_never

from skaldr import models
from skaldr.errors import PublishError
from skaldr.export.lower import Lowering, assemble_page, lower_regions, lowering_for
from skaldr.export.tree import BlockRegion, LoweredDocument, PagePart, Region
from skaldr.publish.connector import Connector, ConnectorRegistry, ContentLimit
from skaldr.publish.content import FIELDS, TITLE, ItemContent, Part, section_part
from skaldr.publish_block import Publish, TargetBase

DOCUMENT_ITEM_LABEL = "document"
PAGE_PART_KEYS = {"header": "page header", "legend": "page legend", "footer": "page footer"}
PAGE_PART_PATHS = {"header": "meta", "legend": "badges", "footer": "meta"}
NO_PUBLISH_BLOCK = (
    "the document has no `publish` block, so it has nowhere to publish; add one (see `skaldr --guide`)"
)


def item_label(section_id: str | None) -> str:
    return DOCUMENT_ITEM_LABEL if section_id is None else f"section {section_id}"


def region_key(region: Region) -> str:
    match region:
        case BlockRegion():
            return region.section_id or f"blocks[{region.source_index}]"
        case PagePart():
            return PAGE_PART_KEYS[region.kind]
        case _:
            assert_never(region)


def region_path(region: Region) -> str:
    match region:
        case BlockRegion():
            return f"blocks[{region.source_index}]"
        case PagePart():
            return PAGE_PART_PATHS[region.kind]
        case _:
            assert_never(region)


@dataclass(frozen=True)
class ItemDraft:
    section_id: str | None
    content: ItemContent
    paths: Mapping[Part, str]


@dataclass(frozen=True)
class TargetDraft:
    label: str
    target: TargetBase
    document: ItemDraft
    sections: tuple[ItemDraft, ...]

    @property
    def items(self) -> tuple[ItemDraft, ...]:
        return (self.document, *self.sections)


def published_targets(report: models.Report) -> Publish:
    if report.publish is None:
        raise PublishError(NO_PUBLISH_BLOCK)
    return report.publish


def _section_title(report: models.Report, region: BlockRegion) -> str:
    block = report.blocks[region.source_index]
    return block.title if isinstance(block, models.Section) else ""


@dataclass(frozen=True)
class _TargetContext:
    report: models.Report
    lowering: Lowering
    target: TargetBase
    connector: Connector
    fields_path: str


def _item_draft(
    context: _TargetContext, page: LoweredDocument, section_id: str | None, title_path: str
) -> ItemDraft:
    texts = context.connector.render_regions(context.report, page)
    return ItemDraft(
        section_id,
        ItemContent(
            title=page.title,
            sections={region_key(region): text for region, text in zip(page.regions, texts, strict=True)},
            fields=context.target.fields_for(section_id),
        ),
        {
            TITLE: title_path,
            FIELDS: context.fields_path,
            **{section_part(region_key(region)): region_path(region) for region in page.regions},
        },
    )


def _refuse_what_cannot_fit(
    draft: ItemDraft, limits: Sequence[ContentLimit], label: str, service: str
) -> None:
    advice = "split the document further with `split`, or shorten it"
    for limit in limits:
        measured = (
            [("the item", "".join(draft.content.sections.values()))]
            if limit.scope == "item"
            else [
                (f"section {key} ({draft.paths[section_part(key)]})", text)
                for key, text in draft.content.sections.items()
            ]
        )
        for what, text in measured:
            size = limit.measure(text)
            if size > limit.maximum:
                raise PublishError(
                    f"{label}, {item_label(draft.section_id)}: {what} has {size:,} {limit.unit}, over the "
                    f"{limit.maximum:,} a {service} {limit.scope} can take; {advice}"
                )


def _target_draft(context: _TargetContext, regions: Sequence[BlockRegion]) -> TargetDraft:
    target = context.target
    chosen = [
        region
        for region in regions
        if target.from_sections is None or region.section_id in target.from_sections
    ]
    on_the_document = [region for region in chosen if region.section_id not in target.split]
    document = _item_draft(context, assemble_page(on_the_document, context.lowering), None, "meta.title")
    children = tuple(
        _item_draft(
            context,
            LoweredDocument(_section_title(context.report, region), (region,)),
            region.section_id,
            f"blocks[{region.source_index}].title",
        )
        for region in chosen
        if region.section_id in target.split
    )
    draft = TargetDraft(target.location_label(), target, document, children)
    for item in draft.items:
        _refuse_what_cannot_fit(item, context.connector.limits, draft.label, target.service())
    return draft


def draft_targets(report: models.Report, registry: ConnectorRegistry) -> tuple[TargetDraft, ...]:
    publish = published_targets(report)
    lowering = lowering_for(report)
    regions = lower_regions(lowering)
    return tuple(
        _target_draft(
            _TargetContext(
                report, lowering, target, registry.for_target(target), f"publish.targets[{position}]"
            ),
            regions,
        )
        for position, target in enumerate(publish.targets)
    )
