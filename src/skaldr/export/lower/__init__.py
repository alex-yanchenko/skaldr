from collections.abc import Sequence

from typing_extensions import assert_never

from skaldr import compute
from skaldr.export.inline import bold, italic, plain
from skaldr.export.lower.context import MAX_HEADING_LEVEL, Lowering, lowering_for, tone_named
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
from skaldr.export.tree import (
    Callout,
    Column,
    Columns,
    Heading,
    ListEntry,
    ListNode,
    Node,
    Paragraph,
    TableOfContents,
    TocEntry,
    Toggle,
)
from skaldr.models import (
    AnyBlock,
    BadgeRow,
    Cards,
    Chart,
    Comparison,
    DefList,
    FactStrip,
    Fan,
    Flow,
    Grid,
    InnerGrid,
    KeyValue,
    ListBlock,
    Matrix,
    Meter,
    Panel,
    Range,
    References,
    Report,
    Request,
    RequestFlow,
    Section,
    StatusList,
    Swimlane,
    Text,
    Timeline,
    Walkthrough,
    WalkthroughStep,
)
from skaldr.models import Callout as CalloutBlock
from skaldr.models import Code as CodeBlockModel
from skaldr.models import Heading as HeadingBlock
from skaldr.models import Image as ImageBlock
from skaldr.models import Note as NoteBlock
from skaldr.models import Quote as QuoteBlock
from skaldr.models import Table as TableBlock
from skaldr.richtext import Chip, Plain

SECTION_HEADING_LEVEL = 2


def lower_report(report: Report) -> tuple[Node, ...]:
    lowering = lowering_for(report)
    nodes: list[Node] = [Paragraph(lowering.rich(line), "muted") for line in report.meta.subtitle]
    toc = _table_of_contents(report, lowering)
    if toc.entries:
        nodes.append(toc)
    nodes += _lower_blocks(report.blocks, lowering, depth=0)
    nodes += _legend(report)
    footer = compute.provenance_footer(report)
    if footer:
        nodes.append(Paragraph(plain(footer), "muted"))
    return tuple(nodes)


def _table_of_contents(report: Report, lowering: Lowering) -> TableOfContents:
    entries = compute.toc_entries(report, dict(lowering.anchors))
    return TableOfContents(tuple(TocEntry(anchor, plain(title)) for anchor, title in entries))


def _lower_blocks(blocks: Sequence[AnyBlock], lowering: Lowering, depth: int) -> list[Node]:
    return [node for block in blocks for node in _lower_block(block, lowering, depth)]


def _lower_block(block: AnyBlock, lowering: Lowering, depth: int) -> list[Node]:
    match block:
        case HeadingBlock():
            heading = Heading(
                min(block.level + depth, MAX_HEADING_LEVEL), plain(block.text), lowering.anchor_of(block)
            )
            sub: list[Node] = [Paragraph(italic(lowering.rich(block.sub)), "muted")] if block.sub else []
            return [heading, *sub]
        case Text():
            return list(lowering.prose(block.body, "muted" if block.muted else None))
        case ListBlock():
            return lower_list(block, lowering)
        case FactStrip():
            return lower_fact_strip(block)
        case KeyValue():
            return lower_key_value(block, lowering)
        case DefList():
            return lower_def_list(block, lowering)
        case Cards():
            return lower_cards(block.items, lowering)
        case BadgeRow():
            return lower_badge_row(block, lowering)
        case CalloutBlock():
            return lower_callout(block, lowering)
        case StatusList():
            return lower_status_list(block, lowering)
        case Meter():
            return lower_meter(block)
        case Range():
            return lower_range(block, lowering)
        case CodeBlockModel():
            return lower_code(block)
        case QuoteBlock():
            return lower_quote(block, lowering)
        case NoteBlock():
            return lower_note(block, lowering)
        case ImageBlock():
            return lower_image(block, lowering)
        case Timeline():
            return lower_timeline(block, lowering)
        case Flow():
            return lower_flow(block, lowering)
        case Fan():
            return lower_fan(block, lowering)
        case Chart():
            return lower_chart(block)
        case Comparison():
            return lower_comparison(block, lowering)
        case Matrix():
            return lower_matrix(block, lowering)
        case Swimlane():
            return lower_swimlane(block)
        case References():
            return lower_references(block, lowering)
        case TableBlock():
            return lower_table(block, lowering)
        case Request():
            return lower_request(block, lowering)
        case RequestFlow():
            return lower_request_flow(block, lowering)
        case Section():
            return _section(block, lowering, depth)
        case Panel():
            return [
                Callout(
                    "neutral", (Paragraph(bold(block.title)), *_lower_blocks(block.blocks, lowering, depth))
                )
            ]
        case Grid() | InnerGrid():
            return _grid(block, lowering, depth)
        case Walkthrough():
            return [
                ListNode("number", tuple(_walkthrough_entry(step, lowering, depth) for step in block.steps))
            ]
        case _:
            assert_never(block)


def _section(block: Section, lowering: Lowering, depth: int) -> list[Node]:
    level = min(SECTION_HEADING_LEVEL + depth, MAX_HEADING_LEVEL)
    updated: list[Node] = (
        [Paragraph(italic(plain(f"updated {block.updated}")), "muted")] if block.updated else []
    )
    children = [*updated, *_lower_blocks(block.blocks, lowering, depth + 1)]
    anchor = lowering.anchor_of(block)
    if block.collapsed:
        return [Toggle(plain(block.title), level, tuple(children), anchor)]
    return [Heading(level, plain(block.title), anchor), *children]


def _grid(block: Grid | InnerGrid, lowering: Lowering, depth: int) -> list[Node]:
    total = sum(cell.span for cell in block.cells)
    columns: list[Column] = []
    for cell in block.cells:
        children: tuple[Node, ...] = tuple(_lower_blocks(cell.blocks, lowering, depth))
        tone = tone_named(cell.tone)
        if tone:
            children = (Callout(tone, children),)
        columns.append(Column(round(cell.span / total * 100), children))
    if len(columns) == 1 or isinstance(block, InnerGrid):
        return [node for column in columns for node in column.children]
    return [Columns(tuple(columns))]


def _walkthrough_entry(step: WalkthroughStep, lowering: Lowering, depth: int) -> ListEntry:
    text = bold(step.label)
    if step.sub:
        text += plain(" ") + italic(lowering.rich(step.sub))
    return ListEntry(text, children=tuple(_lower_blocks(step.detail, lowering, depth)), tone=step.tone)


def _legend(report: Report) -> list[Node]:
    used = compute.used_badges(report)
    if not used:
        return []
    entries = tuple(
        ListEntry((Chip(badge.label, badge.tone), Plain(f" {badge.legend}"))) for _, badge in used
    )
    return [Toggle(plain("Legend: badges used on this page"), None, (ListNode("bullet", entries),))]
