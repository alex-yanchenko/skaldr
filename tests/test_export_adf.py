import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import get_args

import pytest

from skaldr.errors import ReportError
from skaldr.export.adf import (
    AdfUnsupportedError,
    IssueLinks,
    adf_json,
    render_adf,
    render_adf_document,
)
from skaldr.export.adf.blocks import unmapped_node
from skaldr.export.adf.colors import PANEL_TYPE
from skaldr.export.inline import plain
from skaldr.export.runs import Chip, ExportRich
from skaldr.export.tree import (
    HEADING_LEVELS,
    BlockRegion,
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
    HeadingLevel,
    ListEntry,
    ListKind,
    ListNode,
    LoweredDocument,
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
    XYChart,
)
from skaldr.richtext import Code, Plain, Styled
from tests.factories.adf_factory import cell as _cell
from tests.factories.adf_factory import flow_graph as _flow
from tests.factories.adf_factory import minimal_nodes
from tests.factories.adf_factory import para as _para
from tests.factories.adf_factory import text_entry as _text_entry

Json = Mapping[str, object]


def _doc(*blocks: Json) -> Json:
    return {"version": 1, "type": "doc", "content": list(blocks)}


def _text(text: str, *marks: Json) -> Json:
    return {"type": "text", "text": text, **({"marks": list(marks)} if marks else {})}


def _paragraph(*inlines: Json) -> Json:
    return {"type": "paragraph", "content": list(inlines)} if inlines else {"type": "paragraph"}


def _words(text: str) -> Json:
    return _paragraph(_text(text))


def _item(*blocks: Json) -> Json:
    return {"type": "listItem", "content": list(blocks)}


def _rendered(*nodes: Node, links: IssueLinks | None = None) -> Json:
    return json.loads(json.dumps(render_adf(nodes, links)))


def _exactly(message: str) -> str:
    return f"^{re.escape(message)}$"


STRONG: Json = {"type": "strong"}
EM: Json = {"type": "em"}
CODE: Json = {"type": "code"}


def test_a_document_of_nothing_is_one_empty_paragraph() -> None:
    assert _rendered() == _doc({"type": "paragraph"})


@pytest.mark.parametrize("level", HEADING_LEVELS)
def test_a_heading_keeps_its_level(level: HeadingLevel) -> None:
    assert _rendered(Heading(level, plain("Title"))) == _doc(
        {"type": "heading", "attrs": {"level": level}, "content": [_text("Title")]}
    )


def test_a_heading_and_a_paragraph_with_no_text_write_nothing() -> None:
    assert _rendered(Heading(2, ()), Paragraph(())) == _doc({"type": "paragraph"})


def test_a_paragraph_is_inline_runs() -> None:
    node = Paragraph((Plain("a "), Styled("bold", (Plain("b"),)), Code("c")))

    assert _rendered(node) == _doc(_paragraph(_text("a "), _text("b", STRONG), _text("c", CODE)))


def test_a_toned_paragraph_gets_the_text_colour_of_its_tone_but_not_on_code() -> None:
    node = Paragraph((Plain("a"), Code("c")), tone="muted")

    assert _rendered(node) == _doc(
        _paragraph(_text("a", {"type": "textColor", "attrs": {"color": "#6B778C"}}), _text("c", CODE))
    )


def test_a_bullet_list_nests_children() -> None:
    node = ListNode(
        "bullet",
        (
            _text_entry("a", ListNode("bullet", (_text_entry("b"),))),
            _text_entry("c"),
        ),
    )

    assert _rendered(node) == _doc(
        {
            "type": "bulletList",
            "content": [
                _item(_words("a"), {"type": "bulletList", "content": [_item(_words("b"))]}),
                _item(_words("c")),
            ],
        }
    )


def test_an_ordered_list_that_starts_at_one_carries_no_order() -> None:
    node = ListNode("number", (_text_entry("a"), _text_entry("b")))

    assert _rendered(node) == _doc(
        {"type": "orderedList", "content": [_item(_words("a")), _item(_words("b"))]}
    )


def test_an_ordered_list_that_starts_elsewhere_carries_its_order() -> None:
    node = ListNode("number", (_text_entry("a"),), start=4)

    assert _rendered(node) == _doc(
        {"type": "orderedList", "attrs": {"order": 4}, "content": [_item(_words("a"))]}
    )


def test_a_list_entry_may_hold_a_paragraph_a_number_list_and_a_code_block() -> None:
    node = ListNode(
        "bullet",
        (
            _text_entry(
                "a",
                _para("more"),
                ListNode("number", (_text_entry("b"),)),
                CodeBlock("x = 1", "python"),
            ),
        ),
    )

    assert _rendered(node) == _doc(
        {
            "type": "bulletList",
            "content": [
                _item(
                    _words("a"),
                    _words("more"),
                    {"type": "orderedList", "content": [_item(_words("b"))]},
                    {
                        "type": "codeBlock",
                        "attrs": {"language": "python"},
                        "content": [_text("x = 1")],
                    },
                )
            ],
        }
    )


def test_a_bullet_entry_holding_a_panel_ends_the_list_and_the_panel_and_the_rest_follow_it() -> None:
    node = ListNode(
        "bullet",
        (
            _text_entry("a", _para("kept"), Callout("info", (_para("hoisted"),)), _para("after")),
            _text_entry("b"),
        ),
    )

    assert _rendered(node) == _doc(
        {"type": "bulletList", "content": [_item(_words("a"), _words("kept"))]},
        {"type": "panel", "attrs": {"panelType": "info"}, "content": [_words("hoisted")]},
        _words("after"),
        {"type": "bulletList", "content": [_item(_words("b"))]},
    )


def test_a_numbered_list_continues_its_numbers_after_a_hoisted_block() -> None:
    table = TableNode((_cell("h"),), ())
    node = ListNode(
        "number", (_text_entry("a"), _text_entry("b", table), _text_entry("c"), _text_entry("d")), start=1
    )

    assert _rendered(node) == _doc(
        {"type": "orderedList", "content": [_item(_words("a")), _item(_words("b"))]},
        _table(_row(_table_cell("tableHeader", "h"))),
        {"type": "orderedList", "attrs": {"order": 3}, "content": [_item(_words("c")), _item(_words("d"))]},
    )


def test_a_hoisted_block_the_container_cannot_hold_fails() -> None:
    node = Callout("info", (ListNode("bullet", (_text_entry("a", Callout("info", (_para("x"),))),)),))

    with pytest.raises(
        AdfUnsupportedError, match=_exactly("ADF cannot place panel (from Callout) inside a panel")
    ):
        _rendered(node)


def test_an_entry_with_no_text_is_an_empty_paragraph() -> None:
    node = ListNode("bullet", (ListEntry(()),))

    assert _rendered(node) == _doc({"type": "bulletList", "content": [_item({"type": "paragraph"})]})


def test_a_list_with_no_entries_writes_nothing() -> None:
    assert _rendered(ListNode("bullet", ())) == _doc({"type": "paragraph"})


def test_a_task_list_numbers_its_local_ids_in_document_order() -> None:
    node = ListNode(
        "check",
        (
            ListEntry(plain("done"), checked=True),
            ListEntry(
                plain("open"),
                children=(ListNode("check", (ListEntry(plain("inner")),)),),
            ),
        ),
    )

    assert _rendered(node) == _doc(
        {
            "type": "taskList",
            "attrs": {"localId": "skaldr-task-list-1"},
            "content": [
                {
                    "type": "taskItem",
                    "attrs": {"localId": "skaldr-task-2", "state": "DONE"},
                    "content": [_text("done")],
                },
                {
                    "type": "taskItem",
                    "attrs": {"localId": "skaldr-task-3", "state": "TODO"},
                    "content": [_text("open")],
                },
                {
                    "type": "taskList",
                    "attrs": {"localId": "skaldr-task-list-4"},
                    "content": [
                        {
                            "type": "taskItem",
                            "attrs": {"localId": "skaldr-task-5", "state": "TODO"},
                            "content": [_text("inner")],
                        }
                    ],
                },
            ],
        }
    )


def test_a_task_item_with_no_text_has_no_content() -> None:
    assert _rendered(ListNode("check", (ListEntry(()),))) == _doc(
        {
            "type": "taskList",
            "attrs": {"localId": "skaldr-task-list-1"},
            "content": [{"type": "taskItem", "attrs": {"localId": "skaldr-task-2", "state": "TODO"}}],
        }
    )


def test_a_task_item_cannot_hold_anything_but_a_nested_task_list() -> None:
    node = ListNode("check", (ListEntry(plain("a"), children=(_para("detail"),)),))

    with pytest.raises(
        AdfUnsupportedError,
        match=_exactly("ADF cannot place Paragraph inside a task item; only a task list fits"),
    ):
        _rendered(node)


@pytest.mark.parametrize("tone", list(get_args(ToneName)))
def test_a_callout_is_the_panel_of_its_tone(tone: ToneName) -> None:
    expected = {
        "neutral": "note",
        "muted": "note",
        "info": "info",
        "success": "success",
        "warning": "warning",
        "danger": "error",
        "accent": "note",
        "teal": "info",
        "sky": "info",
    }[tone]

    assert _rendered(Callout(tone, (_para("hi"),))) == _doc(
        {"type": "panel", "attrs": {"panelType": expected}, "content": [_words("hi")]}
    )


def test_every_tone_has_a_panel_type() -> None:
    assert set(PANEL_TYPE) == set(get_args(ToneName))


def test_a_callout_may_hold_headings_lists_code_task_lists_and_rules() -> None:
    node = Callout(
        "info",
        (
            Heading(3, plain("h")),
            ListNode("bullet", (_text_entry("a"),)),
            CodeBlock("x"),
            Divider(),
        ),
    )

    assert _rendered(node) == _doc(
        {
            "type": "panel",
            "attrs": {"panelType": "info"},
            "content": [
                {"type": "heading", "attrs": {"level": 3}, "content": [_text("h")]},
                {"type": "bulletList", "content": [_item(_words("a"))]},
                {"type": "codeBlock", "content": [_text("x")]},
                {"type": "rule"},
            ],
        }
    )


def test_an_empty_callout_holds_an_empty_paragraph() -> None:
    assert _rendered(Callout("info", ())) == _doc(
        {"type": "panel", "attrs": {"panelType": "info"}, "content": [{"type": "paragraph"}]}
    )


def test_a_callout_cannot_hold_a_table() -> None:
    table = TableNode((TableCell(plain("h")),), ())

    with pytest.raises(
        AdfUnsupportedError, match=_exactly("ADF cannot place table (from TableNode) inside a panel")
    ):
        _rendered(Callout("info", (table,)))


def test_a_code_block_keeps_its_language_and_every_line() -> None:
    node = CodeBlock("a\n\n  b", "python")

    assert _rendered(node) == _doc(
        {"type": "codeBlock", "attrs": {"language": "python"}, "content": [_text("a\n\n  b")]}
    )


def test_a_code_block_with_no_language_has_no_attrs_and_with_no_content_has_none() -> None:
    assert _rendered(CodeBlock("x"), CodeBlock("")) == _doc(
        {"type": "codeBlock", "content": [_text("x")]}, {"type": "codeBlock"}
    )


def test_display_math_is_a_latex_code_block() -> None:
    assert _rendered(DisplayMath(r"\sum_i x_i")) == _doc(
        {"type": "codeBlock", "attrs": {"language": "latex"}, "content": [_text(r"\sum_i x_i")]}
    )


def test_a_quote_is_a_block_quote_with_one_paragraph_per_line_and_an_italic_cite() -> None:
    node = Quote((plain("one"), plain("two")), cite=plain("Someone"))

    assert _rendered(node) == _doc(
        {
            "type": "blockquote",
            "content": [_words("one"), _words("two"), _paragraph(_text("Someone", EM))],
        }
    )


def test_a_quote_with_no_lines_and_no_cite_writes_nothing() -> None:
    assert _rendered(Quote((), ())) == _doc({"type": "paragraph"})


def test_a_divider_is_a_rule() -> None:
    assert _rendered(Divider()) == _doc({"type": "rule"})


def _table_cell(kind: str, text: str, background: str | None = None) -> Json:
    cell: dict[str, object] = {"type": kind}
    if background:
        cell["attrs"] = {"background": background}
    cell["content"] = [_words(text) if text else {"type": "paragraph"}]
    return cell


def _table(*rows: Json) -> Json:
    return {
        "type": "table",
        "attrs": {"isNumberColumnEnabled": False, "layout": "default"},
        "content": list(rows),
    }


def _row(*cells: Json) -> Json:
    return {"type": "tableRow", "content": list(cells)}


def test_a_table_is_a_header_row_then_body_rows() -> None:
    node = TableNode(
        (_cell("A"), _cell("B")),
        (TableRow((_cell("1"), _cell("2"))),),
    )

    assert _rendered(node) == _doc(
        _table(
            _row(_table_cell("tableHeader", "A"), _table_cell("tableHeader", "B")),
            _row(_table_cell("tableCell", "1"), _table_cell("tableCell", "2")),
        )
    )


def test_a_short_row_is_padded_and_an_empty_cell_holds_an_empty_paragraph() -> None:
    node = TableNode((_cell("A"), _cell("B")), (TableRow((_cell(""),)),))

    assert _rendered(node) == _doc(
        _table(
            _row(_table_cell("tableHeader", "A"), _table_cell("tableHeader", "B")),
            _row(_table_cell("tableCell", ""), _table_cell("tableCell", "")),
        )
    )


def test_cell_row_and_column_tones_are_cell_backgrounds_with_the_cell_winning() -> None:
    node = TableNode(
        (_cell("A"), _cell("B"), _cell("C")),
        (
            TableRow((_cell("1", "danger"), _cell("2"), _cell("3")), tone="success"),
            TableRow((_cell("4"), _cell("5"), _cell("6"))),
        ),
        columns=(TableColumn(), TableColumn("info"), TableColumn()),
    )

    assert _rendered(node) == _doc(
        _table(
            _row(*(_table_cell("tableHeader", name) for name in "ABC")),
            _row(
                _table_cell("tableCell", "1", "#FFEBE6"),
                _table_cell("tableCell", "2", "#E3FCEF"),
                _table_cell("tableCell", "3", "#E3FCEF"),
            ),
            _row(
                _table_cell("tableCell", "4"),
                _table_cell("tableCell", "5", "#DEEBFF"),
                _table_cell("tableCell", "6"),
            ),
        )
    )


def test_a_group_row_is_a_bold_band_and_a_total_row_is_bold() -> None:
    node = TableNode(
        (_cell("A"),),
        (
            TableRow((_cell("g"),), emphasis="group"),
            TableRow((_cell("t"),), emphasis="total"),
        ),
    )
    bold = _paragraph(_text("g", STRONG))

    assert _rendered(node) == _doc(
        _table(
            _row(_table_cell("tableHeader", "A")),
            _row({"type": "tableCell", "attrs": {"background": "#F4F5F7"}, "content": [bold]}),
            _row({"type": "tableCell", "content": [_paragraph(_text("t", STRONG))]}),
        )
    )


def test_a_header_column_makes_the_first_body_cell_a_header_cell() -> None:
    node = TableNode(
        (_cell("A"), _cell("B")),
        (TableRow((_cell("1"), _cell("2"))),),
        header_column=True,
    )

    assert _rendered(node) == _doc(
        _table(
            _row(_table_cell("tableHeader", "A"), _table_cell("tableHeader", "B")),
            _row(_table_cell("tableHeader", "1"), _table_cell("tableCell", "2")),
        )
    )


def test_a_chip_in_a_cell_is_a_lozenge() -> None:
    chip: ExportRich = (Chip("API", "blue"),)
    node = TableNode((TableCell(chip),), ())

    assert _rendered(node) == _doc(
        _table(
            _row(
                {
                    "type": "tableHeader",
                    "content": [_paragraph({"type": "status", "attrs": {"text": "API", "color": "blue"}})],
                }
            )
        )
    )


def test_a_toggle_is_an_expand_titled_with_its_visible_text() -> None:
    node = Toggle((Plain("Why "), Styled("bold", (Plain("now"),))), None, (_para("body"),))

    assert _rendered(node) == _doc(
        {"type": "expand", "attrs": {"title": "Why now"}, "content": [_words("body")]}
    )


def test_a_collapsed_section_is_an_expand_and_an_empty_one_holds_an_empty_paragraph() -> None:
    node = Toggle(plain("Section"), 2, ())

    assert _rendered(node) == _doc(
        {"type": "expand", "attrs": {"title": "Section"}, "content": [{"type": "paragraph"}]}
    )


def test_a_toggle_inside_a_toggle_is_a_nested_expand() -> None:
    node = Toggle(plain("outer"), None, (Toggle(plain("inner"), None, (_para("x"),)),))

    assert _rendered(node) == _doc(
        {
            "type": "expand",
            "attrs": {"title": "outer"},
            "content": [{"type": "nestedExpand", "attrs": {"title": "inner"}, "content": [_words("x")]}],
        }
    )


def test_a_toggle_two_levels_down_has_no_form() -> None:
    node = Toggle(plain("a"), None, (Toggle(plain("b"), None, (Toggle(plain("c"), None, (_para("x"),)),)),))

    with pytest.raises(
        AdfUnsupportedError,
        match=_exactly("ADF cannot place nestedExpand (from Toggle) inside a nested expand"),
    ):
        _rendered(node)


def test_a_toggle_in_a_panel_has_no_form() -> None:
    node = Callout("info", (Toggle(plain("a"), None, (_para("x"),)),))

    with pytest.raises(
        AdfUnsupportedError, match=_exactly("ADF cannot place expand (from Toggle) inside a panel")
    ):
        _rendered(node)


def test_a_table_in_a_toggle_is_allowed_and_in_a_nested_toggle_is_not() -> None:
    table = TableNode((_cell("A"),), ())
    allowed = Toggle(plain("a"), None, (table,))
    refused = Toggle(plain("a"), None, (Toggle(plain("b"), None, (table,)),))

    assert _rendered(allowed) == _doc(
        {
            "type": "expand",
            "attrs": {"title": "a"},
            "content": [_table(_row(_table_cell("tableHeader", "A")))],
        }
    )
    with pytest.raises(
        AdfUnsupportedError, match=_exactly("ADF cannot place table (from TableNode) inside a nested expand")
    ):
        _rendered(refused)


def test_columns_are_written_one_after_another() -> None:
    node = Columns(
        (GridColumn(50, (_para("left"),)), GridColumn(50, (_para("right"), Divider()))),
    )

    assert _rendered(node) == _doc(_words("left"), _words("right"), {"type": "rule"})


def test_tabs_are_one_expand_per_tab() -> None:
    node = Tabs((Tab(plain("One"), (_para("a"),)), Tab(plain("Two"), (_para("b"),), tone="success")))

    assert _rendered(node) == _doc(
        {"type": "expand", "attrs": {"title": "One"}, "content": [_words("a")]},
        {"type": "expand", "attrs": {"title": "Two"}, "content": [_words("b")]},
    )


def test_a_flow_diagram_is_a_bullet_list_of_its_steps_and_where_each_leads() -> None:
    node = Diagram(_flow(), (ListNode("bullet", (_text_entry("detail"),)),))

    assert _rendered(node) == _doc(
        {
            "type": "bulletList",
            "content": [
                _item(_paragraph(_text("1: Draft: write it → 2: Review"))),
                _item(_paragraph(_text("2: Review → 3: Ship"))),
                _item(_paragraph(_text("3: Ship → 1: Draft (loop back)"))),
            ],
        },
        {"type": "bulletList", "content": [_item(_words("detail"))]},
    )


def test_a_fan_diagram_names_each_spoke_its_hub_leads_to() -> None:
    graph = Graph(
        "LR",
        (GraphNode("hub", "Hub"), GraphNode("s1", "A"), GraphNode("s2", "B")),
        (GraphEdge("hub", "s1"), GraphEdge("hub", "s2")),
    )

    assert _rendered(Diagram(graph)) == _doc(
        {
            "type": "bulletList",
            "content": [
                _item(_paragraph(_text("Hub → A, B"))),
                _item(_words("A")),
                _item(_words("B")),
            ],
        }
    )


def test_a_chart_is_its_data_table_alone() -> None:
    table = TableNode((_cell("Slice"), _cell("Value")), (TableRow((_cell("a"), _cell("1"))),))
    pie = Diagram(PieChart((PieSlice("a", 1),)), (table,))
    bars = Diagram(XYChart("bar", ("x",), ((1.0,),)), (table,))

    expected = _doc(
        _table(
            _row(_table_cell("tableHeader", "Slice"), _table_cell("tableHeader", "Value")),
            _row(_table_cell("tableCell", "a"), _table_cell("tableCell", "1")),
        )
    )
    assert _rendered(pie) == expected
    assert _rendered(bars) == expected


def test_a_table_of_contents_is_a_bullet_list_of_its_titles() -> None:
    node = TableOfContents((TocEntry("a", plain("First")), TocEntry("b", plain("Second"))))

    assert _rendered(node) == _doc(
        {"type": "bulletList", "content": [_item(_words("First")), _item(_words("Second"))]}
    )


def test_an_issue_key_in_a_paragraph_becomes_a_card_when_links_are_given() -> None:
    links = IssueLinks("https://example.atlassian.net", frozenset({"PLAN"}))

    assert _rendered(_para("see PLAN-3"), links=links) == _doc(
        _paragraph(
            _text("see "),
            {"type": "inlineCard", "attrs": {"url": "https://example.atlassian.net/browse/PLAN-3"}},
        )
    )


@dataclass(frozen=True)
class FutureBlock:
    pass


def test_a_lowered_node_with_no_adf_form_fails_naming_it() -> None:
    error = unmapped_node(FutureBlock())

    assert (type(error), str(error)) == (
        AdfUnsupportedError,
        "ADF has no form for the lowered node FutureBlock",
    )


def test_the_unsupported_error_is_a_report_error() -> None:
    assert issubclass(AdfUnsupportedError, ReportError)


MINIMAL_NODES = minimal_nodes()


def test_every_lowered_node_type_has_a_minimal_example_so_a_new_one_fails_here() -> None:
    assert set(MINIMAL_NODES) == set(get_args(Node))


@pytest.mark.parametrize("node", MINIMAL_NODES.values(), ids=lambda node: type(node).__name__)
def test_every_lowered_node_type_writes_at_least_one_adf_block(node: Node) -> None:
    content = render_adf((node,))["content"]

    assert content != [{"type": "paragraph"}]


@pytest.mark.parametrize("kind", list(get_args(ListKind)))
def test_every_list_kind_writes_a_list(kind: ListKind) -> None:
    content = render_adf((ListNode(kind, (_text_entry("a"),)),))["content"]

    assert [block["type"] for block in content] == [
        {"bullet": "bulletList", "number": "orderedList", "check": "taskList"}[kind]
    ]


def test_the_document_writer_writes_the_body_without_the_title() -> None:
    document = LoweredDocument(
        "Report title",
        (BlockRegion(0, (_para("one"),)), BlockRegion(1, (_para("two"),))),
    )

    assert json.loads(json.dumps(render_adf_document(document))) == _doc(_words("one"), _words("two"))


def test_the_json_text_is_indented_unescaped_and_ends_in_a_newline() -> None:
    document: Sequence[Node] = (_para("café"),)

    assert adf_json(render_adf(document)) == (
        "{\n"
        '  "version": 1,\n'
        '  "type": "doc",\n'
        '  "content": [\n'
        "    {\n"
        '      "type": "paragraph",\n'
        '      "content": [\n'
        "        {\n"
        '          "type": "text",\n'
        '          "text": "café"\n'
        "        }\n"
        "      ]\n"
        "    }\n"
        "  ]\n"
        "}\n"
    )
