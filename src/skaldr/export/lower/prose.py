from collections.abc import Sequence
from pathlib import PurePosixPath

from skaldr import compute, models
from skaldr.export.inline import bold, italic, labelled, paragraphs, plain
from skaldr.export.lower.context import Lowering, bullets, spaced
from skaldr.export.runs import Chip, ExportRich, Gauge, Mark
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

CODE_LANGUAGE_BY_SUFFIX: dict[str, str] = {
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
    return [bullets(ListEntry(labelled(fact.label) + plain(fact.value)) for fact in block.facts)]


def lower_key_value(block: models.KeyValue, lowering: Lowering) -> list[Node]:
    return [bullets(ListEntry(labelled(pair.label) + lowering.rich(pair.value)) for pair in block.pairs)]


def lower_def_list(block: models.DefList, lowering: Lowering) -> list[Node]:
    return [bullets(_definition(item.term, item.body, lowering) for item in block.items)]


def _definition(term: str, body: str, lowering: Lowering) -> ListEntry:
    parts = paragraphs(body)
    first = lowering.rich(parts[0]) if parts else ()
    rest = tuple(Paragraph(lowering.rich(part)) for part in parts[1:])
    return ListEntry(labelled(term) + first, children=rest)


def lower_cards(cards: Sequence[models.Card], lowering: Lowering) -> list[Node]:
    return [bullets(_card(card, lowering) for card in cards)]


def _derived_card(card: models.Card, badge_key: str, lowering: Lowering) -> ExportRich:
    badge = lowering.report.badges[badge_key]
    count, total = compute.derived_card_tally(card, lowering.matrix_tallies, lowering.table_tallies)
    return (
        Chip(card.label or badge.label, badge.tone),
        *plain(f": {compute.fmt(count)} ({compute.pct(count, total)})"),
    )


def _delta(delta: models.CardDelta) -> ExportRich:
    text = plain(f" {delta.label}")
    return (Plain(" "), Mark("delta", delta.direction), *text) if delta.direction else text


def _card(card: models.Card, lowering: Lowering) -> ListEntry:
    if card.badge and (card.of_matrix or card.of_tables):
        text = _derived_card(card, card.badge, lowering)
    else:
        value: ExportRich = plain(compute.fmt(card.value)) if card.value is not None else ()
        if card.of and isinstance(card.value, (int, float)):
            value += plain(f" ({compute.pct(card.value, card.of)})")
        if card.delta:
            value += _delta(card.delta)
        text = (labelled(card.label) + value) if card.label else value
        if card.badges:
            text += plain(" ") + lowering.chips(card.badges)
    children: tuple[Node, ...] = (Paragraph(plain(card.note), "muted"),) if card.note else ()
    return ListEntry(text, children=children, tone=card.tone)


def lower_badge_row(block: models.BadgeRow, lowering: Lowering) -> list[Node]:
    if block.groups:
        return [
            bullets(
                ListEntry(labelled(group.label) + lowering.badge_items(group.items)) for group in block.groups
            )
        ]
    lead = labelled(block.label) if block.label else ()
    return [Paragraph(lead + lowering.badge_items(block.items))]


def _titled_callout(tone: ToneName, title: str | None, body: str, lowering: Lowering) -> list[Node]:
    heading: tuple[Node, ...] = (Paragraph(bold(title)),) if title else ()
    return [Callout(tone, heading + lowering.prose(body))]


def lower_callout(block: models.Callout, lowering: Lowering) -> list[Node]:
    return _titled_callout(block.tone, block.title, block.body, lowering)


def lower_note(block: models.Note, lowering: Lowering) -> list[Node]:
    return _titled_callout("neutral", block.title, block.body, lowering)


def lower_status_list(block: models.StatusList, lowering: Lowering) -> list[Node]:
    return [
        bullets(
            ListEntry(_marked(Mark("status", item.state), lowering.rich(item.text))) for item in block.items
        )
    ]


def _meter_entry(item: models.MeterItem) -> ListEntry:
    reading = f" {compute.pct(item.value, item.max)} ({compute.fmt(item.value)} of {compute.fmt(item.max)})"
    return ListEntry((*labelled(item.label), Gauge(item.value, item.max), *plain(reading)), tone=item.tone)


def lower_meter(block: models.Meter) -> list[Node]:
    return [bullets(_meter_entry(item) for item in block.items)]


def lower_range(block: models.Range, lowering: Lowering) -> list[Node]:
    total = sum(segment.span for segment in block.segments)
    entries: list[ListEntry] = []
    for segment in block.segments:
        text = labelled(segment.label) + plain(
            f"{compute.fmt(segment.span)} ({compute.pct(segment.span, total)})"
        )
        if segment.sub:
            text += plain(", ") + lowering.rich(segment.sub)
        entries.append(ListEntry(text, tone=segment.tone))
    axis_note: list[Node] = []
    if block.axis and (block.axis.min or block.axis.max):
        axis_note.append(
            Paragraph(plain(f"From {block.axis.min or 'start'} to {block.axis.max or 'end'}"), "muted")
        )
    return [*axis_note, ListNode("bullet", tuple(entries))]


def code_language(label: str | None) -> str:
    if not label:
        return ""
    return CODE_LANGUAGE_BY_SUFFIX.get(PurePosixPath(label.strip()).suffix.lower(), "")


def lower_code(block: models.Code) -> list[Node]:
    label: list[Node] = [Paragraph((Code(block.label),))] if block.label else []
    language = "diff" if block.mode == "diff" else code_language(block.label)
    return [*label, CodeBlock(block.content.rstrip("\n"), language)]


def lower_quote(block: models.Quote, lowering: Lowering) -> list[Node]:
    lines = tuple(lowering.rich(part) for part in paragraphs(block.body))
    return [Quote(lines, plain(block.cite) if block.cite else ())]


def lower_image(block: models.Image, lowering: Lowering) -> list[Node]:
    caption = lowering.rich(block.caption) if block.caption else plain(block.alt)
    return [Paragraph(italic(plain("Image: ") + caption), "muted")]


def _timeline_entry(item: models.TimelineItem, lowering: Lowering) -> ListEntry:
    text: ExportRich = labelled(item.time) if item.time else ()
    text += plain(item.title)
    if item.state:
        text = _marked(Mark("timeline", item.state), text)
    if item.badges:
        text += plain(" ") + lowering.chips(item.badges)
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
