from collections.abc import Sequence

from typing_extensions import assert_never

from skaldr import compute, models
from skaldr.errors import RegionNotFoundError
from skaldr.export.apportion import apportioned
from skaldr.export.inline import bold, italic, plain
from skaldr.export.lower.context import Lowering, lowering_for, spaced, toned
from skaldr.export.lower.diagrams import lower_chart, lower_fan, lower_flow
from skaldr.export.lower.prose import (
    lower_badge_row,
    lower_callout,
    lower_cards,
    lower_code,
    lower_def_list,
    lower_fact_strip,
    lower_image,
    lower_key_value,
    lower_list,
    lower_math,
    lower_meter,
    lower_note,
    lower_quote,
    lower_range,
    lower_references,
    lower_status_list,
    lower_timeline,
)
from skaldr.export.lower.requests import lower_request, lower_request_flow
from skaldr.export.lower.tables import lower_comparison, lower_matrix, lower_swimlane, lower_table
from skaldr.export.runs import ExportRich
from skaldr.export.tree import (
    COLUMN_RATIO_TOTAL,
    BlockRegion,
    Callout,
    Columns,
    Divider,
    GridColumn,
    Heading,
    ListEntry,
    ListNode,
    LoweredDocument,
    Node,
    PagePart,
    Paragraph,
    Region,
    Tab,
    TableOfContents,
    Tabs,
    TocEntry,
    Toggle,
    capped_heading_level,
)
from skaldr.richtext import Plain

PART_HEADING_LEVEL = 1
SECTION_HEADING_LEVEL = 2
FOOTER_SEPARATOR = " · "


def lower_report(report: models.Report) -> LoweredDocument:
    lowering = lowering_for(report)
    return assemble_page(lower_regions(lowering), lowering)


def lower_regions(lowering: Lowering) -> tuple[BlockRegion, ...]:
    return tuple(lower_region(lowering, index) for index in range(len(lowering.report.blocks)))


def region_for_section(regions: Sequence[BlockRegion], section_id: str) -> BlockRegion:
    found = next((region for region in regions if region.section_id == section_id), None)
    if found is None:
        raise RegionNotFoundError(f"no top-level section has the id '{section_id}'")
    return found


def lower_region(lowering: Lowering, source_index: int) -> BlockRegion:
    blocks = lowering.report.blocks
    if source_index not in range(len(blocks)):
        raise RegionNotFoundError(
            f"the report has no top-level block {source_index}; its blocks are 0 to {len(blocks) - 1}"
        )
    block = blocks[source_index]
    return BlockRegion(
        source_index,
        tuple(_lower_block(block, lowering, depth=0)),
        section_id=block.id if isinstance(block, models.Section) else None,
        anchor=lowering.anchor_of(block),
    )


def assemble_page(regions: Sequence[BlockRegion], lowering: Lowering) -> LoweredDocument:
    report = lowering.report
    header = PagePart("header", (*_subtitle(report), *_table_of_contents(report, lowering)))
    legend = PagePart("legend", tuple(_legend(lowering)))
    closing = PagePart("footer", _footer(report, lowering))
    page = [header, *_with_the_legend(regions, legend, compute.first_table_index(report)), closing]
    return LoweredDocument(
        report.meta.title, tuple(region for region in page if isinstance(region, BlockRegion) or region.nodes)
    )


def _subtitle(report: models.Report) -> tuple[Node, ...]:
    return tuple(Paragraph(plain(line), "muted") for line in report.meta.subtitle)


def _footer(report: models.Report, lowering: Lowering) -> tuple[Node, ...]:
    footer = compute.provenance_footer(report)
    return (Paragraph(_footer_runs(footer, lowering), "muted"),) if footer else ()


def _footer_runs(footer: compute.Provenance, lowering: Lowering) -> ExportRich:
    source: list[ExportRich] = [lowering.rich(footer.source)] if footer.source else []
    return spaced([*source, *(plain(fact) for fact in footer.facts)], FOOTER_SEPARATOR)


def _table_of_contents(report: models.Report, lowering: Lowering) -> tuple[TableOfContents, ...]:
    entries = compute.toc_entries(report, lowering.anchors)
    return (
        (TableOfContents(tuple(TocEntry(anchor, plain(title)) for anchor, title in entries)),)
        if entries
        else ()
    )


def _lower_blocks(blocks: Sequence[models.AnyBlock], lowering: Lowering, depth: int) -> list[Node]:
    return [node for block in blocks for node in _lower_block(block, lowering, depth)]


def _heading(block: models.Heading, lowering: Lowering, depth: int) -> list[Node]:
    heading = Heading(capped_heading_level(block.level + depth), plain(block.text), lowering.anchor_of(block))
    subheading: list[Node] = [Paragraph(italic(lowering.rich(block.sub)), "muted")] if block.sub else []
    return [heading, *subheading]


def _lower_block(block: models.AnyBlock, lowering: Lowering, depth: int) -> list[Node]:
    match block:
        case models.Heading():
            return _heading(block, lowering, depth)
        case models.Text():
            return list(lowering.prose(block.body, "muted" if block.muted else None))
        case models.ListBlock():
            return lower_list(block, lowering)
        case models.FactStrip():
            return lower_fact_strip(block)
        case models.KeyValue():
            return lower_key_value(block, lowering)
        case models.DefList():
            return lower_def_list(block, lowering)
        case models.Cards():
            return lower_cards(block, lowering)
        case models.BadgeRow():
            return lower_badge_row(block, lowering)
        case models.Callout():
            return lower_callout(block, lowering)
        case models.StatusList():
            return lower_status_list(block, lowering)
        case models.Meter():
            return lower_meter(block)
        case models.Range():
            return lower_range(block, lowering)
        case models.Code():
            return lower_code(block)
        case models.Math():
            return lower_math(block)
        case models.Quote():
            return lower_quote(block, lowering)
        case models.Note():
            return lower_note(block, lowering)
        case models.Divider():
            return [Divider()]
        case models.Image():
            return lower_image(block)
        case models.Timeline():
            return lower_timeline(block, lowering)
        case models.Flow():
            return lower_flow(block, lowering)
        case models.Fan():
            return lower_fan(block, lowering)
        case models.Chart():
            return lower_chart(block)
        case models.Comparison():
            return lower_comparison(block, lowering)
        case models.Matrix():
            return lower_matrix(block, lowering)
        case models.Swimlane():
            return lower_swimlane(block)
        case models.References():
            return lower_references(block, lowering)
        case models.Table():
            return lower_table(block, lowering)
        case models.Request():
            return lower_request(block, lowering)
        case models.RequestFlow():
            return lower_request_flow(block, lowering)
        case models.Part():
            return _part(block, lowering)
        case models.Section():
            return _section(block, lowering, depth)
        case models.Toggle() | models.InnerToggle():
            return _toggle(block, lowering, depth)
        case models.Tabs():
            return [
                Tabs(
                    tuple(
                        Tab(plain(tab.label), tuple(_lower_blocks(tab.blocks, lowering, depth)), tab.tone)
                        for tab in block.tabs
                    )
                )
            ]
        case models.Panel():
            return [
                Callout(
                    "neutral", (Paragraph(bold(block.title)), *_lower_blocks(block.blocks, lowering, depth))
                )
            ]
        case models.Grid() | models.InnerGrid():
            return _grid(block, lowering, depth)
        case models.Walkthrough():
            return [
                ListNode("number", tuple(_walkthrough_entry(step, lowering, depth) for step in block.steps))
            ]
        case _:
            assert_never(block)


def _part(block: models.Part, lowering: Lowering) -> list[Node]:
    children = _lower_blocks(block.blocks, lowering, depth=0)
    anchor = lowering.anchor_of(block)
    if block.collapsed:
        return [Toggle(plain(block.title), PART_HEADING_LEVEL, tuple(children), anchor)]
    return [Heading(PART_HEADING_LEVEL, plain(block.title), anchor), *children]


def _section(block: models.Section, lowering: Lowering, depth: int) -> list[Node]:
    level = capped_heading_level(SECTION_HEADING_LEVEL + depth)
    updated: list[Node] = (
        [Paragraph(italic(plain(f"updated {block.updated}")), "muted")] if block.updated else []
    )
    children = [*updated, *_lower_blocks(block.blocks, lowering, depth + 1)]
    anchor = lowering.anchor_of(block)
    if block.collapsed:
        return [Toggle(plain(block.title), level, tuple(children), anchor)]
    return [Heading(level, plain(block.title), anchor), *children]


def _toggle(block: models.Toggle | models.InnerToggle, lowering: Lowering, depth: int) -> list[Node]:
    children = _lower_blocks(block.blocks, lowering, depth)
    if block.collapsed:
        return [Toggle(plain(block.title), None, tuple(children))]
    return [Paragraph(bold(block.title)), *children]


def _grid(block: models.Grid | models.InnerGrid, lowering: Lowering, depth: int) -> list[Node]:
    cell_nodes: list[tuple[Node, ...]] = []
    for cell in block.cells:
        children: tuple[Node, ...] = tuple(_lower_blocks(cell.blocks, lowering, depth))
        cell_nodes.append((Callout(cell.tone, children),) if cell.tone else children)
    if len(cell_nodes) == 1 or isinstance(block, models.InnerGrid):
        return [node for children in cell_nodes for node in children]
    ratios = apportioned([cell.span for cell in block.cells], COLUMN_RATIO_TOTAL)
    return [
        Columns(
            tuple(GridColumn(ratio, children) for ratio, children in zip(ratios, cell_nodes, strict=True))
        )
    ]


def _walkthrough_entry(step: models.WalkthroughStep, lowering: Lowering, depth: int) -> ListEntry:
    sub = italic(lowering.rich(step.sub or ""))
    title = bold(step.label) + ((Plain(" "), *sub) if sub else ())
    return ListEntry(toned(step.tone, title), children=tuple(_lower_blocks(step.detail, lowering, depth)))


def _legend(lowering: Lowering) -> list[Node]:
    used = compute.used_badges(lowering.report)
    if not used:
        return []
    entries = tuple(
        ListEntry(spaced([(lowering.chip(key),), plain(badge.legend)]))
        for key, badge in used
        if badge.legend is not False
    )
    title = plain(f"Legend: {compute.BADGE_LEGEND_SUBJECT}")
    return [Toggle(title, None, (ListNode("bullet", entries),))]


def _with_the_legend(regions: Sequence[BlockRegion], legend: PagePart, legend_at: int | None) -> list[Region]:
    split = next(
        (position for position, region in enumerate(regions) if region.source_index >= (legend_at or 0)),
        len(regions),
    )
    return [*regions[:split], legend, *regions[split:]]
