from collections.abc import Sequence
from dataclasses import dataclass

from typing_extensions import assert_never

from skaldr import compute, models
from skaldr.code_language import block_code_language
from skaldr.export.inline import bold, one_line, plain
from skaldr.export.lower.context import Lowering, bullets, spaced, with_bold_label
from skaldr.export.runs import Chip, DecisionMark, ExportRich, Gauge, Mark, SectionLink, StatusMark
from skaldr.export.tree import (
    AuthoredName,
    Callout,
    Card,
    Cards,
    CodeBlock,
    Definition,
    DefinitionList,
    DisplayMath,
    FactStrip,
    KeyValueList,
    LabelledValue,
    LinkCard,
    ListEntry,
    ListKind,
    ListNode,
    Media,
    Node,
    Paragraph,
    Quote,
    ReferenceEntry,
    References,
    TextNumbering,
    Timeline,
    TimelineEvent,
    ToneName,
)
from skaldr.richtext import Code, Link, Plain


def _marked(mark: Mark, text: ExportRich) -> ExportRich:
    return (mark, Plain(" "), *text)


@dataclass(frozen=True)
class _ListShape:
    style: models.ListStyle
    text_numbering: TextNumbering | None


def _text_numbering(numbering: models.ListNumbering | None) -> TextNumbering | None:
    match numbering:
        case "letters" | "roman":
            return numbering
        case "decimal" | None:
            return None
        case _:
            assert_never(numbering)


def lower_list(block: models.ListBlock, lowering: Lowering) -> list[Node]:
    shape = _ListShape(block.style, _text_numbering(block.numbering))
    return [_list_node(block.items, shape, lowering, block.start or 1)]


def _list_kind(shape: _ListShape) -> ListKind:
    return "bullet" if shape.style == "decision" else shape.style


def _list_node(
    items: Sequence[str | models.ListItem], shape: _ListShape, lowering: Lowering, start: int = 1
) -> ListNode:
    entries = tuple(_list_entry(item, shape, lowering) for item in items)
    return ListNode(_list_kind(shape), entries, start, shape.text_numbering)


def _list_entry(item: str | models.ListItem, shape: _ListShape, lowering: Lowering) -> ListEntry:
    if isinstance(item, str):
        source, decided, checked, nested = item, False, False, list[str | models.ListItem]()
    else:
        source, decided, checked, nested = item.text, item.decided, item.checked, item.items
    text = lowering.rich(source)
    if shape.style == "decision":
        text = _marked(DecisionMark(decided), text)
    children: tuple[Node, ...] = (_list_node(nested, shape, lowering),) if nested else ()
    return ListEntry(text, checked, children)


def lower_fact_strip(block: models.FactStrip) -> list[Node]:
    return [FactStrip(tuple(LabelledValue(fact.label, plain(fact.value)) for fact in block.facts))]


def lower_section_fields(fields: models.SectionFields, lowering: Lowering) -> list[Node]:
    facts = compute.section_facts(fields, lowering.section_titles)
    if not facts:
        return []
    return [FactStrip(tuple(LabelledValue(fact.label, _fact_values(fact)) for fact in facts))]


def _fact_values(fact: compute.SectionFact) -> ExportRich:
    if all(value.kind != "link" for value in fact.values):
        return plain(", ".join(value.text for value in fact.values))
    return spaced(tuple((SectionLink(plain(value.text), value.anchor or ""),) for value in fact.values), ", ")


def lower_key_value(block: models.KeyValue, lowering: Lowering) -> list[Node]:
    return [KeyValueList(tuple(LabelledValue(pair.label, lowering.rich(pair.value)) for pair in block.pairs))]


def lower_def_list(block: models.DefList, lowering: Lowering) -> list[Node]:
    return [DefinitionList(tuple(Definition(item.term, lowering.prose(item.body)) for item in block.items))]


def lower_cards(block: models.Cards, lowering: Lowering) -> list[Node]:
    return [Cards(tuple(_card(card, lowering) for card in block.items))]


def _derived_card(card: models.Card, badge_key: str, badge: models.Badge, lowering: Lowering) -> Card:
    count, total = compute.derived_card_tally(
        card, badge_key, lowering.matrix_tallies, lowering.table_tallies
    )
    share = plain(f"{compute.fmt(count)} ({compute.pct(count, total)})")
    return Card(card.label or badge.label, share, note=card.note or "", badge=badge.tone)


def _delta(delta: models.CardDelta) -> ExportRich:
    text = f"{compute.DELTA_GLYPHS[delta.direction]} {delta.label}" if delta.direction else delta.label
    return (Chip.on_one_line(text, models.badge_color_of(delta.tone)),) if delta.tone else plain(text)


def _card(card: models.Card, lowering: Lowering) -> Card:
    if card.derived and card.badge is not None:
        return _derived_card(card, card.badge, lowering.report.badges[card.badge], lowering)
    parts: list[ExportRich] = [plain(compute.fmt(card.value))]
    if card.of and isinstance(card.value, int | float):
        parts.append(plain(f"({compute.pct(card.value, card.of)})"))
    if card.delta:
        parts.append(_delta(card.delta))
    parts.append(lowering.chips(card.badges))
    return Card(
        card.label,
        spaced([part for part in parts if part]),
        note=card.note or "",
        tone=_tone_unless_a_chip_shows_it(card, lowering),
    )


def _tone_unless_a_chip_shows_it(card: models.Card, lowering: Lowering) -> models.ToneLiteral | None:
    chip_tones = {models.BADGE_COLOR_TONE[lowering.report.badges[key].tone] for key in card.badges}
    if card.delta and card.delta.tone:
        chip_tones.add(card.delta.tone)
    return None if card.tone in chip_tones else card.tone


def lower_badge_row(block: models.BadgeRow, lowering: Lowering) -> list[Node]:
    if block.groups:
        return [
            bullets(
                ListEntry(with_bold_label(group.label, lowering.badge_items(group.items)))
                for group in block.groups
            )
        ]
    return [Paragraph(with_bold_label(block.label, lowering.badge_items(block.items)))]


def _titled_callout(
    tone: ToneName, block: models.Callout | models.Note, lowering: Lowering, authored_as: AuthoredName
) -> list[Node]:
    heading: tuple[Node, ...] = (Paragraph(bold(block.title)),) if block.title else ()
    return [Callout(tone, heading + lowering.prose(block.body), block.icon, authored_as=authored_as)]


def lower_callout(block: models.Callout, lowering: Lowering) -> list[Node]:
    return _titled_callout(block.tone, block, lowering, "callout")


def lower_note(block: models.Note, lowering: Lowering) -> list[Node]:
    return _titled_callout("neutral", block, lowering, "note")


def lower_status_list(block: models.StatusList, lowering: Lowering) -> list[Node]:
    return [
        bullets(ListEntry(_marked(StatusMark(item.state), lowering.rich(item.text))) for item in block.items)
    ]


def _meter_entry(item: models.MeterItem) -> ListEntry:
    gauge: ExportRich = (Gauge(item.value, item.max), Plain(" "))
    share = plain(compute.pct(item.value, item.max))
    return ListEntry(with_bold_label(item.label, gauge + share, item.tone))


def lower_meter(block: models.Meter) -> list[Node]:
    return [bullets(_meter_entry(item) for item in block.items)]


def lower_code(block: models.Code) -> list[Node]:
    label: list[Node] = [Paragraph((Code(one_line(block.label)),))] if block.label else []
    language = "diff" if block.mode == "diff" else block_code_language(block)
    return [*label, CodeBlock(block.content.rstrip("\n"), language)]


def lower_math(block: models.Math) -> list[Node]:
    return [DisplayMath("\n".join(line for line in block.expression.split("\n") if line.strip()))]


def lower_quote(block: models.Quote, lowering: Lowering) -> list[Node]:
    return [Quote(lowering.prose(block.body), plain(block.cite) if block.cite else ())]


def lower_image(block: models.Image) -> list[Node]:
    return [Media("image", block.src, plain(block.alt), plain(block.caption or ""))]


def lower_media(block: models.Media) -> list[Node]:
    return [Media(block.kind, block.src, caption=plain(block.caption or ""))]


def lower_link(block: models.Link) -> list[Node]:
    card = compute.link_card(block)
    if block.display == "inline":
        return [Paragraph((Link(plain(card.title), card.url),))]
    return [LinkCard(card.title, card.url, block.display, card.domain, card.caption)]


def _timeline_event(item: models.TimelineItem, lowering: Lowering) -> TimelineEvent:
    return TimelineEvent(
        item.title,
        item.time,
        item.state,
        lowering.chips(item.badges),
        lowering.rich(item.body) if item.body else None,
    )


def lower_timeline(block: models.Timeline, lowering: Lowering) -> list[Node]:
    return [Timeline(tuple(_timeline_event(item, lowering) for item in block.items))]


def _reference_entry(item: models.ReferenceItem, lowering: Lowering) -> ReferenceEntry:
    numbers = lowering.rich_context.reference_numbers or {}
    return ReferenceEntry(numbers[item.key], lowering.rich(item.text), item.url)


def lower_references(block: models.References, lowering: Lowering) -> list[Node]:
    return [References(tuple(_reference_entry(item, lowering) for item in block.items))]
