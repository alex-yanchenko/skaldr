from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from skaldr import compute
from skaldr.export.inline import bold, one_line, rich_line
from skaldr.export.runs import Chip, ExportRich
from skaldr.export.tree import ListEntry, ListNode, Node, Paragraph, ToneName
from skaldr.models import AnyBlock, BadgeLiteral, BadgeRef, Report, iter_reference_items
from skaldr.richtext import Plain, Rich, RichContext


@dataclass(frozen=True)
class Lowering:
    report: Report
    rich_context: RichContext
    anchors: dict[int, str]

    def rich(self, text: str) -> Rich:
        return rich_line(text, self.rich_context)

    def prose(self, text: str, tone: ToneName | None = None) -> tuple[Node, ...]:
        return tuple(Paragraph(self.rich(part), tone) for part in compute.paragraphs(text))

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
    return Lowering(
        report=report,
        rich_context=RichContext(
            reference_numbers=compute.reference_numbers(report),
            reference_urls={item.key: item.url for item in iter_reference_items(report.blocks)},
            anchor_ids=frozenset(anchors.values()),
        ),
        anchors=anchors,
    )


def spaced(parts: Sequence[ExportRich], separator: str = " ") -> ExportRich:
    runs: ExportRich = ()
    for part in parts:
        if runs:
            runs += (Plain(separator),)
        runs += part
    return runs


def with_bold_label(label: str | None, text: ExportRich) -> ExportRich:
    name = bold(one_line(label or "").removesuffix(":").rstrip())
    return (*name, Plain(": "), *text) if name else text


def bullets(entries: Iterable[ListEntry]) -> ListNode:
    return ListNode("bullet", tuple(entries))
