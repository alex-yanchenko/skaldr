import json
from collections.abc import Iterable, Mapping, Sequence
from itertools import count
from typing import Final, Literal

from typing_extensions import Never

from skaldr.errors import ExportInvariantError
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
from skaldr.export.folds import cell_text, folded, quote_lines
from skaldr.export.inline import plain
from skaldr.export.runs import ExportRich, export_visible_text
from skaldr.export.swaps import (
    data_table_swapped_in,
    require_the_swap,
    tabs_swapped_for_toggles,
    web_address_of,
)
from skaldr.export.tree import (
    Callout,
    CodeBlock,
    Columns,
    Diagram,
    DisplayMath,
    Divider,
    GenericNode,
    Heading,
    ListEntry,
    ListNode,
    LoweredDocument,
    Media,
    MediaNodeKind,
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
from skaldr.models import MEDIA_KIND_LABELS

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
MEDIA_NODE_LABELS: Final[Mapping[MediaNodeKind, str]] = {"image": "Image", **MEDIA_KIND_LABELS}
LATEX_LANGUAGE: Final = "latex"
GROUP_ROW_FALLBACK_TONE: Final[ToneName] = "neutral"


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
        for node in folded(nodes):
            produced = self.node_blocks(node, container)
            _require_the_container_holds(node, produced, container)
            written += produced
        return written

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
        paragraphs = [self.paragraph(line) for line in quote_lines(node) if line]
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
            return self.task_blocks(node, container)
        items = [self.list_item(entry, container) for entry in node.entries]
        return [self.listed(node.kind, items, node.start)]

    def listed(self, kind: Literal["bullet", "number"], items: list[AdfListItem], first: int) -> AdfBlock:
        if kind == "bullet":
            return AdfBulletList(type="bulletList", content=items)
        if first == 1:
            return AdfOrderedList(type="orderedList", content=items)
        return AdfOrderedList(type="orderedList", attrs=AdfOrderedListAttrs(order=first), content=items)

    def list_item(self, entry: ListEntry, container: Container) -> AdfListItem:
        content: list[AdfBlock] = [self.paragraph(entry.text)]
        for child in folded(entry.children):
            produced = self.node_blocks(child, container)
            _require_a_list_item_holds(child, produced)
            content += produced
        return AdfListItem(type="listItem", content=content)

    def task_blocks(self, node: ListNode, container: Container) -> list[AdfBlock]:
        attrs = AdfTaskListAttrs(localId=self.local_id("task-list"))
        content: list[AdfTaskItem | AdfTaskList] = []
        for entry in node.entries:
            content.append(self.task_item(entry))
            content += self.nested_task_lists(entry.children, container)
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

    def nested_task_lists(self, children: Sequence[Node], container: Container) -> list[AdfTaskList]:
        nested: list[AdfTaskList] = []
        for child in folded(children):
            produced = self.node_blocks(child, container)
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

    def cell_paragraph(self, cell: TableCell, bold: bool) -> AdfParagraph:
        content = self.inline(cell_text(cell))
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
        band = (row.fill or GROUP_ROW_FALLBACK_TONE) if row.emphasis == "group" else row.fill
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


def render_adf_regions(
    document: LoweredDocument, issue_links: IssueLinks | None = None
) -> tuple[list[AdfBlock], ...]:
    writer = _AdfBlocks(issue_links)
    return tuple(writer.blocks(region.nodes, "doc") for region in document.regions)


def adf_json(document: AdfDoc) -> str:
    return json.dumps(document, ensure_ascii=False, indent=2) + "\n"


def compact_adf_length(document: Mapping[str, object]) -> int:
    return len(json.dumps(document, separators=(",", ":"), ensure_ascii=False))
