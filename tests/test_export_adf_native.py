import json
import re
from collections.abc import Mapping

import pytest

from skaldr.errors import ExportInvariantError
from skaldr.export.adf import render_adf, render_adf_document
from skaldr.export.inline import plain
from skaldr.export.runs import Chip
from skaldr.export.tree import (
    Callout,
    Card,
    Cards,
    CodeBlock,
    Columns,
    Definition,
    DefinitionList,
    Divider,
    FactStrip,
    GridColumn,
    KeyValueList,
    LabelledValue,
    LinkCard,
    ListNode,
    LoweredDocument,
    Node,
    Paragraph,
    Quote,
    TableCell,
    TableNode,
    TableRow,
    Timeline,
    TimelineEvent,
    Toggle,
)
from skaldr.richtext import Citation, Plain
from tests.factories import check_nodes, refusal_of
from tests.factories.adf_factory import cell, para, text_entry

Json = Mapping[str, object]

MUTED_TEXT: Json = {"type": "textColor", "attrs": {"color": "#6B778C"}}
STRONG: Json = {"type": "strong"}
STRIKE: Json = {"type": "strike"}
SUPERSCRIPT: Json = {"type": "subsup", "attrs": {"type": "sup"}}
RUNBOOK = "https://example.com/runbook"


def _exactly(message: str) -> str:
    return f"^{re.escape(message)}$"


def _rendered(*nodes: Node) -> Json:
    return json.loads(json.dumps(render_adf(nodes)))


def _doc(*blocks: Json) -> Json:
    return {"version": 1, "type": "doc", "content": list(blocks)}


def _text(text: str, *marks: Json) -> Json:
    return {"type": "text", "text": text, **({"marks": list(marks)} if marks else {})}


def _paragraph(*inlines: Json) -> Json:
    return {"type": "paragraph", "content": list(inlines)} if inlines else {"type": "paragraph"}


def _words(text: str, *marks: Json) -> Json:
    return _paragraph(_text(text, *marks))


def _cell(kind: str, *content: Json, background: str | None = None) -> Json:
    attrs: Json = {"attrs": {"background": background}} if background else {}
    return {"type": kind, **attrs, "content": list(content) or [_paragraph()]}


def _header(text: str, background: str | None = None) -> Json:
    return _cell("tableHeader", _words(text), background=background) if text else _cell("tableHeader")


def _body(text: str, background: str | None = None) -> Json:
    return _cell("tableCell", _words(text), background=background) if text else _cell("tableCell")


def _row(*cells: Json) -> Json:
    return {"type": "tableRow", "content": list(cells)}


def _table(*rows: Json) -> Json:
    return {
        "type": "table",
        "attrs": {"isNumberColumnEnabled": False, "layout": "default"},
        "content": list(rows),
    }


def _item(*blocks: Json) -> Json:
    return {"type": "listItem", "content": list(blocks)}


def _bullets(*items: Json) -> Json:
    return {"type": "bulletList", "content": list(items)}


def _lozenge(text: str, color: str) -> Json:
    return {"type": "status", "attrs": {"text": text, "color": color}}


def test_a_fact_strip_is_a_table_of_its_labels_as_header_cells_over_a_row_of_its_values() -> None:
    node = FactStrip((LabelledValue("Site:", plain("West")), LabelledValue("Owner", plain("ops"))))

    assert _rendered(node) == _doc(
        _table(_row(_header("Site"), _header("Owner")), _row(_body("West"), _body("ops")))
    )


def test_a_fact_strip_with_one_unlabelled_fact_leaves_its_header_cell_empty() -> None:
    node = FactStrip((LabelledValue("Site", plain("West")), LabelledValue(None, plain("ops"))))

    assert _rendered(node) == _doc(
        _table(_row(_header("Site"), _header("")), _row(_body("West"), _body("ops")))
    )


def test_a_fact_strip_with_no_labels_is_one_row_of_values() -> None:
    node = FactStrip((LabelledValue(None, plain("West")), LabelledValue(" ", plain("ops"))))

    assert _rendered(node) == _doc(_table(_row(_body("West"), _body("ops"))))


def test_a_fact_strip_with_no_facts_writes_nothing() -> None:
    assert _rendered(FactStrip(())) == _doc({"type": "paragraph"})


def test_a_key_value_list_is_a_two_column_table_with_the_keys_as_header_cells() -> None:
    node = KeyValueList((LabelledValue("Owner:", plain("ops")), LabelledValue(None, plain("west"))))

    assert _rendered(node) == _doc(
        _table(_row(_header("Owner"), _body("ops")), _row(_header(""), _body("west")))
    )


def test_a_definition_list_is_a_two_column_table_holding_each_body_as_blocks_in_the_cell() -> None:
    node = DefinitionList(
        (
            Definition("Fix", (para("first"), ListNode("bullet", (text_entry("one"),)))),
            Definition("Gap", ()),
        )
    )

    assert _rendered(node) == _doc(
        _table(
            _row(
                _header("Fix"),
                _cell("tableCell", _words("first"), _bullets(_item(_words("one")))),
            ),
            _row(_header("Gap"), _body("")),
        )
    )


def test_cards_are_a_table_with_a_column_per_card_its_label_value_and_a_grey_note_row() -> None:
    node = Cards(
        (
            Card("Clean", plain("9"), note="since Monday", tone="success"),
            Card("API rows", plain("1 (50.0%)"), badge="blue"),
        )
    )

    assert _rendered(node) == _doc(
        _table(
            _row(
                _header("Clean", "#E3FCEF"),
                _cell("tableHeader", _paragraph(_lozenge("API rows", "blue"))),
            ),
            _row(_body("9", "#E3FCEF"), _body("1 (50.0%)")),
            _row(
                _cell("tableCell", _words("since Monday", MUTED_TEXT), background="#E3FCEF"),
                _body(""),
            ),
        )
    )


def test_cards_with_no_note_write_no_note_row_and_cards_with_no_label_write_no_header_row() -> None:
    node = Cards((Card(None, plain("9")), Card(" ", plain("7"))))

    assert _rendered(node) == _doc(_table(_row(_body("9"), _body("7"))))


def test_a_card_value_keeps_its_chips_as_lozenges() -> None:
    node = Cards((Card("Clean", (Plain("9"), Plain(" "), Chip("api", "blue"))),))

    assert _rendered(node) == _doc(
        _table(
            _row(_header("Clean")),
            _row(_cell("tableCell", _paragraph(_text("9 "), _lozenge("api", "blue")))),
        )
    )


def test_cards_with_no_card_write_nothing() -> None:
    assert _rendered(Cards(())) == _doc({"type": "paragraph"})


def test_a_timeline_is_a_table_of_when_state_and_what() -> None:
    node = Timeline(
        (
            TimelineEvent(
                "Start", time="Mon", state="done", chips=(Chip("api", "blue"),), body=plain("Kick-off.")
            ),
            TimelineEvent("Later", time="Tue", state="current"),
        )
    )

    assert _rendered(node) == _doc(
        _table(
            _row(_header("When"), _header("State"), _header("What")),
            _row(
                _body("Mon"),
                _cell("tableCell", _paragraph(_lozenge("done", "green"))),
                _cell(
                    "tableCell",
                    _paragraph(_text("Start", STRONG), _text(" "), _lozenge("api", "blue")),
                    _words("Kick-off."),
                ),
            ),
            _row(
                _body("Tue"),
                _cell("tableCell", _paragraph(_lozenge("current", "blue"))),
                _cell("tableCell", _paragraph(_text("Later", STRONG))),
            ),
        )
    )


def test_a_timeline_leaves_out_the_when_and_state_columns_no_event_fills() -> None:
    node = Timeline((TimelineEvent("Start"), TimelineEvent("Later")))

    assert _rendered(node) == _doc(
        _table(
            _row(_header("What")),
            _row(_cell("tableCell", _paragraph(_text("Start", STRONG)))),
            _row(_cell("tableCell", _paragraph(_text("Later", STRONG)))),
        )
    )


def test_a_timeline_event_missing_a_time_or_state_leaves_its_cell_empty() -> None:
    node = Timeline((TimelineEvent("Start", time="Mon"), TimelineEvent("Later", state="pending")))

    assert _rendered(node) == _doc(
        _table(
            _row(_header("When"), _header("State"), _header("What")),
            _row(_body("Mon"), _body(""), _cell("tableCell", _paragraph(_text("Start", STRONG)))),
            _row(
                _body(""),
                _cell("tableCell", _paragraph(_lozenge("pending", "neutral"))),
                _cell("tableCell", _paragraph(_text("Later", STRONG))),
            ),
        )
    )


def test_a_timeline_with_no_events_writes_nothing() -> None:
    assert _rendered(Timeline(())) == _doc({"type": "paragraph"})


def test_a_link_card_is_a_block_card_over_a_grey_caption() -> None:
    node = LinkCard("Runbook", RUNBOOK, "card", domain="example.com", caption="Steps")

    assert _rendered(node) == _doc(
        {"type": "blockCard", "attrs": {"url": RUNBOOK}},
        _words("example.com · Steps", MUTED_TEXT),
    )


def test_a_link_embed_is_an_embed_card_over_a_grey_caption_of_its_domain() -> None:
    node = LinkCard("Runbook", RUNBOOK, "embed", domain="example.com")

    assert _rendered(node) == _doc(
        {"type": "embedCard", "attrs": {"url": RUNBOOK, "layout": "center"}},
        _words("example.com", MUTED_TEXT),
    )


def test_a_link_card_with_no_domain_or_caption_is_the_card_alone() -> None:
    assert _rendered(LinkCard("Runbook", RUNBOOK, "card")) == _doc(
        {"type": "blockCard", "attrs": {"url": RUNBOOK}}
    )


def test_a_link_card_in_a_panel_is_a_block_card() -> None:
    node = Callout("info", (LinkCard("Runbook", RUNBOOK, "card", domain="example.com"),))

    check_nodes((node,), "adf")
    assert _rendered(node) == _doc(
        {
            "type": "panel",
            "attrs": {"panelType": "info"},
            "content": [{"type": "blockCard", "attrs": {"url": RUNBOOK}}, _words("example.com", MUTED_TEXT)],
        }
    )


def test_a_link_embed_in_a_panel_is_refused_as_a_quote_in_a_panel() -> None:
    node = Callout("info", (LinkCard("Runbook", RUNBOOK, "embed"),))

    assert str(refusal_of((node,), "adf")) == (
        "ADF cannot place a link embed inside a callout; move the link embed out of the callout"
    )


def test_a_link_card_in_a_list_item_is_refused() -> None:
    node = ListNode("bullet", (text_entry("a", LinkCard("Runbook", RUNBOOK, "card")),))

    assert str(refusal_of((node,), "adf")) == (
        "ADF cannot place a link card inside a list item; move the link card out of the list, after the list"
    )


def test_a_link_card_in_a_toggle_is_a_block_card() -> None:
    node = Toggle(plain("More"), None, (LinkCard("Runbook", RUNBOOK, "card"),))

    assert _rendered(node) == _doc(
        {
            "type": "expand",
            "attrs": {"title": "More"},
            "content": [{"type": "blockCard", "attrs": {"url": RUNBOOK}}],
        }
    )


def test_a_link_card_in_a_toggle_in_a_toggle_stays_the_quote_a_nested_expand_can_hold() -> None:
    node = Toggle(
        plain("Outer"), None, (Toggle(plain("Inner"), None, (LinkCard("Runbook", RUNBOOK, "card"),)),)
    )

    assert _rendered(node) == _doc(
        {
            "type": "expand",
            "attrs": {"title": "Outer"},
            "content": [
                {
                    "type": "nestedExpand",
                    "attrs": {"title": "Inner"},
                    "content": [
                        {
                            "type": "blockquote",
                            "content": [
                                _words("Runbook", {"type": "link", "attrs": {"href": RUNBOOK}}, STRONG),
                            ],
                        }
                    ],
                }
            ],
        }
    )


def test_an_open_toggle_is_an_expand() -> None:
    node = Toggle(plain("More"), None, (para("body"),), open=True)

    assert _rendered(node) == _doc(
        {"type": "expand", "attrs": {"title": "More"}, "content": [_words("body")]}
    )


def test_an_open_toggle_inside_a_toggle_is_a_nested_expand() -> None:
    node = Toggle(plain("Outer"), None, (Toggle(plain("Inner"), None, (para("x"),), open=True),))

    assert _rendered(node) == _doc(
        {
            "type": "expand",
            "attrs": {"title": "Outer"},
            "content": [{"type": "nestedExpand", "attrs": {"title": "Inner"}, "content": [_words("x")]}],
        }
    )


def test_an_open_toggle_where_no_expand_fits_stays_a_bold_title_over_its_content() -> None:
    node = Callout("info", (Toggle(plain("More"), None, (para("body"),), open=True),))

    assert _rendered(node) == _doc(
        {
            "type": "panel",
            "attrs": {"panelType": "info"},
            "content": [_words("More", STRONG), _words("body")],
        }
    )


def test_a_quote_holding_a_list_is_a_block_quote_holding_the_list() -> None:
    node = Quote(
        (
            para("Said:"),
            ListNode("bullet", (text_entry("one", ListNode("number", (text_entry("x"),), start=3)),)),
        ),
        plain("Ana"),
    )

    assert _rendered(node) == _doc(
        {
            "type": "blockquote",
            "content": [
                _words("Said:"),
                _bullets(
                    _item(
                        _words("one"),
                        {
                            "type": "orderedList",
                            "attrs": {"order": 3},
                            "content": [_item(_words("x"))],
                        },
                    )
                ),
                _words("Ana", {"type": "em"}),
            ],
        }
    )


def test_a_table_cell_holding_paragraphs_and_a_list_writes_each_as_its_own_block() -> None:
    node = TableNode(
        (cell("Steps"),),
        (
            TableRow(
                (
                    TableCell(
                        (),
                        blocks=(para("Fix:"), para("Then:"), ListNode("bullet", (text_entry("one"),))),
                    ),
                )
            ),
        ),
    )

    assert _rendered(node) == _doc(
        _table(
            _row(_header("Steps")),
            _row(_cell("tableCell", _words("Fix:"), _words("Then:"), _bullets(_item(_words("one"))))),
        )
    )


def test_a_group_row_holding_a_list_is_bold_throughout() -> None:
    node = TableNode(
        (cell("Steps"),),
        (
            TableRow(
                (TableCell((), blocks=(para("Fix:"), ListNode("bullet", (text_entry("one"),)))),),
                emphasis="group",
            ),
        ),
    )

    assert _rendered(node) == _doc(
        _table(
            _row(_header("Steps")),
            _row(
                _cell(
                    "tableCell",
                    _words("Fix:", STRONG),
                    _bullets(_item(_words("one", STRONG))),
                    background="#F4F5F7",
                )
            ),
        )
    )


def test_a_muted_row_is_struck_through_on_its_grey_fill() -> None:
    node = TableNode(
        (cell("A"), cell("B")),
        (TableRow((cell("1"), cell("2")), tone="muted"), TableRow((cell("3"), cell("4")))),
    )

    assert _rendered(node) == _doc(
        _table(
            _row(_header("A"), _header("B")),
            _row(
                _cell("tableCell", _words("1", STRIKE), background="#F4F5F7"),
                _cell("tableCell", _words("2", STRIKE), background="#F4F5F7"),
            ),
            _row(_body("3"), _body("4")),
        )
    )


def test_a_danger_row_is_filled_and_not_struck_through() -> None:
    node = TableNode((cell("A"),), (TableRow((cell("1"),), tone="danger"),))

    assert _rendered(node) == _doc(_table(_row(_header("A")), _row(_body("1", "#FFEBE6"))))


def test_a_muted_row_holding_a_list_strikes_the_list_too() -> None:
    node = TableNode(
        (cell("A"),),
        (TableRow((TableCell((), blocks=(ListNode("bullet", (text_entry("one"),)),)),), tone="muted"),),
    )

    assert _rendered(node) == _doc(
        _table(
            _row(_header("A")),
            _row(_cell("tableCell", _bullets(_item(_words("one", STRIKE))), background="#F4F5F7")),
        )
    )


def test_a_citation_is_a_superscript_over_its_link() -> None:
    node = Paragraph((Plain("see"), Citation("k", 1, RUNBOOK)))

    assert _rendered(node) == _doc(
        _paragraph(
            _text("see"),
            _text("[1]", {"type": "link", "attrs": {"href": RUNBOOK}}, SUPERSCRIPT),
        )
    )


def test_a_cover_is_a_link_paragraph_before_the_body() -> None:
    document = LoweredDocument("Report", (), cover="https://example.com/cover.png")
    first = LoweredDocument("Report", ())

    assert (
        json.loads(json.dumps(render_adf_document(document))),
        json.loads(json.dumps(render_adf_document(first))),
    ) == (
        _doc(
            _paragraph(
                _text(
                    "Cover image",
                    {"type": "link", "attrs": {"href": "https://example.com/cover.png"}},
                )
            )
        ),
        _doc(_paragraph()),
    )


def _grid_of(count: int) -> Columns:
    share = 100 // count
    return Columns(tuple(GridColumn(share, (para(f"c{index}"),)) for index in range(count)))


def test_a_grid_of_more_than_three_cells_is_a_one_row_table() -> None:
    assert _rendered(_grid_of(4)) == _doc(_table(_row(*(_body(f"c{index}") for index in range(4)))))


def test_a_grid_of_three_plain_cells_stays_its_cells_one_after_another() -> None:
    assert _rendered(_grid_of(3)) == _doc(*(_words(f"c{index}") for index in range(3)))


def test_a_toned_grid_cell_is_a_cell_background_and_makes_the_grid_a_table() -> None:
    toned = Callout("warning", (para("right"), Divider()), authored_as="grid cell")
    node = Columns((GridColumn(50, (para("left"),)), GridColumn(50, (toned,))))

    assert _rendered(node) == _doc(
        _table(
            _row(
                _body("left"),
                _cell("tableCell", _words("right"), {"type": "rule"}, background="#FFFAE6"),
            )
        )
    )


def test_a_grid_cell_holds_a_list_a_callout_and_a_toggle_as_a_nested_expand() -> None:
    cells = (
        GridColumn(25, (ListNode("bullet", (text_entry("a"),)),)),
        GridColumn(25, (Callout("info", (para("b"),), authored_as="callout"),)),
        GridColumn(25, (Toggle(plain("t"), None, (para("c"),)),)),
        GridColumn(25, ()),
    )

    assert _rendered(Columns(cells)) == _doc(
        _table(
            _row(
                _cell("tableCell", _bullets(_item(_words("a")))),
                _cell(
                    "tableCell",
                    {"type": "panel", "attrs": {"panelType": "info"}, "content": [_words("b")]},
                ),
                _cell(
                    "tableCell",
                    {"type": "nestedExpand", "attrs": {"title": "t"}, "content": [_words("c")]},
                ),
                _body(""),
            )
        )
    )


def test_a_grid_inside_a_grid_cell_stays_its_cells_one_after_another_inside_the_cell() -> None:
    outer = Columns(
        (
            GridColumn(25, (para("a"),)),
            GridColumn(25, (_grid_of(4),)),
            GridColumn(25, (para("b"),)),
            GridColumn(25, (para("c"),)),
        )
    )

    assert _rendered(outer) == _doc(
        _table(
            _row(
                _body("a"),
                _cell("tableCell", *(_words(f"c{index}") for index in range(4))),
                _body("b"),
                _body("c"),
            )
        )
    )


def test_a_fact_strip_in_a_grid_cell_stays_bullets_since_a_cell_holds_no_table() -> None:
    cells = tuple(
        GridColumn(25, (FactStrip((LabelledValue("Site", plain("West")),)) if index == 0 else para("x"),))
        for index in range(4)
    )

    assert _rendered(Columns(cells))["content"] == [
        _table(
            _row(
                _cell(
                    "tableCell",
                    _bullets(_item(_paragraph(_text("Site", STRONG), _text(": West")))),
                ),
                _body("x"),
                _body("x"),
                _body("x"),
            )
        )
    ]


def test_a_fact_strip_in_a_callout_stays_bullets_since_a_panel_holds_no_table() -> None:
    node = Callout("info", (FactStrip((LabelledValue("Site", plain("West")),)),))

    assert _rendered(node) == _doc(
        {
            "type": "panel",
            "attrs": {"panelType": "info"},
            "content": [_bullets(_item(_paragraph(_text("Site", STRONG), _text(": West"))))],
        }
    )


def test_a_timeline_in_a_nested_expand_stays_bullets_since_a_nested_expand_holds_no_table() -> None:
    node = Toggle(plain("a"), None, (Toggle(plain("b"), None, (Timeline((TimelineEvent("Start"),)),)),))

    assert _rendered(node) == _doc(
        {
            "type": "expand",
            "attrs": {"title": "a"},
            "content": [
                {
                    "type": "nestedExpand",
                    "attrs": {"title": "b"},
                    "content": [_bullets(_item(_words("Start")))],
                }
            ],
        }
    )


def test_a_fact_strip_in_a_list_item_stays_bullets_since_a_list_item_holds_no_table() -> None:
    node = ListNode("bullet", (text_entry("a", FactStrip((LabelledValue("Site", plain("West")),))),))

    assert _rendered(node) == _doc(
        _bullets(
            _item(
                _words("a"),
                _bullets(_item(_paragraph(_text("Site", STRONG), _text(": West")))),
            )
        )
    )


TABLE_A = TableNode((cell("A"),), (TableRow((cell("1"),)),))
TABLE_A_WRITTEN = _table(_row(_header("A")), _row(_body("1")))


def _grid_holding_a_table(cells: int) -> Columns:
    held = tuple(GridColumn(100 // cells, (para(f"c{index}"),)) for index in range(cells - 1))
    return Columns((*held, GridColumn(100 // cells, (TABLE_A,))))


@pytest.mark.parametrize("cells", [2, 4])
def test_a_grid_holding_a_table_writes_its_cells_one_after_another_as_it_always_did(cells: int) -> None:
    grid = _grid_holding_a_table(cells)

    check_nodes((grid,), "adf")
    assert _rendered(grid) == _doc(*(_words(f"c{index}") for index in range(cells - 1)), TABLE_A_WRITTEN)


def test_a_grid_holding_a_table_in_a_toggle_writes_its_cells_one_after_another() -> None:
    node = Toggle(plain("More"), None, (_grid_holding_a_table(4),))

    check_nodes((node,), "adf")
    assert _rendered(node) == _doc(
        {
            "type": "expand",
            "attrs": {"title": "More"},
            "content": [*(_words(f"c{index}") for index in range(3)), TABLE_A_WRITTEN],
        }
    )


def test_a_toned_grid_cell_holding_a_table_is_refused_as_a_table_in_a_panel_as_it_always_was() -> None:
    toned = Callout("warning", (TABLE_A,), authored_as="grid cell")
    grid = Columns((GridColumn(50, (para("left"),)), GridColumn(50, (toned,))))

    assert str(refusal_of((grid,), "adf")) == (
        "ADF cannot place a table inside a grid cell; move the table out of the grid cell"
    )


def test_a_toggle_two_deep_in_a_table_form_grid_cell_passes_the_check_and_stops_the_writer() -> None:
    inner = Toggle(plain("Inner"), None, (para("x"),))
    outer = Toggle(plain("Outer"), None, (inner,))
    cells = (*(GridColumn(25, (para(f"c{index}"),)) for index in range(3)), GridColumn(25, (outer,)))

    check_nodes((Columns(cells),), "adf")
    with pytest.raises(
        ExportInvariantError,
        match=_exactly(
            "ADF does not allow a nestedExpand inside a nested_expand, written from a Toggle; "
            "the export check should have refused it"
        ),
    ):
        render_adf((Columns(cells),))


def test_a_cell_block_the_writer_cannot_mark_is_an_internal_error() -> None:
    node = TableNode((cell("A"),), (TableRow((TableCell((), blocks=(CodeBlock("x"),)),), emphasis="group"),))

    with pytest.raises(
        ExportInvariantError,
        match=_exactly(
            "ADF cannot mark a codeBlock inside a table cell; "
            "the lowering should hold only paragraphs and lists there"
        ),
    ):
        render_adf((node,))


def test_a_grid_cell_holding_what_a_table_cell_holds_passes_the_check() -> None:
    cells = (
        GridColumn(50, (ListNode("bullet", (text_entry("a"),)), Divider())),
        GridColumn(50, (Callout("info", (para("b"),)), Quote((para("q"),)))),
    )

    check_nodes((Columns(cells),), "adf")
