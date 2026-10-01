from pathlib import PurePosixPath

from skaldr import compute
from skaldr.export.inline import bold, italic, labelled, paragraphs, plain
from skaldr.export.lower.context import Lowering, bullets, spaced
from skaldr.export.tree import Callout, CodeBlock, ListEntry, ListKind, ListNode, Node, Paragraph, Quote
from skaldr.models import (
    BadgeRow,
    Card,
    CardDelta,
    DefList,
    FactStrip,
    KeyValue,
    ListBlock,
    ListItem,
    Meter,
    MeterItem,
    Range,
    ReferenceItem,
    References,
    StatusList,
    StatusState,
    Timeline,
    TimelineItem,
    TimelineState,
)
from skaldr.models import Callout as CalloutBlock
from skaldr.models import Code as CodeBlockModel
from skaldr.models import Image as ImageBlock
from skaldr.models import Note as NoteBlock
from skaldr.models import Quote as QuoteBlock
from skaldr.richtext import Chip, Code, Link, Plain, Rich

STATUS_MARK: dict[StatusState, str] = {
    "done": "✅",
    "current": "🔵",
    "pending": "⚪",
    "failed": "❌",
    "blocked": "⛔",
}
TIMELINE_MARK: dict[TimelineState, str] = {"done": "✅", "current": "🔵", "pending": "⚪"}
DELTA_MARK = {"up": "▲", "down": "▼", "flat": "→"}
METER_CELLS = 10
CODE_LANGUAGE_BY_SUFFIX = {
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


def lower_list(block: ListBlock, lowering: Lowering) -> list[Node]:
    return [ListNode(block.style, tuple(_list_entry(item, block.style, lowering) for item in block.items))]


def _list_entry(item: str | ListItem, kind: ListKind, lowering: Lowering) -> ListEntry:
    if isinstance(item, str):
        return ListEntry(lowering.rich(item))
    children: tuple[Node, ...] = ()
    if item.items:
        children = (ListNode(kind, tuple(_list_entry(child, kind, lowering) for child in item.items)),)
    return ListEntry(lowering.rich(item.text), item.checked, children)


def lower_fact_strip(block: FactStrip) -> list[Node]:
    return [bullets(ListEntry(labelled(fact.label) + plain(fact.value)) for fact in block.facts)]


def lower_key_value(block: KeyValue, lowering: Lowering) -> list[Node]:
    return [bullets(ListEntry(labelled(pair.label) + lowering.rich(pair.value)) for pair in block.pairs)]


def lower_def_list(block: DefList, lowering: Lowering) -> list[Node]:
    return [bullets(_definition(item.term, item.body, lowering) for item in block.items)]


def _definition(term: str, body: str, lowering: Lowering) -> ListEntry:
    parts = paragraphs(body)
    first = lowering.rich(parts[0]) if parts else ()
    rest = tuple(Paragraph(lowering.rich(part)) for part in parts[1:])
    return ListEntry(labelled(term) + first, children=rest)


def lower_cards(cards: list[Card], lowering: Lowering) -> list[Node]:
    return [bullets(_card(card, lowering) for card in cards)]


def _derived_card(card: Card, badge_key: str, lowering: Lowering) -> Rich:
    badge = lowering.report.badges[badge_key]
    if card.of_matrix:
        tally = lowering.matrix_tallies[card.of_matrix]
        count, total = tally["counts"].get(badge_key, 0), tally["total"]
    else:
        tallies = [lowering.table_tallies[table_id] for table_id in card.of_tables or []]
        count = sum(tally["counts"].get(badge_key, 0) for tally in tallies)
        total = sum(tally["total"] for tally in tallies)
    return (
        Chip(card.label or badge.label, badge.tone),
        *plain(f": {compute.fmt(count)} ({compute.pct(count, total)})"),
    )


def _delta(delta: CardDelta) -> Rich:
    mark = f"{DELTA_MARK[delta.direction]} " if delta.direction else ""
    return plain(f" {mark}{delta.label}")


def _card(card: Card, lowering: Lowering) -> ListEntry:
    if card.badge and (card.of_matrix or card.of_tables):
        text = _derived_card(card, card.badge, lowering)
    else:
        value = plain(compute.fmt(card.value)) if card.value is not None else ()
        if card.of and isinstance(card.value, (int, float)):
            value += plain(f" ({compute.pct(card.value, card.of)})")
        if card.delta:
            value += _delta(card.delta)
        text = (labelled(card.label) + value) if card.label else value
        if card.badges:
            text += plain(" ") + lowering.chips(card.badges)
    children: tuple[Node, ...] = (Paragraph(plain(card.note), "muted"),) if card.note else ()
    return ListEntry(text, children=children, tone=card.tone)


def lower_badge_row(block: BadgeRow, lowering: Lowering) -> list[Node]:
    if block.groups:
        return [
            bullets(
                ListEntry(labelled(group.label) + lowering.badge_items(group.items)) for group in block.groups
            )
        ]
    lead = labelled(block.label) if block.label else ()
    return [Paragraph(lead + lowering.badge_items(block.items))]


def lower_callout(block: CalloutBlock, lowering: Lowering) -> list[Node]:
    title: tuple[Node, ...] = (Paragraph(bold(block.title)),) if block.title else ()
    return [Callout(block.tone, title + lowering.prose(block.body))]


def lower_note(block: NoteBlock, lowering: Lowering) -> list[Node]:
    title: tuple[Node, ...] = (Paragraph(bold(block.title)),) if block.title else ()
    return [Callout("neutral", title + lowering.prose(block.body))]


def lower_status_list(block: StatusList, lowering: Lowering) -> list[Node]:
    return [
        bullets(
            ListEntry(plain(f"{STATUS_MARK[item.state]} ") + lowering.rich(item.text)) for item in block.items
        )
    ]


def _meter_bar(value: float, maximum: float) -> str:
    filled = max(0, min(METER_CELLS, round(value / maximum * METER_CELLS))) if maximum else 0
    return "█" * filled + "░" * (METER_CELLS - filled)


def _meter_entry(item: MeterItem) -> ListEntry:
    reading = f"{_meter_bar(item.value, item.max)} {compute.pct(item.value, item.max)} "
    reading += f"({compute.fmt(item.value)} of {compute.fmt(item.max)})"
    return ListEntry(labelled(item.label) + plain(reading), tone=item.tone)


def lower_meter(block: Meter) -> list[Node]:
    return [bullets(_meter_entry(item) for item in block.items)]


def lower_range(block: Range, lowering: Lowering) -> list[Node]:
    total = sum(segment.span for segment in block.segments)
    entries: list[ListEntry] = []
    for segment in block.segments:
        text = labelled(segment.label) + plain(
            f"{compute.fmt(segment.span)} ({compute.pct(segment.span, total)})"
        )
        if segment.sub:
            text += plain(", ") + lowering.rich(segment.sub)
        entries.append(ListEntry(text, tone=segment.tone))
    nodes: list[Node] = []
    if block.axis and (block.axis.min or block.axis.max):
        nodes.append(
            Paragraph(plain(f"From {block.axis.min or 'start'} to {block.axis.max or 'end'}"), "muted")
        )
    return [*nodes, ListNode("bullet", tuple(entries))]


def code_language(label: str | None) -> str:
    if not label:
        return ""
    return CODE_LANGUAGE_BY_SUFFIX.get(PurePosixPath(label.strip()).suffix.lower(), "")


def lower_code(block: CodeBlockModel) -> list[Node]:
    label: list[Node] = [Paragraph((Code(block.label),))] if block.label else []
    language = "diff" if block.mode == "diff" else code_language(block.label)
    return [*label, CodeBlock(block.content.rstrip("\n"), language)]


def lower_quote(block: QuoteBlock, lowering: Lowering) -> list[Node]:
    lines = tuple(lowering.rich(part) for part in paragraphs(block.body))
    return [Quote(lines, plain(block.cite) if block.cite else ())]


def lower_image(block: ImageBlock, lowering: Lowering) -> list[Node]:
    caption = lowering.rich(block.caption) if block.caption else plain(block.alt)
    return [Paragraph(italic(plain("Image: ") + caption), "muted")]


def _timeline_entry(item: TimelineItem, lowering: Lowering) -> ListEntry:
    text: Rich = plain(f"{TIMELINE_MARK[item.state]} ") if item.state else ()
    if item.time:
        text += labelled(item.time)
    text += plain(item.title)
    if item.badges:
        text += plain(" ") + lowering.chips(item.badges)
    children: tuple[Node, ...] = (Paragraph(lowering.rich(item.body)),) if item.body else ()
    return ListEntry(text, children=children)


def lower_timeline(block: Timeline, lowering: Lowering) -> list[Node]:
    return [bullets(_timeline_entry(item, lowering) for item in block.items)]


def _reference_entry(item: ReferenceItem, lowering: Lowering) -> ListEntry:
    number = lowering.rich_context.reference_numbers or {}
    parts: list[Rich] = [plain(f"[{number[item.key]}]"), lowering.rich(item.text)]
    if item.url:
        parts.append((Link((Plain("source"),), item.url),))
    return ListEntry(spaced(parts))


def lower_references(block: References, lowering: Lowering) -> list[Node]:
    return [bullets(_reference_entry(item, lowering) for item in block.items)]
