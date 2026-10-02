from collections.abc import Mapping
from pathlib import PurePosixPath
from typing import Final

from skaldr import compute, models
from skaldr.errors import ReportError
from skaldr.export.inline import bold, italic, one_line, plain
from skaldr.export.lower.context import Lowering, bullets, spaced, with_bold_label
from skaldr.export.runs import Chip, ExportRich, Gauge, Mark, StatusMark
from skaldr.export.tree import (
    Callout,
    CodeBlock,
    ListEntry,
    ListKind,
    ListNode,
    Node,
    Paragraph,
    Quote,
    ToneName,
)
from skaldr.richtext import Code, Link, Plain

CODE_LANGUAGE_BY_SUFFIX: Final[Mapping[str, str]] = {
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".mjs": "javascript",
    ".py": "python",
    ".sh": "bash",
    ".bash": "bash",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".sql": "sql",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".rb": "ruby",
    ".css": "css",
    ".html": "html",
    ".toml": "toml",
    ".md": "markdown",
}


def _marked(mark: Mark, text: ExportRich) -> ExportRich:
    return (mark, Plain(" "), *text)


def lower_list(block: models.ListBlock, lowering: Lowering) -> list[Node]:
    return [ListNode(block.style, tuple(_list_entry(item, block.style, lowering) for item in block.items))]


def _list_entry(item: str | models.ListItem, kind: ListKind, lowering: Lowering) -> ListEntry:
    if isinstance(item, str):
        return ListEntry(lowering.rich(item))
    children: tuple[Node, ...] = ()
    if item.items:
        children = (ListNode(kind, tuple(_list_entry(child, kind, lowering) for child in item.items)),)
    return ListEntry(lowering.rich(item.text), item.checked, children)


def lower_fact_strip(block: models.FactStrip) -> list[Node]:
    return [bullets(ListEntry(with_bold_label(fact.label, plain(fact.value))) for fact in block.facts)]


def lower_key_value(block: models.KeyValue, lowering: Lowering) -> list[Node]:
    return [
        bullets(ListEntry(with_bold_label(pair.label, lowering.rich(pair.value))) for pair in block.pairs)
    ]


def lower_def_list(block: models.DefList, lowering: Lowering) -> list[Node]:
    return [bullets(_definition(item.term, item.body, lowering) for item in block.items)]


def _definition(term: str, body: str, lowering: Lowering) -> ListEntry:
    parts = compute.paragraphs(body)
    first = lowering.rich(parts[0]) if parts else ()
    rest = tuple(Paragraph(lowering.rich(part)) for part in parts[1:])
    return ListEntry(with_bold_label(term, first), children=rest)


def lower_cards(block: models.Cards, lowering: Lowering) -> list[Node]:
    return [bullets(_card(card, lowering) for card in block.items)]


def _delta(delta: models.CardDelta) -> ExportRich:
    text = f"{compute.DELTA_GLYPHS[delta.direction]} {delta.label}" if delta.direction else delta.label
    return (Chip.on_one_line(text, models.badge_color_of(delta.tone)),) if delta.tone else plain(text)


def _card(card: models.Card, lowering: Lowering) -> ListEntry:
    if card.derived:
        raise ReportError("a derived `cards` item has no Markdown export yet")
    parts: list[ExportRich] = [plain(compute.fmt(card.value))]
    if card.of and isinstance(card.value, int | float):
        parts.append(plain(f"({compute.pct(card.value, card.of)})"))
    if card.delta:
        parts.append(_delta(card.delta))
    parts.append(lowering.chips(card.badges))
    text = with_bold_label(card.label, spaced([part for part in parts if part]))
    children: tuple[Node, ...] = (Paragraph(plain(card.note), "muted"),) if card.note else ()
    return ListEntry(text, children=children, tone=card.tone)


def lower_badge_row(block: models.BadgeRow, lowering: Lowering) -> list[Node]:
    if block.groups:
        return [
            bullets(
                ListEntry(with_bold_label(group.label, lowering.badge_items(group.items)))
                for group in block.groups
            )
        ]
    return [Paragraph(with_bold_label(block.label, lowering.badge_items(block.items)))]


def _titled_callout(tone: ToneName, title: str | None, body: str, lowering: Lowering) -> list[Node]:
    heading: tuple[Node, ...] = (Paragraph(bold(title)),) if title else ()
    return [Callout(tone, heading + lowering.prose(body))]


def lower_callout(block: models.Callout, lowering: Lowering) -> list[Node]:
    return _titled_callout(block.tone, block.title, block.body, lowering)


def lower_note(block: models.Note, lowering: Lowering) -> list[Node]:
    return _titled_callout("neutral", block.title, block.body, lowering)


def lower_status_list(block: models.StatusList, lowering: Lowering) -> list[Node]:
    return [
        bullets(ListEntry(_marked(StatusMark(item.state), lowering.rich(item.text))) for item in block.items)
    ]


def _meter_entry(item: models.MeterItem) -> ListEntry:
    reading = f"{compute.pct(item.value, item.max)} ({compute.fmt(item.value)} of {compute.fmt(item.max)})"
    gauge: ExportRich = (Gauge(item.value, item.max), Plain(" "))
    return ListEntry(with_bold_label(item.label, gauge + plain(reading)), tone=item.tone)


def lower_meter(block: models.Meter) -> list[Node]:
    return [bullets(_meter_entry(item) for item in block.items)]


def _range_segment(segment: models.RangeSegment, total: float, lowering: Lowering) -> ListEntry:
    share = plain(compute.pct(segment.span, total))
    if segment.sub:
        share += (Plain(", "), *lowering.rich(segment.sub))
    return ListEntry(with_bold_label(segment.label, share), tone=segment.tone)


def _axis_ends(axis: models.RangeAxis | None) -> list[Node]:
    start = (axis.min or "").strip() if axis else ""
    end = (axis.max or "").strip() if axis else ""
    if start and end:
        words = f"{start} to {end}"
    elif start or end:
        words = f"From {start}" if start else f"To {end}"
    else:
        return []
    return [Paragraph(plain(words), "muted")]


def lower_range(block: models.Range, lowering: Lowering) -> list[Node]:
    total = sum(segment.span for segment in block.segments)
    return [
        *_axis_ends(block.axis),
        bullets(_range_segment(segment, total, lowering) for segment in block.segments),
    ]


def code_language(label: str | None) -> str:
    if not label:
        return ""
    return CODE_LANGUAGE_BY_SUFFIX.get(PurePosixPath(label.strip()).suffix.lower(), "")


def lower_code(block: models.Code) -> list[Node]:
    label: list[Node] = [Paragraph((Code(one_line(block.label)),))] if block.label else []
    language = "diff" if block.mode == "diff" else code_language(block.label)
    return [*label, CodeBlock(block.content.rstrip("\n"), language)]


def lower_quote(block: models.Quote, lowering: Lowering) -> list[Node]:
    lines = tuple(lowering.rich(part) for part in compute.paragraphs(block.body))
    return [Quote(lines, plain(block.cite) if block.cite else ())]


def lower_image(block: models.Image) -> list[Node]:
    return [Paragraph(italic(plain(f"Image: {block.caption or block.alt}")), "muted")]


def _timeline_entry(item: models.TimelineItem, lowering: Lowering) -> ListEntry:
    text = with_bold_label(item.time, plain(item.title))
    if item.state:
        text = _marked(StatusMark(item.state), text)
    if item.badges:
        text += (Plain(" "), *lowering.chips(item.badges))
    children: tuple[Node, ...] = (Paragraph(lowering.rich(item.body)),) if item.body else ()
    return ListEntry(text, children=children)


def lower_timeline(block: models.Timeline, lowering: Lowering) -> list[Node]:
    return [bullets(_timeline_entry(item, lowering) for item in block.items)]


def _reference_entry(item: models.ReferenceItem, lowering: Lowering) -> ListEntry:
    numbers = lowering.rich_context.reference_numbers or {}
    parts: list[ExportRich] = [plain(f"[{numbers[item.key]}]"), lowering.rich(item.text)]
    if item.url:
        parts.append((Link((Plain("source"),), item.url),))
    return ListEntry(spaced(parts))


def lower_references(block: models.References, lowering: Lowering) -> list[Node]:
    return [bullets(_reference_entry(item, lowering) for item in block.items)]
