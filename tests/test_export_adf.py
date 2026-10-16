import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import get_args

import pytest

from skaldr.errors import ExportInvariantError, ExportRejectedError, ReportError
from skaldr.export.adf import (
    IssueLinks,
    adf_json,
    render_adf,
    render_adf_document,
    render_adf_regions,
)
from skaldr.export.adf import blocks as blocks_module
from skaldr.export.adf.colors import PANEL_TYPE
from skaldr.export.inline import plain
from skaldr.export.runs import Chip, ExportRich
from skaldr.export.tree import (
    HEADING_LEVELS,
    BlockRegion,
    Callout,
    Cards,
    CodeBlock,
    Columns,
    DefinitionList,
    Diagram,
    DisplayMath,
    Divider,
    FactStrip,
    GridColumn,
    Heading,
    HeadingLevel,
    KeyValueList,
    LinkCard,
    ListEntry,
    ListKind,
    ListNode,
    LoweredDocument,
    Media,
    MediaNodeKind,
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
    TocEntry,
    Toggle,
    ToneName,
    XYChart,
)
from skaldr.richtext import Code, Plain, Styled
from tests.factories import (
    API_AND_RISK_BADGES,
    check_nodes,
    lowered,
    make_command_request,
    refusal_of,
)
from tests.factories.adf_factory import cell as _cell
from tests.factories.adf_factory import minimal_nodes, showcase_nodes
from tests.factories.adf_factory import para as _para
from tests.factories.adf_factory import text_entry as _text_entry
from tests.factories.capability_factory import xy_chart

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


def test_the_adf_writer_refuses_a_panel_in_a_list_entry_as_an_invariant() -> None:
    node = ListNode("bullet", (_text_entry("a", _para("kept"), Callout("info", (_para("c"),))),))

    with pytest.raises(ExportInvariantError) as raised:
        render_adf([node])

    assert str(raised.value) == (
        "ADF does not allow a panel inside a list item, written from a Callout; "
        "the export check should have refused it"
    )


def test_a_callout_in_a_list_entry_inside_a_callout_is_refused_as_a_block_inside_a_list_item() -> None:
    node = Callout("info", (ListNode("bullet", (_text_entry("a", Callout("info", (_para("x"),))),)),))

    assert str(refusal_of((node,), "adf")) == (
        "ADF cannot place a callout inside a list item; move the callout out of the list, after the list"
    )


def test_a_list_entry_holding_a_toggle_is_refused_naming_the_heading_above() -> None:
    refused = (
        Heading(2, plain("Plan")),
        Callout("info", (ListNode("bullet", (_text_entry("a", Toggle(plain("t"), None, (_para("x"),))),)),)),
    )

    assert str(refusal_of(refused, "adf")) == (
        "ADF cannot place a toggle inside a list item, under the heading 'Plan'; "
        "move the toggle out of the list, after the list"
    )


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


def _task_item(local_id: int, state: str, text: str) -> Json:
    return {
        "type": "taskItem",
        "attrs": {"localId": f"skaldr-task-{local_id}", "state": state},
        "content": [_text(text)],
    }


def _task_list(local_id: int, *content: Json) -> Json:
    return {
        "type": "taskList",
        "attrs": {"localId": f"skaldr-task-list-{local_id}"},
        "content": list(content),
    }


def test_a_task_entry_keeps_its_nested_task_lists_inside_the_one_task_list() -> None:
    node = ListNode(
        "check",
        (
            ListEntry(plain("a"), children=(ListNode("check", (ListEntry(plain("sub")),)),)),
            ListEntry(plain("b"), checked=True),
        ),
    )

    assert _rendered(node) == _doc(
        _task_list(
            1,
            _task_item(2, "TODO", "a"),
            _task_list(3, _task_item(4, "TODO", "sub")),
            _task_item(5, "DONE", "b"),
        )
    )


@pytest.mark.parametrize(
    ("detail", "written", "node_name"),
    [
        pytest.param(_para("detail"), "paragraph", "Paragraph", id="paragraph"),
        pytest.param(CodeBlock("recount", "sh"), "codeBlock", "CodeBlock", id="code-block"),
        pytest.param(
            ListNode("bullet", (ListEntry(plain("x")),)), "bulletList", "ListNode", id="bullet-list"
        ),
    ],
)
def test_a_task_entry_holding_anything_but_a_nested_task_list_is_an_invariant_lowering_backs(
    detail: Node, written: str, node_name: str
) -> None:
    node = ListNode("check", (ListEntry(plain("a"), children=(detail,)),))

    with pytest.raises(ExportInvariantError) as raised:
        render_adf([node])

    assert str(raised.value) == (
        f"ADF does not allow a {written} inside a task item, written from a {node_name}; "
        "skaldr lowers a checklist entry's detail only as a nested checklist"
    )


def test_a_task_entry_holding_a_toggle_is_refused_like_any_list_item() -> None:
    detail = Toggle(plain("t"), None, (_para("x"),))
    node = Callout("info", (ListNode("check", (ListEntry(plain("a"), children=(detail,)),)),))

    assert str(refusal_of((node,), "adf")) == (
        "ADF cannot place a toggle inside a list item; move the toggle out of the list, after the list"
    )


def test_rendering_the_same_tree_twice_is_byte_identical_and_local_ids_never_repeat() -> None:
    tree = (*showcase_nodes(), *showcase_nodes())

    first, second = adf_json(render_adf(tree)), adf_json(render_adf(tree))
    local_ids = re.findall(r'"localId": "([^"]+)"', first)

    assert first == second
    assert local_ids != []
    assert len(local_ids) == len(set(local_ids))


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


@pytest.mark.parametrize("empty", [Quote((), ()), Tabs(())], ids=["empty-quote", "empty-tabs"])
def test_a_callout_holding_a_block_that_writes_nothing_passes_the_check_as_an_empty_panel(
    empty: Node,
) -> None:
    callout = Callout("info", (empty,))

    check_nodes((callout,), "adf")
    assert _rendered(callout) == _doc(
        {"type": "panel", "attrs": {"panelType": "info"}, "content": [{"type": "paragraph"}]}
    )


def test_a_callout_cannot_hold_a_table() -> None:
    table = TableNode((TableCell(plain("h")),), ())

    assert str(refusal_of((Callout("info", (table,)),), "adf")) == (
        "ADF cannot place a table inside a callout; move the table out of the callout"
    )


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
    node = Quote((Paragraph(plain("one")), Paragraph(plain("two"))), cite=plain("Someone"))

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


def _link_mark(href: str) -> Json:
    return {"type": "link", "attrs": {"href": href}}


@pytest.mark.parametrize(
    ("kind", "label"),
    [("image", "Image"), ("video", "Video"), ("audio", "Audio"), ("file", "File"), ("pdf", "PDF")],
)
def test_a_media_node_is_a_paragraph_of_its_kind_and_a_link_named_by_the_caption(
    kind: MediaNodeKind, label: str
) -> None:
    node = Media(kind, "https://example.com/a.bin", plain("alt"), plain("Dock walkthrough"))

    assert _rendered(node) == _doc(
        _paragraph(_text(f"{label}: "), _text("Dock walkthrough", _link_mark("https://example.com/a.bin")))
    )


def test_a_media_node_without_a_caption_names_its_link_by_the_description() -> None:
    node = Media("image", "https://example.com/a.png", plain("Aisle 12"))

    assert _rendered(node) == _doc(
        _paragraph(_text("Image: "), _text("Aisle 12", _link_mark("https://example.com/a.png")))
    )


def test_a_media_node_without_a_caption_or_description_names_its_link_by_the_url() -> None:
    node = Media("pdf", "https://example.com/a.pdf")

    assert _rendered(node) == _doc(
        _paragraph(
            _text("PDF: "), _text("https://example.com/a.pdf", _link_mark("https://example.com/a.pdf"))
        )
    )


def test_a_media_node_with_a_scheme_adf_does_not_link_is_the_label_and_the_name_alone() -> None:
    node = Media("file", "ftp://example.com/a.zip", caption=plain("Archive"))

    assert _rendered(node) == _doc(_paragraph(_text("File: Archive")))


def test_a_media_node_inside_a_callout_stays_a_paragraph() -> None:
    node = Callout("info", (Media("video", "https://example.com/v.mp4", caption=plain("Clip")),))

    assert _rendered(node) == _doc(
        {
            "type": "panel",
            "attrs": {"panelType": "info"},
            "content": [_paragraph(_text("Video: "), _text("Clip", _link_mark("https://example.com/v.mp4")))],
        }
    )


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


def test_a_tinted_row_is_a_cell_background_as_a_toned_row_is() -> None:
    node = TableNode(
        (_cell("A"), _cell("B")), (TableRow((_cell("1", "danger"), _cell("2")), tint="success"),)
    )

    assert _rendered(node) == _doc(
        _table(
            _row(_table_cell("tableHeader", "A"), _table_cell("tableHeader", "B")),
            _row(_table_cell("tableCell", "1", "#FFEBE6"), _table_cell("tableCell", "2", "#E3FCEF")),
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

    assert str(refusal_of((node,), "adf")) == (
        "ADF cannot place a toggle inside a toggle that is itself inside a toggle; "
        "move the toggle out of the toggle"
    )


def test_a_toggle_in_a_panel_has_no_form() -> None:
    node = Callout("info", (Toggle(plain("a"), None, (_para("x"),)),))

    assert (
        str(refusal_of((node,), "adf"))
        == "ADF cannot place a toggle inside a callout; move the toggle out of the callout"
    )


def test_a_table_in_a_toggle_is_allowed_and_in_a_nested_toggle_is_not() -> None:
    table = TableNode((_cell("A"),), ())
    allowed = Toggle(plain("a"), None, (table,))
    refused = Toggle(plain("a"), None, (Toggle(plain("b"), None, (table,)),))

    check_nodes((allowed,), "adf")
    assert _rendered(allowed) == _doc(
        {
            "type": "expand",
            "attrs": {"title": "a"},
            "content": [_table(_row(_table_cell("tableHeader", "A")))],
        }
    )
    assert str(refusal_of((refused,), "adf")) == (
        "ADF cannot place a table inside a toggle that is itself inside a toggle; "
        "move the table out of the toggle"
    )


def test_columns_are_a_one_row_table_with_a_cell_width_per_column() -> None:
    node = Columns(
        (GridColumn(50, (_para("left"),)), GridColumn(50, (_para("right"), Divider()))),
    )

    assert _rendered(node) == _doc(
        {
            "type": "table",
            "attrs": {"isNumberColumnEnabled": False, "layout": "center", "width": 760},
            "content": [
                _row(
                    {
                        "type": "tableCell",
                        "content": [_words("left")],
                        "attrs": {"colwidth": [380]},
                    },
                    {
                        "type": "tableCell",
                        "content": [_words("right"), {"type": "rule"}],
                        "attrs": {"colwidth": [380]},
                    },
                )
            ],
        }
    )


def test_a_table_in_a_column_is_an_ordinary_table_after_the_columns_before_it() -> None:
    table = TableNode((_cell("A"),), (TableRow((_cell("1"),)),))
    node = Columns((GridColumn(50, (_para("left"),)), GridColumn(50, (table,))))

    assert _rendered(node) == _doc(
        _words("left"),
        _table(_row(_table_cell("tableHeader", "A")), _row(_table_cell("tableCell", "1"))),
    )


def test_tabs_are_one_expand_per_tab_titled_with_the_icon_of_the_tab_tone() -> None:
    node = Tabs((Tab(plain("One"), (_para("a"),)), Tab(plain("Two"), (_para("b"),), tone="success")))

    assert _rendered(node) == _doc(
        {"type": "expand", "attrs": {"title": "One"}, "content": [_words("a")]},
        {"type": "expand", "attrs": {"title": "✅ Two"}, "content": [_words("b")]},
    )


def test_a_request_with_several_cases_is_one_expand_per_case_titled_with_its_status_icon() -> None:
    cases = [
        {"label": "finding", "tone": "warning", "response": {"body": "1"}},
        {"label": "control", "tone": "success", "response": {"body": "2"}},
    ]
    strong = {"type": "strong"}

    def case_expand(title: str, body: str) -> Json:
        return {
            "type": "expand",
            "attrs": {"title": title},
            "content": [
                {"type": "codeBlock", "attrs": {"language": "bash"}, "content": [_text("list-tiers")]},
                _paragraph(_text("Recorded output", strong)),
                {"type": "codeBlock", "attrs": {"language": "json"}, "content": [_text(body)]},
            ],
        }

    assert _rendered(*lowered([make_command_request(cases=cases, command="list-tiers")])) == _doc(
        _paragraph(_text("Tier mappings on the partner API", strong)),
        case_expand("⚠️ finding", "1"),
        case_expand("✅ control", "2"),
    )


def test_a_chart_is_its_data_table_alone() -> None:
    table = TableNode((_cell("Slice"), _cell("Value")), (TableRow((_cell("a"), _cell("1"))),))
    pie = Diagram(PieChart((PieSlice("a", 1),)), (table,))
    bars = Diagram(XYChart("bar", ("x",), ((1.0,),), stacked=False), (table,))

    expected = _doc(
        _table(
            _row(_table_cell("tableHeader", "Slice"), _table_cell("tableHeader", "Value")),
            _row(_table_cell("tableCell", "a"), _table_cell("tableCell", "1")),
        )
    )
    assert _rendered(pie) == expected
    assert _rendered(bars) == expected


def _series_table(*rows: tuple[str, str, str], total: tuple[str, str, str] | None = None) -> Json:
    header = _row(*(_table_cell("tableHeader", text) for text in ("Series", "Mon", "Tue")))
    body = [_row(*(_table_cell("tableCell", text) for text in row)) for row in rows]
    if total is not None:
        bold = [{"type": "tableCell", "content": [_paragraph(_text(text, STRONG))]} for text in total]
        body.append(_row(*bold))
    return _doc(_table(header, *body))


@pytest.mark.parametrize(
    "chart",
    [
        pytest.param(xy_chart("line", [4, 6]), id="line"),
        pytest.param(xy_chart("bar", [4, 6]), id="bar"),
        pytest.param(xy_chart("bar", [4, 6], stacked=True), id="stacked-bar"),
    ],
)
def test_adf_writes_a_chart_with_one_series_as_a_table_of_that_series(chart: dict[str, object]) -> None:
    assert render_adf(lowered([chart])) == _series_table(("Zone 1", "4", "6"))


def test_adf_writes_a_line_chart_with_several_series_as_a_table_with_a_row_per_series() -> None:
    chart = xy_chart("line", [4, 6], [1, 2])

    assert render_adf(lowered([chart])) == _series_table(("Zone 1", "4", "6"), ("Zone 2", "1", "2"))


def test_adf_writes_a_stacked_chart_with_several_series_with_a_bold_total_row() -> None:
    chart = xy_chart("bar", [4, 6], [1, 2], stacked=True)

    assert render_adf(lowered([chart])) == _series_table(
        ("Zone 1", "4", "6"), ("Zone 2", "1", "2"), total=("Total", "5", "8")
    )


def test_a_table_of_contents_writes_nothing() -> None:
    node = TableOfContents((TocEntry("a", plain("First")), TocEntry("b", plain("Second"))))

    assert _rendered(_para("before"), node, _para("after")) == _doc(_words("before"), _words("after"))


def test_a_table_of_contents_alone_leaves_the_empty_paragraph_every_document_has() -> None:
    node = TableOfContents((TocEntry("a", plain("First")),))

    assert _rendered(node) == _doc(_paragraph())


def test_an_issue_key_in_a_paragraph_becomes_a_card_when_links_are_given() -> None:
    links = IssueLinks("https://example.atlassian.net", frozenset({"PLAN"}))

    assert _rendered(_para("see PLAN-3"), links=links) == _doc(
        _paragraph(
            _text("see "),
            {"type": "inlineCard", "attrs": {"url": "https://example.atlassian.net/browse/PLAN-3"}},
        )
    )


API_LEGEND: Json = {
    "type": "expand",
    "attrs": {"title": "Legend: badges used on this page"},
    "content": [
        {
            "type": "bulletList",
            "content": [
                _item(
                    _paragraph(
                        {"type": "status", "attrs": {"text": "api", "color": "blue"}}, _text(" the API")
                    )
                )
            ],
        }
    ],
}


@pytest.mark.parametrize(
    ("tone", "fill"),
    [
        pytest.param("danger", {"attrs": {"background": "#FFEBE6"}}, id="other"),
        pytest.param("info", {}, id="same"),
    ],
)
def test_a_card_column_keeps_its_fill_unless_a_badge_of_the_same_tone_shows_it(tone: str, fill: Json) -> None:
    card = {"label": "Err", "value": "3", "tone": tone, "badges": ["API"]}
    lozenge = {"type": "status", "attrs": {"text": "api", "color": "blue"}}

    assert render_adf(lowered([{"type": "cards", "items": [card]}], badges=API_AND_RISK_BADGES)) == _doc(
        API_LEGEND,
        _table(
            _row({"type": "tableHeader", "content": [_words("Err")], **fill}),
            _row({"type": "tableCell", "content": [_paragraph(_text("3 "), lozenge)], **fill}),
        ),
    )


@dataclass(frozen=True)
class FutureBlock:
    pass


def test_a_lowered_node_with_no_adf_form_is_an_internal_error_naming_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(blocks_module, "Divider", FutureBlock)

    with pytest.raises(ExportInvariantError, match=_exactly("ADF has no form for the lowered node Divider")):
        render_adf((Divider(),))


def test_a_block_the_check_would_refuse_is_an_internal_error_when_the_writer_is_called_alone() -> None:
    with pytest.raises(
        ExportInvariantError,
        match=_exactly(
            "ADF does not allow a table inside a panel, written from a TableNode; "
            "the export check should have refused it"
        ),
    ):
        render_adf((Callout("info", (TableNode((TableCell(plain("h")),), ()),)),))


def test_the_rejection_error_is_a_report_error() -> None:
    assert issubclass(ExportRejectedError, ReportError)


MINIMAL_NODES = minimal_nodes()


def test_every_lowered_node_type_has_a_minimal_example_so_a_new_one_fails_here() -> None:
    assert set(MINIMAL_NODES) == set(get_args(Node))


FIRST_BLOCK_OF_EACH_NODE_TYPE: Mapping[type, str] = {
    Heading: "heading",
    Paragraph: "paragraph",
    ListNode: "bulletList",
    TableNode: "table",
    CodeBlock: "codeBlock",
    DisplayMath: "codeBlock",
    Callout: "panel",
    Quote: "blockquote",
    Divider: "rule",
    Media: "paragraph",
    Toggle: "expand",
    Columns: "table",
    Tabs: "expand",
    Diagram: "table",
    FactStrip: "table",
    KeyValueList: "table",
    DefinitionList: "table",
    Cards: "table",
    Timeline: "table",
    LinkCard: "blockCard",
}
NODES_WRITING_A_FIRST_BLOCK = {
    kind: node for kind, node in MINIMAL_NODES.items() if kind is not TableOfContents
}


def test_each_minimal_node_type_has_an_expected_first_block() -> None:
    assert set(FIRST_BLOCK_OF_EACH_NODE_TYPE) == set(NODES_WRITING_A_FIRST_BLOCK)


@pytest.mark.parametrize("node", NODES_WRITING_A_FIRST_BLOCK.values(), ids=lambda node: type(node).__name__)
def test_every_lowered_node_type_writes_its_expected_first_block(node: Node) -> None:
    content = render_adf((node,))["content"]

    assert content[0]["type"] == FIRST_BLOCK_OF_EACH_NODE_TYPE[type(node)]


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


def test_the_page_slices_into_the_blocks_of_each_region_numbered_across_the_whole_page() -> None:
    checklist = ListNode("check", (ListEntry(plain("pack")),))
    document = LoweredDocument(
        "Report title",
        (
            BlockRegion(0, (_para("one"), checklist)),
            BlockRegion(1, ()),
            BlockRegion(2, (checklist, _para("two"))),
        ),
    )

    regions = render_adf_regions(document)

    assert json.loads(json.dumps(regions)) == [
        [_words("one"), _task_list(1, _task_item(2, "TODO", "pack"))],
        [],
        [_task_list(3, _task_item(4, "TODO", "pack")), _words("two")],
    ]


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
