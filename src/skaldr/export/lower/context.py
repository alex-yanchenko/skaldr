from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from skaldr import compute
from skaldr.export.inline import paragraphs, rich_line
from skaldr.export.tree import ListEntry, ListNode, Node, Paragraph, ToneName
from skaldr.models import AnyBlock, Report, iter_reference_items
from skaldr.richtext import Plain, Rich, RichContext

MAX_HEADING_LEVEL = 4


@dataclass(frozen=True)
class Lowering:
    rich_context: RichContext
    anchors: dict[int, str]

    def rich(self, text: str) -> Rich:
        return rich_line(text, self.rich_context)

    def prose(self, text: str, tone: ToneName | None = None) -> tuple[Node, ...]:
        return tuple(Paragraph(self.rich(part), tone) for part in paragraphs(text))

    def anchor_of(self, block: AnyBlock) -> str | None:
        return self.anchors.get(id(block))


def lowering_for(report: Report) -> Lowering:
    anchors = compute.anchor_slugs(report)
    return Lowering(
        rich_context=RichContext(
            reference_numbers=compute.reference_numbers(report),
            reference_urls={item.key: item.url for item in iter_reference_items(report.blocks)},
            anchor_ids=frozenset(anchors.values()),
        ),
        anchors=anchors,
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
