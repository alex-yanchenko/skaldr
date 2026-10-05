from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Final, TypeGuard

from skaldr import compute
from skaldr.export.inline import bold, one_line, plain, rich_line
from skaldr.export.runs import Chip, ExportRich
from skaldr.export.tree import ListEntry, ListNode, Node, Paragraph, TableCell, ToneName
from skaldr.models import (
    TONE_BADGE_COLOR,
    AnyBlock,
    BadgeLiteral,
    BadgeRef,
    Report,
    ToneLiteral,
    iter_reference_items,
)
from skaldr.prose_blocks import ProseBlock, ProseItem, ProseList, prose_blocks
from skaldr.richtext import Plain, Rich, RichContext

TEXT_BULLET: Final = "• "
NESTED_TEXT_BULLET: Final = "◦ "


def _is_tone(value: object) -> TypeGuard[ToneLiteral]:
    return isinstance(value, str) and value in TONE_BADGE_COLOR


def tone_of(value: object) -> ToneLiteral | None:
    return value if _is_tone(value) else None


def tone_named(value: object) -> ToneName | None:
    return "muted" if value == "muted" else tone_of(value)


@dataclass(frozen=True)
class Lowering:
    report: Report
    rich_context: RichContext
    anchors: dict[int, str]
    matrix_tallies: Mapping[str, compute.DerivedTally]
    table_tallies: Mapping[str, compute.DerivedTally]

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

    def prose_lines(self, text: str) -> tuple[ExportRich, ...]:
        return tuple(line for block in prose_blocks(text) for line in self._text_lines(block, depth=0))

    def _text_lines(self, block: ProseBlock, depth: int) -> list[ExportRich]:
        if isinstance(block, str):
            return [self.rich(block)]
        lines: list[ExportRich] = []
        for marker, item in _item_markers(block, depth):
            lines.append((Plain(marker), *self.rich(item.text)))
            for child in item.blocks:
                lines += self._text_lines(child, depth + 1)
        return lines

    def anchor_of(self, block: AnyBlock) -> str | None:
        return self.anchors.get(id(block))

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
    )
    compute.validate_rich_text_fields(report, rich_context)
    return Lowering(
        report=report,
        rich_context=rich_context,
        anchors=anchors,
        matrix_tallies=compute.matrix_tallies(report),
        table_tallies=compute.table_tallies(report),
    )


def _item_markers(block: ProseList, depth: int) -> list[tuple[str, ProseItem]]:
    if block.start is None:
        return [(TEXT_BULLET if depth == 0 else NESTED_TEXT_BULLET, item) for item in block.items]
    return [(f"{number}. ", item) for number, item in enumerate(block.items, start=block.start)]


def spaced(parts: Sequence[ExportRich], separator: str = " ") -> ExportRich:
    runs: ExportRich = ()
    for part in parts:
        if runs:
            runs += (Plain(separator),)
        runs += part
    return runs


def with_bold_label(label: str | None, text: ExportRich) -> ExportRich:
    name = bold(one_line(label or "").removesuffix(":").rstrip())
    return (*name, Plain(": "), *text) if name and text else name + text


def bullets(entries: Iterable[ListEntry]) -> ListNode:
    return ListNode("bullet", tuple(entries))


def plain_cells(*texts: str) -> tuple[TableCell, ...]:
    return tuple(TableCell(plain(text)) for text in texts)
