from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from skaldr import compute
from skaldr.export.inline import paragraphs, plain, rich_line
from skaldr.export.tree import ListEntry, ListNode, Node, Paragraph, TableCell, ToneName
from skaldr.models import AnyBlock, BadgeLiteral, BadgeRef, Report, iter_reference_items
from skaldr.richtext import Chip, Plain, Rich, RichContext

TONE_BY_NAME: dict[str, ToneName] = {
    "slate": "neutral",
    "blue": "info",
    "green": "success",
    "amber": "warning",
    "red": "danger",
    "violet": "accent",
    "teal": "teal",
    "sky": "sky",
    "neutral": "neutral",
    "info": "info",
    "success": "success",
    "warning": "warning",
    "danger": "danger",
    "accent": "accent",
    "muted": "muted",
}
MAX_HEADING_LEVEL = 4


def tone_named(name: str | None) -> ToneName | None:
    return TONE_BY_NAME.get(name) if name else None


@dataclass(frozen=True)
class Lowering:
    report: Report
    rich_context: RichContext
    anchors: Mapping[int, str]
    matrix_tallies: Mapping[str, compute.DerivedTally]
    table_tallies: Mapping[str, compute.DerivedTally]

    def rich(self, text: str) -> Rich:
        return rich_line(text, self.rich_context)

    def prose(self, text: str, tone: ToneName | None = None) -> tuple[Node, ...]:
        return tuple(Paragraph(self.rich(part), tone) for part in paragraphs(text))

    def anchor_of(self, block: AnyBlock) -> str | None:
        return self.anchors.get(id(block))

    def chip(self, key: str) -> Chip:
        badge = self.report.badges[key]
        return Chip(badge.label, badge.tone)

    def chips(self, keys: Sequence[str]) -> Rich:
        return spaced(tuple((self.chip(key),) for key in keys))

    def badge_items(self, items: Sequence[BadgeRef | BadgeLiteral]) -> Rich:
        return spaced(
            tuple(
                (self.chip(item.key),) if isinstance(item, BadgeRef) else (Chip(item.label, item.tone),)
                for item in items
            )
        )


def lowering_for(report: Report) -> Lowering:
    anchors = compute.anchor_slugs(report)
    return Lowering(
        report=report,
        rich_context=RichContext(
            reference_numbers=compute.reference_numbers(report),
            reference_urls={item.key: item.url for item in iter_reference_items(report.blocks)},
            anchor_ids=frozenset(anchors.values()),
        ),
        anchors=anchors,
        matrix_tallies=compute.matrix_tallies(report),
        table_tallies=compute.table_tallies(report),
    )


def spaced(parts: Sequence[Rich], separator: str = " ") -> Rich:
    runs: Rich = ()
    for part in parts:
        if runs:
            runs += (Plain(separator),)
        runs += part
    return runs


def bullets(entries: Iterable[ListEntry]) -> ListNode:
    return ListNode("bullet", tuple(entries))


def cells(*texts: str) -> tuple[TableCell, ...]:
    return tuple(TableCell(plain(text)) for text in texts)
