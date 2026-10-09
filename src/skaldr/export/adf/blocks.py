import json
from collections.abc import Iterable, Mapping, Sequence
from itertools import count, takewhile
from typing import Final, Literal

from typing_extensions import Never

from skaldr.errors import AdfUnsupportedError
from skaldr.export.adf.colors import BACKGROUND_COLOR, PANEL_TYPE
from skaldr.export.adf.inline import AdfRuns, IssueLinks, text_color_mark, with_mark
from skaldr.export.adf.nodes import (
    AdfBlock,
    AdfBlockquote,
    AdfBulletList,
    AdfCellAttrs,
    AdfCodeBlock,
    AdfCodeBlockAttrs,
    AdfDoc,
    AdfEm,
    AdfExpand,
    AdfExpandAttrs,
    AdfHeading,
    AdfHeadingAttrs,
    AdfInline,
    AdfListItem,
    AdfNestedExpand,
    AdfOrderedList,
    AdfOrderedListAttrs,
    AdfPanel,
    AdfPanelAttrs,
    AdfParagraph,
    AdfRule,
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
from skaldr.export.runs import ExportRich, export_visible_text
from skaldr.export.tree import (
    Callout,
    CodeBlock,
    Columns,
    Diagram,
    DisplayMath,
    Divider,
    Graph,
    Heading,
    ListEntry,
    ListNode,
    LoweredDocument,
    Node,
    Paragraph,
    Quote,
    TableCell,
    TableNode,
    TableOfContents,
    TableRow,
    Tabs,
    Toggle,
    ToneName,
    nested_nodes,
)
from skaldr.richtext import Plain

Container = Literal["doc", "panel", "expand", "nested_expand"]

JIRA_DESCRIPTION_LIMIT: Final = 32_767
_TEXT_BLOCKS: Final = frozenset({"paragraph", "heading", "bulletList", "orderedList", "taskList"})
_FENCED_BLOCKS: Final = frozenset({"codeBlock", "rule", "panel", "blockquote"})
_ALLOWED_BLOCKS: Final[Mapping[Container, frozenset[str]]] = {
    "doc": _TEXT_BLOCKS | _FENCED_BLOCKS | {"table", "expand"},
    "expand": _TEXT_BLOCKS | _FENCED_BLOCKS | {"table", "nestedExpand"},
    "nested_expand": _TEXT_BLOCKS | _FENCED_BLOCKS,
    "panel": _TEXT_BLOCKS | {"codeBlock", "rule"},
}
_LIST_ITEM_BLOCKS: Final = frozenset({"paragraph", "bulletList", "orderedList", "taskList", "codeBlock"})
_CONTAINER_TERM: Final[Mapping[Container, str]] = {
    "doc": "the document",
    "panel": "a callout",
    "expand": "a toggle",
    "nested_expand": "a toggle that is itself inside a toggle",
}
_NODE_TERM: Final[Mapping[type, str]] = {
    Heading: "heading",
    Paragraph: "text",
    ListNode: "list",
    TableNode: "table",
    CodeBlock: "code block",
    DisplayMath: "math block",
    Callout: "callout",
    Quote: "quote",
    Divider: "divider",
    Toggle: "toggle",
    Columns: "grid",
    Tabs: "set of tabs",
    Diagram: "diagram",
    TableOfContents: "table of contents",
}
LATEX_LANGUAGE: Final = "latex"
LOOP_BACK_NOTE: Final = " (loop back)"
LEADS_TO: Final = " \N{RIGHTWARDS ARROW} "
GROUP_ROW_FALLBACK_TONE: Final[ToneName] = "neutral"


def _fits_in_a_list_item(block: AdfBlock) -> bool:
    return block["type"] in _LIST_ITEM_BLOCKS


def _empty_paragraph() -> AdfParagraph:
    return AdfParagraph(type="paragraph")


def _padded(cells: Sequence[TableCell], width: int) -> list[TableCell]:
    return [*cells, *[TableCell(())] * (width - len(cells))]


def _graph_entries(graph: Graph) -> tuple[ListEntry, ...]:
    labels = {node.key: node.label for node in graph.nodes}
    entries: list[ListEntry] = []
    for node in graph.nodes:
        text = node.label + (f": {node.note}" if node.note else "")
        leads_to = [
            labels[edge.target] + (LOOP_BACK_NOTE if edge.dashed else "")
            for edge in graph.edges
            if edge.source == node.key
        ]
        if leads_to:
            text += LEADS_TO + ", ".join(leads_to)
        entries.append(ListEntry((Plain(text),)))
    return tuple(entries)


class _AdfBlocks:
    def __init__(self, issue_links: IssueLinks | None) -> None:
        self.runs = AdfRuns(issue_links)
        self.local_ids = count(1)
        self.heading = ""

    def local_id(self, kind: str) -> str:
        return f"skaldr-{kind}-{next(self.local_ids)}"

    def inline(self, runs: ExportRich) -> list[AdfInline]:
        return list(self.runs.write(runs))

    def paragraph(self, runs: ExportRich) -> AdfParagraph:
        content = self.inline(runs)
        return AdfParagraph(type="paragraph", content=content) if content else _empty_paragraph()

    def require_places(self, node: Node, produced: Iterable[AdfBlock], container: Container) -> None:
        for block in produced:
            if block["type"] not in _ALLOWED_BLOCKS[container]:
                message = f"ADF cannot place a {_NODE_TERM[type(node)]} inside {_CONTAINER_TERM[container]}"
                if self.heading:
                    message += f", under the heading '{self.heading}'"
                raise AdfUnsupportedError(message)

    def blocks(self, nodes: Iterable[Node], container: Container) -> list[AdfBlock]:
        written: list[AdfBlock] = []
        for node in nodes:
            produced = self.node_blocks(node, container)
            self.require_places(node, produced, container)
            written += produced
        return written

    def node_blocks(self, node: Node, container: Container) -> list[AdfBlock]:
        match node:
            case Heading():
                content = self.inline(node.text)
                self.heading = export_visible_text(node.text).strip() or self.heading
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
                return [self.code_block(node.expression, LATEX_LANGUAGE)]
            case Callout():
                content = self.blocks(node.children, "panel") or [_empty_paragraph()]
                panel = AdfPanelAttrs(panelType=PANEL_TYPE[node.tone])
                return [AdfPanel(type="panel", attrs=panel, content=content)]
            case Quote():
                return self.quote_blocks(node)
            case Divider():
                return [AdfRule(type="rule")]
            case Toggle():
                title = export_visible_text(node.title)
                if node.heading_level is not None:
                    self.heading = title.strip() or self.heading
                return [self.expand(container, title, node.children)]
            case Columns():
                return self.blocks(nested_nodes(node), container)
            case Tabs():
                return [
                    self.expand(container, export_visible_text(tab.title), tab.children) for tab in node.tabs
                ]
            case Diagram():
                return self.diagram_blocks(node, container)
            case TableOfContents():
                entries = tuple(ListEntry(entry.title) for entry in node.entries if entry.title)
                return self.list_blocks(ListNode("bullet", entries), container)
            case _:
                exhausted: Never = node
                raise AdfUnsupportedError(f"ADF has no form for the lowered node {type(exhausted).__name__}")

    def paragraph_blocks(self, node: Paragraph) -> list[AdfBlock]:
        content = self.inline(node.text)
        if not content:
            return []
        if node.tone is not None:
            content = list(with_mark(tuple(content), text_color_mark(node.tone)))
        return [AdfParagraph(type="paragraph", content=content)]

    def code_block(self, content: str, language: str) -> AdfCodeBlock:
        block = AdfCodeBlock(type="codeBlock")
        if language:
            block["attrs"] = AdfCodeBlockAttrs(language=language)
        if content:
            block["content"] = [AdfText(type="text", text=content)]
        return block

    def quote_blocks(self, node: Quote) -> list[AdfBlock]:
        paragraphs = [self.paragraph(line) for line in node.lines if line]
        cite = with_mark(tuple(self.inline(node.cite)), AdfEm(type="em"))
        if cite:
            paragraphs.append(AdfParagraph(type="paragraph", content=list(cite)))
        return [AdfBlockquote(type="blockquote", content=paragraphs)] if paragraphs else []

    def expand(self, container: Container, title: str, children: Sequence[Node]) -> AdfBlock:
        attrs = AdfExpandAttrs(title=title)
        if container in ("expand", "nested_expand"):
            nested = self.blocks(children, "nested_expand") or [_empty_paragraph()]
            return AdfNestedExpand(type="nestedExpand", attrs=attrs, content=nested)
        content = self.blocks(children, "expand") or [_empty_paragraph()]
        return AdfExpand(type="expand", attrs=attrs, content=content)

    def diagram_blocks(self, node: Diagram, container: Container) -> list[AdfBlock]:
        supplement = self.blocks(node.supplement, container)
        if not isinstance(node.figure, Graph):
            return supplement
        steps = self.list_blocks(ListNode("bullet", _graph_entries(node.figure)), container)
        return [*steps, *supplement]

    def list_blocks(self, node: ListNode, container: Container) -> list[AdfBlock]:
        if not node.entries:
            return []
        if node.kind == "check":
            return self.task_blocks(node, container)
        written: list[AdfBlock] = []
        items: list[AdfListItem] = []
        first_number = node.start
        for number, entry in enumerate(node.entries, start=node.start):
            item, overflow = self.list_item(entry, container)
            items.append(item)
            if overflow:
                written += [self.listed(node.kind, items, first_number), *overflow]
                items = []
                first_number = number + 1
        if items:
            written.append(self.listed(node.kind, items, first_number))
        return written

    def listed(self, kind: Literal["bullet", "number"], items: list[AdfListItem], first: int) -> AdfBlock:
        if kind == "bullet":
            return AdfBulletList(type="bulletList", content=items)
        if first == 1:
            return AdfOrderedList(type="orderedList", content=items)
        return AdfOrderedList(type="orderedList", attrs=AdfOrderedListAttrs(order=first), content=items)

    def list_item(self, entry: ListEntry, container: Container) -> tuple[AdfListItem, list[AdfBlock]]:
        content: list[AdfBlock] = [self.paragraph(entry.text)]
        overflow: list[AdfBlock] = []
        for child in entry.children:
            produced = self.node_blocks(child, container)
            fitting = [] if overflow else list(takewhile(_fits_in_a_list_item, produced))
            content += fitting
            beyond = produced[len(fitting) :]
            self.require_places(child, beyond, container)
            overflow += beyond
        return AdfListItem(type="listItem", content=content), overflow

    def task_blocks(self, node: ListNode, container: Container) -> list[AdfBlock]:
        written: list[AdfBlock] = []
        list_id: str | None = None
        content: list[AdfTaskItem | AdfTaskList] = []
        for entry in node.entries:
            list_id = list_id or self.local_id("task-list")
            content.append(self.task_item(entry))
            nested, overflow = self.task_details(entry.children, container)
            content += nested
            if overflow:
                attrs = AdfTaskListAttrs(localId=list_id)
                written += [AdfTaskList(type="taskList", attrs=attrs, content=content), *overflow]
                list_id, content = None, []
        if list_id is not None:
            attrs = AdfTaskListAttrs(localId=list_id)
            written.append(AdfTaskList(type="taskList", attrs=attrs, content=content))
        return written

    def task_item(self, entry: ListEntry) -> AdfTaskItem:
        state = "DONE" if entry.checked else "TODO"
        item = AdfTaskItem(
            type="taskItem", attrs=AdfTaskItemAttrs(localId=self.local_id("task"), state=state)
        )
        text = self.inline(entry.text)
        if text:
            item["content"] = text
        return item

    def task_details(
        self, children: Sequence[Node], container: Container
    ) -> tuple[list[AdfTaskList], list[AdfBlock]]:
        nested: list[AdfTaskList] = []
        overflow: list[AdfBlock] = []
        for child in children:
            produced = self.node_blocks(child, container)
            is_a_task_list = isinstance(child, ListNode) and child.kind == "check"
            if produced and is_a_task_list and not overflow:
                first = produced[0]
                if first["type"] == "taskList":
                    nested.append(first)
                    produced = produced[1:]
            self.require_places(child, produced, container)
            overflow += produced
        return nested, overflow

    def cell_paragraph(self, cell: TableCell, bold: bool) -> AdfParagraph:
        content = self.inline(cell.text)
        if bold:
            content = list(with_mark(tuple(content), AdfStrong(type="strong")))
        return AdfParagraph(type="paragraph", content=content) if content else _empty_paragraph()

    def table_cell(
        self, cell: TableCell, tone: ToneName | None, *, header: bool, bold: bool = False
    ) -> AdfTableCell | AdfTableHeader:
        content = [self.cell_paragraph(cell, bold)]
        if header:
            head = AdfTableHeader(type="tableHeader", content=content)
            if tone:
                head["attrs"] = AdfCellAttrs(background=BACKGROUND_COLOR[tone])
            return head
        body = AdfTableCell(type="tableCell", content=content)
        if tone:
            body["attrs"] = AdfCellAttrs(background=BACKGROUND_COLOR[tone])
        return body

    def body_row(self, table: TableNode, row: TableRow, width: int) -> AdfTableRow:
        band = (row.tone or GROUP_ROW_FALLBACK_TONE) if row.emphasis == "group" else row.tone
        cells: list[AdfTableCell | AdfTableHeader] = []
        for index, cell in enumerate(_padded(row.cells, width)):
            column = table.columns[index].tone if index < len(table.columns) else None
            cells.append(
                self.table_cell(
                    cell,
                    cell.tone or band or column,
                    header=table.header_column and index == 0,
                    bold=row.emphasis is not None,
                )
            )
        return AdfTableRow(type="tableRow", content=cells)

    def table(self, node: TableNode) -> AdfTable:
        width = max(len(cells) for cells in (node.header, *(row.cells for row in node.rows)))
        header = AdfTableRow(
            type="tableRow",
            content=[self.table_cell(cell, cell.tone, header=True) for cell in _padded(node.header, width)],
        )
        rows = [header, *(self.body_row(node, row, width) for row in node.rows)]
        attrs = AdfTableAttrs(isNumberColumnEnabled=False, layout="default")
        return AdfTable(type="table", attrs=attrs, content=rows)


def render_adf(nodes: Sequence[Node], issue_links: IssueLinks | None = None) -> AdfDoc:
    content = _AdfBlocks(issue_links).blocks(nodes, "doc")
    return AdfDoc(version=1, type="doc", content=content or [_empty_paragraph()])


def render_adf_document(document: LoweredDocument, issue_links: IssueLinks | None = None) -> AdfDoc:
    return render_adf(document.body, issue_links)


def adf_json(document: AdfDoc) -> str:
    return json.dumps(document, ensure_ascii=False, indent=2) + "\n"


def compact_adf_length(document: Mapping[str, object]) -> int:
    return len(json.dumps(document, separators=(",", ":"), ensure_ascii=False))
