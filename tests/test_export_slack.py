import json
from datetime import date
from pathlib import Path

import pytest

from skaldr.cli import main
from skaldr.export import EXPORT_MANIFEST, ExportResult, export_slack
from skaldr.export.runs import Break, Chip, ExportRun, StatusMark
from skaldr.export.slack import SlackCanvas, render_slack
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
from skaldr.models import Person, load_report
from skaldr.richtext import (
    AnchorLink,
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
    Rich,
    ScriptText,
    Styled,
    Tinted,
)
from tests.conftest import REPO_ROOT
from tests.factories import folder_texts, make_report, slack_of, write_report

EXAMPLE = REPO_ROOT / "data" / "example.yaml"
SLACK_GOLDEN = REPO_ROOT / "tests" / "golden" / "example.slack"
CANVAS_LIMIT_CODE_LENGTH = 1_048_567
MERMAID_ONE_NODE = '```mermaid\nflowchart LR\n    s1["A"]\n```'
ONE_NODE_GRAPH = Graph("LR", (GraphNode("s1", "A"),), ())
TABLE_LIMIT_MESSAGE = "a table has 301 cells, over Slack's limit of 300 per canvas table"


def _text(text: str) -> Rich:
    return (Plain(text),)


def _para(text: str) -> Paragraph:
    return Paragraph(_text(text))


def _entry(text: str, *children: Node, checked: bool = False) -> ListEntry:
    return ListEntry(_text(text), checked, children)


def _bullets(*entries: ListEntry) -> ListNode:
    return ListNode("bullet", entries)


def _cell(text: str) -> TableCell:
    return TableCell(_text(text))


def _key_value_table() -> TableNode:
    return TableNode((_cell("k"),), (TableRow((_cell("v"),)),))


def _one_column_table(cells: int) -> TableNode:
    return TableNode((_cell("h"),), tuple(TableRow((_cell("v"),)) for _ in range(cells - 1)))


def _one_column_table_text(cells: int) -> str:
    return "\n".join(["| h |", "| --- |", *["| v |"] * (cells - 1)]) + "\n"


def _canvas(text: str) -> SlackCanvas:
    return SlackCanvas(text)


def test_the_example_exports_to_the_slack_golden_regenerated_by_the_export_command(tmp_path: Path) -> None:
    export_slack(load_report(EXAMPLE), tmp_path)

    assert folder_texts(tmp_path) == folder_texts(SLACK_GOLDEN)


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
    assert render_slack([Heading(level, _text("Counts"), "counts")]) == _canvas(f"{line}\n")


def test_a_paragraph_is_its_inline_text_and_drops_its_tone() -> None:
    assert render_slack([Paragraph(_text("Counted twice."), "warning")]) == _canvas("Counted twice.\n")


@pytest.mark.parametrize(
    ("node", "text"),
    [
        pytest.param(_bullets(_entry("a"), _entry("b")), "* a\n* b\n", id="bullet"),
        pytest.param(ListNode("number", (_entry("a"), _entry("b")), 3), "3. a\n4. b\n", id="number-start"),
        pytest.param(
            ListNode("check", (_entry("a"), _entry("b", checked=True))), "* [ ] a\n* [x] b\n", id="check"
        ),
        pytest.param(_bullets(ListEntry(())), "*\n", id="bare-marker"),
    ],
)
def test_a_list_writes_the_markers_slack_stores(node: ListNode, text: str) -> None:
    assert render_slack([node]) == _canvas(text)


@pytest.mark.parametrize(
    ("kind", "nested_kind", "text"),
    [
        pytest.param("bullet", "number", "* a\n  * b\n", id="number-under-bullet"),
        pytest.param("number", "bullet", "1. a\n   1. b\n", id="bullet-under-number"),
        pytest.param("check", "bullet", "* [ ] a\n  * [ ] b\n", id="bullet-under-check"),
        pytest.param("bullet", "check", "* a\n  * b\n", id="check-under-bullet"),
        pytest.param("number", "number", "1. a\n   1. b\n", id="same-kind"),
    ],
)
def test_a_nested_list_is_written_in_its_parents_kind(
    kind: ListKind, nested_kind: ListKind, text: str
) -> None:
    nested = ListNode(nested_kind, (_entry("b"),))

    assert render_slack([ListNode(kind, (_entry("a", nested),))]) == _canvas(text)


def test_a_nested_list_three_deep_indents_to_each_content_column() -> None:
    deepest = ListNode("number", (_entry("c"),))
    middle = ListNode("number", (_entry("b", deepest),))

    assert render_slack([ListNode("number", (_entry("a", middle),), 9)]) == _canvas(
        "9. a\n   1. b\n      1. c\n"
    )


def test_a_paragraph_inside_a_list_item_joins_the_item_text() -> None:
    node = _bullets(
        _entry("Drift", _para("first"), _para("second")), ListEntry((), children=(_para("alone"),))
    )

    assert render_slack([node]) == _canvas("* Drift first second\n* alone\n")


@pytest.mark.parametrize(
    ("moved", "text"),
    [
        pytest.param(CodeBlock("x", "bash"), "```bash\nx\n```", id="code"),
        pytest.param(_key_value_table(), "| k |\n| --- |\n| v |", id="table"),
        pytest.param(Quote((_text("said"),)), "> said", id="quote"),
        pytest.param(Callout("info", (_para("careful"),)), "::: {.callout}\n💡 careful\n:::", id="callout"),
        pytest.param(
            Media("image", "https://example.com/a.png", _text("a chart")),
            "![a chart](https://example.com/a.png)",
            id="media",
        ),
        pytest.param(Diagram(ONE_NODE_GRAPH), MERMAID_ONE_NODE, id="diagram"),
        pytest.param(DisplayMath("x^2"), "```latex\nx^2\n```", id="math"),
        pytest.param(Heading(2, _text("Inner")), "## Inner", id="heading"),
    ],
)
def test_a_block_a_list_item_cannot_hold_moves_after_the_whole_top_level_list(moved: Node, text: str) -> None:
    nested = _bullets(_entry("c", moved))
    nodes = [_bullets(_entry("a"), _entry("b", nested)), _para("after")]

    assert render_slack(nodes) == _canvas(f"* a\n* b\n  * c\n\n{text}\n\nafter\n")


def test_the_rest_of_a_list_item_moves_with_its_first_block_so_the_order_holds() -> None:
    entry = _entry("a", _para("lead"), CodeBlock("x"), _para("tail"), _bullets(_entry("n")))
    nodes = [ListNode("number", (entry, _entry("b"))), _para("after")]

    assert render_slack(nodes) == _canvas("1. a lead\n2. b\n\n```\nx\n```\n\ntail\n\n* n\n\nafter\n")


def test_blocks_moved_from_several_list_items_keep_their_order() -> None:
    nodes = [_bullets(_entry("a", CodeBlock("one")), _entry("b", CodeBlock("two")))]

    assert render_slack(nodes) == _canvas("* a\n* b\n\n```\none\n```\n\n```\ntwo\n```\n")


def test_a_divider_and_a_table_of_contents_inside_a_list_item_are_dropped() -> None:
    contents = TableOfContents((TocEntry("x", _text("X")),))

    assert render_slack([_bullets(_entry("a", Divider(), contents))]) == _canvas("* a\n")


def test_a_table_is_a_pipe_table_without_tones_or_widths_and_with_pipes_escaped_and_lines_joined() -> None:
    table = TableNode(
        (_cell("Item"), _cell("Note")),
        (
            TableRow(
                (TableCell(_text("a|b"), "danger"), TableCell((Plain("one"), Break(), Plain("two")))),
                "warning",
            ),
            TableRow((_cell("Total"), _cell("2")), emphasis="total"),
        ),
        columns=(TableColumn("info", 0.3), TableColumn()),
    )

    assert render_slack([table]) == _canvas(
        "| Item | Note |\n| --- | --- |\n| a\\|b | one<br>two |\n| **Total** | **2** |\n"
    )


@pytest.mark.parametrize("cells", [pytest.param(299, id="299"), pytest.param(300, id="300")])
def test_a_table_of_up_to_300_cells_header_included_is_not_reported(cells: int) -> None:
    assert render_slack([_one_column_table(cells)]) == _canvas(_one_column_table_text(cells))


def test_a_table_over_300_cells_is_written_whole_and_reported() -> None:
    assert render_slack([_one_column_table(301)]) == SlackCanvas(
        _one_column_table_text(301), (TABLE_LIMIT_MESSAGE,)
    )


def test_a_table_over_300_cells_is_reported_with_the_heading_above_it() -> None:
    nodes = [Heading(2, _text("Counts")), Callout("info", (_one_column_table(301),))]

    assert render_slack(nodes) == SlackCanvas(
        "## Counts\n\n::: {.callout}\n💡\n:::\n\n" + _one_column_table_text(301),
        (f"{TABLE_LIMIT_MESSAGE}, under the heading 'Counts'",),
    )


def test_padding_counts_toward_the_cells_of_a_table() -> None:
    table = TableNode((_cell("a"), _cell("b")), tuple(TableRow((_cell("v"),)) for _ in range(150)))

    assert render_slack([table]) == SlackCanvas(
        "| a | b |\n| --- | --- |\n" + "| v |  |\n" * 150,
        ("a table has 302 cells, over Slack's limit of 300 per canvas table",),
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
            Diagram(ONE_NODE_GRAPH, (_bullets(_entry("A", _bullets(_entry("by aisle")))),)),
            f"{MERMAID_ONE_NODE}\n\n* A\n  * by aisle\n",
            id="diagram-with-its-supplement",
        ),
    ],
)
def test_a_fenced_block_carries_its_language(node: Node, text: str) -> None:
    assert render_slack([node]) == _canvas(text)


@pytest.mark.parametrize(
    ("node", "text"),
    [
        pytest.param(
            Media("image", "https://example.com/a.png", _text("a chart"), _text("Q3 counts")),
            "![a chart](https://example.com/a.png)\n\n*Q3 counts*\n",
            id="image-with-caption",
        ),
        pytest.param(
            Media("image", "https://example.com/a b.png", _text("a chart")),
            "![a chart](https://example.com/a%20b.png)\n",
            id="image",
        ),
        pytest.param(
            Media("video", "https://example.com/v.mp4", caption=_text("Walkthrough")),
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
    assert render_slack([node]) == _canvas(text)


@pytest.mark.parametrize(
    ("node", "text"),
    [
        pytest.param(
            Callout("warning", (_para("careful"),)), "::: {.callout}\n⚠️ careful\n:::\n", id="tone-icon"
        ),
        pytest.param(
            Callout("info", (_para("north"),), "🧭"), "::: {.callout}\n🧭 north\n:::\n", id="own-icon"
        ),
        pytest.param(
            Callout("info", (_bullets(_entry("a")), _para("b"))),
            "::: {.callout}\n💡\n\n* a\n\nb\n:::\n",
            id="led-by-a-list",
        ),
        pytest.param(Callout("info", ()), "::: {.callout}\n💡\n:::\n", id="empty"),
        pytest.param(
            Callout("success", (_bullets(_entry("a", CodeBlock("x"))),)),
            "::: {.callout}\n✅\n\n* a\n\n```\nx\n```\n:::\n",
            id="list-moves-its-code-within-the-callout",
        ),
    ],
)
def test_a_callout_is_a_fenced_callout_whose_unindented_body_starts_with_its_icon(
    node: Callout, text: str
) -> None:
    assert render_slack([node]) == _canvas(text)


def test_a_table_callout_divider_or_column_layout_inside_a_callout_moves_after_it() -> None:
    columns = Columns((GridColumn(50, (_para("left"),)), GridColumn(50, (_para("right"),))))
    inner = Callout("danger", (_para("inner"),))
    node = Callout("info", (_para("lead"), _key_value_table(), inner, Divider(), columns, _para("tail")))

    assert render_slack([node]) == _canvas(
        "::: {.callout}\n💡 lead\n\ntail\n:::\n\n"
        "| k |\n| --- |\n| v |\n\n"
        "::: {.callout}\n🛑 inner\n:::\n\n"
        "---\n\n"
        "::: {.layout}\n::: {.column}\nleft\n:::\n::: {.column}\nright\n:::\n:::\n"
    )


def test_a_table_moved_out_of_a_list_in_a_callout_moves_on_after_the_callout() -> None:
    node = Callout("info", (_bullets(_entry("a", _key_value_table())),))

    assert render_slack([node]) == _canvas("::: {.callout}\n💡\n\n* a\n:::\n\n| k |\n| --- |\n| v |\n")


def test_a_callout_inside_a_callout_inside_a_callout_comes_out_flat_in_order() -> None:
    innermost = Callout("danger", (_para("c"),))
    middle = Callout("warning", (_para("b"), innermost))

    assert render_slack([Callout("info", (_para("a"), middle))]) == _canvas(
        "::: {.callout}\n💡 a\n:::\n\n::: {.callout}\n⚠️ b\n:::\n\n::: {.callout}\n🛑 c\n:::\n"
    )


def test_a_quote_is_quoted_lines_with_the_cite_on_its_own_italic_line() -> None:
    node = Quote((_text("said"), _text("# again")), _text("Ana"))

    assert render_slack([node]) == _canvas("> said\n>\n> \\# again\n>\n> *Ana*\n")


def test_a_divider_stays_at_the_top_level() -> None:
    toggle = Toggle(_text("More"), None, (Divider(),))

    assert render_slack([_para("a"), Divider(), _para("b"), toggle]) == _canvas(
        "a\n\n---\n\nb\n\n**More**\n\n---\n"
    )


@pytest.mark.parametrize(
    ("node", "text"),
    [
        pytest.param(Toggle(_text("Raw"), 2, (_para("x"),)), "## Raw\n\nx\n", id="heading-level-2"),
        pytest.param(Toggle(_text("Raw"), 5, (_para("x"),)), "### Raw\n\nx\n", id="heading-level-5-folds"),
        pytest.param(Toggle(_text("Raw"), None, (_para("x"),)), "**Raw**\n\nx\n", id="no-heading"),
        pytest.param(Toggle((), None, (_para("x"),)), "x\n", id="no-title"),
    ],
)
def test_a_toggle_is_its_heading_or_bold_title_then_its_children(node: Toggle, text: str) -> None:
    assert render_slack([node]) == _canvas(text)


def test_up_to_three_columns_are_a_column_layout_without_dividers() -> None:
    node = Columns(
        (
            GridColumn(40, (_para("left"), Divider())),
            GridColumn(30, (_bullets(_entry("a")),)),
            GridColumn(30, (Toggle(_text("T"), None, (_para("x"),)),)),
        )
    )

    assert render_slack([node]) == _canvas(
        "::: {.layout}\n"
        "::: {.column}\nleft\n:::\n"
        "::: {.column}\n* a\n:::\n"
        "::: {.column}\n**T**\n\nx\n:::\n"
        ":::\n"
    )


def test_more_than_three_columns_are_their_children_one_after_another() -> None:
    node = Columns(tuple(GridColumn(25, (_para(name), Divider())) for name in "abcd"))

    assert render_slack([node]) == _canvas("a\n\n---\n\nb\n\n---\n\nc\n\n---\n\nd\n\n---\n")


@pytest.mark.parametrize(
    ("held", "text"),
    [
        pytest.param(_key_value_table(), "| k |\n| --- |\n| v |", id="table"),
        pytest.param(Callout("info", (_para("c"),)), "::: {.callout}\n💡 c\n:::", id="callout"),
        pytest.param(
            _bullets(_entry("a", _key_value_table())), "* a\n\n| k |\n| --- |\n| v |", id="table-from-a-list"
        ),
    ],
)
def test_columns_holding_a_table_or_callout_are_their_children_one_after_another(
    held: Node, text: str
) -> None:
    node = Columns((GridColumn(50, (_para("left"),)), GridColumn(50, (held, Divider()))))

    assert render_slack([node]) == _canvas(f"left\n\n{text}\n\n---\n")


def test_columns_inside_a_column_are_their_children_one_after_another_inside_the_layout() -> None:
    inner = Columns((GridColumn(50, (_para("x"),)), GridColumn(50, (_para("y"),))))
    node = Columns((GridColumn(50, (_para("left"),)), GridColumn(50, (inner,))))

    assert render_slack([node]) == _canvas(
        "::: {.layout}\n::: {.column}\nleft\n:::\n::: {.column}\nx\n\ny\n:::\n:::\n"
    )


def test_tabs_are_bold_titles_led_by_the_tone_icon_then_their_children() -> None:
    node = Tabs(
        (
            Tab(_text("Floor"), (_para("a"),), "warning"),
            Tab(_text("System"), (_para("b"),), "accent"),
        )
    )

    assert render_slack([node]) == _canvas("**⚠️ Floor**\n\na\n\n**System**\n\nb\n")


def test_a_table_of_contents_writes_nothing() -> None:
    contents = TableOfContents((TocEntry("x", _text("X")),))

    assert render_slack([_para("a"), contents, _para("b")]) == _canvas("a\n\nb\n")


@pytest.mark.parametrize(
    ("run", "written"),
    [
        pytest.param(Styled("bold", _text("b")), "**b**", id="bold"),
        pytest.param(Styled("italic", _text("i")), "*i*", id="italic"),
        pytest.param(Styled("strike", _text("s")), "~~s~~", id="strike"),
        pytest.param(Styled("underline", _text("u")), "u", id="underline-is-plain"),
        pytest.param(Tinted("danger", "warning", _text("t")), "t", id="tint-is-plain"),
        pytest.param(ScriptText("subscript", "2"), "2", id="subscript-is-plain"),
        pytest.param(ScriptText("superscript", "*3"), "\\*3", id="superscript-is-plain-and-escaped"),
        pytest.param(Code("a`b"), "``a`b``", id="code-outgrows-its-backticks"),
        pytest.param(Chip("a*b", "blue"), "**a\\*b**", id="chip-is-bold"),
        pytest.param(StatusMark("done"), "✅", id="status-mark"),
        pytest.param(AnchorLink(_text("method"), "method"), "method", id="anchor-link-is-its-label"),
        pytest.param(
            DateMention(_text("1 Oct"), date(2026, 10, 1), None), "![](slack_date:2026-10-01)", id="date"
        ),
        pytest.param(
            DateMention(_text("1 to 3 Oct"), date(2026, 10, 1), date(2026, 10, 3)),
            "![](slack_date:2026-10-01) to ![](slack_date:2026-10-03)",
            id="date-range",
        ),
        pytest.param(PersonMention(_text("Ada"), "ada", Person()), "Ada", id="person-without-a-slack-id"),
        pytest.param(
            Link(_text("x"), "https://example.com/a b"), "[x](https://example.com/a%20b)", id="https"
        ),
        pytest.param(Link(_text("x"), "http://example.com"), "[x](http://example.com)", id="http"),
        pytest.param(Link(_text("x"), "mailto:ops@example.com"), "[x](mailto:ops@example.com)", id="mailto"),
        pytest.param(Link(_text("x"), "tel:+15550100"), "[x](tel:+15550100)", id="tel"),
        pytest.param(Link(_text("x"), "ftp://example.com/f"), "[x](ftp://example.com/f)", id="ftp"),
        pytest.param(Link(_text("x"), "slack://open"), "[x](slack://open)", id="slack"),
        pytest.param(Link(_text("x"), "docs/plan.md"), "[x](docs/plan.md)", id="relative-path"),
        pytest.param(Link(_text("x"), "#top"), "x", id="fragment-only-is-its-label"),
        pytest.param(Link(_text("x"), "javascript:void(0)"), "x", id="other-scheme-is-its-label"),
        pytest.param(Link(_text("x"), "FILE:///tmp/a"), "x", id="scheme-case-ignored"),
        pytest.param(InlineMath("x_i"), "`x_i`", id="inline-math-is-code"),
        pytest.param(
            DocumentLink(_text("the plan"), "plan", None), "the plan", id="document-link-is-its-label"
        ),
        pytest.param(
            IssueLink(_text("ABC-1"), "ABC-1", "https://example.atlassian.net/browse/ABC-1"),
            "[ABC-1](https://example.atlassian.net/browse/ABC-1)",
            id="issue-link",
        ),
        pytest.param(
            Citation("a", 1, "https://example.com"), "[\\[1\\]](https://example.com)", id="citation"
        ),
        pytest.param(Citation("a", 1, "javascript:void(0)"), "\\[1\\]", id="citation-to-another-scheme"),
        pytest.param(Placeholder("owner"), "`{{owner}}`", id="placeholder"),
    ],
)
def test_an_inline_run_becomes_canvas_markdown(run: ExportRun, written: str) -> None:
    assert render_slack([Paragraph((run,))]) == _canvas(f"{written}\n")


@pytest.mark.parametrize(
    ("runs", "written"),
    [
        pytest.param(
            (Styled("bold", _text("(x)")), Plain("y")), "(x)y", id="bold-followed-by-a-word-character"
        ),
        pytest.param(
            (Plain("a"), Styled("italic", _text("(b)")), Plain(".")),
            "a(b).",
            id="italic-between-a-letter-and-punctuation",
        ),
        pytest.param(
            (Styled("bold", _text("a")), Styled("italic", _text("b"))),
            "**a**b",
            id="italic-running-into-a-bold-closer",
        ),
        pytest.param((Styled("strike", _text("(s)")), Plain("t")), "(s)t", id="strike-followed-by-a-letter"),
    ],
)
def test_emphasis_whose_markers_a_canvas_cannot_read_drops_its_style_and_never_becomes_a_tag(
    runs: tuple[ExportRun, ...], written: str
) -> None:
    assert render_slack([Paragraph(runs)]) == _canvas(f"{written}\n")


def test_canvas_special_characters_are_escaped_in_text_but_not_dollars() -> None:
    nodes = [Paragraph(_text("a*b_c~d`e|f [x] <@U0EXAMPLE1> $5 &amp; done!"))]

    assert render_slack(nodes) == _canvas(
        "a\\*b\\_c\\~d\\`e|f \\[x\\] \\<@U0EXAMPLE1\\> $5 \\&amp; done\\!\n"
    )


def test_canvas_special_characters_and_pipes_are_escaped_in_a_table_cell() -> None:
    table = TableNode((_cell("a*b_c~d`e|f"),), (TableRow((TableCell((Code("x|y"),)),)),))

    assert render_slack([table]) == _canvas("| a\\*b\\_c\\~d\\`e\\|f |\n| --- |\n| `x\\|y` |\n")


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
    assert render_slack([_para(text)]) == _canvas(f"{line}\n")


def test_a_list_item_that_starts_like_a_callout_fence_stays_text() -> None:
    assert render_slack([_bullets(_entry(":::"))]) == _canvas("* \\:::\n")


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


@pytest.mark.parametrize(
    ("code_length", "reported"),
    [
        pytest.param(CANVAS_LIMIT_CODE_LENGTH, (), id="at-the-limit"),
        pytest.param(
            CANVAS_LIMIT_CODE_LENGTH + 1,
            ("the canvas Markdown is 1,048,577 characters, over Slack's limit of 1,048,576",),
            id="over-the-limit",
        ),
    ],
)
def test_canvas_markdown_over_one_mebibyte_is_written_and_reported(
    tmp_path: Path, code_length: int, reported: tuple[str, ...]
) -> None:
    blocks = [{"type": "code", "content": "x" * code_length}]
    report = load_report(write_report(tmp_path, make_report(blocks=blocks)))
    out_dir = tmp_path / "out"

    result = export_slack(report, out_dir)

    assert (result, (out_dir / "page.md").read_text(encoding="utf-8")) == (
        ExportResult("Test Report", (out_dir / "page.md",), reported),
        "```\n" + "x" * code_length + "\n```\n",
    )


def test_the_cli_exports_slack_and_writes_the_manifest_whose_title_names_the_canvas(
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


def test_the_cli_warns_about_a_table_over_the_canvas_limit_and_still_writes_the_page(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    table = {"type": "table", "columns": [{"key": "item", "label": "Item"}], "rows": [["v"]] * 300}
    blocks = [{"type": "heading", "text": "Counts"}, table]
    data_path = write_report(tmp_path, make_report(blocks=blocks))
    export_dir = tmp_path / "exported"

    assert main([str(data_path), "--export", "slack", "--export-dir", str(export_dir)]) == 0

    captured = capsys.readouterr()
    assert (captured.err, captured.out, (export_dir / "page.md").is_file()) == (
        f"warning: {TABLE_LIMIT_MESSAGE}, under the heading 'Counts'\n",
        f"OK  {export_dir / 'page.md'}\n",
        True,
    )
