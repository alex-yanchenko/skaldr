import json
from collections.abc import Iterable, Mapping, Sequence
from itertools import count, groupby
from typing import Final, Literal

from typing_extensions import Never

from skaldr.errors import ExportInvariantError
from skaldr.export.adf.colors import BACKGROUND_COLOR, PANEL_TYPE
from skaldr.export.adf.inline import AdfRuns, IssueLinks, text_color_mark, with_mark
from skaldr.export.adf.nodes import (
    AdfBlock,
    AdfBlockCard,
    AdfBlockCardAttrs,
    AdfBlockquote,
    AdfBulletList,
    AdfCellAttrs,
    AdfCodeBlock,
    AdfCodeBlockAttrs,
    AdfDecisionItem,
    AdfDecisionItemAttrs,
    AdfDecisionList,
    AdfDecisionListAttrs,
    AdfDoc,
    AdfEm,
    AdfEmbedCard,
    AdfEmbedCardAttrs,
    AdfExpand,
    AdfExpandAttrs,
    AdfHeading,
    AdfHeadingAttrs,
    AdfInline,
    AdfListItem,
    AdfMark,
    AdfNestedExpand,
    AdfOrderedList,
    AdfOrderedListAttrs,
    AdfPanel,
    AdfPanelAttrs,
    AdfParagraph,
    AdfRule,
    AdfStrike,
    AdfStrong,
    AdfTable,
    AdfTableAttrs,
    AdfTableCell,
    AdfTableHeader,
    AdfTableRow,
    AdfTaskItem,
    AdfTaskItemAttrs,
    AdfTaskList,
    AdfTaskListAttrs,
    AdfText,
)
from skaldr.export.apportion import apportioned, apportioned_at_least
from skaldr.export.folds import folded, link_card_detail
from skaldr.export.inline import bold, one_line, plain
from skaldr.export.runs import Chip, DecisionMark, ExportRich, StatusMark, export_visible_text
from skaldr.export.swaps import (
    data_table_swapped_in,
    require_the_swap,
    tabs_swapped_for_toggles,
    web_address_of,
)
from skaldr.export.tree import (
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
    GridColumn,
    Heading,
    KeyValueList,
    LabelledValue,
    LinkCard,
    LinkCardDisplay,
    ListEntry,
    ListNode,
    LoweredDocument,
    Media,
    MediaNodeKind,
    Node,
    Paragraph,
    Quote,
    TableCell,
    TableColumn,
    TableNode,
    TableOfContents,
    TableRow,
    Tabs,
    Timeline,
    TimelineEvent,
    Toggle,
    ToneName,
    nested_nodes,
)
from skaldr.models import MEDIA_KIND_LABELS
from skaldr.richtext import Link, Plain

Container = Literal["doc", "panel", "expand", "nested_expand", "cell", "list item", "quote"]

JIRA_DESCRIPTION_LIMIT: Final = 32_767
_TEXT_BLOCKS: Final = frozenset(
    {"paragraph", "heading", "bulletList", "orderedList", "taskList", "decisionList"}
)
_FENCED_BLOCKS: Final = frozenset({"codeBlock", "rule", "panel", "blockquote"})
_CARDS: Final = frozenset({"blockCard", "embedCard"})
_LIST_ITEM_BLOCKS: Final = frozenset({"paragraph", "bulletList", "orderedList", "taskList", "codeBlock"})
_ALLOWED_BLOCKS: Final[Mapping[Container, frozenset[str]]] = {
    "doc": _TEXT_BLOCKS | _FENCED_BLOCKS | _CARDS | {"table", "expand"},
    "expand": _TEXT_BLOCKS | _FENCED_BLOCKS | _CARDS | {"table", "nestedExpand"},
    "nested_expand": _TEXT_BLOCKS | _FENCED_BLOCKS,
    "panel": _TEXT_BLOCKS | {"codeBlock", "rule", "blockCard"},
    "cell": _TEXT_BLOCKS | _FENCED_BLOCKS | _CARDS | {"nestedExpand"},
    "list item": _LIST_ITEM_BLOCKS,
    "quote": frozenset({"paragraph", "bulletList", "orderedList"}),
}
_NESTED_EXPAND_CONTAINERS: Final = frozenset({"expand", "nested_expand", "cell"})
_CARDS_BY_DISPLAY: Final[Mapping[LinkCardDisplay, str]] = {"card": "blockCard", "embed": "embedCard"}
MEDIA_NODE_LABELS: Final[Mapping[MediaNodeKind, str]] = {"image": "Image", **MEDIA_KIND_LABELS}
LATEX_LANGUAGE: Final = "latex"
GROUP_ROW_FALLBACK_TONE: Final[ToneName] = "neutral"
PLAIN_GRID_COLUMN_LIMIT: Final = 3
TABLE_WIDTH: Final = 760
UNSHARED_COLUMN_MINIMUM_SHARE: Final = 0.1
MINIMUM_COLUMN_WIDTH: Final = 60
DECISION_MARK_SEPARATOR: Final = " "
MOST_TOGGLE_LEVELS_IN_A_CELL: Final = 1
COVER_LABEL: Final = "Cover image"
WHEN_COLUMN: Final = "When"
STATE_COLUMN: Final = "State"
WHAT_COLUMN: Final = "What"


def _require_the_container_holds(node: Node, produced: Iterable[AdfBlock], container: Container) -> None:
    for block in produced:
        if block["type"] not in _ALLOWED_BLOCKS[container]:
            raise ExportInvariantError(
                f"ADF does not allow a {block['type']} inside a {container}, written from a "
                f"{type(node).__name__}; the export check should have refused it"
            )


def _require_a_list_item_holds(node: Node, produced: Iterable[AdfBlock]) -> None:
    for block in produced:
        if block["type"] not in _LIST_ITEM_BLOCKS:
            raise ExportInvariantError(
                f"ADF does not allow a {block['type']} inside a list item, written from a "
                f"{type(node).__name__}; the export check should have refused it"
            )


def _empty_paragraph() -> AdfParagraph:
    return AdfParagraph(type="paragraph")


def _padded(cells: Sequence[TableCell], width: int) -> list[TableCell]:
    return [*cells, *[TableCell(())] * (width - len(cells))]


def _marked_item(item: AdfListItem, mark: AdfMark) -> AdfListItem:
    return AdfListItem(type="listItem", content=[_marked_block(child, mark) for child in item["content"]])


def _marked_decision_item(item: AdfDecisionItem, mark: AdfMark) -> AdfDecisionItem:
    marked = AdfDecisionItem(type="decisionItem", attrs=item["attrs"])
    if "content" in item:
        marked["content"] = list(with_mark(tuple(item["content"]), mark))
    return marked


def _marked_block(block: AdfBlock, mark: AdfMark) -> AdfBlock:
    if block["type"] == "paragraph":
        return _paragraph_of(list(with_mark(tuple(block.get("content", [])), mark)))
    if block["type"] == "bulletList":
        return AdfBulletList(
            type="bulletList", content=[_marked_item(item, mark) for item in block["content"]]
        )
    if block["type"] == "orderedList":
        marked = AdfOrderedList(
            type="orderedList", content=[_marked_item(item, mark) for item in block["content"]]
        )
        if "attrs" in block:
            marked["attrs"] = block["attrs"]
        return marked
    if block["type"] == "decisionList":
        return AdfDecisionList(
            type="decisionList",
            attrs=block["attrs"],
            content=[_marked_decision_item(item, mark) for item in block["content"]],
        )
    raise ExportInvariantError(
        f"ADF cannot mark a {block['type']} inside a table cell; "
        "the lowering should hold only paragraphs and lists there"
    )


def _label_runs(label: str | None) -> ExportRich:
    return plain(one_line(label or "").removesuffix(":").rstrip())


def _card_label(card: Card) -> ExportRich:
    if card.badge is None:
        return _label_runs(card.label)
    return (Chip.on_one_line(card.label or "", card.badge),)


def _paragraph_of(content: list[AdfInline]) -> AdfParagraph:
    return AdfParagraph(type="paragraph", content=content) if content else _empty_paragraph()


def _table_cell(
    content: list[AdfBlock], *, header: bool, tone: ToneName | None = None
) -> AdfTableCell | AdfTableHeader:
    cell: AdfTableCell | AdfTableHeader = (
        AdfTableHeader(type="tableHeader", content=content)
        if header
        else AdfTableCell(type="tableCell", content=content)
    )
    if tone:
        cell["attrs"] = AdfCellAttrs(background=BACKGROUND_COLOR[tone])
    return cell


def _sized_cell(cell: AdfTableCell | AdfTableHeader, width: int) -> AdfTableCell | AdfTableHeader:
    background = cell.get("attrs", AdfCellAttrs()).get("background")
    attrs = (
        AdfCellAttrs(colwidth=[width])
        if background is None
        else AdfCellAttrs(background=background, colwidth=[width])
    )
    if cell["type"] == "tableHeader":
        return AdfTableHeader(type="tableHeader", attrs=attrs, content=cell["content"])
    return AdfTableCell(type="tableCell", attrs=attrs, content=cell["content"])


def _sized_row(
    row: Sequence[AdfTableCell | AdfTableHeader], widths: Sequence[int]
) -> list[AdfTableCell | AdfTableHeader]:
    return [_sized_cell(cell, width) for cell, width in zip(row, widths, strict=True)]


def _table_of(
    rows: Sequence[Sequence[AdfTableCell | AdfTableHeader]], widths: Sequence[int] | None = None
) -> AdfTable:
    if widths is None:
        attrs = AdfTableAttrs(isNumberColumnEnabled=False, layout="default")
    else:
        attrs = AdfTableAttrs(isNumberColumnEnabled=False, layout="center", width=TABLE_WIDTH)
        rows = [_sized_row(row, widths) for row in rows]
    return AdfTable(
        type="table", attrs=attrs, content=[AdfTableRow(type="tableRow", content=list(row)) for row in rows]
    )


def _column_widths(columns: Sequence[TableColumn], column_count: int) -> list[int] | None:
    shares = [column.share for column in columns][:column_count]
    shares += [None] * (column_count - len(shares))
    unshared = shares.count(None)
    if unshared == column_count:
        return None
    left_over = max(0.0, 1 - sum(share or 0 for share in shares))
    unshared_share = max(left_over / unshared, UNSHARED_COLUMN_MINIMUM_SHARE) if unshared else 0.0
    return _widths_over_the_table([unshared_share if share is None else share for share in shares])


def _widths_over_the_table(weights: Sequence[float]) -> list[int]:
    if len(weights) * MINIMUM_COLUMN_WIDTH > TABLE_WIDTH:
        return apportioned([1] * len(weights), TABLE_WIDTH)
    return apportioned_at_least(weights, TABLE_WIDTH, MINIMUM_COLUMN_WIDTH)


def _decided_words(entry: ListEntry) -> ExportRich | None:
    match entry.text:
        case (DecisionMark(decided=True), Plain(text=separator), *words) if (
            separator == DECISION_MARK_SEPARATOR and not entry.children
        ):
            return tuple(words)
        case _:
            return None


def _is_a_decided_point(entry: ListEntry) -> bool:
    return _decided_words(entry) is not None


def _toned_grid_cell(column: GridColumn) -> Callout | None:
    match column.children:
        case (Callout(authored_as="grid cell") as cell,):
            return cell
        case _:
            return None


def _holds_a_table(nodes: Iterable[Node]) -> bool:
    return any(isinstance(node, TableNode) or _holds_a_table(nested_nodes(node)) for node in nodes)


def _toggle_levels(nodes: Iterable[Node]) -> int:
    return max(
        (_toggle_levels(nested_nodes(node)) + int(isinstance(node, Toggle | Tabs)) for node in nodes),
        default=0,
    )


def _row_marks(row: TableRow) -> list[AdfMark]:
    emphasised: list[AdfMark] = [AdfStrong(type="strong")] if row.emphasis is not None else []
    struck: list[AdfMark] = [AdfStrike(type="strike")] if row.tone == "muted" else []
    return [*emphasised, *struck]


def _expand_type(container: Container) -> Literal["expand", "nestedExpand"]:
    return "nestedExpand" if container in _NESTED_EXPAND_CONTAINERS else "expand"


class _AdfBlocks:
    def __init__(self, issue_links: IssueLinks | None) -> None:
        self.runs = AdfRuns(issue_links)
        self.local_ids = count(1)

    def local_id(self, kind: str) -> str:
        return f"skaldr-{kind}-{next(self.local_ids)}"

    def inline(self, runs: ExportRich) -> list[AdfInline]:
        return list(self.runs.write(runs))

    def paragraph(self, runs: ExportRich) -> AdfParagraph:
        content = self.inline(runs)
        return AdfParagraph(type="paragraph", content=content) if content else _empty_paragraph()

    def blocks(self, nodes: Iterable[Node], container: Container) -> list[AdfBlock]:
        written: list[AdfBlock] = []
        for node in nodes:
            native = self.native_blocks(node, container)
            if native is not None:
                _require_the_container_holds(node, native, container)
                written += native
                continue
            for each in folded((node,)):
                produced = self.node_blocks(each, container)
                _require_the_container_holds(each, produced, container)
                written += produced
        return written

    def native_blocks(self, node: Node, container: Container) -> list[AdfBlock] | None:
        allowed = _ALLOWED_BLOCKS[container]
        match node:
            case FactStrip() | KeyValueList() | DefinitionList() | Cards() | Timeline():
                return self.table_blocks(node) if "table" in allowed else None
            case LinkCard():
                return self.link_card_blocks(node) if _CARDS_BY_DISPLAY[node.display] in allowed else None
            case Toggle() if node.open and _expand_type(container) in allowed:
                return [self.expand(container, export_visible_text(node.title), node.children)]
            case Columns() if "table" in allowed and self.is_a_table_of_cells(node):
                return [self.grid_table(node)]
            case _:
                return None

    def is_a_table_of_cells(self, node: Columns) -> bool:
        held = nested_nodes(node)
        if _holds_a_table(held):
            return False
        needs_a_table = len(node.columns) > PLAIN_GRID_COLUMN_LIMIT or any(
            _toned_grid_cell(column) is not None for column in node.columns
        )
        return needs_a_table or _toggle_levels(held) <= MOST_TOGGLE_LEVELS_IN_A_CELL

    def node_blocks(self, node: GenericNode, container: Container) -> list[AdfBlock]:
        match node:
            case Heading():
                content = self.inline(node.text)
                level = AdfHeadingAttrs(level=node.level)
                return [AdfHeading(type="heading", attrs=level, content=content)] if content else []
            case Paragraph():
                return self.paragraph_blocks(node)
            case ListNode():
                return self.list_blocks(node, container)
            case TableNode():
                return [self.table(node)]
            case CodeBlock():
                return [self.code_block(node.content, node.language)]
            case DisplayMath():
                require_the_swap("math block", "adf")
                return [self.code_block(node.expression, LATEX_LANGUAGE)]
            case Callout():
                content = self.blocks(node.children, "panel") or [_empty_paragraph()]
                panel = AdfPanelAttrs(panelType=PANEL_TYPE[node.tone])
                return [AdfPanel(type="panel", attrs=panel, content=content)]
            case Quote():
                return self.quote_blocks(node)
            case Divider():
                return [AdfRule(type="rule")]
            case Media():
                return [self.media_paragraph(node)]
            case Toggle():
                return [self.expand(container, export_visible_text(node.title), node.children)]
            case Columns():
                return self.blocks(nested_nodes(node), container)
            case Tabs():
                return self.tabs_blocks(node, container)
            case Diagram():
                return self.diagram_blocks(node, container)
            case TableOfContents():
                return []
            case _:
                exhausted: Never = node
                raise ExportInvariantError(f"ADF has no form for the lowered node {type(exhausted).__name__}")

    def paragraph_blocks(self, node: Paragraph) -> list[AdfBlock]:
        content = self.inline(node.text)
        if not content:
            return []
        if node.tone is not None:
            content = list(with_mark(tuple(content), text_color_mark(node.tone)))
        return [AdfParagraph(type="paragraph", content=content)]

    def media_paragraph(self, node: Media) -> AdfParagraph:
        url = web_address_of(node, "adf")
        name = self.runs.write(node.caption or node.description or plain(url))
        label = (AdfText(type="text", text=f"{MEDIA_NODE_LABELS[node.kind]}: "),)
        return AdfParagraph(
            type="paragraph", content=list(self.runs.concat([label, self.runs.link(name, url)]))
        )

    def code_block(self, content: str, language: str) -> AdfCodeBlock:
        block = AdfCodeBlock(type="codeBlock")
        if language:
            block["attrs"] = AdfCodeBlockAttrs(language=language)
        if content:
            block["content"] = [AdfText(type="text", text=content)]
        return block

    def quote_blocks(self, node: Quote) -> list[AdfBlock]:
        content = self.blocks(node.body, "quote")
        cite = with_mark(tuple(self.inline(node.cite)), AdfEm(type="em"))
        if cite:
            content.append(AdfParagraph(type="paragraph", content=list(cite)))
        return [AdfBlockquote(type="blockquote", content=content)] if content else []

    def link_card_blocks(self, node: LinkCard) -> list[AdfBlock]:
        card: AdfBlockCard | AdfEmbedCard
        if node.display == "card":
            card = AdfBlockCard(type="blockCard", attrs=AdfBlockCardAttrs(url=node.url))
        else:
            card = AdfEmbedCard(type="embedCard", attrs=AdfEmbedCardAttrs(url=node.url, layout="center"))
        return [card, *self.paragraph_blocks(Paragraph(plain(link_card_detail(node)), "muted"))]

    def expand(self, container: Container, title: str, children: Sequence[Node]) -> AdfBlock:
        attrs = AdfExpandAttrs(title=title)
        if container in _NESTED_EXPAND_CONTAINERS:
            nested = self.blocks(children, "nested_expand") or [_empty_paragraph()]
            return AdfNestedExpand(type="nestedExpand", attrs=attrs, content=nested)
        content = self.blocks(children, "expand") or [_empty_paragraph()]
        return AdfExpand(type="expand", attrs=attrs, content=content)

    def tabs_blocks(self, node: Tabs, container: Container) -> list[AdfBlock]:
        return [
            block
            for toggle in tabs_swapped_for_toggles(node, "adf")
            for block in self.node_blocks(toggle, container)
        ]

    def diagram_blocks(self, node: Diagram, container: Container) -> list[AdfBlock]:
        return self.blocks(data_table_swapped_in(node, "adf"), container)

    def list_blocks(self, node: ListNode, container: Container) -> list[AdfBlock]:
        if not node.entries:
            return []
        if node.kind == "check":
            return self.task_blocks(node)
        if node.kind == "bullet" and "decisionList" in _ALLOWED_BLOCKS[container]:
            return self.bullet_and_decision_blocks(node)
        items = [self.list_item(entry) for entry in node.entries]
        return [self.listed(node.kind, items, node.start)]

    def bullet_and_decision_blocks(self, node: ListNode) -> list[AdfBlock]:
        blocks: list[AdfBlock] = []
        for decided, entries in groupby(node.entries, _is_a_decided_point):
            if decided:
                blocks.append(self.decision_list(list(entries)))
            else:
                blocks.append(self.listed("bullet", [self.list_item(entry) for entry in entries]))
        return blocks

    def decision_list(self, entries: Sequence[ListEntry]) -> AdfDecisionList:
        attrs = AdfDecisionListAttrs(localId=self.local_id("decision-list"))
        return AdfDecisionList(
            type="decisionList", attrs=attrs, content=[self.decision_item(entry) for entry in entries]
        )

    def decision_item(self, entry: ListEntry) -> AdfDecisionItem:
        attrs = AdfDecisionItemAttrs(localId=self.local_id("decision"), state="DECIDED")
        item = AdfDecisionItem(type="decisionItem", attrs=attrs)
        words = self.inline(_decided_words(entry) or ())
        if words:
            item["content"] = words
        return item

    def listed(self, kind: Literal["bullet", "number"], items: list[AdfListItem], first: int = 1) -> AdfBlock:
        if kind == "bullet":
            return AdfBulletList(type="bulletList", content=items)
        if first == 1:
            return AdfOrderedList(type="orderedList", content=items)
        return AdfOrderedList(type="orderedList", attrs=AdfOrderedListAttrs(order=first), content=items)

    def list_item(self, entry: ListEntry) -> AdfListItem:
        content: list[AdfBlock] = [self.paragraph(entry.text)]
        for child in folded(entry.children):
            produced = self.node_blocks(child, "list item")
            _require_a_list_item_holds(child, produced)
            content += produced
        return AdfListItem(type="listItem", content=content)

    def task_blocks(self, node: ListNode) -> list[AdfBlock]:
        attrs = AdfTaskListAttrs(localId=self.local_id("task-list"))
        content: list[AdfTaskItem | AdfTaskList] = []
        for entry in node.entries:
            content.append(self.task_item(entry))
            content += self.nested_task_lists(entry.children)
        return [AdfTaskList(type="taskList", attrs=attrs, content=content)]

    def task_item(self, entry: ListEntry) -> AdfTaskItem:
        state = "DONE" if entry.checked else "TODO"
        item = AdfTaskItem(
            type="taskItem", attrs=AdfTaskItemAttrs(localId=self.local_id("task"), state=state)
        )
        text = self.inline(entry.text)
        if text:
            item["content"] = text
        return item

    def nested_task_lists(self, children: Sequence[Node]) -> list[AdfTaskList]:
        nested: list[AdfTaskList] = []
        for child in folded(children):
            produced = self.node_blocks(child, "list item")
            _require_a_list_item_holds(child, produced)
            for block in produced:
                if block["type"] != "taskList":
                    raise ExportInvariantError(
                        f"ADF does not allow a {block['type']} inside a task item, written from a "
                        f"{type(child).__name__}; "
                        "skaldr lowers a checklist entry's detail only as a nested checklist"
                    )
                nested.append(block)
        return nested

    def cell_blocks(self, cell: TableCell) -> list[AdfBlock]:
        if not cell.blocks:
            return [self.paragraph(cell.text)]
        return self.blocks(cell.blocks, "cell") or [_empty_paragraph()]

    def table_cell(
        self, cell: TableCell, tone: ToneName | None, *, header: bool, marks: Sequence[AdfMark] = ()
    ) -> AdfTableCell | AdfTableHeader:
        content = self.cell_blocks(cell)
        for mark in marks:
            content = [_marked_block(block, mark) for block in content]
        return _table_cell(content, header=header, tone=tone)

    def run_cell(
        self, runs: ExportRich, *, header: bool, tone: ToneName | None = None
    ) -> AdfTableCell | AdfTableHeader:
        return _table_cell([self.paragraph(runs)], header=header, tone=tone)

    def body_row(self, table: TableNode, row: TableRow, width: int) -> list[AdfTableCell | AdfTableHeader]:
        band = (row.fill or GROUP_ROW_FALLBACK_TONE) if row.emphasis == "group" else row.fill
        marks = _row_marks(row)
        cells: list[AdfTableCell | AdfTableHeader] = []
        for index, cell in enumerate(_padded(row.cells, width)):
            column = table.columns[index].tone if index < len(table.columns) else None
            cells.append(
                self.table_cell(
                    cell,
                    cell.tone or band or column,
                    header=table.header_column and index == 0,
                    marks=marks,
                )
            )
        return cells

    def table(self, node: TableNode) -> AdfTable:
        width = max(len(cells) for cells in (node.header, *(row.cells for row in node.rows)))
        header = [self.table_cell(cell, cell.tone, header=True) for cell in _padded(node.header, width)]
        rows = [header, *(self.body_row(node, row, width) for row in node.rows)]
        return _table_of(rows, _column_widths(node.columns, width))

    def table_blocks(
        self, node: FactStrip | KeyValueList | DefinitionList | Cards | Timeline
    ) -> list[AdfBlock]:
        match node:
            case FactStrip():
                return self.fact_strip_blocks(node)
            case KeyValueList():
                return self.labelled_rows(node.pairs)
            case DefinitionList():
                return self.definition_rows(node.definitions)
            case Cards():
                return self.cards_blocks(node)
            case Timeline():
                return self.timeline_blocks(node)

    def fact_strip_blocks(self, node: FactStrip) -> list[AdfBlock]:
        if not node.facts:
            return []
        labels = [_label_runs(fact.label) for fact in node.facts]
        values = [self.run_cell(fact.value, header=False) for fact in node.facts]
        if not any(labels):
            return [_table_of([values])]
        return [_table_of([[self.run_cell(label, header=True) for label in labels], values])]

    def labelled_rows(self, pairs: Sequence[LabelledValue]) -> list[AdfBlock]:
        rows = [
            [self.run_cell(_label_runs(pair.label), header=True), self.run_cell(pair.value, header=False)]
            for pair in pairs
        ]
        return [_table_of(rows)] if rows else []

    def definition_rows(self, definitions: Sequence[Definition]) -> list[AdfBlock]:
        rows = [
            [
                self.run_cell(plain(definition.term), header=True),
                _table_cell(self.blocks(definition.body, "cell") or [_empty_paragraph()], header=False),
            ]
            for definition in definitions
        ]
        return [_table_of(rows)] if rows else []

    def cards_blocks(self, node: Cards) -> list[AdfBlock]:
        if not node.cards:
            return []
        labels = [self.inline(_card_label(card)) for card in node.cards]
        rows = [[self.run_cell(card.value, header=False, tone=card.tone) for card in node.cards]]
        if any(labels):
            rows.insert(
                0,
                [
                    _table_cell([_paragraph_of(label)], header=True, tone=card.tone)
                    for label, card in zip(labels, node.cards, strict=True)
                ],
            )
        if any(card.note for card in node.cards):
            rows.append([self.note_cell(card) for card in node.cards])
        return [_table_of(rows)]

    def note_cell(self, card: Card) -> AdfTableCell | AdfTableHeader:
        note = self.paragraph_blocks(Paragraph(plain(card.note), "muted")) or [_empty_paragraph()]
        return _table_cell(note, header=False, tone=card.tone)

    def timeline_blocks(self, node: Timeline) -> list[AdfBlock]:
        if not node.events:
            return []
        has_when = any(event.time for event in node.events)
        has_state = any(event.state for event in node.events)
        header = [
            self.run_cell(plain(name), header=True)
            for name, shown in (
                (WHEN_COLUMN, has_when),
                (STATE_COLUMN, has_state),
                (WHAT_COLUMN, True),
            )
            if shown
        ]
        rows = [header, *(self.event_row(event, has_when, has_state) for event in node.events)]
        return [_table_of(rows)]

    def event_row(
        self, event: TimelineEvent, has_when: bool, has_state: bool
    ) -> list[AdfTableCell | AdfTableHeader]:
        cells: list[AdfTableCell | AdfTableHeader] = []
        if has_when:
            cells.append(self.run_cell(plain(event.time or ""), header=False))
        if has_state:
            state = (StatusMark(event.state),) if event.state else ()
            cells.append(self.run_cell(state, header=False))
        title = (*bold(event.title), *((Plain(" "), *event.chips) if event.chips else ()))
        what = [self.paragraph(title)]
        if event.body:
            what.append(self.paragraph(event.body))
        cells.append(_table_cell(list(what), header=False))
        return cells

    def grid_table(self, node: Columns) -> AdfTable:
        widths = _widths_over_the_table([column.ratio for column in node.columns])
        return _table_of([[self.grid_cell(column) for column in node.columns]], widths)

    def grid_cell(self, column: GridColumn) -> AdfTableCell | AdfTableHeader:
        toned = _toned_grid_cell(column)
        children = toned.children if toned else column.children
        content = self.blocks(children, "cell") or [_empty_paragraph()]
        return _table_cell(content, header=False, tone=toned.tone if toned else None)


def render_adf(nodes: Sequence[Node], issue_links: IssueLinks | None = None) -> AdfDoc:
    content = _AdfBlocks(issue_links).blocks(nodes, "doc")
    return AdfDoc(version=1, type="doc", content=content or [_empty_paragraph()])


def _cover_link(cover: str | None) -> tuple[Paragraph, ...]:
    return (Paragraph((Link((Plain(COVER_LABEL),), cover),)),) if cover else ()


def render_adf_document(document: LoweredDocument, issue_links: IssueLinks | None = None) -> AdfDoc:
    return render_adf((*_cover_link(document.cover), *document.body), issue_links)


def render_adf_regions(
    document: LoweredDocument, issue_links: IssueLinks | None = None
) -> tuple[list[AdfBlock], ...]:
    writer = _AdfBlocks(issue_links)
    return tuple(writer.blocks(region.nodes, "doc") for region in document.regions)


def adf_json(document: AdfDoc) -> str:
    return json.dumps(document, ensure_ascii=False, indent=2) + "\n"


def compact_adf_length(document: Mapping[str, object]) -> int:
    return len(json.dumps(document, separators=(",", ":"), ensure_ascii=False))
