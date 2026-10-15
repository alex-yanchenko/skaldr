from collections.abc import Iterable, Mapping
from dataclasses import replace
from typing import Final

from typing_extensions import assert_never

from skaldr import compute
from skaldr.export.capabilities import FIRST_LIST_NUMBER
from skaldr.export.inline import bold, plain
from skaldr.export.lower.context import with_bold_label
from skaldr.export.runs import Chip, ExportRich, StatusMark, export_visible_text
from skaldr.export.tree import (
    AuthoredName,
    Callout,
    Card,
    Cards,
    CodeBlock,
    Columns,
    Definition,
    DefinitionList,
    Diagram,
    DisplayMath,
    Divider,
    FactStrip,
    GenericNode,
    Heading,
    KeyValueList,
    LabelledValue,
    LinkCard,
    LinkCardDisplay,
    ListEntry,
    ListNode,
    Media,
    Node,
    Paragraph,
    Quote,
    TableNode,
    TableOfContents,
    Tabs,
    TextNumbering,
    Timeline,
    TimelineEvent,
    Toggle,
)
from skaldr.richtext import Link, Plain, Styled

LINK_CARD_SEPARATOR: Final = " · "
LINK_CARD_NAMES: Final[Mapping[LinkCardDisplay, AuthoredName]] = {
    "card": "link card",
    "embed": "link embed",
}


def _bullets(entries: Iterable[ListEntry], path: str | None) -> ListNode:
    return ListNode("bullet", tuple(entries), authored_at=path)


def _labelled_values(values: Iterable[LabelledValue], path: str | None) -> ListNode:
    return _bullets((ListEntry(with_bold_label(value.label, value.value)) for value in values), path)


def _definition_entry(definition: Definition) -> ListEntry:
    body = definition.body
    if body and isinstance(body[0], Paragraph):
        return ListEntry(with_bold_label(definition.term, body[0].text), children=body[1:])
    return ListEntry(with_bold_label(definition.term, ()), children=body)


def _card_text(card: Card) -> ExportRich:
    if card.badge is None:
        return with_bold_label(card.label, card.value, card.tone)
    chip = Chip.on_one_line(card.label or "", card.badge)
    return (chip, Plain(": "), *card.value) if card.value else (chip,)


def _card_entry(card: Card, path: str | None) -> ListEntry:
    note: tuple[Node, ...] = (Paragraph(plain(card.note), "muted", authored_at=path),) if card.note else ()
    return ListEntry(_card_text(card), children=note)


def _event_entry(event: TimelineEvent, path: str | None) -> ListEntry:
    text = with_bold_label(event.time, plain(event.title))
    if event.state:
        text = (StatusMark(event.state), Plain(" "), *text)
    if event.chips:
        text += (Plain(" "), *event.chips)
    body: tuple[Node, ...] = (Paragraph(event.body, authored_at=path),) if event.body is not None else ()
    return ListEntry(text, children=body)


def _link_card_quote(card: LinkCard) -> Quote:
    link = Link(plain(card.title), card.url)
    detail = LINK_CARD_SEPARATOR.join(part for part in (card.domain, card.caption) if part)
    return Quote(
        ((Styled("bold", (link,)),),),
        plain(detail),
        authored_as=LINK_CARD_NAMES[card.display],
        authored_at=card.authored_at,
    )


def _bold_title_over_its_content(toggle: Toggle) -> tuple[GenericNode, ...]:
    title = bold(export_visible_text(toggle.title))
    return (Paragraph(title, authored_at=toggle.authored_at), *folded(toggle.children))


def _bullets_led_by_their_labels(node: ListNode, numbering: TextNumbering) -> ListNode:
    entries = tuple(
        replace(entry, text=(Plain(f"{compute.list_label(index, numbering)}. "), *entry.text))
        for index, entry in enumerate(node.entries, start=node.start)
    )
    return replace(node, kind="bullet", entries=entries, start=FIRST_LIST_NUMBER, numbering=None)


def _as_written_today(node: Node) -> tuple[GenericNode, ...]:
    match node:
        case Toggle() if node.open:
            return _bold_title_over_its_content(node)
        case ListNode() if node.numbering is not None:
            return (_bullets_led_by_their_labels(node, node.numbering),)
        case FactStrip():
            return (_labelled_values(node.facts, node.authored_at),)
        case KeyValueList():
            return (_labelled_values(node.pairs, node.authored_at),)
        case DefinitionList():
            return (_bullets(map(_definition_entry, node.definitions), node.authored_at),)
        case Cards():
            return (_bullets((_card_entry(card, node.authored_at) for card in node.cards), node.authored_at),)
        case Timeline():
            events = (_event_entry(event, node.authored_at) for event in node.events)
            return (_bullets(events, node.authored_at),)
        case LinkCard():
            return (_link_card_quote(node),)
        case (
            Heading()
            | Paragraph()
            | ListNode()
            | TableNode()
            | CodeBlock()
            | DisplayMath()
            | Media()
            | Callout()
            | Quote()
            | Divider()
            | Toggle()
            | Columns()
            | Tabs()
            | Diagram()
            | TableOfContents()
        ):
            return (node,)
        case _:
            assert_never(node)


def folded(nodes: Iterable[Node]) -> tuple[GenericNode, ...]:
    return tuple(written for node in nodes for written in _as_written_today(node))
