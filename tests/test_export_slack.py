import json
from datetime import date
from pathlib import Path
from typing import Any, Final

import pytest

from skaldr.cli import main
from skaldr.errors import ExportInvariantError, ExportRejectedError
from skaldr.export import EXPORT_MANIFEST, ExportResult, export_slack
from skaldr.export.runs import Break, Chip, ExportRun, SectionLink, StatusMark, TonedLabel
from skaldr.export.slack import render_slack
from skaldr.export.tree import (
    Callout,
    CodeBlock,
    Columns,
    Diagram,
    DisplayMath,
    Divider,
    Graph,
    GraphNode,
    GridColumn,
    Heading,
    HeadingLevel,
    ListEntry,
    ListKind,
    ListNode,
    Media,
    Node,
    Paragraph,
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
)
from skaldr.models import Person, Report, load_report, parse_report
from skaldr.richtext import (
    Citation,
    Code,
    DateMention,
    DocumentLink,
    InlineMath,
    IssueLink,
    Link,
    PersonMention,
    Placeholder,
    Plain,
    ScriptText,
    Styled,
)
from tests.factories import (
    folder_texts,
    make_bullets,
    make_list_entry,
    make_paragraph,
    make_report,
    make_rich_text,
    make_section,
    make_table_cell,
    refusal_of,
    slack_of,
    write_report,
)
from tests.factories.capability_factory import LONG_TABLE
from tests.factories.example_factory import (
    EXAMPLE,
    FIRST_REFUSAL_IN_DOCUMENT_ORDER_OF_THE_EXAMPLE,
    example_for,
    golden_of,
    golden_or_scratch_folder,
)

CANVAS_STEP_DETAIL_TYPES = ("text", "list")
CANVAS_LIMIT_CODE_LENGTH = 1_048_567
MERMAID_ONE_NODE = '```mermaid\nflowchart LR\n    s1["A"]\n```'
ONE_NODE_GRAPH = Graph("LR", (GraphNode("s1", "A"),), ())
TABLE_LIMIT_WHY = "a table has 301 cells, over the 300 a Slack canvas table can hold"
TABLE_LIMIT_INSTEAD = "split it into two tables or export it elsewhere"
LIST_SEPARATOR = "&nbsp;"
OUT_OF_THE_LIST = "move it out of the list, after the list"
OUT_OF_THE_STEP = "move it out of the step, after the walkthrough"
CANVAS_LIMIT_WHY = (
    "the canvas Markdown is 1,048,577 characters, "
    "over the 1,048,576 characters (1 MiB) a Slack canvas can hold"
)
CANVAS_LIMIT_INSTEAD = "split the document into several canvases or export it elsewhere"
SCRIPT_WITHOUT_A_FORM: Final = ScriptText("superscript", "q")
SCRIPT_WHY: Final = (
    "a Slack canvas cannot show the superscript 'q', since 'q' has no Unicode superscript form"
)
SCRIPT_INSTEAD: Final = "write the text without the superscript or export the document elsewhere"
SCRIPT_INVARIANT: Final = (
    "a Slack canvas has no superscript form for 'q' in 'q'; the export check should have refused it"
)


def _key_value_table() -> TableNode:
    return TableNode((make_table_cell("k"),), (TableRow((make_table_cell("v"),)),))


def _one_column_table(cells: int) -> TableNode:
    return TableNode(
        (make_table_cell("h"),), tuple(TableRow((make_table_cell("v"),)) for _ in range(cells - 1))
    )


def _one_column_table_text(cells: int) -> str:
    return "\n".join(["| h |", "| --- |", *["| v |"] * (cells - 1)]) + "\n"


def _step_detail_reworked_for_a_canvas(detail: dict[str, Any]) -> dict[str, Any]:
    return {"type": "text", "body": detail["body"]} if detail["type"] == "callout" else detail


def _example_reworked_for_a_canvas() -> dict[str, Any]:
    data = example_for("slack")
    blocks: list[dict[str, Any]] = []
    for block in data["blocks"]:
        blocks.append(block)
        if block["type"] != "walkthrough":
            continue
        for step in block["steps"]:
            detail = [_step_detail_reworked_for_a_canvas(inner) for inner in step["detail"]]
            step["detail"] = [inner for inner in detail if inner["type"] in CANVAS_STEP_DETAIL_TYPES]
            blocks += [inner for inner in detail if inner["type"] not in CANVAS_STEP_DETAIL_TYPES]
    return {**data, "blocks": blocks}


def test_the_example_is_refused_for_slack_at_its_first_refusal_in_document_order(tmp_path: Path) -> None:
    with pytest.raises(ExportRejectedError) as raised:
        export_slack(load_report(EXAMPLE), tmp_path / "out")

    assert str(raised.value) == FIRST_REFUSAL_IN_DOCUMENT_ORDER_OF_THE_EXAMPLE["slack"]


def test_the_example_reworked_for_a_canvas_exports_to_the_slack_golden(
    tmp_path: Path,
) -> None:
    out_dir = golden_or_scratch_folder("slack", tmp_path)

    export_slack(parse_report(_example_reworked_for_a_canvas()), out_dir)

    assert folder_texts(out_dir) == folder_texts(golden_of("slack"))


@pytest.mark.parametrize(
    ("level", "line"),
    [
        pytest.param(1, "# Counts", id="level-1"),
        pytest.param(2, "## Counts", id="level-2"),
        pytest.param(3, "### Counts", id="level-3"),
        pytest.param(4, "### Counts", id="level-4-folds-to-3"),
        pytest.param(6, "### Counts", id="level-6-folds-to-3"),
    ],
)
def test_a_heading_keeps_its_level_up_to_three_and_deeper_ones_fold_to_three(
    level: HeadingLevel, line: str
) -> None:
    assert render_slack([Heading(level, make_rich_text("Counts"), "counts")]) == f"{line}\n"


def test_a_paragraph_is_its_inline_text_and_drops_its_tone() -> None:
    assert render_slack([Paragraph(make_rich_text("Counted twice."), "warning")]) == "Counted twice.\n"


def _broken_line(second: str) -> tuple[ExportRun, ...]:
    return (Plain("one"), Break(), Plain(second))


@pytest.mark.parametrize(
    ("node", "text"),
    [
        pytest.param(Paragraph(_broken_line("two")), "one\\\ntwo\n", id="paragraph-hard-break"),
        pytest.param(
            Paragraph(_broken_line("# two")), "one\\\n\\# two\n", id="paragraph-line-after-the-break-escaped"
        ),
        pytest.param(
            Callout("info", (Paragraph(_broken_line(":::")),)),
            "::: {.callout}\n💡 one\\\n\\:::\n:::\n",
            id="callout-paragraph-line-after-the-break-is-not-a-fence",
        ),
        pytest.param(Heading(2, _broken_line("two")), "## one two\n", id="heading-space"),
        pytest.param(make_bullets(ListEntry(_broken_line("two"))), "* one two\n", id="list-item-space"),
        pytest.param(Quote((_broken_line("two"),)), "> one two\n", id="quote-space"),
        pytest.param(Toggle(_broken_line("two"), None, ()), "**one two**\n", id="title-space"),
    ],
)
def test_a_line_break_outside_a_table_cell_is_a_hard_break_in_a_paragraph_and_a_space_elsewhere(
    node: Node, text: str
) -> None:
    assert render_slack([node]) == text


@pytest.mark.parametrize(
    ("node", "text"),
    [
        pytest.param(make_bullets(make_list_entry("a"), make_list_entry("b")), "* a\n* b\n", id="bullet"),
        pytest.param(
            ListNode("number", (make_list_entry("a"), make_list_entry("b"))), "1. a\n2. b\n", id="number"
        ),
        pytest.param(
            ListNode("check", (make_list_entry("a"), make_list_entry("b", checked=True))),
            "* [ ] a\n* [x] b\n",
            id="check",
        ),
        pytest.param(make_bullets(ListEntry(())), "*\n", id="bare-marker"),
        pytest.param(
            ListNode(
                "number", (make_list_entry("a", make_bullets(make_list_entry("b"))), make_list_entry("c"))
            ),
            "1. a\n   * b\n2. c\n",
            id="number-with-nested-bullets",
        ),
    ],
)
def test_a_list_writes_the_markers_slack_stores(node: ListNode, text: str) -> None:
    assert render_slack([node]) == text


@pytest.mark.parametrize(
    ("blocks", "start", "where"),
    [
        pytest.param(
            [{"type": "list", "style": "number", "start": 4, "items": ["a", "b"]}],
            4,
            "at blocks.0.list",
            id="list-block",
        ),
        pytest.param([{"type": "text", "body": "3. a\n4. b"}], 3, "at blocks.0.text", id="numbered-text"),
        pytest.param(
            [{"type": "text", "body": "- a\n- b\n\n  2. c"}], 2, "at blocks.0.text", id="nested-in-text"
        ),
        pytest.param([{"type": "text", "body": "0. a\n1. b"}], 0, "at blocks.0.text", id="start-zero"),
        pytest.param(
            [{"type": "callout", "tone": "info", "body": "Steps:\n\n3. a\n4. b"}],
            3,
            "at blocks.0.callout",
            id="in-a-callout",
        ),
    ],
)
def test_a_numbered_list_that_does_not_start_at_1_is_rejected_naming_its_path(
    blocks: list[dict[str, Any]], start: int, where: str
) -> None:
    with pytest.raises(ExportRejectedError) as raised:
        slack_of(blocks)

    assert vars(raised.value) == _canvas_rejection(
        f"a Slack canvas numbers every list from 1, so it cannot show a numbered list that starts at {start}",
        "number the list from 1, or export it elsewhere",
        where,
    )


def test_a_numbered_list_in_a_table_cell_keeps_its_numbers_as_text() -> None:
    block = {
        "type": "table",
        "columns": [{"key": "n", "label": "N", "kind": "text"}],
        "rows": [{"n": "3. a\n4. b"}],
    }

    assert slack_of([block]) == "| N |\n| --- |\n| 3. a<br>4. b |\n"


def test_a_numbered_list_in_a_quote_is_refused_since_a_canvas_quote_holds_only_text() -> None:
    with pytest.raises(ExportRejectedError) as raised:
        slack_of([{"type": "quote", "body": "3. a\n4. b"}])

    assert vars(raised.value) == _canvas_rejection(
        "a Slack canvas quote holds only text, so it cannot show a list inside a quote",
        "move the list out of the quote, after it",
        "at blocks.0.quote",
    )


@pytest.mark.parametrize(
    ("nodes", "text"),
    [
        pytest.param([Paragraph(()), make_paragraph("a")], "a\n", id="empty-paragraph"),
        pytest.param(
            [make_bullets(make_list_entry("a", Paragraph(())))], "* a\n", id="empty-paragraph-in-a-list-item"
        ),
        pytest.param(
            [make_bullets(ListEntry((), children=(Paragraph(()),)))],
            "*\n",
            id="empty-paragraph-in-an-empty-item",
        ),
    ],
)
def test_an_empty_paragraph_writes_nothing(nodes: list[Node], text: str) -> None:
    assert render_slack(nodes) == text


@pytest.mark.parametrize(
    ("kind", "nested_kind", "text"),
    [
        pytest.param("bullet", "number", "* a\n  1. b\n", id="number-under-bullet"),
        pytest.param("number", "bullet", "1. a\n   * b\n", id="bullet-under-number"),
        pytest.param("check", "bullet", "* [ ] a\n  * b\n", id="bullet-under-check"),
        pytest.param("bullet", "check", "* a\n  * [ ] b\n", id="check-under-bullet"),
        pytest.param("number", "check", "1. a\n   * [ ] b\n", id="check-under-number"),
        pytest.param("number", "number", "1. a\n   1. b\n", id="same-kind"),
    ],
)
def test_a_nested_list_keeps_its_own_kind(kind: ListKind, nested_kind: ListKind, text: str) -> None:
    nested = ListNode(nested_kind, (make_list_entry("b"),))

    assert render_slack([ListNode(kind, (make_list_entry("a", nested),))]) == text


def test_a_nested_list_three_deep_indents_to_each_content_column() -> None:
    deepest = ListNode("number", (make_list_entry("c"),))
    middle = ListNode("number", (make_list_entry("b", deepest),))
    tenth = make_list_entry("j", middle)
    outer = ListNode("number", (*(make_list_entry(letter) for letter in "abcdefghi"), tenth))

    first_nine = "".join(f"{number}. {letter}\n" for number, letter in enumerate("abcdefghi", start=1))

    assert render_slack([outer]) == f"{first_nine}10. j\n    1. b\n       1. c\n"


@pytest.mark.parametrize(
    ("second", "second_text"),
    [
        pytest.param(make_bullets(make_list_entry("b")), "* b", id="same-kind"),
        pytest.param(ListNode("number", (make_list_entry("b"),)), "1. b", id="bullet-then-number"),
        pytest.param(ListNode("check", (make_list_entry("b"),)), "* [ ] b", id="bullet-then-check"),
    ],
)
def test_two_lists_in_a_row_are_kept_apart_by_an_nbsp_entity_paragraph(
    second: ListNode, second_text: str
) -> None:
    assert (
        render_slack([make_bullets(make_list_entry("a")), second])
        == f"* a\n\n{LIST_SEPARATOR}\n\n{second_text}\n"
    )


def test_lists_brought_together_by_a_container_with_no_title_are_kept_apart() -> None:
    untitled = Toggle((), None, (make_bullets(make_list_entry("b")),))

    assert render_slack([make_bullets(make_list_entry("a")), untitled]) == f"* a\n\n{LIST_SEPARATOR}\n\n* b\n"


def test_lists_in_a_row_inside_a_callout_or_a_column_are_kept_apart() -> None:
    lists = (make_bullets(make_list_entry("a")), make_bullets(make_list_entry("b")))
    columns = Columns((GridColumn(50, lists), GridColumn(50, (make_paragraph("c"),))))

    assert render_slack([Callout("info", lists), columns]) == (
        f"::: {{.callout}}\n💡\n\n* a\n\n{LIST_SEPARATOR}\n\n* b\n:::\n\n"
        f"::: {{.layout}}\n::: {{.column}}\n* a\n\n{LIST_SEPARATOR}\n\n* b\n:::\n"
        "::: {.column}\nc\n:::\n:::\n"
    )


def test_lists_with_a_paragraph_between_them_need_no_separator() -> None:
    assert (
        render_slack(
            [make_bullets(make_list_entry("a")), make_paragraph("b"), make_bullets(make_list_entry("c"))]
        )
        == "* a\n\nb\n\n* c\n"
    )


def _list_item_why(what: str) -> str:
    return f"a Slack canvas list item holds only text and one nested list, so it cannot show {what}"


def _canvas_rejection(why: str, instead: str, where: str | None = None) -> dict[str, str | None]:
    return {"target": "slack", "why": why, "instead": instead, "where": where}


def test_a_second_list_in_one_list_item_is_rejected() -> None:
    entry = make_list_entry(
        "a", make_bullets(make_list_entry("b")), ListNode("number", (make_list_entry("c"),))
    )

    assert vars(refusal_of([make_bullets(entry, make_list_entry("d"))], "slack")) == _canvas_rejection(
        _list_item_why("a second nested list"), OUT_OF_THE_LIST
    )


def test_a_paragraph_inside_a_list_item_joins_the_item_text() -> None:
    node = make_bullets(
        make_list_entry("Drift", make_paragraph("first"), make_paragraph("second")),
        ListEntry((), children=(make_paragraph("alone"),)),
    )

    assert render_slack([node]) == "* Drift first second\n* alone\n"


@pytest.mark.parametrize(
    ("held", "what"),
    [
        pytest.param(CodeBlock("x", "bash"), "a code block", id="code"),
        pytest.param(_key_value_table(), "a table", id="table"),
        pytest.param(Quote((make_rich_text("said"),)), "a quote", id="quote"),
        pytest.param(Callout("info", (make_paragraph("careful"),)), "a callout", id="callout"),
        pytest.param(
            Media("image", "https://example.com/a.png", make_rich_text("a chart")),
            "an image or a media link",
            id="media",
        ),
        pytest.param(Diagram(ONE_NODE_GRAPH), "a diagram", id="diagram"),
        pytest.param(DisplayMath("x^2"), "a math block", id="math"),
        pytest.param(Heading(2, make_rich_text("Inner")), "a heading", id="heading"),
        pytest.param(Toggle(make_rich_text("More"), None, (make_paragraph("x"),)), "a toggle", id="toggle"),
        pytest.param(Tabs((Tab(make_rich_text("A"), (make_paragraph("x"),)),)), "a set of tabs", id="tabs"),
        pytest.param(
            Columns((GridColumn(50, (make_paragraph("l"),)), GridColumn(50, (make_paragraph("r"),)))),
            "a column layout",
            id="columns",
        ),
    ],
)
def test_a_block_a_list_item_cannot_hold_is_rejected_even_two_lists_deep(held: Node, what: str) -> None:
    nested = make_bullets(make_list_entry("c", held))
    nodes = [make_bullets(make_list_entry("a"), make_list_entry("b", nested)), make_paragraph("after")]

    assert vars(refusal_of(nodes, "slack")) == _canvas_rejection(_list_item_why(what), OUT_OF_THE_LIST)


def test_a_paragraph_before_a_nested_list_in_a_list_item_is_written_in_place() -> None:
    entry = make_list_entry("a", make_paragraph("lead"), make_bullets(make_list_entry("n")))

    assert render_slack([ListNode("number", (entry, make_list_entry("b")))]) == "1. a lead\n   * n\n2. b\n"


@pytest.mark.parametrize(
    ("held", "what"),
    [
        pytest.param(Divider(authored_at="blocks.0.list"), "a divider", id="divider"),
        pytest.param(
            TableOfContents((TocEntry("x", make_rich_text("X")),), authored_at="blocks.0.list"),
            "a table of contents",
            id="table-of-contents",
        ),
        pytest.param(
            Paragraph(make_rich_text("tail"), authored_at="blocks.0.list"),
            "a paragraph after its nested list",
            id="paragraph-after-the-nested-list",
        ),
    ],
)
def test_a_list_item_holding_a_divider_a_table_of_contents_or_a_paragraph_after_its_list_is_rejected(
    held: Node, what: str
) -> None:
    entry = make_list_entry("a", make_bullets(make_list_entry("n")), held)
    node = ListNode("bullet", (entry,), authored_at="blocks.0.list")

    assert vars(refusal_of([node], "slack")) == _canvas_rejection(
        _list_item_why(what), OUT_OF_THE_LIST, "at blocks.0.list"
    )


def test_an_empty_paragraph_after_a_nested_list_in_a_list_item_writes_nothing() -> None:
    entry = make_list_entry("a", make_bullets(make_list_entry("n")), Paragraph(()))

    assert render_slack([make_bullets(entry)]) == "* a\n  * n\n"


def test_a_block_authored_on_its_own_in_a_list_item_is_rejected_as_a_step_detail_naming_its_path() -> None:
    detail = CodeBlock("recount", authored_at="blocks.0.walkthrough.steps.0.detail.0.code")
    entry = make_list_entry("Scan", detail)
    node = ListNode("number", (entry,), authored_at="blocks.0.walkthrough")

    assert vars(refusal_of([node], "slack")) == _canvas_rejection(
        _list_item_why("a code block"), OUT_OF_THE_STEP, "at blocks.0.walkthrough.steps.0.detail.0.code"
    )


def test_a_table_is_a_pipe_table_without_tones_or_widths_and_with_pipes_escaped_and_lines_joined() -> None:
    table = TableNode(
        (make_table_cell("Item"), make_table_cell("Note")),
        (
            TableRow(
                (
                    TableCell(make_rich_text("a|b"), "danger"),
                    TableCell((Plain("one"), Break(), Plain("two"))),
                ),
                "warning",
            ),
            TableRow((make_table_cell("Total"), make_table_cell("2")), emphasis="total"),
        ),
        columns=(TableColumn("info", 0.3), TableColumn()),
    )

    assert render_slack([table]) == (
        "| Item | Note |\n| --- | --- |\n| a\\|b | one<br>two |\n| **Total** | **2** |\n"
    )


@pytest.mark.parametrize("cells", [pytest.param(299, id="299"), pytest.param(300, id="300")])
def test_a_table_of_up_to_300_cells_header_included_is_written(cells: int) -> None:
    assert render_slack([_one_column_table(cells)]) == _one_column_table_text(cells)


@pytest.mark.parametrize(
    ("entry", "held"),
    [
        pytest.param(make_list_entry("a", CodeBlock("recount")), "CodeBlock", id="code-block"),
        pytest.param(
            make_list_entry("a", make_bullets("b"), make_bullets("c")), "ListNode", id="second-list"
        ),
        pytest.param(
            make_list_entry("a", make_bullets("b"), make_paragraph("after")),
            "Paragraph",
            id="paragraph-after",
        ),
    ],
)
def test_the_canvas_writer_alone_raises_an_internal_error_for_a_list_item_the_check_refuses(
    entry: ListEntry, held: str
) -> None:
    with pytest.raises(ExportInvariantError) as raised:
        render_slack([make_bullets(entry)])

    assert str(raised.value) == (
        f"a Slack canvas list item has no place for a {held} here; the export check should have refused it"
    )


def test_the_canvas_writer_alone_raises_an_internal_error_for_a_numbered_list_starting_past_1() -> None:
    with pytest.raises(ExportInvariantError) as raised:
        render_slack([ListNode("number", (make_list_entry("a"), make_list_entry("b")), start=3)])

    assert str(raised.value) == (
        "a Slack canvas numbers every list from 1, so it has no form for a list starting at 3; "
        "the export check should have refused it"
    )


def test_the_canvas_writer_alone_raises_an_internal_error_for_a_table_over_300_cells() -> None:
    with pytest.raises(ExportInvariantError) as raised:
        render_slack([_one_column_table(301)])

    assert str(raised.value) == (
        "a Slack canvas table holds at most 300 cells, not 301; the export check should have refused it"
    )


def test_a_table_over_300_cells_with_no_heading_above_it_is_rejected_naming_no_place() -> None:
    assert vars(refusal_of([_one_column_table(301)], "slack")) == _canvas_rejection(
        TABLE_LIMIT_WHY, TABLE_LIMIT_INSTEAD
    )


def test_a_table_over_300_cells_is_rejected_naming_the_heading_above_it() -> None:
    nodes = [Heading(2, make_rich_text("Counts")), Callout("info", (_one_column_table(301),))]

    assert vars(refusal_of(nodes, "slack")) == _canvas_rejection(
        TABLE_LIMIT_WHY, TABLE_LIMIT_INSTEAD, "under the heading 'Counts'"
    )


def test_a_table_over_300_cells_in_a_collapsed_section_is_rejected_naming_the_section_as_its_heading(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    section = make_section("counts", title="Counts", collapsed=True, blocks=[LONG_TABLE])
    data_path = write_report(tmp_path, make_report(blocks=[section]))

    assert main([str(data_path), "--export", "slack", "--export-dir", str(tmp_path / "exported")]) == 1

    assert capsys.readouterr().err == (
        f"error: {TABLE_LIMIT_WHY}, at blocks.0.section.blocks.0.table, under the heading 'Counts'; "
        f"{TABLE_LIMIT_INSTEAD}\n"
    )


def test_a_heading_without_text_leaves_the_heading_above_it_named_in_a_table_rejection() -> None:
    nodes = [Heading(2, make_rich_text("Counts")), Heading(3, ()), _one_column_table(301)]

    assert vars(refusal_of(nodes, "slack")) == _canvas_rejection(
        TABLE_LIMIT_WHY, TABLE_LIMIT_INSTEAD, "under the heading 'Counts'"
    )


def test_padding_counts_toward_the_cells_of_a_table() -> None:
    table = TableNode(
        (make_table_cell("a"), make_table_cell("b")),
        tuple(TableRow((make_table_cell("v"),)) for _ in range(150)),
    )

    assert vars(refusal_of([table], "slack")) == _canvas_rejection(
        "a table has 302 cells, over the 300 a Slack canvas table can hold", TABLE_LIMIT_INSTEAD
    )


def test_a_cell_count_in_the_thousands_is_written_with_a_thousands_separator() -> None:
    table = TableNode(
        tuple(make_table_cell(f"h{index}") for index in range(7)),
        tuple(TableRow(tuple(make_table_cell("v") for _ in range(7))) for _ in range(142)),
    )

    assert vars(refusal_of([table], "slack")) == _canvas_rejection(
        "a table has 1,001 cells, over the 300 a Slack canvas table can hold", TABLE_LIMIT_INSTEAD
    )


@pytest.mark.parametrize(
    ("node", "text"),
    [
        pytest.param(CodeBlock("x", "bash"), "```bash\nx\n```\n", id="code-with-language"),
        pytest.param(CodeBlock("x"), "```\nx\n```\n", id="code-without-language"),
        pytest.param(CodeBlock("a ``` b"), "````\na ``` b\n````\n", id="code-with-a-fence-inside"),
        pytest.param(DisplayMath("e = mc^2"), "```latex\ne = mc^2\n```\n", id="math"),
        pytest.param(Diagram(ONE_NODE_GRAPH), f"{MERMAID_ONE_NODE}\n", id="diagram"),
        pytest.param(
            Diagram(
                ONE_NODE_GRAPH,
                (make_bullets(make_list_entry("A", make_bullets(make_list_entry("by aisle")))),),
            ),
            f"{MERMAID_ONE_NODE}\n\n* A\n  * by aisle\n",
            id="diagram-with-its-supplement",
        ),
    ],
)
def test_a_fenced_block_carries_its_language(node: Node, text: str) -> None:
    assert render_slack([node]) == text


@pytest.mark.parametrize(
    ("node", "text"),
    [
        pytest.param(
            Media(
                "image", "https://example.com/a.png", make_rich_text("a chart"), make_rich_text("Q3 counts")
            ),
            "![a chart](https://example.com/a.png)\n\n*Q3 counts*\n",
            id="image-with-caption",
        ),
        pytest.param(
            Media("image", "https://example.com/a b.png", make_rich_text("a chart")),
            "![a chart](https://example.com/a%20b.png)\n",
            id="image",
        ),
        pytest.param(
            Media("video", "https://example.com/v.mp4", caption=make_rich_text("Walkthrough")),
            "[Walkthrough](https://example.com/v.mp4)\n",
            id="video-with-caption",
        ),
        pytest.param(
            Media("video", "https://example.com/v.mp4"), "[Video](https://example.com/v.mp4)\n", id="video"
        ),
        pytest.param(
            Media("pdf", "https://example.com/r.pdf"), "[PDF](https://example.com/r.pdf)\n", id="pdf"
        ),
    ],
)
def test_media_is_an_image_or_a_link_labelled_with_its_caption_or_kind(node: Media, text: str) -> None:
    assert render_slack([node]) == text


@pytest.mark.parametrize(
    ("node", "text"),
    [
        pytest.param(
            Callout("warning", (make_paragraph("careful"),)),
            "::: {.callout}\n⚠️ careful\n:::\n",
            id="tone-icon",
        ),
        pytest.param(
            Callout("info", (make_paragraph("north"),), "🧭"),
            "::: {.callout}\n🧭 north\n:::\n",
            id="own-icon",
        ),
        pytest.param(
            Callout("info", (make_bullets(make_list_entry("a")), make_paragraph("b"))),
            "::: {.callout}\n💡\n\n* a\n\nb\n:::\n",
            id="led-by-a-list",
        ),
        pytest.param(Callout("info", ()), "::: {.callout}\n💡\n:::\n", id="empty"),
        pytest.param(
            Callout("info", (Toggle(make_rich_text("T"), None, (make_paragraph("x"),)),)),
            "::: {.callout}\n💡 **T**\n\nx\n:::\n",
            id="led-by-a-toggle-title",
        ),
        pytest.param(
            Callout("info", (Tabs((Tab(make_rich_text("T"), (make_paragraph("x"),)),)),)),
            "::: {.callout}\n💡 **T**\n\nx\n:::\n",
            id="led-by-a-tab-title",
        ),
    ],
)
def test_a_callout_is_a_fenced_callout_whose_unindented_body_starts_with_its_icon(
    node: Callout, text: str
) -> None:
    assert render_slack([node]) == text


def test_a_panel_is_a_fenced_callout_with_no_icon_as_on_the_page() -> None:
    panel = {"type": "panel", "title": "Card", "blocks": [{"type": "text", "body": "inside"}]}

    assert slack_of([panel]) == "::: {.callout}\n**Card**\n\ninside\n:::\n"


def test_a_table_callout_divider_or_column_layout_inside_a_callout_moves_after_it() -> None:
    columns = Columns((GridColumn(50, (make_paragraph("left"),)), GridColumn(50, (make_paragraph("right"),))))
    inner = Callout("danger", (make_paragraph("inner"),))
    node = Callout(
        "info",
        (make_paragraph("lead"), _key_value_table(), inner, Divider(), columns, make_paragraph("tail")),
    )

    assert render_slack([node]) == (
        "::: {.callout}\n💡 lead\n\ntail\n:::\n\n"
        "| k |\n| --- |\n| v |\n\n"
        "::: {.callout}\n🛑 inner\n:::\n\n"
        "---\n\n"
        "::: {.layout}\n::: {.column}\nleft\n:::\n::: {.column}\nright\n:::\n:::\n"
    )


def test_a_table_in_a_list_item_in_a_callout_is_rejected() -> None:
    node = Callout("info", (make_bullets(make_list_entry("a", _key_value_table())),))

    assert vars(refusal_of([node], "slack")) == _canvas_rejection(_list_item_why("a table"), OUT_OF_THE_LIST)


def test_a_callout_inside_a_callout_inside_a_callout_comes_out_flat_in_order() -> None:
    innermost = Callout("danger", (make_paragraph("c"),))
    middle = Callout("warning", (make_paragraph("b"), innermost))

    assert render_slack([Callout("info", (make_paragraph("a"), middle))]) == (
        "::: {.callout}\n💡 a\n:::\n\n::: {.callout}\n⚠️ b\n:::\n\n::: {.callout}\n🛑 c\n:::\n"
    )


def test_a_quote_is_quoted_lines_with_the_cite_on_its_own_italic_line() -> None:
    node = Quote((make_rich_text("said"), make_rich_text("# again")), make_rich_text("Ana"))

    assert render_slack([node]) == "> said\n>\n> \\# again\n>\n> *Ana*\n"


def test_a_divider_stays_at_the_top_level() -> None:
    toggle = Toggle(make_rich_text("More"), None, (Divider(),))

    assert render_slack([make_paragraph("a"), Divider(), make_paragraph("b"), toggle]) == (
        "a\n\n---\n\nb\n\n**More**\n\n---\n"
    )


@pytest.mark.parametrize(
    ("node", "text"),
    [
        pytest.param(
            Toggle(make_rich_text("Raw"), 2, (make_paragraph("x"),)), "## Raw\n\nx\n", id="heading-level-2"
        ),
        pytest.param(
            Toggle(make_rich_text("Raw"), 5, (make_paragraph("x"),)),
            "### Raw\n\nx\n",
            id="heading-level-5-folds",
        ),
        pytest.param(
            Toggle(make_rich_text("Raw"), None, (make_paragraph("x"),)), "**Raw**\n\nx\n", id="no-heading"
        ),
        pytest.param(Toggle((), None, (make_paragraph("x"),)), "x\n", id="no-title"),
    ],
)
def test_a_toggle_is_its_heading_or_bold_title_then_its_children(node: Toggle, text: str) -> None:
    assert render_slack([node]) == text


def test_up_to_three_columns_are_a_column_layout_without_dividers() -> None:
    node = Columns(
        (
            GridColumn(40, (make_paragraph("left"), Divider())),
            GridColumn(30, (make_bullets(make_list_entry("a")),)),
            GridColumn(30, (Toggle(make_rich_text("T"), None, (make_paragraph("x"),)),)),
        )
    )

    assert render_slack([node]) == (
        "::: {.layout}\n"
        "::: {.column}\nleft\n:::\n"
        "::: {.column}\n* a\n:::\n"
        "::: {.column}\n**T**\n\nx\n:::\n"
        ":::\n"
    )


def test_more_than_three_columns_are_their_children_one_after_another() -> None:
    node = Columns(tuple(GridColumn(25, (make_paragraph(name), Divider())) for name in "abcd"))

    assert render_slack([node]) == "a\n\n---\n\nb\n\n---\n\nc\n\n---\n\nd\n\n---\n"


@pytest.mark.parametrize(
    ("held", "text"),
    [
        pytest.param(_key_value_table(), "| k |\n| --- |\n| v |", id="table"),
        pytest.param(Callout("info", (make_paragraph("c"),)), "::: {.callout}\n💡 c\n:::", id="callout"),
    ],
)
def test_columns_holding_a_table_or_callout_are_their_children_one_after_another(
    held: Node, text: str
) -> None:
    node = Columns((GridColumn(50, (make_paragraph("left"),)), GridColumn(50, (held, Divider()))))

    assert render_slack([node]) == f"left\n\n{text}\n\n---\n"


def test_columns_inside_a_column_are_their_children_one_after_another_inside_the_layout() -> None:
    inner = Columns((GridColumn(50, (make_paragraph("x"),)), GridColumn(50, (make_paragraph("y"),))))
    node = Columns((GridColumn(50, (make_paragraph("left"),)), GridColumn(50, (inner,))))

    assert render_slack([node]) == (
        "::: {.layout}\n::: {.column}\nleft\n:::\n::: {.column}\nx\n\ny\n:::\n:::\n"
    )


def test_tabs_are_bold_titles_led_by_the_tone_icon_then_their_children() -> None:
    node = Tabs(
        (
            Tab(make_rich_text("Floor"), (make_paragraph("a"),), "warning"),
            Tab(make_rich_text("System"), (make_paragraph("b"),), "accent"),
        )
    )

    assert render_slack([node]) == "**⚠️ Floor**\n\na\n\n**System**\n\nb\n"


@pytest.mark.parametrize(
    ("tab", "text"),
    [
        pytest.param(Tab((), (make_paragraph("a"),), "warning"), "⚠️\n\na\n", id="icon-without-a-title"),
        pytest.param(Tab((), (make_paragraph("a"),)), "a\n", id="neither-icon-nor-title"),
    ],
)
def test_a_tab_without_a_title_writes_its_icon_alone_or_nothing_before_its_children(
    tab: Tab, text: str
) -> None:
    assert render_slack([Tabs((tab,))]) == text


def test_a_table_of_contents_writes_nothing() -> None:
    contents = TableOfContents((TocEntry("x", make_rich_text("X")),))

    assert render_slack([make_paragraph("a"), contents, make_paragraph("b")]) == "a\n\nb\n"


@pytest.mark.parametrize(
    ("run", "written"),
    [
        pytest.param(Styled("bold", make_rich_text("b")), "**b**", id="bold"),
        pytest.param(Styled("italic", make_rich_text("i")), "*i*", id="italic"),
        pytest.param(Styled("strike", make_rich_text("s")), "~~s~~", id="strike"),
        pytest.param(TonedLabel("danger", make_rich_text("t")), "t", id="toned-label-is-plain"),
        pytest.param(ScriptText("subscript", "2"), "\N{SUBSCRIPT TWO}", id="subscript-digit"),
        pytest.param(
            ScriptText("subscript", "i=0"),
            "\N{LATIN SUBSCRIPT SMALL LETTER I}\N{SUBSCRIPT EQUALS SIGN}\N{SUBSCRIPT ZERO}",
            id="subscript-letter-sign-and-digit",
        ),
        pytest.param(
            ScriptText("superscript", "-3"),
            "\N{SUPERSCRIPT MINUS}\N{SUPERSCRIPT THREE}",
            id="superscript-hyphen-is-a-superscript-minus",
        ),
        pytest.param(
            ScriptText("superscript", "(n+1)"),
            "\N{SUPERSCRIPT LEFT PARENTHESIS}\N{SUPERSCRIPT LATIN SMALL LETTER N}\N{SUPERSCRIPT PLUS SIGN}"
            "\N{SUPERSCRIPT ONE}\N{SUPERSCRIPT RIGHT PARENTHESIS}",
            id="superscript-brackets-letter-and-sign",
        ),
        pytest.param(
            ScriptText("superscript", "TM"),
            "\N{MODIFIER LETTER CAPITAL T}\N{MODIFIER LETTER CAPITAL M}",
            id="superscript-capitals",
        ),
        pytest.param(
            ScriptText("superscript", "ao"),
            "\N{MODIFIER LETTER SMALL A}\N{MODIFIER LETTER SMALL O}",
            id="superscript-a-and-o-are-letters-not-ordinal-indicators",
        ),
        pytest.param(Code("a`b"), "``a`b``", id="code-outgrows-its-backticks"),
        pytest.param(Chip("a*b", "blue"), "**a\\*b**", id="chip-is-bold"),
        pytest.param(StatusMark("done"), "✅", id="status-mark"),
        pytest.param(
            SectionLink(make_rich_text("method"), "method"), "method", id="section-link-is-its-label"
        ),
        pytest.param(
            DateMention(make_rich_text("1 Oct"), date(2026, 10, 1), None),
            "![](slack_date:2026-10-01)",
            id="date",
        ),
        pytest.param(
            DateMention(make_rich_text("1 to 3 Oct"), date(2026, 10, 1), date(2026, 10, 3)),
            "![](slack_date:2026-10-01) to ![](slack_date:2026-10-03)",
            id="date-range",
        ),
        pytest.param(
            PersonMention(make_rich_text("Ada"), "ada", Person()), "Ada", id="person-without-a-slack-id"
        ),
        pytest.param(
            Link(make_rich_text("x"), "https://example.com/a b"), "[x](https://example.com/a%20b)", id="https"
        ),
        pytest.param(Link(make_rich_text("x"), "http://example.com"), "[x](http://example.com)", id="http"),
        pytest.param(
            Link(make_rich_text("x"), "mailto:ops@example.com"), "[x](mailto:ops@example.com)", id="mailto"
        ),
        pytest.param(InlineMath("x_i"), "`x_i`", id="inline-math-is-code"),
        pytest.param(
            IssueLink(make_rich_text("ABC-1"), "ABC-1", "https://example.atlassian.net/browse/ABC-1"),
            "[ABC-1](https://example.atlassian.net/browse/ABC-1)",
            id="issue-link",
        ),
        pytest.param(
            Citation("a", 1, "https://example.com"), "[\\[1\\]](https://example.com)", id="citation"
        ),
        pytest.param(Citation("a", 1, None), "\\[1\\]", id="citation-without-a-url"),
        pytest.param(Placeholder("owner"), "`{{owner}}`", id="placeholder"),
    ],
)
def test_an_inline_run_becomes_canvas_markdown(run: ExportRun, written: str) -> None:
    assert render_slack([Paragraph((run,))]) == f"{written}\n"


@pytest.mark.parametrize(
    ("run", "why", "instead"),
    [
        pytest.param(
            ScriptText("superscript", "*3"),
            "a Slack canvas cannot show the superscript '*3', since '*' has no Unicode superscript form",
            "write the text without the superscript or export the document elsewhere",
            id="superscript-punctuation",
        ),
        pytest.param(
            ScriptText("superscript", "q"),
            "a Slack canvas cannot show the superscript 'q', since 'q' has no Unicode superscript form",
            "write the text without the superscript or export the document elsewhere",
            id="superscript-letter-with-no-form",
        ),
        pytest.param(
            ScriptText("subscript", "ab"),
            "a Slack canvas cannot show the subscript 'ab', since 'b' has no Unicode subscript form",
            "write the text without the subscript or export the document elsewhere",
            id="subscript-letter-with-no-form",
        ),
        pytest.param(
            ScriptText("subscript", "1 2"),
            "a Slack canvas cannot show the subscript '1 2', since ' ' has no Unicode subscript form",
            "write the text without the subscript or export the document elsewhere",
            id="subscript-space",
        ),
    ],
)
def test_a_script_with_a_character_that_has_no_unicode_form_is_rejected(
    run: ExportRun, why: str, instead: str
) -> None:
    assert vars(refusal_of([Paragraph((run,))], "slack")) == _canvas_rejection(why, instead)


@pytest.mark.parametrize(
    "node",
    [
        pytest.param(Heading(2, (SCRIPT_WITHOUT_A_FORM,)), id="heading"),
        pytest.param(ListNode("bullet", (ListEntry((SCRIPT_WITHOUT_A_FORM,)),)), id="list-entry"),
        pytest.param(TableNode((TableCell((SCRIPT_WITHOUT_A_FORM,)),), ()), id="table-header"),
        pytest.param(
            TableNode((make_table_cell("h"),), (TableRow((TableCell((SCRIPT_WITHOUT_A_FORM,)),)),)),
            id="table-cell",
        ),
        pytest.param(Quote((make_rich_text("q"),), (SCRIPT_WITHOUT_A_FORM,)), id="quote-cite"),
        pytest.param(Toggle((SCRIPT_WITHOUT_A_FORM,), None, ()), id="toggle-title"),
        pytest.param(Tabs((Tab((SCRIPT_WITHOUT_A_FORM,), ()),)), id="tab-title"),
        pytest.param(
            Media("image", "https://example.com/a.png", caption=(SCRIPT_WITHOUT_A_FORM,)), id="image-caption"
        ),
        pytest.param(
            Paragraph((Link((Styled("bold", (SCRIPT_WITHOUT_A_FORM,)),), "https://example.com"),)),
            id="bold-inside-a-link-label",
        ),
    ],
)
def test_a_script_with_no_unicode_form_is_refused_by_the_check_wherever_the_canvas_writes_text(
    node: Node,
) -> None:
    with pytest.raises(ExportInvariantError) as raised:
        render_slack([node])

    assert (str(raised.value), vars(refusal_of([node], "slack"))) == (
        SCRIPT_INVARIANT,
        _canvas_rejection(SCRIPT_WHY, SCRIPT_INSTEAD),
    )


def test_the_canvas_writer_alone_raises_an_internal_error_for_a_script_with_no_unicode_form() -> None:
    with pytest.raises(ExportInvariantError) as raised:
        render_slack([Paragraph((SCRIPT_WITHOUT_A_FORM,))])

    assert str(raised.value) == SCRIPT_INVARIANT


@pytest.mark.parametrize(
    ("runs", "written"),
    [
        pytest.param(
            (Styled("bold", make_rich_text("(x)")), Plain("y")),
            "(x)y",
            id="bold-followed-by-a-word-character",
        ),
        pytest.param(
            (Plain("a"), Styled("italic", make_rich_text("(b)")), Plain(".")),
            "a(b).",
            id="italic-between-a-letter-and-punctuation",
        ),
        pytest.param(
            (Styled("bold", make_rich_text("a")), Styled("italic", make_rich_text("b"))),
            "**a**b",
            id="italic-running-into-a-bold-closer",
        ),
        pytest.param(
            (Styled("strike", make_rich_text("(s)")), Plain("t")), "(s)t", id="strike-followed-by-a-letter"
        ),
        pytest.param(
            (
                Styled(
                    "bold",
                    (
                        Styled("italic", make_rich_text("a")),
                        Plain(" x"),
                        Styled("italic", make_rich_text("y")),
                    ),
                ),
            ),
            "**a xy**",
            id="italic-at-both-edges-of-a-bold",
        ),
    ],
)
def test_emphasis_whose_markers_a_canvas_cannot_read_drops_its_style_and_never_becomes_a_tag(
    runs: tuple[ExportRun, ...], written: str
) -> None:
    assert render_slack([Paragraph(runs)]) == f"{written}\n"


COUNTS_HEADING: dict[str, Any] = {"type": "heading", "text": "Counts", "id": "counts"}


@pytest.mark.parametrize(
    ("body", "written"),
    [
        pytest.param(
            "**[*a*](https://x.io)**", "**[*a*](https://x.io)**", id="italic-in-a-link-label-in-a-bold"
        ),
        pytest.param(
            "*[_a_](https://x.io)*", "*[a](https://x.io)*", id="italic-in-a-link-label-in-an-italic"
        ),
    ],
)
def test_emphasis_inside_a_link_label_inside_emphasis_on_a_canvas(body: str, written: str) -> None:
    assert slack_of([COUNTS_HEADING, {"type": "text", "body": body}]) == f"## Counts\n\n{written}\n"


@pytest.mark.parametrize(
    ("run", "message"),
    [
        pytest.param(
            Styled("underline", make_rich_text("u")),
            "a Slack canvas has no underline; the export check should have refused it",
            id="underline",
        ),
        pytest.param(
            DocumentLink(make_rich_text("the plan"), "plan", None),
            "this target cannot link to another skaldr document; the export check should have refused it",
            id="link-to-another-document",
        ),
    ],
)
def test_the_canvas_writer_refuses_what_the_export_check_refuses_as_an_invariant(
    run: ExportRun, message: str
) -> None:
    with pytest.raises(ExportInvariantError) as raised:
        render_slack([Paragraph((run,))])

    assert str(raised.value) == message


@pytest.mark.parametrize(
    ("runs", "written"),
    [
        pytest.param(
            (
                Styled(
                    "bold",
                    (
                        Plain("x "),
                        Styled("italic", make_rich_text("a")),
                        Styled("italic", make_rich_text(" ")),
                    ),
                ),
            ),
            "**x a** ",
            id="italic-before-a-trailing-blank-italic-closes-the-bold",
        ),
        pytest.param(
            (Plain("x"), Styled("bold", make_rich_text("(a)")), Styled("bold", make_rich_text("b"))),
            "x(a)**b**",
            id="bold-straight-after-a-bold-written-plain-keeps-its-markers",
        ),
    ],
)
def test_emphasis_beside_emphasis_that_writes_no_marker_is_judged_on_what_is_written_on_a_canvas(
    runs: tuple[ExportRun, ...], written: str
) -> None:
    assert render_slack([Paragraph(runs)]) == f"{written}\n"


def test_emphasis_nested_in_the_same_emphasis_is_written_once_on_a_canvas() -> None:
    nested = Styled("italic", (Plain("a "), Styled("italic", make_rich_text("b")), Plain(" c")))

    assert render_slack([Paragraph((nested,))]) == "*a b c*\n"


def test_canvas_special_characters_are_escaped_in_text_but_not_dollars() -> None:
    nodes = [Paragraph(make_rich_text("a*b_c~d`e|f [x] <@U0EXAMPLE1> $5 &amp; done!"))]

    assert render_slack(nodes) == ("a\\*b\\_c\\~d\\`e|f \\[x\\] \\<@U0EXAMPLE1\\> $5 \\&amp; done\\!\n")


def test_canvas_special_characters_and_pipes_are_escaped_in_a_table_cell() -> None:
    table = TableNode((make_table_cell("a*b_c~d`e|f"),), (TableRow((TableCell((Code("x|y"),)),)),))

    assert render_slack([table]) == "| a\\*b\\_c\\~d\\`e\\|f |\n| --- |\n| `x\\|y` |\n"


@pytest.mark.parametrize(
    ("text", "line"),
    [
        pytest.param("::: {.callout}", "\\::: {.callout}", id="callout-fence"),
        pytest.param(":::", "\\:::", id="bare-fence"),
        pytest.param("# not a heading", "\\# not a heading", id="heading-marker"),
        pytest.param("- not a list", "\\- not a list", id="list-marker"),
        pytest.param("1. not a list", "1\\. not a list", id="ordered-marker"),
        pytest.param("a ::: b", "a ::: b", id="fence-mid-line"),
    ],
)
def test_a_paragraph_that_starts_like_a_block_marker_stays_a_paragraph(text: str, line: str) -> None:
    assert render_slack([make_paragraph(text)]) == f"{line}\n"


def test_a_list_item_that_starts_like_a_callout_fence_stays_text() -> None:
    assert render_slack([make_bullets(make_list_entry(":::"))]) == "* \\:::\n"


def test_a_document_exports_its_body_without_the_title_since_the_canvas_takes_the_title(
    tmp_path: Path,
) -> None:
    report = load_report(write_report(tmp_path, make_report(blocks=[{"type": "text", "body": "Hi."}])))
    out_dir = tmp_path / "out"

    result = export_slack(report, out_dir)

    assert (result, folder_texts(out_dir)) == (
        ExportResult("Test Report", (out_dir / "page.md",)),
        {
            EXPORT_MANIFEST: '{\n  "title": "Test Report",\n  "files": [\n    "page.md"\n  ]\n}\n',
            "page.md": "Hi.\n",
        },
    )


def test_a_document_built_from_yaml_exports_through_the_lowering() -> None:
    blocks = [
        {"type": "heading", "text": "Counts"},
        {"type": "callout", "tone": "warning", "title": "Recount", "body": "Aisle 4 by **Friday**."},
    ]

    assert slack_of(blocks) == "## Counts\n\n::: {.callout}\n⚠️ **Recount**\n\nAisle 4 by **Friday**.\n:::\n"


def _code_report(tmp_path: Path, code_length: int, character: str = "x") -> Report:
    blocks = [{"type": "code", "content": character * code_length}]
    return load_report(write_report(tmp_path, make_report(blocks=blocks)))


@pytest.mark.parametrize(
    "character",
    [
        pytest.param("x", id="one-byte-characters"),
        pytest.param("\N{LATIN SMALL LETTER E WITH ACUTE}", id="two-byte-characters-counted-as-characters"),
    ],
)
def test_canvas_markdown_of_exactly_1_048_576_characters_is_written(tmp_path: Path, character: str) -> None:
    out_dir = tmp_path / "out"

    result = export_slack(_code_report(tmp_path, CANVAS_LIMIT_CODE_LENGTH, character), out_dir)

    assert (result, (out_dir / "page.md").read_text(encoding="utf-8")) == (
        ExportResult("Test Report", (out_dir / "page.md",)),
        "```\n" + character * CANVAS_LIMIT_CODE_LENGTH + "\n```\n",
    )


def test_canvas_markdown_over_1_048_576_characters_is_rejected_before_anything_is_written(
    tmp_path: Path,
) -> None:
    out_dir = tmp_path / "out"

    with pytest.raises(ExportRejectedError) as raised:
        export_slack(_code_report(tmp_path, CANVAS_LIMIT_CODE_LENGTH + 1), out_dir)

    assert (vars(raised.value), out_dir.exists()) == (
        _canvas_rejection(CANVAS_LIMIT_WHY, CANVAS_LIMIT_INSTEAD),
        False,
    )


def test_a_table_over_the_canvas_limit_is_rejected_before_anything_is_written(tmp_path: Path) -> None:
    table = {"type": "table", "columns": [{"key": "item", "label": "Item"}], "rows": [["v"]] * 300}
    report = load_report(write_report(tmp_path, make_report(blocks=[table])))
    out_dir = tmp_path / "out"

    with pytest.raises(ExportRejectedError) as raised:
        export_slack(report, out_dir)

    assert (vars(raised.value), out_dir.exists()) == (
        _canvas_rejection(TABLE_LIMIT_WHY, TABLE_LIMIT_INSTEAD, "at blocks.0.table"),
        False,
    )


def test_the_cli_exports_slack_and_writes_the_manifest_whose_title_names_the(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data_path = write_report(tmp_path, make_report(blocks=[{"type": "text", "body": "Hi."}]))
    export_dir = tmp_path / "exported"

    assert main([str(data_path), "--export", "slack", "--export-dir", str(export_dir)]) == 0

    captured = capsys.readouterr()
    assert (
        captured.out,
        captured.err,
        json.loads((export_dir / EXPORT_MANIFEST).read_text(encoding="utf-8")),
        (export_dir / "page.md").read_text(encoding="utf-8"),
    ) == (f"OK  {export_dir / 'page.md'}\n", "", {"title": "Test Report", "files": ["page.md"]}, "Hi.\n")


def test_the_cli_writes_a_slack_export_under_out_named_for_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_path = write_report(tmp_path, make_report())
    monkeypatch.chdir(tmp_path)

    assert main([str(data_path), "--export", "slack"]) == 0

    assert (tmp_path / "out" / "doc.slack" / "page.md").read_text(encoding="utf-8") == "Hello.\n"


def _walkthrough_grid_message(walkthrough_index: int) -> str:
    return (
        "a Slack canvas cannot show a grid inside a walkthrough step, since a canvas list item holds only "
        f"text, at blocks.{walkthrough_index}.walkthrough.steps.1.detail.1.grid; move the grid out of the "
        "step, after the walkthrough"
    )


def _walkthrough_with_a_grid_in_its_second_step() -> dict[str, Any]:
    grid = {
        "type": "grid",
        "cells": [
            {"span": 3, "blocks": [{"type": "text", "body": "Action"}]},
            {"span": 3, "blocks": [{"type": "code", "content": "recount --aisle 4"}]},
        ],
    }
    return {
        "type": "walkthrough",
        "steps": [
            {"label": "Freeze", "detail": [{"type": "text", "body": "Lock the aisle."}]},
            {"label": "Scan", "detail": [{"type": "text", "body": "Twice."}, grid]},
        ],
    }


def test_a_grid_inside_a_walkthrough_step_is_rejected_before_anything_is_written(tmp_path: Path) -> None:
    blocks = [{"type": "heading", "text": "Recount"}, _walkthrough_with_a_grid_in_its_second_step()]
    report = load_report(write_report(tmp_path, make_report(blocks=blocks)))
    out_dir = tmp_path / "out"

    with pytest.raises(ExportRejectedError) as raised:
        export_slack(report, out_dir)

    assert (vars(raised.value), out_dir.exists()) == (
        _canvas_rejection(
            "a Slack canvas cannot show a grid inside a walkthrough step, "
            "since a canvas list item holds only text",
            "move the grid out of the step, after the walkthrough",
            "at blocks.1.walkthrough.steps.1.detail.1.grid",
        ),
        False,
    )


def _walkthrough_detail_message(path: str, what: str) -> str:
    return (
        f"a Slack canvas list item holds only text and one nested list, so it cannot show {what}, at {path}; "
        "move it out of the step, after the walkthrough"
    )


def _walkthrough_whose_second_step_holds(detail: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "walkthrough",
        "steps": [
            {"label": "Freeze", "detail": [{"type": "text", "body": "Lock the aisle."}]},
            {"label": "Scan", "detail": [{"type": "list", "items": ["Twice.", "Then reconcile."]}, detail]},
        ],
    }


@pytest.mark.parametrize(
    ("detail", "what"),
    [
        pytest.param({"type": "code", "content": "recount --aisle 4"}, "a code block", id="code"),
        pytest.param(
            {"type": "callout", "tone": "warning", "body": "Stop first."}, "a callout", id="callout"
        ),
        pytest.param({"type": "math", "expression": "x^2"}, "a math block", id="math"),
        pytest.param(
            {"type": "table", "columns": [{"key": "a", "label": "A"}], "rows": [["v"]]}, "a table", id="table"
        ),
        pytest.param({"type": "quote", "body": "Count twice."}, "a quote", id="quote"),
        pytest.param(
            {"type": "image", "src": "https://example.com/a.png", "alt": "aisle"},
            "an image or a media link",
            id="image",
        ),
        pytest.param({"type": "heading", "text": "Inner"}, "a heading", id="heading"),
        pytest.param({"type": "divider"}, "a divider", id="divider"),
        pytest.param({"type": "list", "items": ["one", "two"]}, "a second nested list", id="second-list"),
        pytest.param(
            {"type": "text", "body": "Then file it."},
            "a paragraph after its nested list",
            id="text-after-the-list",
        ),
    ],
)
def test_a_walkthrough_step_holding_a_block_a_canvas_list_item_cannot_hold_is_rejected_naming_its_path(
    tmp_path: Path, detail: dict[str, Any], what: str
) -> None:
    blocks = [{"type": "heading", "text": "Recount"}, _walkthrough_whose_second_step_holds(detail)]
    report = load_report(write_report(tmp_path, make_report(blocks=blocks)))
    out_dir = tmp_path / "out"

    with pytest.raises(ExportRejectedError) as raised:
        export_slack(report, out_dir)

    path = f"blocks.1.walkthrough.steps.1.detail.1.{detail['type']}"
    assert (vars(raised.value), out_dir.exists()) == (
        _canvas_rejection(_list_item_why(what), OUT_OF_THE_STEP, f"at {path}"),
        False,
    )


@pytest.mark.parametrize(
    ("blocks", "what", "path"),
    [
        pytest.param(
            [{"type": "def_list", "items": [{"term": "Scan", "body": "Lead.\n\n- a\n- b\n\n1. c\n2. d"}]}],
            "a second nested list",
            "blocks.0.def_list",
            id="definition-with-two-lists",
        ),
        pytest.param(
            [{"type": "def_list", "items": [{"term": "Scan", "body": "Lead.\n\n- a\n- b\n\nTail."}]}],
            "a paragraph after its nested list",
            "blocks.0.def_list",
            id="definition-with-a-paragraph-after-its-list",
        ),
        pytest.param(
            [{"type": "text", "body": "- a\n  - b\n  - c\n\n  1. d\n  2. e\n- f"}],
            "a second nested list",
            "blocks.0.text",
            id="text-body-list",
        ),
        pytest.param(
            [{"type": "callout", "tone": "info", "body": "- a\n  - b\n  - c\n\n  1. d\n  2. e\n- f"}],
            "a second nested list",
            "blocks.0.callout",
            id="callout-body-list",
        ),
        pytest.param(
            [
                {"type": "heading", "text": "Lead"},
                {
                    "type": "section",
                    "title": "Counts",
                    "blocks": [
                        {"type": "text", "body": "Intro."},
                        {"type": "text", "body": "- a\n  - b\n\n  Tail.\n- f"},
                    ],
                },
            ],
            "a paragraph after its nested list",
            "blocks.1.section.blocks.1.text",
            id="text-inside-a-section",
        ),
    ],
)
def test_a_list_item_in_a_block_body_is_rejected_naming_the_yaml_path_of_that_block(
    blocks: list[dict[str, Any]], what: str, path: str
) -> None:
    with pytest.raises(ExportRejectedError) as raised:
        slack_of(blocks)

    assert vars(raised.value) == _canvas_rejection(_list_item_why(what), OUT_OF_THE_LIST, f"at {path}")


def test_the_cli_refuses_a_code_block_inside_a_walkthrough_step(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    walkthrough = _walkthrough_whose_second_step_holds({"type": "code", "content": "recount"})
    data_path = write_report(tmp_path, make_report(blocks=[walkthrough]))
    export_dir = tmp_path / "exported"

    assert main([str(data_path), "--export", "slack", "--export-dir", str(export_dir)]) == 1

    captured = capsys.readouterr()
    message = _walkthrough_detail_message("blocks.0.walkthrough.steps.1.detail.1.code", "a code block")
    assert (captured.err, captured.out, export_dir.exists()) == (f"error: {message}\n", "", False)


def test_a_walkthrough_step_with_text_then_one_list_exports_as_one_list_item() -> None:
    detail = [{"type": "text", "body": "Twice."}, {"type": "list", "items": ["a", "b"]}]
    walkthrough = {"type": "walkthrough", "steps": [{"label": "Scan", "detail": detail}]}

    assert slack_of([walkthrough]) == "1. **Scan** Twice.\n   * a\n   * b\n"


def test_a_walkthrough_whose_steps_hold_no_grid_exports() -> None:
    walkthrough = {
        "type": "walkthrough",
        "steps": [{"label": "Freeze", "detail": [{"type": "text", "body": "Lock the aisle."}]}],
    }

    assert slack_of([walkthrough]) == "1. **Freeze** Lock the aisle.\n"


def test_a_grid_outside_a_walkthrough_step_exports_as_a_layout() -> None:
    grid = {
        "type": "grid",
        "cells": [
            {"span": 3, "blocks": [{"type": "text", "body": "left"}]},
            {"span": 3, "blocks": [{"type": "text", "body": "right"}]},
        ],
    }

    assert slack_of([grid]) == "::: {.layout}\n::: {.column}\nleft\n:::\n::: {.column}\nright\n:::\n:::\n"


def test_the_cli_refuses_a_grid_inside_a_walkthrough_step(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data_path = write_report(tmp_path, make_report(blocks=[_walkthrough_with_a_grid_in_its_second_step()]))
    export_dir = tmp_path / "exported"

    assert main([str(data_path), "--export", "slack", "--export-dir", str(export_dir)]) == 1

    captured = capsys.readouterr()
    assert (captured.err, captured.out, export_dir.exists()) == (
        f"error: {_walkthrough_grid_message(0)}\n",
        "",
        False,
    )


def test_the_cli_refuses_a_table_over_the_canvas_limit_and_writes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    table = {"type": "table", "columns": [{"key": "item", "label": "Item"}], "rows": [["v"]] * 300}
    blocks = [{"type": "heading", "text": "Counts"}, table]
    data_path = write_report(tmp_path, make_report(blocks=blocks))
    export_dir = tmp_path / "exported"

    assert main([str(data_path), "--export", "slack", "--export-dir", str(export_dir)]) == 1

    captured = capsys.readouterr()
    assert (captured.err, captured.out, export_dir.exists()) == (
        f"error: {TABLE_LIMIT_WHY}, at blocks.1.table, under the heading 'Counts'; {TABLE_LIMIT_INSTEAD}\n",
        "",
        False,
    )
