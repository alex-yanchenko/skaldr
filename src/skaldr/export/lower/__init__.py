from collections.abc import Sequence

from skaldr import compute, models
from skaldr.errors import ReportError
from skaldr.export.inline import bold, italic, plain
from skaldr.export.lower.context import MAX_HEADING_LEVEL, Lowering, lowering_for, spaced
from skaldr.export.lower.prose import (
    lower_callout,
    lower_code,
    lower_image,
    lower_list,
    lower_note,
    lower_quote,
    lower_references,
)
from skaldr.export.tree import (
    Callout,
    Heading,
    ListEntry,
    ListNode,
    LoweredDocument,
    Node,
    Paragraph,
    TableOfContents,
    TocEntry,
    Toggle,
)

SECTION_HEADING_LEVEL = 2


def lower_report(report: models.Report) -> LoweredDocument:
    lowering = lowering_for(report)
    nodes: list[Node] = [Paragraph(plain(line), "muted") for line in report.meta.subtitle]
    toc = _table_of_contents(report, lowering)
    if toc.entries:
        nodes.append(toc)
    nodes += _lower_blocks(report.blocks, lowering, depth=0)
    footer = compute.provenance_footer(report)
    if footer:
        nodes.append(Paragraph(plain(footer), "muted"))
    return LoweredDocument(report.meta.title, tuple(nodes))


def _table_of_contents(report: models.Report, lowering: Lowering) -> TableOfContents:
    entries = compute.toc_entries(report, lowering.anchors)
    return TableOfContents(tuple(TocEntry(anchor, plain(title)) for anchor, title in entries))


def _lower_blocks(blocks: Sequence[models.AnyBlock], lowering: Lowering, depth: int) -> list[Node]:
    return [node for block in blocks for node in _lower_block(block, lowering, depth)]


def _heading(block: models.Heading, lowering: Lowering, depth: int) -> list[Node]:
    heading = Heading(
        min(block.level + depth, MAX_HEADING_LEVEL), plain(block.text), lowering.anchor_of(block)
    )
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
        case models.Callout():
            return lower_callout(block, lowering)
        case models.Code():
            return lower_code(block)
        case models.Quote():
            return lower_quote(block, lowering)
        case models.Note():
            return lower_note(block, lowering)
        case models.Image():
            return lower_image(block)
        case models.References():
            return lower_references(block, lowering)
        case models.Section():
            return _section(block, lowering, depth)
        case models.Panel():
            return [
                Callout(
                    "neutral", (Paragraph(bold(block.title)), *_lower_blocks(block.blocks, lowering, depth))
                )
            ]
        case models.Walkthrough():
            return [
                ListNode("number", tuple(_walkthrough_entry(step, lowering, depth) for step in block.steps))
            ]
        case _:
            raise ReportError(f"a `{block.type}` block has no Markdown export yet")


def _section(block: models.Section, lowering: Lowering, depth: int) -> list[Node]:
    level = min(SECTION_HEADING_LEVEL + depth, MAX_HEADING_LEVEL)
    updated: list[Node] = (
        [Paragraph(italic(plain(f"updated {block.updated}")), "muted")] if block.updated else []
    )
    children = [*updated, *_lower_blocks(block.blocks, lowering, depth + 1)]
    anchor = lowering.anchor_of(block)
    if block.collapsed:
        return [Toggle(plain(block.title), level, tuple(children), anchor)]
    return [Heading(level, plain(block.title), anchor), *children]


def _walkthrough_entry(step: models.WalkthroughStep, lowering: Lowering, depth: int) -> ListEntry:
    parts = [bold(step.label), italic(lowering.rich(step.sub or ""))]
    return ListEntry(
        spaced([part for part in parts if part]),
        children=tuple(_lower_blocks(step.detail, lowering, depth)),
        tone=step.tone,
    )
