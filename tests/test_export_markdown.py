from pathlib import Path
from typing import get_args

import pytest

from skaldr.export import ExportResult, export_markdown
from skaldr.export.markdown import github_heading_slugs, github_slug, render_markdown
from skaldr.export.markup import CALLOUT_ICON, code_block_lines, code_span, gauge_bar, styled
from skaldr.export.runs import (
    Break,
    CheckMark,
    Chip,
    DecisionMark,
    ExportRich,
    ExportRun,
    Gauge,
    IndicatorMark,
    StatusMark,
    SwimlaneMark,
    export_visible_text,
)
from skaldr.export.tree import (
    Callout,
    CodeBlock,
    Diagram,
    Graph,
    GraphNode,
    Heading,
    ListEntry,
    ListKind,
    ListNode,
    Node,
    Paragraph,
    Quote,
    Tab,
    TableCell,
    TableNode,
    TableOfContents,
    TableRow,
    Tabs,
    TocEntry,
    Toggle,
    ToneName,
)
from skaldr.models import load_report, parse_report
from skaldr.richtext import AnchorLink, Citation, Link, Placeholder, Plain, Run, Styled, parse_rich
from tests.conftest import REPO_ROOT
from tests.factories import (
    API_BADGES,
    BADGE_AND_STATE_BLOCKS,
    folder_texts,
    make_command_request,
    make_report,
    make_toggle,
    markdown_of,
)

EXAMPLE = REPO_ROOT / "data" / "example.yaml"
MARKDOWN_GOLDEN = REPO_ROOT / "tests" / "golden" / "example.markdown"


def test_the_example_exports_to_the_markdown_golden_regenerated_by_the_export_command(tmp_path: Path) -> None:
    export_markdown(load_report(EXAMPLE), tmp_path)

    assert folder_texts(tmp_path) == folder_texts(MARKDOWN_GOLDEN)


def test_a_request_with_several_cases_lists_each_case_under_a_bold_title() -> None:
    cases = [
        {"label": "finding", "tone": "warning", "response": {"body": "[]"}},
        {"label": "control", "tone": "success", "response": {"body": "none"}},
    ]
    request = make_command_request(cases=cases, command="list-tiers")

    assert markdown_of([request]) == (
        "**Tier mappings on the partner API**\n\n"
        "**⚠️ finding**\n\n```bash\nlist-tiers\n```\n\n**Recorded output**\n\n```json\n[]\n```\n\n"
        "**✅ control**\n\n```bash\nlist-tiers\n```\n\n**Recorded output**\n\n```\nnone\n```\n"
    )


@pytest.mark.parametrize(
    ("tone", "title"),
    [
        pytest.param("success", "**✅ t**", id="success"),
        pytest.param("info", "**💡 t**", id="info-matches-its-callout"),
        pytest.param("warning", "**⚠️ t**", id="warning"),
        pytest.param("danger", "**🛑 t**", id="danger"),
        pytest.param("neutral", "**t**", id="neutral-has-no-icon"),
        pytest.param(None, "**t**", id="no-tone"),
    ],
)
def test_a_tab_title_carries_the_icon_of_its_case_tone(tone: ToneName | None, title: str) -> None:
    assert (
        render_markdown([Tabs((Tab((Plain("t"),), (Paragraph((Plain("z"),)),), tone),))]) == f"{title}\n\nz\n"
    )


def test_a_flow_keeps_its_mermaid_and_the_detail_mermaid_cannot_show() -> None:
    flow = {
        "type": "flow",
        "numbered": False,
        "steps": [{"label": "Scan", "points": ["by aisle"]}, {"label": "Fix"}],
    }

    assert markdown_of([flow]) == (
        "```mermaid\n"
        "flowchart LR\n"
        '    s1["Scan"]\n'
        '    s2["Fix"]\n'
        "    s1 --> s2\n"
        "```\n"
        "\n"
        "- **Scan**\n"
        "  - by aisle\n"
    )


def test_a_diagram_with_nothing_beside_it_is_its_fence_alone() -> None:
    diagram = Diagram(Graph("LR", (GraphNode("s1", "A"),), ()))

    assert render_markdown([diagram, Paragraph((Plain("after"),))]) == (
        '```mermaid\nflowchart LR\n    s1["A"]\n```\n\nafter\n'
    )


def test_the_page_starts_with_the_title_as_its_only_top_level_heading(tmp_path: Path) -> None:
    report = parse_report(make_report(meta={"title": "Q3 *count*"}))

    result = export_markdown(report, tmp_path)

    assert result == ExportResult("Q3 *count*", (tmp_path / "page.md",))
    assert (tmp_path / "page.md").read_text(encoding="utf-8") == "# Q3 \\*count\\*\n\nHello.\n"


def test_markdown_special_characters_are_escaped_in_text_but_not_in_code_or_link_urls() -> None:
    text = r"a *b* c_d [x] <y> ~n c:\d AT&T &amp; and `a*b [c]` via [x_y](https://example.com/a_b?q=[1])"

    assert render_markdown([Paragraph(parse_rich(text))]) == (
        r"a *b* c\_d \[x\] \<y\> \~n c:\\d AT&T \&amp; and `a*b [c]` via [x\_y](https://example.com/a_b?q=[1])"
        "\n"
    )


@pytest.mark.parametrize(
    ("run", "written"),
    [
        pytest.param(
            Citation("a", 1, "https://example.com/a b"),
            r"[\[1\]](https://example.com/a%20b)",
            id="citation-with-url",
        ),
        pytest.param(Citation("b", 2), r"\[2\]", id="citation-without-url"),
        pytest.param(Placeholder("owner"), "`{{owner}}`", id="placeholder"),
        pytest.param(Styled("strike", (Plain("old"),)), "~~old~~", id="strike"),
        pytest.param(
            Link((Plain("paren"),), "https://example.com/(x)>"),
            "[paren](https://example.com/%28x%29%3E)",
            id="link-with-parens",
        ),
        pytest.param(AnchorLink((Plain("method"),), "method"), "[method](#how-we-count)", id="anchor-link"),
        pytest.param(AnchorLink((Plain("gone"),), "nowhere"), "gone", id="anchor-link-to-no-heading"),
        pytest.param(StatusMark("done"), "✅", id="status-mark"),
        pytest.param(SwimlaneMark("deferred"), "⏸️", id="swimlane-mark"),
        pytest.param(IndicatorMark("warning"), "🟡", id="indicator-mark"),
        pytest.param(CheckMark(checked=False), "✗", id="check-mark"),
        pytest.param(Break(), "<br>", id="line-break"),
        pytest.param(Gauge(10, 10), "██████████", id="full-gauge"),
        pytest.param(Chip("a*b_c", "blue"), r"**a\*b\_c**", id="chip-label-is-escaped"),
    ],
)
def test_an_inline_run_becomes_markdown(run: ExportRun, written: str) -> None:
    nodes = [Heading(2, (Plain("How we count"),), "method"), Paragraph((run,))]

    assert render_markdown(nodes) == f"## How we count\n\n{written}\n"


@pytest.mark.parametrize(
    ("target", "written"),
    [
        pytest.param(Link((Plain("x"),), "https://e.com"), "[x](https://e.com)", id="link"),
        pytest.param(AnchorLink((Plain("x"),), "method"), "[x](#m)", id="anchor-link"),
        pytest.param(Citation("a", 1, "https://e.com"), r"[\[1\]](https://e.com)", id="citation"),
    ],
)
def test_a_bang_right_before_anything_written_as_a_link_is_escaped_so_it_is_not_an_image(
    target: Run, written: str
) -> None:
    nodes = [Heading(2, (Plain("M"),), "method"), Paragraph((Plain("wow!"), target))]

    assert render_markdown(nodes) == f"## M\n\nwow\\!{written}\n"


def test_a_bang_ending_text_is_escaped_even_with_nothing_after_it() -> None:
    assert markdown_of([{"type": "text", "body": "Done!"}]) == "Done\\!\n"


def test_a_backslash_in_a_link_target_stays_a_backslash_like_the_html_href() -> None:
    assert render_markdown([Paragraph((Link((Plain("x"),), "https://e.com/a\\b"),))]) == (
        "[x](https://e.com/a\\\\b)\n"
    )


@pytest.mark.parametrize(
    ("url", "written"),
    [
        pytest.param("https://e.com/a?q=1#top", "https://e.com/a?q=1#top", id="plain-url"),
        pytest.param("https://e.com/a\n\n# Injected", "https://e.com/a%0A%0A#%20Injected", id="line-breaks"),
        pytest.param("https://e.com/\ta\r<b>", "https://e.com/%09a%0D%3Cb%3E", id="tab-cr-and-angles"),
    ],
)
def test_a_reference_url_is_percent_encoded_in_its_citation_and_its_source_link(
    url: str, written: str
) -> None:
    references = {
        "type": "references",
        "items": [{"key": "a", "text": "SOP", "url": url}, {"key": "b", "text": "Memo"}],
    }

    assert markdown_of([{"type": "text", "body": "see [^a] [^b]"}, references]) == (
        f"see [\\[1\\]]({written}) \\[2\\]\n\n- \\[1\\] SOP [source]({written})\n- \\[2\\] Memo\n"
    )


def test_a_dollar_sign_is_escaped_so_github_does_not_render_math() -> None:
    assert markdown_of([{"type": "text", "body": "costs $5 and $x$"}]) == "costs \\$5 and \\$x\\$\n"


def test_emphasis_at_the_start_of_a_line_keeps_its_markers() -> None:
    assert markdown_of([{"type": "text", "body": "**- not a list** and *+ more*"}]) == (
        "**- not a list** and *+ more*\n"
    )


@pytest.mark.parametrize(
    ("text", "span"),
    [
        pytest.param("plain", "`plain`", id="no-backtick"),
        pytest.param("a`b", "``a`b``", id="inner-backtick"),
        pytest.param("`edge", "`` `edge ``", id="leading-backtick"),
        pytest.param(" a ", "`  a  `", id="a-space-at-both-ends"),
        pytest.param(" a", "` a`", id="a-space-at-one-end"),
        pytest.param("  ", "`  `", id="only-spaces"),
    ],
)
def test_a_code_span_outgrows_the_backticks_it_contains(text: str, span: str) -> None:
    assert code_span(text) == span


@pytest.mark.parametrize(
    ("content", "fence"),
    [
        pytest.param("x", "```", id="no-backticks"),
        pytest.param("```\ny\n```", "````", id="contains-a-fence"),
        pytest.param("`````", "``````", id="contains-five"),
    ],
)
def test_a_code_block_fence_outgrows_any_run_of_backticks_inside(content: str, fence: str) -> None:
    assert code_block_lines(CodeBlock(content, "md")) == [f"{fence}md", *content.split("\n"), fence]


@pytest.mark.parametrize(
    ("value", "maximum", "bar"),
    [
        pytest.param(5, 10, "█████░░░░░", id="half"),
        pytest.param(0, 10, "░░░░░░░░░░", id="empty"),
        pytest.param(12, 10, "██████████", id="over-the-maximum-stays-full"),
        pytest.param(-1, 10, "░░░░░░░░░░", id="below-zero-stays-empty"),
        pytest.param(1, 4, "███░░░░░░░", id="two-and-a-half-cells-fill-three"),
        pytest.param(3, 4, "████████░░", id="seven-and-a-half-cells-fill-eight"),
        pytest.param(5, 100, "█░░░░░░░░░", id="a-half-cell-fills-one-so-a-small-share-shows"),
    ],
)
def test_a_gauge_is_ten_cells_filled_in_proportion(value: float, maximum: float, bar: str) -> None:
    assert gauge_bar(value, maximum) == bar


def test_visible_text_of_export_runs_reads_chips_and_states_as_words() -> None:
    runs: ExportRich = (Chip("api", "blue"), Plain(" "), StatusMark("done"), Gauge(1, 2))

    assert export_visible_text(runs) == "api done"


def test_visible_text_reads_a_line_break_as_a_space_and_every_mark_kind_as_its_word() -> None:
    runs: ExportRich = (
        SwimlaneMark("todo"),
        Break(),
        IndicatorMark("info"),
        Plain(" "),
        CheckMark(checked=True),
        Plain(" "),
        CheckMark(checked=False),
        Plain(" "),
        DecisionMark(decided=True),
        Plain(" "),
        DecisionMark(decided=False),
    )

    assert export_visible_text(runs) == "todo info yes no decided open"


def test_a_total_row_of_plain_cells_is_written_bold() -> None:
    table = TableNode(
        (TableCell((Plain("Issue"),)), TableCell((Plain("Units"),))),
        (
            TableRow((TableCell((Plain("x"),)), TableCell((Plain("2"),)))),
            TableRow((TableCell((Plain("Total"),)), TableCell((Plain("2"),))), emphasis="total"),
        ),
    )

    assert render_markdown([table]) == "| Issue | Units |\n| --- | --- |\n| x | 2 |\n| **Total** | **2** |\n"


def test_styled_text_keeps_surrounding_spaces_outside_its_markers() -> None:
    assert (styled("bold", " x "), styled("italic", "  "), styled("bold", "")) == (" **x** ", "  ", "")


def test_a_table_is_a_pipe_table_with_pipes_escaped_in_text_and_code() -> None:
    table = {
        "type": "table",
        "columns": [{"key": "a", "label": "Name"}, {"key": "n", "label": "Units", "kind": "number"}],
        "rows": [{"a": "a|b and `x|y`", "n": 2}, {"a": "two\n\nlines", "n": 3}],
        "totals": {"column": "n"},
    }

    assert markdown_of([table]) == (
        "| Name | Units |\n"
        "| --- | --- |\n"
        "| a\\|b and `x\\|y` | 2 |\n"
        "| two<br>lines | 3 |\n"
        "| **Total** | **5** |\n"
    )


def test_a_table_pads_short_rows_and_drops_tones_markdown_cannot_show() -> None:
    table = TableNode(
        (TableCell((Plain("A"),)), TableCell((Plain("B"),))),
        (
            TableRow((TableCell((Plain("group"),)),), emphasis="group"),
            TableRow((TableCell((Plain("x"),), "danger"), TableCell((Plain("y"),))), "sky"),
        ),
        header_column=True,
    )

    assert render_markdown([table]) == "| A | B |\n| --- | --- |\n| **group** |  |\n| **x** | y |\n"


def test_a_table_drops_column_tones_and_widths_markdown_cannot_show() -> None:
    table = {
        "type": "table",
        "columns": [
            {"key": "a", "label": "A", "width": 1},
            {"key": "b", "label": "B", "tone": "info", "width": 3},
        ],
        "rows": [{"a": "x", "b": "y"}],
    }

    assert markdown_of([table]) == "| A | B |\n| --- | --- |\n| x | y |\n"


def test_a_comparison_bolds_its_feature_column_and_leaves_the_header_to_the_pipe_table() -> None:
    comparison = {
        "type": "comparison",
        "options": ["A", "B"],
        "highlight": 1,
        "rows": [{"feature": "Risky", "values": [True, False]}],
    }

    assert markdown_of([comparison]) == "|  | A | ★ B |\n| --- | --- | --- |\n| **Risky** | ✓ | ✗ |\n"


def test_a_swimlane_bolds_each_lane_cell_as_a_whole_and_leaves_the_header_to_the_pipe_table() -> None:
    swimlane = {
        "type": "swimlane",
        "lanes": ["Ops"],
        "columns": [{"name": "Plan", "sub": "wk 1"}],
        "steps": [{"lane": "Ops", "col": "Plan", "n": "1", "label": "Draft", "value": 2}],
    }

    assert markdown_of([swimlane]) == (
        "| Lane | Plan<br>*wk 1* |\n"
        "| --- | --- |\n"
        "| **Ops (2)** | ⚪ **1** Draft (2) |\n"
        "| **Total** | **2** |\n"
    )


def test_a_grid_becomes_its_cells_in_order() -> None:
    grid = {
        "type": "grid",
        "cells": [
            {"span": 2, "blocks": [{"type": "text", "body": "a"}]},
            {"span": 4, "blocks": [{"type": "text", "body": "b"}]},
        ],
    }

    assert markdown_of([grid]) == "a\n\nb\n"


@pytest.mark.parametrize(
    ("body", "line"),
    [
        pytest.param("- not a list", "\\- not a list", id="dash"),
        pytest.param("+ not a list", "\\+ not a list", id="plus"),
        pytest.param("1. not a list", "1\\. not a list", id="ordered-dot"),
        pytest.param("2) not a list", "2\\) not a list", id="ordered-paren"),
        pytest.param("# not a heading", "\\# not a heading", id="hash"),
        pytest.param("--- not a rule", "\\--- not a rule", id="rule"),
        pytest.param("=== not an underline", "\\=== not an underline", id="setext"),
        pytest.param("-5 degrees", "-5 degrees", id="negative-number"),
        pytest.param("> not a quote", "\\> not a quote", id="quote"),
        pytest.param("####### x", "####### x", id="seven-hashes-are-no-heading"),
        pytest.param("+++", "\\+++", id="plus-run"),
        pytest.param("1234567890. x", "1234567890. x", id="ten-digit-ordinal-is-no-list"),
    ],
)
def test_a_paragraph_that_starts_like_a_block_marker_stays_a_paragraph(body: str, line: str) -> None:
    assert markdown_of([{"type": "text", "body": body}]) == f"{line}\n"


def test_quote_lines_escape_a_leading_block_marker() -> None:
    quote = {"type": "quote", "body": "# quoted heading\n\n- quoted bullet"}

    assert markdown_of([quote]) == "> \\# quoted heading\n>\n> \\- quoted bullet\n"


@pytest.mark.parametrize(
    ("text", "line"),
    [
        pytest.param("Issue #", "## Issue \\#", id="trailing-hash"),
        pytest.param("###", "## \\###", id="only-hashes"),
    ],
)
def test_a_heading_ending_in_hashes_keeps_them(text: str, line: str) -> None:
    assert markdown_of([{"type": "heading", "text": text}]) == f"{line}\n"


def test_nested_list_children_indent_to_the_content_column_of_their_marker() -> None:
    block = {
        "type": "list",
        "style": "number",
        "items": [{"text": "parent", "items": ["child", {"text": "mid", "items": ["leaf"]}]}],
    }

    assert markdown_of([block]) == "1. parent\n   1. child\n   2. mid\n      1. leaf\n"


def test_a_two_digit_ordinal_indents_its_children_one_column_further() -> None:
    block = {"type": "list", "style": "number", "items": [*"abcdefghi", {"text": "j", "items": ["child"]}]}

    assert markdown_of([block]) == (
        "1. a\n2. b\n3. c\n4. d\n5. e\n6. f\n7. g\n8. h\n9. i\n10. j\n    1. child\n"
    )


def test_an_alternate_ordinal_marker_indents_its_children_to_its_content() -> None:
    blocks = [
        {"type": "list", "style": "number", "items": ["a"]},
        {"type": "list", "style": "number", "items": [{"text": "b", "items": ["child"]}]},
    ]

    assert markdown_of(blocks) == "1. a\n\n1) b\n   1. child\n"


def test_a_walkthrough_step_with_no_sub_is_its_bold_label_over_its_detail() -> None:
    walkthrough = {
        "type": "walkthrough",
        "steps": [{"label": "Go", "detail": [{"type": "text", "body": "d"}]}],
    }

    assert markdown_of([walkthrough]) == "1. **Go**\n\n   d\n"


def test_a_check_list_becomes_a_task_list() -> None:
    block = {"type": "list", "style": "check", "items": [{"text": "done", "checked": True}, "open"]}

    assert markdown_of([block]) == "- [x] done\n- [ ] open\n"


@pytest.mark.parametrize(
    ("options", "markdown"),
    [
        pytest.param(
            {"start": 9}, "9. c\n10. d\n    1. e\n", id="start-counts-on-and-a-nested-list-from-one"
        ),
        pytest.param({"numbering": "decimal"}, "1. c\n2. d\n   1. e\n", id="decimal-is-native"),
        pytest.param(
            {"numbering": "letters"}, "- a. c\n- b. d\n  - a. e\n", id="letters-are-bullets-led-by-the-letter"
        ),
        pytest.param(
            {"start": 4, "numbering": "roman"},
            "- iv. c\n- v. d\n  - i. e\n",
            id="roman-is-bullets-led-by-the-numeral-from-the-start",
        ),
    ],
)
def test_a_numbered_list_keeps_its_start_and_its_numbering(options: dict[str, object], markdown: str) -> None:
    block = {"type": "list", "style": "number", "items": ["c", {"text": "d", "items": ["e"]}], **options}

    assert markdown_of([block]) == markdown


def test_a_decision_list_is_a_bullet_list_led_by_decided_and_open_glyphs() -> None:
    block = {"type": "list", "style": "decision", "items": ["open", {"text": "done", "decided": True}]}

    assert markdown_of([block]) == "- ❓ open\n- ☑️ done\n"


def test_a_nested_decision_list_marks_every_level_and_reads_apart_from_a_check_list() -> None:
    blocks = [
        {
            "type": "list",
            "style": "decision",
            "items": [
                {"text": "region", "decided": True, "items": ["failover", {"text": "zone", "decided": True}]}
            ],
        },
        {"type": "list", "style": "check", "items": [{"text": "shipped", "checked": True}, "tested"]},
        {"type": "status_list", "items": [{"state": "done", "text": "rolled out"}]},
    ]

    assert markdown_of(blocks) == (
        "- ☑️ region\n  - ❓ failover\n  - ☑️ zone\n\n* [x] shipped\n* [ ] tested\n\n- ✅ rolled out\n"
    )


def test_a_nested_check_list_indents_under_the_dash_not_the_box() -> None:
    block = {"type": "list", "style": "check", "items": [{"text": "parent", "items": ["child"]}]}

    assert markdown_of([block]) == "- [ ] parent\n  - [ ] child\n"


def test_a_list_entry_with_no_text_is_a_bare_marker() -> None:
    assert render_markdown([ListNode("bullet", (ListEntry(()),))]) == "-\n"


def test_an_empty_string_list_item_exports_as_a_bare_marker() -> None:
    block = {"type": "list", "items": ["", "two"]}

    assert markdown_of([block]) == "-\n- two\n"


@pytest.mark.parametrize(
    ("kind", "markdown"),
    [
        pytest.param("bullet", "-\n  detail\n", id="bullet"),
        pytest.param("number", "1.\n   detail\n", id="number"),
    ],
)
def test_a_bare_marker_keeps_its_children_inside_the_item(kind: ListKind, markdown: str) -> None:
    entry = ListEntry((), children=(Paragraph((Plain("detail"),)),))

    assert render_markdown([ListNode(kind, (entry,))]) == markdown


def test_a_section_title_ending_in_a_newline_links_to_its_heading() -> None:
    section = {
        "type": "section",
        "title": "Appendix\n",
        "blocks": [{"type": "text", "body": "[x](#appendix)"}],
    }

    assert markdown_of([section], meta={"title": "T", "toc": True}) == (
        "- [Appendix](#appendix)\n\n## Appendix\n\n[x](#appendix)\n"
    )


def test_a_subtitle_led_by_spaces_and_a_dash_stays_a_paragraph() -> None:
    assert markdown_of([{"type": "text", "body": "b"}], meta={"title": "T", "subtitle": ["  - draft"]}) == (
        "\\- draft\n\nb\n"
    )


def test_every_tone_has_a_callout_icon() -> None:
    assert sorted(CALLOUT_ICON) == sorted(get_args(ToneName))


def test_a_callout_led_by_a_list_puts_its_icon_on_a_line_of_its_own() -> None:
    callout = Callout("info", (ListNode("bullet", (ListEntry((Plain("a"),)),)),))

    assert render_markdown([callout]) == "> 💡\n>\n> - a\n"


def test_a_table_of_contents_entry_with_no_heading_is_its_title_alone() -> None:
    assert render_markdown([TableOfContents((TocEntry("gone", (Plain("Gone"),)),))]) == "- Gone\n"


def test_back_to_back_lists_switch_markers_so_they_stay_separate_lists() -> None:
    blocks = [
        {"type": "list", "items": ["a"]},
        {"type": "list", "items": ["b"]},
        {"type": "list", "style": "check", "items": ["c"]},
        {"type": "list", "style": "number", "items": ["d"]},
        {"type": "list", "style": "number", "items": ["e"]},
    ]

    assert markdown_of(blocks) == "- a\n\n* b\n\n- [ ] c\n\n1. d\n\n1) e\n"


@pytest.mark.parametrize(
    ("node", "markdown"),
    [
        pytest.param(Callout("info", (ListNode("bullet", ()),)), "> 💡\n", id="callout-with-nothing-to-say"),
        pytest.param(
            Callout("warning", (Paragraph((Plain("careful"),)),)), "> ⚠️ careful\n", id="callout-paragraph"
        ),
        pytest.param(Quote(((Plain("said"),),)), "> said\n", id="quote"),
        pytest.param(
            Toggle((Plain("Legend"),), None, (Paragraph((Plain("x"),)),)),
            "**Legend**\n\nx\n",
            id="toggle-without-heading",
        ),
        pytest.param(
            ListNode("bullet", (ListEntry((Plain("card"),), children=(Paragraph((Plain("note"),)),)),)),
            "- card\n\n  note\n",
            id="list-entry-with-a-paragraph",
        ),
    ],
)
def test_a_block_node_becomes_a_markdown_block(node: Node, markdown: str) -> None:
    assert render_markdown([node]) == markdown


def test_a_toggle_is_its_bold_title_over_its_content() -> None:
    toggle = {
        "type": "toggle",
        "title": "Raw counts",
        "blocks": [
            {"type": "text", "body": "x"},
            {"type": "toggle", "title": "Inner", "blocks": [{"type": "text", "body": "y"}]},
        ],
    }

    assert markdown_of([toggle]) == "**Raw counts**\n\nx\n\n**Inner**\n\ny\n"


def test_an_open_toggle_is_its_bold_title_over_its_content() -> None:
    toggle = make_toggle({"type": "text", "body": "x"}, title="Raw counts", collapsed=False)

    assert markdown_of([toggle]) == "**Raw counts**\n\nx\n"


def _authored_tabs() -> dict[str, object]:
    return {
        "type": "tabs",
        "tabs": [
            {"label": "Floor", "tone": "warning", "blocks": [{"type": "text", "body": "a"}]},
            {"label": "System", "tone": "accent", "blocks": [{"type": "text", "body": "b"}]},
            {"label": "Vendor", "blocks": [{"type": "text", "body": "c"}]},
        ],
    }


def test_authored_tabs_are_bold_titled_parts_led_by_the_icon_a_request_case_tone_gets() -> None:
    assert markdown_of([_authored_tabs()]) == "**⚠️ Floor**\n\na\n\n**System**\n\nb\n\n**Vendor**\n\nc\n"


def test_a_level_four_heading_is_four_hashes_and_a_link_reaches_its_github_slug() -> None:
    blocks = [
        {"type": "heading", "level": 4, "text": "Bin detail", "id": "bins"},
        {"type": "text", "body": "See [bins](#bins)."},
    ]

    assert markdown_of(blocks) == "#### Bin detail\n\nSee [bins](#bin-detail).\n"


def test_level_three_and_four_headings_inside_a_section_stay_one_level_apart() -> None:
    section = {
        "type": "section",
        "title": "Appendix",
        "collapsed": False,
        "blocks": [
            {"type": "heading", "level": 3, "text": "Zone C"},
            {"type": "heading", "level": 4, "text": "Bin 12"},
        ],
    }

    assert markdown_of([section]) == "## Appendix\n\n#### Zone C\n\n##### Bin 12\n"


def test_a_divider_stands_apart_from_the_paragraph_above_so_it_is_never_a_setext_underline() -> None:
    blocks = [{"type": "text", "body": "Above"}, {"type": "divider"}, {"type": "text", "body": "Below"}]

    assert markdown_of(blocks) == "Above\n\n---\n\nBelow\n"


def test_a_divider_in_a_walkthrough_step_stands_apart_inside_the_list_entry() -> None:
    walkthrough = {
        "type": "walkthrough",
        "steps": [{"label": "Go", "detail": [{"type": "text", "body": "a"}, {"type": "divider"}]}],
    }

    assert markdown_of([walkthrough]) == "1. **Go**\n\n   a\n\n   ---\n"


def test_a_callout_is_a_blockquote_led_by_its_icon_and_bold_title() -> None:
    callout = {"type": "callout", "tone": "warning", "title": "Heads up", "body": "one\n\ntwo"}

    assert markdown_of([callout]) == "> ⚠️ **Heads up**\n>\n> one\n>\n> two\n"


def test_a_callout_and_a_note_icon_take_the_place_of_the_tone_icon() -> None:
    blocks = [
        {"type": "callout", "tone": "warning", "icon": "🚧", "title": "Heads up", "body": "one"},
        {"type": "note", "icon": "📌", "body": "aside"},
    ]

    assert markdown_of(blocks) == "> 🚧 **Heads up**\n>\n> one\n\n> 📌 aside\n"


def test_an_icon_leads_a_callout_whose_first_block_is_a_list_on_a_line_of_its_own() -> None:
    callout = Callout("info", (ListNode("bullet", (ListEntry((Plain("a"),)),)),), icon="🚀")

    assert render_markdown([callout]) == "> 🚀\n>\n> - a\n"


def test_a_quote_keeps_its_paragraphs_and_italic_cite() -> None:
    quote = {"type": "quote", "body": "first\n\nsecond", "cite": "Ops lead"}

    assert markdown_of([quote]) == "> first\n>\n> second\n>\n> *Ops lead*\n"


def test_a_collapsed_section_becomes_a_heading_with_its_content_below() -> None:
    section = {
        "type": "section",
        "title": "Appendix",
        "blocks": [{"type": "heading", "text": "Raw"}, {"type": "text", "body": "t"}],
    }

    assert markdown_of([section]) == "## Appendix\n\n### Raw\n\nt\n"


def test_the_badge_legend_is_a_bold_title_over_its_list() -> None:
    row = {"type": "badge_row", "items": [{"key": "API"}]}

    assert (
        markdown_of([row], badges=API_BADGES)
        == "**Legend: badges used on this page**\n\n- **api** the API\n\n**api**\n"
    )


def test_every_badge_and_state_block_becomes_github_markdown() -> None:
    assert markdown_of(BADGE_AND_STATE_BLOCKS, badges=API_BADGES) == (
        "**Legend: badges used on this page**\n\n- **api** the API\n\n"
        "- **Site**: West\n- **Owner**: ops\n\n"
        "* **Lead**: **Ana**\n\n"
        "- **Drift**: first\n\n  second\n- **Gap**\n\n"
        "* **Clean**: 9 (90.0%) **▲ +1** **api**\n\n  since Monday\n* **Lag**: 3 days → flat\n\n"
        "**Affects**: **api** **ops**\n\n"
        "- **Owners**: **web**\n\n"
        "* ✅ Ship\n* ⛔ Vendor\n\n"
        "- 🔵 **Mon**: Start **api**\n\n  kick-off\n- Later\n\n"
        "* **Zone**: ████░░░░░░ 42.9%\n\n"
        "Jan to Dec\n\n"
        "- **Q1**: 25.0%, slow\n- **Rest**: 75.0%\n"
    )


def test_a_badge_is_a_bold_label_and_a_label_colon_is_not_doubled() -> None:
    row = {"type": "badge_row", "label": "Affects:", "items": [{"label": "api", "tone": "blue"}]}

    assert markdown_of([row]) == "**Affects**: **api**\n"


@pytest.mark.parametrize(
    ("heading", "slug"),
    [
        pytest.param("Count pipeline", "count-pipeline", id="spaces"),
        pytest.param("Q2: the audit (final)", "q2-the-audit-final", id="punctuation"),
        pytest.param("A & B", "a--b", id="dropped-symbol-keeps-both-spaces"),
        pytest.param("snake_case-name", "snake_case-name", id="underscore-and-hyphen"),
        pytest.param("Café Ünï", "café-ünï", id="unicode-letters-stay"),
        pytest.param("Ship it 🚀", "ship-it-", id="emoji-dropped"),
        pytest.param("नमस्ते दुनिया", "नमस्ते-दुनिया", id="combining-marks-stay"),
        pytest.param("Café", "café", id="decomposed-accent-stays"),
        pytest.param("x² ½", "x²-½", id="other-numbers-stay"),
    ],
)
def test_a_heading_slug_follows_github(heading: str, slug: str) -> None:
    assert github_slug(heading) == slug


def test_a_repeated_heading_skips_a_slug_another_heading_already_took() -> None:
    nodes = [
        Heading(2, (Plain("Foo"),), "a"),
        Heading(2, (Plain("Foo 1"),), "b"),
        Heading(2, (Plain("Foo"),), "c"),
    ]

    assert github_heading_slugs(nodes) == {"a": "foo", "b": "foo-1", "c": "foo-2"}


def test_github_slugs_count_headings_nested_in_callouts_and_list_entries() -> None:
    nodes = [
        Heading(2, (Plain("Same"),), "top"),
        Callout("info", (Heading(3, (Plain("Same"),), "in-callout"),)),
        ListNode("bullet", (ListEntry((Plain("x"),), children=(Heading(3, (Plain("Same"),), "in-entry"),)),)),
    ]

    assert github_heading_slugs(nodes) == {"top": "same", "in-callout": "same-1", "in-entry": "same-2"}


def test_github_slugs_number_repeats_in_document_order_across_every_heading() -> None:
    nodes = [
        Heading(1, (Plain("Overview"),)),
        Heading(2, (Plain("Overview"),), "overview"),
        Toggle((Plain("Overview"),), 2, (Heading(3, (Plain("Detail"),), "detail"),), "overview-2"),
    ]

    assert github_heading_slugs(nodes) == {
        "overview": "overview-1",
        "overview-2": "overview-2",
        "detail": "detail",
    }


def test_the_table_of_contents_and_anchor_links_point_at_github_slugs() -> None:
    blocks = [
        {"type": "text", "body": "see [the detail](#overview-2)"},
        {"type": "heading", "text": "Overview"},
        {"type": "heading", "text": "Overview"},
    ]

    assert markdown_of(blocks, meta={"title": "T", "toc": True}) == (
        "- [Overview](#overview)\n- [Overview](#overview-1)\n\n"
        "see [the detail](#overview-1)\n\n"
        "## Overview\n\n## Overview\n"
    )


def test_a_list_right_after_the_table_of_contents_stays_its_own_list() -> None:
    blocks = [
        {"type": "fact_strip", "facts": [{"label": "Site", "value": "West"}]},
        {"type": "heading", "text": "A"},
    ]

    assert markdown_of(blocks, meta={"title": "T", "toc": True}) == "- [A](#a)\n\n* **Site**: West\n\n## A\n"


def test_a_page_with_no_toc_entries_drops_the_table_of_contents() -> None:
    assert markdown_of([{"type": "text", "body": "only"}], meta={"title": "T", "toc": True}) == "only\n"
