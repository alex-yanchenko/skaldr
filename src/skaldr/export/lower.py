import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, cast

from typing_extensions import assert_never

from skaldr import compute
from skaldr.export.inline import (
    Break,
    Chip,
    Code,
    InlineContext,
    Link,
    Plain,
    Rich,
    bold,
    italic,
    labelled,
    paragraphs,
    parse_rich,
    plain,
    visible_text,
)
from skaldr.export.tree import (
    Callout,
    CodeBlock,
    Column,
    Columns,
    Diagram,
    Heading,
    Image,
    ListEntry,
    ListNode,
    Node,
    Paragraph,
    Quote,
    Tab,
    Table,
    TableCell,
    TableOfContents,
    TableRow,
    Tabs,
    Toggle,
    ToneName,
)
from skaldr.models import (
    AnyBlock,
    BadgeLiteral,
    BadgeRef,
    BadgeRow,
    Card,
    Cards,
    Chart,
    Comparison,
    ComparisonCell,
    DefList,
    FactStrip,
    Fan,
    Flow,
    FlowStep,
    Grid,
    InnerGrid,
    KeyValue,
    ListBlock,
    ListItem,
    Matrix,
    Meter,
    Note,
    Panel,
    Range,
    ReferenceItem,
    References,
    Report,
    Request,
    RequestCase,
    RequestFlow,
    RequestLike,
    RequestVariable,
    Section,
    StatusList,
    Swimlane,
    SwimlaneStep,
    Text,
    Timeline,
    TimelineItem,
    Walkthrough,
    WalkthroughStep,
    iter_reference_items,
)
from skaldr.models import Callout as CalloutBlock
from skaldr.models import Code as CodeModel
from skaldr.models import Heading as HeadingBlock
from skaldr.models import Image as ImageBlock
from skaldr.models import Quote as QuoteBlock
from skaldr.models import Table as TableBlock

STATUS_MARK = {"done": "✅", "current": "🔵", "pending": "⚪", "failed": "❌", "blocked": "⛔"}
SWIMLANE_MARK = {"done": "✅", "current": "🔵", "todo": "⚪", "blocked": "⛔", "deferred": "⏸️"}
TIMELINE_MARK = {"done": "✅", "current": "🔵", "pending": "⚪"}
DELTA_MARK = {"up": "▲", "down": "▼", "flat": "→"}
INDICATOR_MARK = {"success": "🟢", "warning": "🟡", "danger": "🔴", "info": "🔵", "neutral": "⚪"}
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
MERMAID_FILL = {
    "success": ("#e6f4ea", "#1e8e3e"),
    "info": ("#e8f0fe", "#1a73e8"),
    "warning": ("#fef7e0", "#b06000"),
    "danger": ("#fce8e6", "#c5221f"),
    "accent": ("#f3e8fd", "#8430ce"),
    "teal": ("#e4f7f6", "#00796b"),
    "sky": ("#e1f5fe", "#0277bd"),
    "neutral": ("#f1f3f4", "#5f6368"),
}
MERMAID_TEXT = "#1f2328"
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
METER_CELLS = 10


def tone_named(name: str | None) -> ToneName | None:
    return TONE_BY_NAME.get(name) if name else None


@dataclass(frozen=True)
class _Lowering:
    report: Report
    inline: InlineContext
    matrix_tallies: dict[str, compute.DerivedTally]
    table_tallies: dict[str, compute.DerivedTally]

    def rich(self, text: str) -> Rich:
        return parse_rich(text, self.inline)

    def prose(self, text: str, tone: ToneName | None = None) -> tuple[Node, ...]:
        return tuple(Paragraph(self.rich(part), tone) for part in paragraphs(text))

    def chip(self, key: str) -> Chip:
        badge = self.report.badges[key]
        return Chip(badge.label, badge.tone)

    def chips(self, keys: Sequence[str]) -> Rich:
        runs: list[Plain | Chip] = []
        for key in keys:
            if runs:
                runs.append(Plain(" "))
            runs.append(self.chip(key))
        return tuple(runs)


def lower_report(report: Report) -> tuple[Node, ...]:
    lowering = _Lowering(
        report=report,
        inline=InlineContext(
            citation_numbers=compute.reference_numbers(report),
            citation_urls={item.key: item.url for item in iter_reference_items(report.blocks)},
            anchor_ids=frozenset(compute.anchor_slugs(report).values()),
        ),
        matrix_tallies=compute.matrix_tallies(report),
        table_tallies=compute.table_tallies(report),
    )
    nodes: list[Node] = [Paragraph(lowering.rich(line), "muted") for line in report.meta.subtitle]
    if report.meta.toc:
        nodes.append(TableOfContents())
    nodes += lower_blocks(report.blocks, lowering, depth=0)
    nodes += _legend(report)
    footer = compute.provenance_footer(report)
    if footer:
        nodes.append(Paragraph(plain(footer), "muted"))
    return tuple(nodes)


def lower_blocks(blocks: Sequence[AnyBlock], lowering: _Lowering, depth: int) -> list[Node]:
    nodes: list[Node] = []
    for block in blocks:
        nodes += lower_block(block, lowering, depth)
    return nodes


def lower_block(block: AnyBlock, lowering: _Lowering, depth: int) -> list[Node]:
    match block:
        case HeadingBlock():
            nodes: list[Node] = [Heading(min(block.level + depth, 4), plain(block.text))]
            if block.sub:
                nodes.append(Paragraph(italic(lowering.rich(block.sub)), "muted"))
            return nodes
        case Text():
            return list(lowering.prose(block.body, "muted" if block.muted else None))
        case ListBlock():
            return [
                ListNode(block.style, tuple(_list_entry(item, block.style, lowering) for item in block.items))
            ]
        case FactStrip():
            return [_bullets(ListEntry(labelled(fact.label) + plain(fact.value)) for fact in block.facts)]
        case KeyValue():
            return [
                _bullets(ListEntry(labelled(pair.label) + lowering.rich(pair.value)) for pair in block.pairs)
            ]
        case DefList():
            return [_bullets(_definition(item.term, item.body, lowering) for item in block.items)]
        case Cards():
            return [_bullets(_card(card, lowering) for card in block.items)]
        case BadgeRow():
            return _badge_row(block, lowering)
        case CalloutBlock():
            title: tuple[Node, ...] = (Paragraph(bold(block.title)),) if block.title else ()
            return [Callout(block.tone, title + lowering.prose(block.body))]
        case StatusList():
            return [
                _bullets(
                    ListEntry(plain(f"{STATUS_MARK[item.state]} ") + lowering.rich(item.text))
                    for item in block.items
                )
            ]
        case Meter():
            return [_bullets(_meter_entry(item.label, item.value, item.max) for item in block.items)]
        case Range():
            return _range(block, lowering)
        case CodeModel():
            return _code(block)
        case QuoteBlock():
            lines = tuple(lowering.rich(part) for part in paragraphs(block.body))
            return [Quote(lines, plain(block.cite) if block.cite else ())]
        case Note():
            heading: tuple[Node, ...] = (Paragraph(bold(block.title)),) if block.title else ()
            return [Callout("neutral", heading + lowering.prose(block.body))]
        case ImageBlock():
            return _image(block, lowering)
        case Timeline():
            return [_bullets(_timeline_entry(item, lowering) for item in block.items)]
        case Flow():
            return [_flow(block, lowering)]
        case Fan():
            return [_fan(block, lowering)]
        case Chart():
            return _chart(block)
        case Comparison():
            return [_comparison(block, lowering)]
        case Matrix():
            return [_matrix(block, lowering)]
        case Swimlane():
            return _swimlane(block)
        case References():
            return [_bullets(_reference_entry(item, lowering) for item in block.items)]
        case TableBlock():
            return _table(block, lowering)
        case Request():
            return _request(block, lowering)
        case RequestFlow():
            return _request_flow(block, lowering)
        case Section():
            return _section(block, lowering, depth)
        case Panel():
            return [
                Callout(
                    "neutral", (Paragraph(bold(block.title)), *lower_blocks(block.blocks, lowering, depth))
                )
            ]
        case Grid() | InnerGrid():
            return _grid(block, lowering, depth)
        case Walkthrough():
            return [
                ListNode("number", tuple(_walkthrough_entry(step, lowering, depth) for step in block.steps))
            ]
        case _:
            assert_never(block)


def _bullets(entries: Any) -> ListNode:
    return ListNode("bullet", tuple(cast("list[ListEntry]", list(entries))))


def _list_entry(item: "str | ListItem", style: str, lowering: _Lowering) -> ListEntry:
    if isinstance(item, str):
        return ListEntry(lowering.rich(item))
    children: tuple[Node, ...] = ()
    if item.items:
        kind = "check" if style == "check" else "bullet" if style == "bullet" else "number"
        children = (ListNode(kind, tuple(_list_entry(child, style, lowering) for child in item.items)),)
    return ListEntry(lowering.rich(item.text), item.checked, children)


def _definition(term: str, body: str, lowering: _Lowering) -> ListEntry:
    parts = paragraphs(body)
    first = lowering.rich(parts[0]) if parts else ()
    rest = tuple(Paragraph(lowering.rich(part)) for part in parts[1:])
    return ListEntry(labelled(term) + first, children=rest)


def _derived_card(card: Card, lowering: _Lowering) -> Rich:
    badge_key = card.badge or ""
    badge = lowering.report.badges[badge_key]
    if card.of_matrix:
        tally = lowering.matrix_tallies[card.of_matrix]
        count, total = tally["counts"].get(badge_key, 0), tally["total"]
    else:
        table_ids = card.of_tables or []
        count = sum(lowering.table_tallies[table_id]["counts"].get(badge_key, 0) for table_id in table_ids)
        total = sum(lowering.table_tallies[table_id]["total"] for table_id in table_ids)
    return (
        Chip(card.label or badge.label, badge.tone),
        *plain(f": {compute.fmt(count)} ({compute.pct(count, total)})"),
    )


def _card(card: Card, lowering: _Lowering) -> ListEntry:
    if card.of_matrix or card.of_tables:
        text = _derived_card(card, lowering)
    else:
        value = plain(compute.fmt(card.value)) if card.value is not None else ()
        if card.of and isinstance(card.value, (int, float)):
            value += plain(f" ({compute.pct(card.value, card.of)})")
        if card.delta:
            mark = f"{DELTA_MARK[card.delta.direction]} " if card.delta.direction else ""
            value += plain(f" {mark}{card.delta.label}")
        text = (labelled(card.label) + value) if card.label else value
        if card.badges:
            text += plain(" ") + lowering.chips(card.badges)
    children: tuple[Node, ...] = (Paragraph(plain(card.note), "muted"),) if card.note else ()
    return ListEntry(text, children=children)


def _badge_items(items: Sequence[BadgeRef | BadgeLiteral], lowering: _Lowering) -> Rich:
    runs: list[Plain | Chip] = []
    for item in items:
        if runs:
            runs.append(Plain(" "))
        runs.append(lowering.chip(item.key) if isinstance(item, BadgeRef) else Chip(item.label, item.tone))
    return tuple(runs)


def _badge_row(block: BadgeRow, lowering: _Lowering) -> list[Node]:
    if block.groups:
        return [
            _bullets(
                ListEntry(labelled(group.label) + _badge_items(group.items, lowering))
                for group in block.groups
            )
        ]
    lead = labelled(block.label) if block.label else ()
    return [Paragraph(lead + _badge_items(block.items, lowering))]


def _meter_bar(value: float, maximum: float) -> str:
    filled = max(0, min(METER_CELLS, round(value / maximum * METER_CELLS))) if maximum else 0
    return "█" * filled + "░" * (METER_CELLS - filled)


def _meter_entry(label: str, value: float, maximum: float) -> ListEntry:
    share = compute.pct(value, maximum)
    reading = f"{_meter_bar(value, maximum)} {share} ({compute.fmt(value)} of {compute.fmt(maximum)})"
    return ListEntry(labelled(label) + plain(reading))


def _range(block: Range, lowering: _Lowering) -> list[Node]:
    total = sum(segment.span for segment in block.segments)
    entries: list[ListEntry] = []
    for segment in block.segments:
        text = labelled(segment.label) + plain(
            f"{compute.fmt(segment.span)} ({compute.pct(segment.span, total)})"
        )
        if segment.sub:
            text += plain(", ") + lowering.rich(segment.sub)
        entries.append(ListEntry(text))
    nodes: list[Node] = []
    if block.axis and (block.axis.min or block.axis.max):
        nodes.append(
            Paragraph(plain(f"From {block.axis.min or 'start'} to {block.axis.max or 'end'}"), "muted")
        )
    nodes.append(ListNode("bullet", tuple(entries)))
    return nodes


def code_language(label: str | None) -> str:
    if not label:
        return ""
    return CODE_LANGUAGE_BY_SUFFIX.get(PurePosixPath(label.strip()).suffix.lower(), "")


def _code(block: CodeModel) -> list[Node]:
    nodes: list[Node] = [Paragraph((Code(block.label),))] if block.label else []
    language = "diff" if block.mode == "diff" else code_language(block.label)
    nodes.append(CodeBlock(block.content.rstrip("\n"), language))
    return nodes


def _image(block: ImageBlock, lowering: _Lowering) -> list[Node]:
    caption = lowering.rich(block.caption) if block.caption else plain(block.alt)
    if block.src.startswith(("http://", "https://")):
        return [Image(block.src, caption)]
    return [Paragraph(italic(plain("Image: ") + caption), "muted")]


def _timeline_entry(item: TimelineItem, lowering: _Lowering) -> ListEntry:
    text: Rich = plain(f"{TIMELINE_MARK[item.state]} ") if item.state else ()
    if item.time:
        text += labelled(item.time)
    text += plain(item.title)
    if item.badges:
        text += plain(" ") + lowering.chips(item.badges)
    children: tuple[Node, ...] = (Paragraph(lowering.rich(item.body)),) if item.body else ()
    return ListEntry(text, children=children)


def _mermaid_label(text: str) -> str:
    return text.replace('"', "#quot;")


def _mermaid_node(node_id: str, step: FlowStep, lowering: _Lowering, prefix: str = "") -> str:
    label = _mermaid_label(prefix + step.label)
    if step.note:
        label += "<br>" + _mermaid_label(visible_text(lowering.rich(step.note)))
    tone_class = f":::{step.tone}" if step.tone else ""
    return f'    {node_id}["{label}"]{tone_class}'


def _mermaid_classes(steps: Sequence[FlowStep]) -> list[str]:
    tones = sorted({step.tone for step in steps if step.tone})
    return [_mermaid_class(tone) for tone in tones if tone in MERMAID_FILL]


def _mermaid_class(tone: str) -> str:
    fill, stroke = MERMAID_FILL[tone]
    return f"    classDef {tone} fill:{fill},stroke:{stroke},color:{MERMAID_TEXT}"


def _step_entry(step: FlowStep, lowering: _Lowering) -> ListEntry:
    text = bold(step.label)
    if step.note:
        text += plain(": ") + lowering.rich(step.note)
    if step.badges:
        text += plain(" ") + lowering.chips(step.badges)
    children: tuple[Node, ...] = ()
    if step.points:
        children = (_bullets(ListEntry(lowering.rich(point)) for point in step.points),)
    return ListEntry(text, children=children)


def _supplement(steps: Sequence[FlowStep], lowering: _Lowering) -> tuple[Node, ...]:
    detailed = [step for step in steps if step.points or step.badges]
    return (_bullets(_step_entry(step, lowering) for step in detailed),) if detailed else ()


def _flow(block: Flow, lowering: _Lowering) -> Diagram:
    direction = "TB" if block.style == "steps" else "LR"
    lines = [f"flowchart {direction}"]
    lines += [
        _mermaid_node(f"s{index}", step, lowering, f"{index}: " if block.numbered else "")
        for index, step in enumerate(block.steps, start=1)
    ]
    lines += [f"    s{index} --> s{index + 1}" for index in range(1, len(block.steps))]
    if block.loop:
        lines.append(f"    s{len(block.steps)} -.-> s1")
    lines += _mermaid_classes(block.steps)
    kind = "number" if block.numbered else "bullet"
    fallback: list[Node] = [ListNode(kind, tuple(_step_entry(step, lowering) for step in block.steps))]
    if block.loop:
        fallback.append(Paragraph(plain(f"Then back to {block.steps[0].label}."), "muted"))
    return Diagram("\n".join(lines), tuple(fallback), _supplement(block.steps, lowering))


def _fan(block: Fan, lowering: _Lowering) -> Diagram:
    lines = ["flowchart LR", _mermaid_node("hub", block.hub, lowering)]
    lines += [
        _mermaid_node(f"s{index}", spoke, lowering) for index, spoke in enumerate(block.spokes, start=1)
    ]
    for index in range(1, len(block.spokes) + 1):
        lines.append(f"    s{index} --> hub" if block.direction == "in" else f"    hub --> s{index}")
    lines += _mermaid_classes([block.hub, *block.spokes])
    joined = "flow into" if block.direction == "in" else "fan out from"
    hub_note = plain(": ") + lowering.rich(block.hub.note) if block.hub.note else ()
    fallback: tuple[Node, ...] = (
        Paragraph(plain(f"These {joined} ") + bold(block.hub.label) + hub_note),
        _bullets(_step_entry(spoke, lowering) for spoke in block.spokes),
    )
    return Diagram("\n".join(lines), fallback, _supplement([block.hub, *block.spokes], lowering))


def _mermaid_text(text: str) -> str:
    return '"' + text.replace('"', "'") + '"'


def _cells(*texts: str) -> tuple[TableCell, ...]:
    return tuple(TableCell(plain(text)) for text in texts)


def _chart(block: Chart) -> list[Node]:
    nodes: list[Node] = [Paragraph(bold(block.title))] if block.title else []
    if block.variant == "donut":
        total = sum(item.value for item in block.slices)
        table = Table(
            _cells("Slice", "Value", "Share"),
            tuple(
                TableRow(_cells(item.label, compute.fmt(item.value), compute.pct(item.value, total)))
                for item in block.slices
            ),
        )
        lines = ["pie"] + [f"    {_mermaid_text(item.label)} : {item.value}" for item in block.slices]
        nodes.append(Diagram("\n".join(lines), (table,)))
        return nodes
    table = Table(
        _cells("Series", *block.categories),
        tuple(
            TableRow(_cells(series.label, *(compute.fmt(value) for value in series.values)))
            for series in block.series
        ),
    )
    if block.stacked:
        nodes.append(table)
        return nodes
    mark = "bar" if block.variant == "bar" else "line"
    lines = [
        "xychart-beta",
        "    x-axis [" + ", ".join(_mermaid_text(category) for category in block.categories) + "]",
    ]
    lines += [
        f"    {mark} [" + ", ".join(str(value) for value in series.values) + "]" for series in block.series
    ]
    nodes.append(Diagram("\n".join(lines), (table,), (table,) if len(block.series) > 1 else ()))
    return nodes


def _comparison_cell(cell: "bool | str | ComparisonCell", negative: bool, lowering: _Lowering) -> TableCell:
    if isinstance(cell, bool):
        good = cell != negative
        return TableCell(plain("✓" if cell else "✗"), "success" if good else "danger")
    if isinstance(cell, str):
        return TableCell(lowering.rich(cell))
    return TableCell(lowering.rich(cell.value), tone_named(cell.tone))


def _comparison(block: Comparison, lowering: _Lowering) -> Table:
    header = (
        TableCell(()),
        *tuple(
            TableCell(bold(f"★ {option}") if index == block.highlight else plain(option))
            for index, option in enumerate(block.options)
        ),
    )
    polarity = block.polarity or []
    rows: list[TableRow] = []
    for row in block.rows:
        cells = [TableCell(bold(row.feature))]
        for index, cell in enumerate(row.values):
            negative = index < len(polarity) and polarity[index] == "negative"
            cells.append(_comparison_cell(cell, negative, lowering))
        rows.append(TableRow(tuple(cells)))
    return Table(header, tuple(rows), header_column=True)


def _matrix(block: Matrix, lowering: _Lowering) -> Table:
    grid = compute.matrix_grid(block)
    header = (TableCell(()), *_cells(*block.columns))
    rows: list[TableRow] = []
    for row_name, cells in zip(block.rows, grid, strict=False):
        row_cells = [TableCell(bold(row_name))]
        for cell in cells:
            if cell is None:
                row_cells.append(TableCell(()))
            elif cell.badge:
                badge = lowering.report.badges[cell.badge]
                row_cells.append(TableCell(plain(cell.label or badge.label), tone_named(badge.tone)))
            else:
                row_cells.append(TableCell(plain(cell.label or ""), tone_named(cell.tone)))
        rows.append(TableRow(tuple(row_cells)))
    return Table(header, tuple(rows), header_column=True)


def _swim_step(step: SwimlaneStep, id_to_n: dict[str, str]) -> Rich:
    mark = plain(f"{SWIMLANE_MARK[step.state]} ")
    number: Rich = (Link((Plain(step.n),), step.url),) if step.url else bold(step.n)
    text = mark + number + plain(f" {step.label}")
    if step.value is not None:
        text += plain(f" ({compute.fmt(step.value)})")
    if step.depends_on:
        needs = ", ".join(dict.fromkeys(id_to_n[dep] for dep in step.depends_on))
        text += italic(plain(f" needs {needs}"))
    return text


def _swimlane_header(block: Swimlane, has_values: bool) -> tuple[TableCell, ...]:
    groups_by_column: dict[str, list[str]] = {}
    for group in block.groups:
        for column in group.columns:
            groups_by_column.setdefault(column, []).append(group.name)
    header = [TableCell(plain("Lane"))]
    for column in block.columns:
        text: Rich = bold(column.name)
        if column.sub:
            text += (Break(), *italic(plain(column.sub)))
        if column.key in groups_by_column:
            text += (Break(), *plain(", ".join(groups_by_column[column.key])))
        header.append(TableCell(text))
    if has_values:
        header.append(TableCell(plain("Total")))
    return tuple(header)


def _swimlane(block: Swimlane) -> list[Node]:
    id_to_n = {step.id: step.n for step in block.steps if step.id is not None}
    has_values = any(step.value is not None for step in block.steps)
    rows: list[TableRow] = []
    for lane in block.lanes:
        cells = [TableCell(bold(lane.name))]
        lane_total = 0.0
        for column in block.columns:
            runs: Rich = ()
            for step in block.steps:
                if step.lane != lane.key or step.col != column.key:
                    continue
                if runs:
                    runs += (Break(),)
                runs += _swim_step(step, id_to_n)
                lane_total += step.value or 0
            cells.append(TableCell(runs))
        if has_values:
            cells.append(TableCell(plain(compute.fmt(lane_total))))
        rows.append(TableRow(tuple(cells)))
    if has_values:
        totals = [TableCell(bold("Total"))]
        for column in block.columns:
            totals.append(
                TableCell(
                    plain(compute.fmt(sum(step.value or 0 for step in block.steps if step.col == column.key)))
                )
            )
        totals.append(TableCell(plain(compute.fmt(sum(step.value or 0 for step in block.steps)))))
        rows.append(TableRow(tuple(totals), emphasis="total"))
    nodes: list[Node] = [Table(_swimlane_header(block, has_values), tuple(rows), header_column=True)]
    states = list(dict.fromkeys(step.state for step in block.steps))
    if len(states) > 1:
        nodes.append(
            Paragraph(plain(" · ".join(f"{SWIMLANE_MARK[state]} {state}" for state in states)), "muted")
        )
    return nodes


def _reference_entry(item: ReferenceItem, lowering: _Lowering) -> ListEntry:
    runs = plain(f"[{lowering.inline.citation_numbers[item.key]}] ") + lowering.rich(item.text)
    if item.url:
        runs += (*plain(" "), Link((Plain("source"),), item.url))
    return ListEntry(runs)


def _cell_text(value: object, lowering: _Lowering) -> Rich:
    runs: Rich = ()
    if value is None or value == "":
        return runs
    for part in paragraphs(str(value)):
        if runs:
            runs += (Break(),)
        runs += lowering.rich(part)
    return runs


def _badge_keys(raw: object) -> list[str]:
    keys: list[object] = cast("list[object]", raw) if isinstance(raw, list) else [raw]
    return [str(key).strip() for key in keys if key is not None and str(key).strip()]


def _title_cell(block: TableBlock, row: dict[str, Any], value: object, lowering: _Lowering) -> TableCell:
    text = _cell_text(value, lowering)
    for badge_column in block.title_badges:
        keys = _badge_keys(row.get(badge_column.key))
        if keys:
            text += plain(" ") + lowering.chips(keys)
    subrows = cast("list[dict[str, Any]]", row.get("subrows") or [])
    for sub in subrows:
        text += (Break(), *plain(f"{sub['label']}: {compute.fmt(sub['value'])}"))
    return TableCell(text)


def _table_row(block: TableBlock, row: dict[str, Any], title_key: str, lowering: _Lowering) -> TableRow:
    cells: list[TableCell] = []
    for column in block.cell_columns:
        value: object = row.get(column.key)
        if column.key == title_key:
            cells.append(_title_cell(block, row, value, lowering))
        elif column.kind == "number":
            text = plain(compute.fmt(value)) if value is not None else ()
            if column.pct_of_total and block.reconcile and isinstance(value, (int, float)):
                text += plain(f" ({compute.pct(value, block.reconcile.total)} of total)")
            cells.append(TableCell(text))
        elif column.kind == "indicator":
            tone = str(value or "").strip()
            cells.append(TableCell(plain(INDICATOR_MARK.get(tone, "")), tone_named(tone)))
        elif column.kind == "badge":
            cells.append(TableCell(lowering.chips(_badge_keys(value))))
        else:
            cells.append(TableCell(_cell_text(value, lowering)))
    tone = tone_named(cast("str | None", row.get("tone")))
    if tone is None and block.tint_by:
        keys = _badge_keys(row.get(block.tint_by))
        if keys:
            tone = tone_named(lowering.report.badges[keys[0]].tone)
    return TableRow(tuple(cells), tone)


def _blank_cells(count: int) -> tuple[TableCell, ...]:
    return tuple(TableCell(()) for _ in range(count))


def _table_body(block: TableBlock, title_key: str, lowering: _Lowering) -> list[TableRow]:
    sum_key = block.reconcile.column if block.reconcile else block.totals.column if block.totals else None
    width = len(block.cell_columns)
    if block.groups is None:
        return [_table_row(block, row, title_key, lowering) for row in block.all_rows()]
    rows: list[TableRow] = []
    for group in block.groups:
        group_rows = cast("list[dict[str, Any]]", group.rows)
        label = bold(group.name)
        if sum_key:
            label += plain(f" ({compute.fmt(compute.col_sum(group_rows, sum_key))})")
        rows.append(TableRow((TableCell(label), *_blank_cells(width - 1)), emphasis="group"))
        if group_rows:
            rows += [_table_row(block, row, title_key, lowering) for row in group_rows]
        else:
            rows.append(TableRow((TableCell(italic(plain("none"))), *_blank_cells(width - 1))))
    return rows


def _table(block: TableBlock, lowering: _Lowering) -> list[Node]:
    text_keys = [column.key for column in block.columns if column.kind == "text"]
    rich_keys = [column.key for column in block.columns if column.kind == "rich"]
    title_key = text_keys[0] if text_keys else rich_keys[0] if rich_keys else block.cell_columns[0].key
    rows = _table_body(block, title_key, lowering)
    if block.totals:
        total_key = block.totals.column
        totals = [
            TableCell(bold(compute.fmt(compute.col_sum(block.all_rows(), total_key))))
            if column.key == total_key
            else TableCell(bold("Total") if index == 0 else ())
            for index, column in enumerate(block.cell_columns)
        ]
        rows.append(TableRow(tuple(totals), emphasis="total"))
    nodes: list[Node] = [Table(_cells(*(column.label for column in block.cell_columns)), tuple(rows))]
    buckets = compute.table_rollup(block)
    if buckets:
        runs: Rich = labelled(block.rollup.label) if block.rollup and block.rollup.label else ()
        for index, bucket in enumerate(buckets):
            if index:
                runs += plain(" · ")
            runs += (lowering.chip(bucket["key"]), *plain(f" {bucket['count']}"))
        nodes.append(Paragraph(runs))
    if block.reconcile:
        nodes.append(Paragraph(plain(compute.reconcile_line(block)), "muted"))
    return nodes


def _is_json(body: str) -> bool:
    try:
        json.loads(body)
    except ValueError:
        return False
    return True


def _response_block(case: RequestCase) -> CodeBlock:
    body = compute.recorded_body(case.response.body).rstrip("\n")
    lines: list[str] = []
    for name, values in case.response.headers.items():
        lines += [f"{name}: {value}" for value in ([values] if isinstance(values, str) else values)]
    if lines:
        return CodeBlock("\n".join([*lines, "", body]), "http")
    return CodeBlock(body, "json" if _is_json(body) else "")


def _case_nodes(core: RequestLike, case: RequestCase, lowering: _Lowering) -> tuple[Node, ...]:
    nodes: list[Node] = [CodeBlock(compute.command_for(core, case), "bash")]
    if core.command_note:
        nodes.append(Paragraph(italic(lowering.rich(core.command_note)), "muted"))
    if case.response.status is not None or core.command is None:
        nodes.append(Paragraph(bold("Response") + plain(f": {compute.status_line(case.response)}")))
    else:
        nodes.append(Paragraph(bold("Output")))
    nodes.append(_response_block(case))
    if case.verdict:
        verdict = Paragraph(bold("Verdict") + plain(": ") + lowering.rich(case.verdict))
        nodes.append(Callout(compute.case_tone(case), (verdict,)))
    return tuple(nodes)


def _cases(core: RequestLike, lowering: _Lowering) -> list[Node]:
    if len(core.cases) == 1:
        case = core.cases[0]
        return [Paragraph(italic(plain(case.label))), *_case_nodes(core, case, lowering)]
    tabs = tuple(
        Tab(plain(case.label), _case_nodes(core, case, lowering), compute.case_tone(case))
        for case in core.cases
    )
    return [Tabs(tabs)]


def _variable_entry(variable: RequestVariable) -> ListEntry:
    if variable.secret:
        detail = "a secret, supply your own"
    elif variable.example:
        detail = f"for example {variable.example}"
    else:
        detail = "supply a value"
    return ListEntry(
        (Code("{{" + variable.name + "}}"), *plain(f" {variable.label or variable.name}: {detail}"))
    )


def _variables(variables: Sequence[RequestVariable]) -> list[Node]:
    if not variables:
        return []
    return [
        Paragraph(bold("Values you supply")),
        ListNode("bullet", tuple(_variable_entry(variable) for variable in variables)),
    ]


def _request(block: Request, lowering: _Lowering) -> list[Node]:
    return [Paragraph(bold(block.label)), *_variables(block.variables), *_cases(block, lowering)]


def _request_flow(block: RequestFlow, lowering: _Lowering) -> list[Node]:
    nodes: list[Node] = [Paragraph(bold(block.label)), *_variables(block.variables)]
    for index, step in enumerate(block.steps, start=1):
        heading: Rich = bold(f"Step {index} of {len(block.steps)}: {step.label}")
        for position, capture in enumerate(step.captures):
            heading += (*plain(", captures " if position == 0 else ", "), Code(capture.name))
        nodes.append(Paragraph(heading))
        nodes += _cases(step, lowering)
    return nodes


def _section(block: Section, lowering: _Lowering, depth: int) -> list[Node]:
    level = min(2 + depth, 4)
    children: list[Node] = (
        [Paragraph(italic(plain(f"updated {block.updated}")), "muted")] if block.updated else []
    )
    children += lower_blocks(block.blocks, lowering, depth + 1)
    if block.collapsed:
        return [Toggle(plain(block.title), level, tuple(children))]
    return [Heading(level, plain(block.title)), *children]


def _grid(block: Grid | InnerGrid, lowering: _Lowering, depth: int) -> list[Node]:
    total = sum(cell.span for cell in block.cells)
    columns: list[Column] = []
    for cell in block.cells:
        children: tuple[Node, ...] = tuple(lower_blocks(cell.blocks, lowering, depth))
        tone = tone_named(cell.tone)
        if tone:
            children = (Callout(tone, children),)
        columns.append(Column(round(cell.span / total * 100), children))
    if len(columns) == 1 or isinstance(block, InnerGrid):
        return [node for column in columns for node in column.children]
    return [Columns(tuple(columns))]


def _walkthrough_entry(step: WalkthroughStep, lowering: _Lowering, depth: int) -> ListEntry:
    text = bold(step.label)
    if step.sub:
        text += plain(" ") + italic(lowering.rich(step.sub))
    return ListEntry(text, children=tuple(lower_blocks(step.detail, lowering, depth)))


def _legend(report: Report) -> list[Node]:
    used = compute.used_badges(report)
    if not used:
        return []
    entries = tuple(
        ListEntry((Chip(badge.label, badge.tone), *plain(f" {badge.legend}"))) for _, badge in used
    )
    return [Toggle(plain("Legend: badges used on this page"), None, (ListNode("bullet", entries),))]
