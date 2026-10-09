from collections.abc import Mapping

from skaldr.export.inline import plain
from skaldr.export.runs import Break, CheckMark, Chip, StatusMark, SwimlaneMark
from skaldr.export.tree import (
    Callout,
    CodeBlock,
    Columns,
    Diagram,
    DisplayMath,
    Divider,
    Graph,
    GraphEdge,
    GraphNode,
    GridColumn,
    Heading,
    ListEntry,
    ListNode,
    Node,
    Paragraph,
    PieChart,
    PieSlice,
    Quote,
    Tab,
    TableCell,
    TableColumn,
    TableNode,
    TableOfContents,
    TableRow,
    Tabs,
    TocEntry,
    Toggle,
    ToneName,
)
from skaldr.richtext import Citation, Code, Link, Plain, ScriptText, Styled, Tinted


def text_entry(text: str, *children: Node) -> ListEntry:
    return ListEntry(plain(text), children=children)


def para(text: str) -> Paragraph:
    return Paragraph(plain(text))


def cell(text: str, tone: ToneName | None = None) -> TableCell:
    return TableCell(plain(text), tone)


def flow_graph() -> Graph:
    return Graph(
        "TB",
        (GraphNode("s1", "1: Draft", "write it"), GraphNode("s2", "2: Review"), GraphNode("s3", "3: Ship")),
        (GraphEdge("s1", "s2"), GraphEdge("s2", "s3"), GraphEdge("s3", "s1", dashed=True)),
    )


def minimal_nodes() -> Mapping[type, Node]:
    return {
        Heading: Heading(1, plain("h")),
        Paragraph: para("p"),
        ListNode: ListNode("bullet", (text_entry("a"),)),
        TableNode: TableNode((cell("h"),), (TableRow((cell("c"),)),)),
        CodeBlock: CodeBlock("x"),
        DisplayMath: DisplayMath("x"),
        Callout: Callout("info", (para("c"),)),
        Quote: Quote((plain("q"),)),
        Divider: Divider(),
        Toggle: Toggle(plain("t"), None, (para("c"),)),
        Columns: Columns((GridColumn(100, (para("c"),)),)),
        Tabs: Tabs((Tab(plain("t"), (para("c"),)),)),
        Diagram: Diagram(flow_graph()),
        TableOfContents: TableOfContents((TocEntry("a", plain("t")),)),
    }


def showcase_nodes() -> tuple[Node, ...]:
    tones: tuple[ToneName, ...] = ("neutral", "info", "success", "warning", "danger", "accent")
    return (
        Heading(1, plain("Showcase")),
        TableOfContents((TocEntry("a", plain("Marks")),)),
        Heading(2, plain("Marks")),
        Paragraph(
            (
                Plain("plain "),
                Styled("bold", (Plain("bold "), Styled("italic", (Plain("both"),)))),
                Styled("underline", (Plain(" under"),)),
                Styled("strike", (Plain(" struck"),)),
                Code(" code"),
                Link((Styled("bold", (Code("linked code"),)),), "https://example.com/a?b=c&d=e"),
                Tinted("danger", None, (Plain(" red"),)),
                ScriptText("subscript", "2"),
                ScriptText("superscript", "n"),
                Citation("k", 1, "https://example.com/k"),
                Break(),
                Chip("API", "violet"),
                StatusMark("blocked"),
                SwimlaneMark("deferred"),
                CheckMark(True),
            ),
            tone="muted",
        ),
        *(Callout(tone, (para(f"{tone} callout"), CodeBlock("x = 1", "python"))) for tone in tones),
        ListNode(
            "bullet",
            (
                text_entry("outer", ListNode("number", (text_entry("inner", CodeBlock("ls")),), start=3)),
                text_entry(
                    "check parent", ListNode("check", (ListEntry(plain("nested task"), checked=True),))
                ),
            ),
        ),
        ListNode("check", (ListEntry(plain("done"), checked=True), ListEntry(plain("open")))),
        Quote((plain("a quote"), plain("second line")), cite=plain("Someone")),
        Divider(),
        DisplayMath(r"\frac{a}{b}"),
        TableNode(
            (cell("Name"), cell("State", "info"), cell("Note")),
            (
                TableRow((cell("group"),), emphasis="group"),
                TableRow(
                    (cell("a", "success"), TableCell((Chip("ok", "green"),)), cell("n")), tone="warning"
                ),
                TableRow((cell("total"), cell("1"), cell("2")), emphasis="total"),
            ),
            header_column=True,
            columns=(TableColumn(), TableColumn("accent")),
        ),
        Toggle(
            plain("Collapsed"),
            2,
            (
                para("inside"),
                Toggle(plain("Deeper"), None, (para("deep"), Divider())),
                Callout("neutral", (para("c"),)),
            ),
        ),
        Tabs((Tab(plain("Case one"), (para("a"),), tone="success"), Tab(plain("Case two"), (para("b"),)))),
        Columns((GridColumn(60, (para("left"),)), GridColumn(40, (para("right"),)))),
        Diagram(flow_graph(), (ListNode("bullet", (text_entry("detail"),)),)),
        Diagram(PieChart((PieSlice("a", 1),)), (TableNode((cell("Slice"),), (TableRow((cell("a"),)),)),)),
    )
