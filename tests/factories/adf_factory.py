from collections.abc import Mapping
from datetime import date

from skaldr.export.inline import plain
from skaldr.export.runs import Break, CheckMark, Chip, DecisionMark, StatusMark, SwimlaneMark
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
    GridColumn,
    Heading,
    KeyValueList,
    LabelledValue,
    LinkCard,
    ListEntry,
    ListNode,
    Media,
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
    Timeline,
    TimelineEvent,
    TocEntry,
    Toggle,
    ToneName,
)
from skaldr.models import Person
from skaldr.richtext import (
    Citation,
    Code,
    DateMention,
    IssueLink,
    Link,
    PersonMention,
    Placeholder,
    Plain,
    ScriptText,
    Styled,
    Tinted,
)


def text_entry(text: str, *children: Node) -> ListEntry:
    return ListEntry(plain(text), children=children)


def para(text: str) -> Paragraph:
    return Paragraph(plain(text))


def cell(text: str, tone: ToneName | None = None) -> TableCell:
    return TableCell(plain(text), tone)


def pie_over_its_table() -> Diagram:
    return Diagram(PieChart((PieSlice("a", 1),)), (TableNode((cell("Slice"),), (TableRow((cell("a"),)),)),))


def minimal_nodes() -> Mapping[type, Node]:
    return {
        Heading: Heading(1, plain("h")),
        Paragraph: para("p"),
        ListNode: ListNode("bullet", (text_entry("a"),)),
        TableNode: TableNode((cell("h"),), (TableRow((cell("c"),)),)),
        CodeBlock: CodeBlock("x"),
        DisplayMath: DisplayMath("x"),
        Callout: Callout("info", (para("c"),)),
        Quote: Quote((para("q"),)),
        Divider: Divider(),
        Media: Media("video", "https://example.com/v.mp4", caption=plain("m")),
        Toggle: Toggle(plain("t"), None, (para("c"),)),
        Columns: Columns((GridColumn(100, (para("c"),)),)),
        Tabs: Tabs((Tab(plain("t"), (para("c"),)),)),
        Diagram: pie_over_its_table(),
        TableOfContents: TableOfContents((TocEntry("a", plain("t")),)),
        FactStrip: FactStrip((LabelledValue("Site", plain("West")),)),
        KeyValueList: KeyValueList((LabelledValue("Owner", plain("ops")),)),
        DefinitionList: DefinitionList((Definition("Fix", (para("d"),)),)),
        Cards: Cards((Card("Clean", plain("9")),)),
        Timeline: Timeline((TimelineEvent("Start"),)),
        LinkCard: LinkCard("Runbook", "https://example.com/runbook", "card"),
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
                Tinted(None, "warning", (Plain(" marked"),)),
                Tinted("danger", "sky", (Plain(" red on blue"),)),
                Placeholder("owner"),
                ScriptText("subscript", "2"),
                ScriptText("superscript", "n"),
                Citation("k", 1, "https://example.com/k"),
                DateMention((Plain("1 Oct"),), date(2026, 10, 1), None),
                DateMention((Plain("the week"),), date(2026, 10, 5), date(2026, 10, 9)),
                PersonMention((Plain("Ada"),), "ada", Person(jira="acct-1")),
                PersonMention((Plain("Bo"),), "bo", Person()),
                IssueLink((Plain("PLAN-1"),), "PLAN-1", "https://example.atlassian.net/browse/PLAN-1"),
                IssueLink((Plain("PLAN-2"),), "PLAN-2", None),
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
        ListNode(
            "bullet",
            (
                ListEntry((DecisionMark(True), Plain(" "), Plain("ship"))),
                ListEntry((DecisionMark(False), Plain(" "), Plain("who signs?"))),
            ),
        ),
        Quote((para("a quote"), para("second line")), cite=plain("Someone")),
        Divider(),
        Media("image", "https://example.com/a.png", plain("Aisle"), plain("Fig 1")),
        Media("pdf", "https://example.com/a.pdf"),
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
            columns=(TableColumn(share=0.5), TableColumn("accent", 0.2), TableColumn()),
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
        pie_over_its_table(),
    )
