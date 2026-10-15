from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from skaldr import compute
from skaldr.export.inline import bold, one_line, plain, rich_line
from skaldr.export.runs import Break, Chip, ExportRich, ExportRun, TonedLabel
from skaldr.export.tree import ListEntry, ListNode, Node, Paragraph, TableCell, ToneName
from skaldr.models import (
    AnyBlock,
    BadgeLiteral,
    BadgeRef,
    Report,
    ToneLiteral,
    iter_reference_items,
)
from skaldr.prose_blocks import ProseBlock, prose_blocks
from skaldr.richtext import Plain, Rich, RichContext


@dataclass(frozen=True)
class Lowering:
    report: Report
    rich_context: RichContext
    anchors: dict[int, str]
    matrix_tallies: Mapping[str, compute.DerivedTally]
    table_tallies: Mapping[str, compute.DerivedTally]
    section_titles: Mapping[str, str]
    block_paths: Mapping[int, str]

    def rich(self, text: str) -> Rich:
        return rich_line(text, self.rich_context)

    def prose(self, text: str, tone: ToneName | None = None) -> tuple[Node, ...]:
        return tuple(self._prose_node(block, tone) for block in prose_blocks(text))

    def _prose_node(self, block: ProseBlock, tone: ToneName | None) -> Node:
        if isinstance(block, str):
            return Paragraph(self.rich(block), tone)
        entries = tuple(
            ListEntry(
                self.rich(item.text), children=tuple(self._prose_node(child, None) for child in item.blocks)
            )
            for item in block.items
        )
        return (
            ListNode("bullet", entries) if block.start is None else ListNode("number", entries, block.start)
        )

    def anchor_of(self, block: AnyBlock) -> str | None:
        return self.anchors.get(id(block))

    def path_of(self, block: AnyBlock) -> str | None:
        return self.block_paths.get(id(block))

    def chip(self, key: str) -> Chip:
        badge = self.report.badges[key]
        return Chip.on_one_line(badge.label, badge.tone)

    def chips(self, keys: Sequence[str]) -> ExportRich:
        return spaced(tuple((self.chip(key),) for key in keys))

    def badge_items(self, items: Sequence[BadgeRef | BadgeLiteral]) -> ExportRich:
        return spaced(
            tuple(
                (
                    self.chip(item.key)
                    if isinstance(item, BadgeRef)
                    else Chip.on_one_line(item.label, item.tone),
                )
                for item in items
            )
        )


def lowering_for(report: Report) -> Lowering:
    anchors = compute.anchor_slugs(report)
    rich_context = RichContext(
        reference_numbers=compute.reference_numbers(report),
        reference_urls={item.key: item.url for item in iter_reference_items(report.blocks)},
        anchor_ids=frozenset(anchors.values()),
        people=report.meta.people,
        jira_site=report.meta.jira_site,
        part_anchors=compute.part_anchors(report, anchors),
    )
    compute.validate_rich_text_fields(report, rich_context)
    return Lowering(
        report=report,
        rich_context=rich_context,
        anchors=anchors,
        matrix_tallies=compute.matrix_tallies(report),
        table_tallies=compute.table_tallies(report),
        section_titles=compute.section_titles_by_id(report),
        block_paths={id(block): path for path, block in report.located_blocks},
    )


def spaced(parts: Sequence[ExportRich], separator: str = " ") -> ExportRich:
    runs: ExportRich = ()
    for part in parts:
        if runs:
            runs += (Plain(separator),)
        runs += part
    return runs


def joined_by_breaks(lines: Iterable[ExportRich]) -> ExportRich:
    runs: list[ExportRun] = []
    for line in lines:
        if line and runs:
            runs.append(Break())
        runs.extend(line)
    return tuple(runs)


def toned(tone: ToneLiteral | None, runs: Rich) -> ExportRich:
    return (TonedLabel(tone, runs),) if tone and runs else runs


def with_bold_label(label: str | None, text: ExportRich, tone: ToneLiteral | None = None) -> ExportRich:
    name = toned(tone, bold(one_line(label or "").removesuffix(":").rstrip()))
    return (*name, Plain(": "), *text) if name and text else name + text


def bullets(entries: Iterable[ListEntry]) -> ListNode:
    return ListNode("bullet", tuple(entries))


def plain_cells(*texts: str) -> tuple[TableCell, ...]:
    return tuple(TableCell(plain(text)) for text in texts)
