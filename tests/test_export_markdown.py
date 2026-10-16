from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from markdown_it import MarkdownIt

from skaldr.errors import ExportInvariantError, ExportRejectedError, ReportError
from skaldr.export import ExportResult, export_markdown, render_export
from skaldr.export import markdown as markdown_module
from skaldr.export.flanking import markers_flank
from skaldr.export.markdown import github_heading_slugs, github_slug, render_markdown
from skaldr.export.markup import code_block_lines, code_span, styled
from skaldr.export.runs import (
    Break,
    CheckMark,
    Chip,
    DecisionMark,
    ExportRich,
    ExportRun,
    Gauge,
    IndicatorMark,
    SectionLink,
    StatusMark,
    SwimlaneMark,
    TonedLabel,
    export_visible_text,
)
from skaldr.export.tree import (
    Callout,
    CodeBlock,
    Columns,
    Diagram,
    Graph,
    GraphNode,
    GridColumn,
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
from skaldr.models import BadgeColorLiteral, ToneLiteral, load_report, parse_report
from skaldr.richtext import (
    AnchorLink,
    Citation,
    Code,
    DateMention,
    Link,
    Placeholder,
    Plain,
    Run,
    ScriptText,
    Styled,
    Tinted,
    parse_rich,
)
from tests.factories import (
    API_AND_RISK_BADGES,
    API_BADGES,
    BADGE_AND_STATE_BLOCKS,
    REFUSED_IN_THE_EXAMPLE,
    TEXT_X_BLOCK,
    accepted_example,
    folder_texts,
    in_a_grid_cell,
    in_an_open_section,
    make_bullets,
    make_command_request,
    make_paragraph,
    make_query_request,
    make_report,
    make_tab,
    make_tabs,
    make_toggle,
    markdown_of,
    refused_block_types,
)
from tests.factories.example_factory import (
    EXAMPLE,
    FIRST_REFUSAL_IN_DOCUMENT_ORDER_OF_THE_EXAMPLE,
    example_for,
    golden_of,
    golden_or_scratch_folder,
)


def test_the_example_is_refused_for_github_at_its_first_refusal_in_document_order(tmp_path: Path) -> None:
    with pytest.raises(ExportRejectedError) as raised:
        export_markdown(load_report(EXAMPLE), tmp_path)

    assert str(raised.value) == FIRST_REFUSAL_IN_DOCUMENT_ORDER_OF_THE_EXAMPLE["markdown"]


def test_the_example_reworked_for_github_less_the_blocks_github_refuses_matches_the_markdown_golden(
    tmp_path: Path,
) -> None:
    out_dir = golden_or_scratch_folder("markdown", tmp_path)

    export_markdown(accepted_example("markdown"), out_dir)

    assert (refused_block_types(example_for("markdown"), "markdown"), folder_texts(out_dir)) == (
        REFUSED_IN_THE_EXAMPLE["markdown"],
        folder_texts(golden_of("markdown")),
    )


API_LEGEND = (
    "<details>\n<summary>Legend: badges used on this page</summary>\n\n- 🔵 **api** the API\n\n</details>\n\n"
)


def test_a_request_with_several_cases_is_a_details_block_per_case_with_the_first_open() -> None:
    cases = [
        {"label": "finding", "tone": "warning", "response": {"body": "[]"}},
        {"label": "control", "tone": "success", "response": {"body": "none"}},
    ]
    request = make_command_request(cases=cases, command="list-tiers")

    assert markdown_of([request]) == (
        "**Tier mappings on the partner API**\n\n"
        "<details open>\n<summary>⚠️ finding</summary>\n\n"
        "```bash\nlist-tiers\n```\n\n**Recorded output**\n\n```json\n[]\n```\n\n</details>\n\n"
        "<details>\n<summary>✅ control</summary>\n\n"
        "```bash\nlist-tiers\n```\n\n**Recorded output**\n\n```\nnone\n```\n\n</details>\n"
    )


def test_a_query_request_exports_a_fenced_block_in_its_language_labelled_with_the_runner() -> None:
    request = make_query_request()

    assert markdown_of([request]) == (
        "**Open orders in the shop database**\n\n"
        "*open orders*\n\n"
        "**Query**: mongosh, orders database\n\n"
        '```json\n[{"$match": {"status": "open"}}, {"$count": "n"}]\n```\n\n'
        '**Recorded output**\n\n```json\n[\n  {\n    "n": 12\n  }\n]\n```\n'
    )


def test_a_query_holding_backticks_gets_a_longer_fence() -> None:
    query = {"runner": "psql", "lang": "sql", "content": "SELECT '```' AS fence"}

    assert markdown_of([make_query_request(query=query)]) == (
        "**Open orders in the shop database**\n\n"
        "*open orders*\n\n"
        "**Query**: psql\n\n"
        "````sql\nSELECT '```' AS fence\n````\n\n"
        '**Recorded output**\n\n```json\n[\n  {\n    "n": 12\n  }\n]\n```\n'
    )


@pytest.mark.parametrize(
    ("tone", "title"),
    [
        pytest.param("success", "✅ t", id="success"),
        pytest.param("info", "💡 t", id="info-matches-its-callout"),
        pytest.param("warning", "⚠️ t", id="warning"),
        pytest.param("danger", "🛑 t", id="danger"),
        pytest.param("neutral", "t", id="neutral-has-no-icon"),
        pytest.param(None, "t", id="no-tone"),
    ],
)
def test_a_tab_title_carries_the_icon_of_its_case_tone(tone: ToneName | None, title: str) -> None:
    assert (
        render_markdown([Tabs((Tab((Plain("t"),), (Paragraph((Plain("z"),)),), tone),))])
        == f"<details open>\n<summary>{title}</summary>\n\nz\n\n</details>\n"
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
    diagram = Diagram(Graph("LR", (GraphNode("s1", "A"),), (), "flow"))

    assert render_markdown([diagram, Paragraph((Plain("after"),))]) == (
        '```mermaid\nflowchart LR\n    s1["A"]\n```\n\nafter\n'
    )


def test_the_page_starts_with_the_title_as_its_only_top_level_heading(tmp_path: Path) -> None:
    report = parse_report(make_report(meta={"title": "Q3 *count*"}))

    result = export_markdown(report, tmp_path)

    assert result == ExportResult("Q3 *count*", (tmp_path / "page.md",))
    assert (tmp_path / "page.md").read_text(encoding="utf-8") == "# Q3 \\*count\\*\n\nHello.\n"


def test_a_page_cover_is_an_image_under_the_icon_led_title() -> None:
    report = parse_report(
        make_report(meta={"title": "Q3", "icon": "📦", "cover": "https://example.com/covers/q3.png"})
    )

    assert render_export(report, "markdown").pages["page.md"] == (
        "# 📦 Q3\n\n![Cover](https://example.com/covers/q3.png)\n\nHello.\n"
    )


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
        pytest.param(Styled("underline", (Plain("a*b"),)), r"<ins>a\*b</ins>", id="underline"),
        pytest.param(ScriptText("subscript", "<i>"), r"<sub>\<i\></sub>", id="subscript"),
        pytest.param(ScriptText("superscript", "-1"), "<sup>-1</sup>", id="superscript"),
        pytest.param(
            Link((Plain("paren"),), "https://example.com/(x)>"),
            "[paren](https://example.com/%28x%29%3E)",
            id="link-with-parens",
        ),
        pytest.param(AnchorLink((Plain("method"),), "method"), "[method](#how-we-count)", id="anchor-link"),
        pytest.param(AnchorLink((Plain("gone"),), "nowhere"), "gone", id="anchor-link-to-no-heading"),
        pytest.param(SectionLink((Plain("method"),), "method"), "[method](#how-we-count)", id="section-link"),
        pytest.param(
            TonedLabel("danger", (Plain("Scan"),)), "🔴 Scan", id="toned-label-is-led-by-its-tone-dot"
        ),
        pytest.param(StatusMark("done"), "✅", id="status-mark"),
        pytest.param(SwimlaneMark("deferred"), "⏸️", id="swimlane-mark"),
        pytest.param(IndicatorMark("warning"), "🟡", id="indicator-mark"),
        pytest.param(CheckMark(checked=False), "✗", id="check-mark"),
        pytest.param(Break(), "<br>", id="line-break"),
        pytest.param(Gauge(10, 10), "██████████", id="full-gauge"),
        pytest.param(Chip("a*b_c", "blue"), r"🔵 **a\*b\_c**", id="chip-label-is-escaped"),
    ],
)
def test_an_inline_run_becomes_markdown(run: ExportRun, written: str) -> None:
    nodes = [Heading(2, (Plain("How we count"),), "method"), Paragraph((run,))]

    assert render_markdown(nodes) == f"## How we count\n\n{written}\n"


def test_a_date_chip_inside_a_link_label_is_written_inside_the_link() -> None:
    chip = DateMention((Plain("1 Oct"),), date(2026, 10, 1), None)
    week = DateMention((Plain("the week"),), date(2026, 10, 5), date(2026, 10, 9))

    link = Link((Plain("due "), chip, Plain(" "), week), "https://e.com")

    assert render_markdown([Paragraph((link,))]) == (
        '[due <time datetime="2026-10-01">1 Oct</time> '
        '<span data-range="2026-10-05/2026-10-09">the week</span>](https://e.com)\n'
    )


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


def test_a_highlight_span_is_a_mark_tag_around_its_text_whatever_its_tone() -> None:
    span = Tinted(None, "warning", (Plain("Friday"),))
    other = Tinted(None, "sky", (Styled("bold", (Plain("soon"),)),))

    assert render_markdown([Paragraph((Plain("due "), span, Plain(" or "), other))]) == (
        "due <mark>Friday</mark> or <mark>**soon**</mark>\n"
    )


@pytest.mark.parametrize(
    ("tone", "background"),
    [
        pytest.param("danger", None, id="colour"),
        pytest.param("danger", "sky", id="colour-and-highlight"),
    ],
)
def test_the_github_writer_alone_raises_an_internal_error_for_a_span_the_check_refuses(
    tone: ToneLiteral | None, background: ToneLiteral | None
) -> None:
    with pytest.raises(ExportInvariantError) as raised:
        render_markdown([Paragraph((Tinted(tone, background, (Plain("behind"),)),))])

    assert str(raised.value) == (
        "GitHub Markdown cannot colour or highlight text; the export check should have refused it"
    )


def test_an_anchor_link_to_a_heading_whose_github_slug_is_empty_is_its_label() -> None:
    nodes = [Heading(2, (Plain("!!!"),), "bang"), Paragraph((AnchorLink((Plain("x"),), "bang"),))]

    assert render_markdown(nodes) == "## !!\\!\n\nx\n"


def test_a_bang_ending_text_is_escaped_even_with_nothing_after_it() -> None:
    assert markdown_of([{"type": "text", "body": "Done!"}]) == "Done\\!\n"


def test_a_backslash_in_a_link_target_stays_a_backslash_like_the_html_href() -> None:
    assert render_markdown([Paragraph((Link((Plain("x"),), "https://e.com/a\\b"),))]) == (
        "[x](https://e.com/a\\\\b)\n"
    )


@pytest.mark.parametrize(
    ("url", "written"),
    [
        pytest.param("https://e.com/a\n\n# Injected", "https://e.com/a%0A%0A#%20Injected", id="line-breaks"),
        pytest.param("https://e.com/\ta\r<b>", "https://e.com/%09a%0D%3Cb%3E", id="tab-cr-and-angles"),
    ],
)
def test_a_link_target_holding_whitespace_is_percent_encoded(url: str, written: str) -> None:
    assert render_markdown([Paragraph((Link((Plain("x"),), url),))]) == f"[x]({written})\n"


@pytest.mark.parametrize(
    ("url", "written"),
    [
        pytest.param("https://e.com/a?q=1#top", "https://e.com/a?q=1#top", id="plain-url"),
        pytest.param("https://e.com/a<b>", "https://e.com/a%3Cb%3E", id="angles"),
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


def test_underline_and_scripts_in_prose_become_github_html_tags() -> None:
    assert markdown_of([{"type": "text", "body": "++new++ H~2~O at 10^3^"}]) == (
        "<ins>new</ins> H<sub>2</sub>O at 10<sup>3</sup>\n"
    )


def test_inline_math_is_written_unescaped_in_github_math_form_while_prose_dollars_stay_escaped() -> None:
    assert markdown_of([{"type": "text", "body": "costs $5, so $`x_i < 2`$ holds"}]) == (
        "costs \\$5, so $`x_i < 2`$ holds\n"
    )


def test_a_math_block_is_a_github_math_fence() -> None:
    block = {"type": "math", "expression": "\\sum_{i=1}^{n} x_i\n\n= y\n"}

    assert markdown_of([block]) == "```math\n\\sum_{i=1}^{n} x_i\n= y\n```\n"


def test_a_math_block_inside_a_panel_is_a_quoted_github_math_fence() -> None:
    callout = {"type": "callout", "tone": "info", "body": "Rate"}
    panel = {"type": "panel", "title": "P", "blocks": [callout, {"type": "math", "expression": "x_i"}]}

    assert markdown_of([panel]) == "> **P**\n>\n> > 💡 Rate\n>\n> ```math\n> x_i\n> ```\n"


def test_a_math_block_holding_a_backtick_fence_line_gets_a_longer_fence() -> None:
    assert markdown_of([{"type": "math", "expression": "a\n```\nb"}]) == "````math\na\n```\nb\n````\n"


def test_brackets_followed_by_braces_that_are_not_a_span_stay_escaped_prose_in_markdown() -> None:
    assert markdown_of([{"type": "text", "body": "a_b [x]{y}"}]) == "a\\_b \\[x\\]{y}\n"


def test_marker_characters_that_form_no_mark_stay_escaped_prose_in_markdown() -> None:
    assert markdown_of([{"type": "text", "body": "C++ in ~5 days, 2^10 {x} and a ++ b ++ c"}]) == (
        "C++ in \\~5 days, 2^10 {x} and a ++ b ++ c\n"
    )


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
    ("code", "fence"),
    [
        pytest.param({"content": "x"}, "```", id="no-language-stays-a-bare-fence"),
        pytest.param({"content": "x", "lang": "shell"}, "```shell", id="an-authored-language"),
    ],
)
def test_a_github_code_fence_carries_the_authored_language(code: dict[str, Any], fence: str) -> None:
    assert markdown_of([{"type": "code", **code}]) == f"{fence}\nx\n```\n"


def test_the_github_footer_shows_rich_text_from_the_source_and_plain_facts() -> None:
    page = markdown_of(
        [{"type": "text", "body": "x"}], meta={"title": "T", "source": "see `app.ts`", "date": "5 Oct"}
    )

    assert page.splitlines()[-1] == "see `app.ts` · 5 Oct"


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


def test_a_table_pads_short_rows_and_dots_its_tones() -> None:
    table = TableNode(
        (TableCell((Plain("A"),)), TableCell((Plain("B"),))),
        (
            TableRow((TableCell((Plain("group"),)),), emphasis="group"),
            TableRow((TableCell((Plain("x"),), "danger"), TableCell((Plain("y"),))), "sky"),
        ),
        header_column=True,
    )

    assert render_markdown([table]) == "| A | B |\n| --- | --- |\n| **group** |  |\n| **🔵 🔴 x** | y |\n"


def _number_and_title(title: ExportRich, title_tone: ToneName | None = None) -> tuple[TableCell, ...]:
    return (TableCell((Plain("1"),)), TableCell(title, title_tone))


@pytest.mark.parametrize(
    ("row", "written"),
    [
        pytest.param(
            TableRow(_number_and_title((Plain("(old)"),)), "muted"),
            "| 1 | ~~(old)~~ |",
            id="a-muted-row-strikes-its-title",
        ),
        pytest.param(
            TableRow(_number_and_title(parse_rich("a ~~b~~ **c**")), "muted"),
            "| 1 | ~~a b **c**~~ |",
            id="a-strike-inside-a-struck-title-is-written-once",
        ),
        pytest.param(TableRow(_number_and_title(()), "muted"), "| 1 |  |", id="an-empty-struck-title"),
        pytest.param(
            TableRow(_number_and_title((Plain("fire"),)), "danger"), "| 1 | 🔴 fire |", id="a-danger-row"
        ),
        pytest.param(
            TableRow(_number_and_title(()), "danger"), "| 1 | 🔴 |", id="a-danger-row-with-an-empty-title"
        ),
        pytest.param(
            TableRow(_number_and_title((Plain("fire"),), "warning"), "danger"),
            "| 1 | 🔴 🟡 fire |",
            id="the-row-dot-before-the-title-cell-dot",
        ),
        pytest.param(
            TableRow(_number_and_title((Plain("old"),), "warning"), "muted"),
            "| 1 | 🟡 ~~old~~ |",
            id="a-muted-row-strikes-the-text-after-the-title-cell-dot",
        ),
        pytest.param(
            TableRow(_number_and_title((Plain("fire"),), "muted"), "danger"),
            "| 1 | 🔴 ~~fire~~ |",
            id="a-muted-title-cell-in-a-danger-row-is-struck-after-the-row-dot",
        ),
        pytest.param(
            TableRow(_number_and_title((Plain("fire"),), "danger"), "danger"),
            "| 1 | 🔴 fire |",
            id="a-title-cell-on-the-row-tone-shows-one-dot",
        ),
        pytest.param(
            TableRow(_number_and_title((Plain("fire"),)), tint="danger"),
            "| 1 | fire |",
            id="a-tint-is-dropped",
        ),
        pytest.param(
            TableRow((TableCell((Plain("1"),), "muted"), TableCell((Plain("x"),)))),
            "| ~~1~~ | x |",
            id="a-muted-cell-is-struck",
        ),
        pytest.param(
            TableRow((TableCell((IndicatorMark("warning"),), "warning"), TableCell((Plain("x"),)))),
            "| 🟡 | x |",
            id="an-indicator-on-its-own-tone-is-the-dot-alone",
        ),
        pytest.param(
            TableRow((TableCell((CheckMark(checked=True),), "danger"), TableCell(()))),
            "| 🔴 ✓ |  |",
            id="a-check-mark-on-a-tone",
        ),
    ],
)
def test_a_row_tone_marks_the_title_cell_and_a_cell_tone_its_cell(row: TableRow, written: str) -> None:
    table = TableNode((TableCell((Plain("N"),)), TableCell((Plain("Item"),))), (row,), title_column=1)

    assert render_markdown([table]) == f"| N | Item |\n| --- | --- |\n{written}\n"


@pytest.mark.parametrize(
    ("color", "dot"),
    [
        pytest.param("slate", "⚪", id="slate"),
        pytest.param("blue", "🔵", id="blue"),
        pytest.param("green", "🟢", id="green"),
        pytest.param("amber", "🟡", id="amber"),
        pytest.param("red", "🔴", id="red"),
        pytest.param("violet", "🟣", id="violet"),
        pytest.param("teal", "🟢", id="teal"),
        pytest.param("sky", "🔵", id="sky"),
    ],
)
def test_a_chip_is_its_color_dot_and_bold_label(color: BadgeColorLiteral, dot: str) -> None:
    assert render_markdown([Paragraph((Chip("High", color),))]) == f"{dot} **High**\n"


def test_a_comparison_dots_verdicts_by_polarity_and_cells_by_tone() -> None:
    comparison = {
        "type": "comparison",
        "options": ["A", "B"],
        "polarity": ["positive", "negative"],
        "rows": [
            {"feature": "Logs", "values": [True, True]},
            {"feature": "Cost", "values": [False, {"value": "high", "tone": "warning"}]},
        ],
    }

    assert markdown_of([comparison]) == (
        "|  | A | B |\n| --- | --- | --- |\n| **Logs** | 🟢 ✓ | 🔴 ✓ |\n| **Cost** | 🔴 ✗ | 🟡 high |\n"
    )


def test_a_matrix_cell_fill_is_its_dot_before_its_label_or_the_dot_alone() -> None:
    matrix = {
        "type": "matrix",
        "rows": ["Build"],
        "columns": ["Plain", "Fill", "Both"],
        "cells": [
            {"row": "Build", "col": "Plain", "label": "x"},
            {"row": "Build", "col": "Fill", "tone": "red"},
            {"row": "Build", "col": "Both", "tone": "green", "label": "ok"},
        ],
    }

    assert markdown_of([matrix]) == (
        "|  | Plain | Fill | Both |\n| --- | --- | --- | --- |\n| **Build** | x | 🔴 | 🟢 ok |\n"
    )


def test_a_table_shows_row_tones_on_the_title_and_drops_a_tint() -> None:
    table = {
        "type": "table",
        "columns": [
            {"key": "n", "label": "N", "kind": "number"},
            {"key": "a", "label": "Item"},
            {"key": "risk", "label": "Risk", "kind": "indicator"},
            {"key": "tag", "label": "Tag", "kind": "badge"},
        ],
        "tint_by": "tag",
        "rows": [
            {"n": 1, "a": "old (x)", "risk": "warning", "tag": "API", "tone": "muted"},
            {"n": 2, "a": "fire", "risk": "danger", "tag": "", "tone": "danger"},
            {"n": 3, "a": "tinted", "risk": "", "tag": "RISK"},
        ],
    }

    assert markdown_of([table], badges=API_AND_RISK_BADGES) == (
        f"{API_LEGEND}"
        "| N | Item | Risk | Tag |\n"
        "| --- | --- | --- | --- |\n"
        "| 1 | ~~old (x)~~ | 🟡 | 🔵 **api** |\n"
        "| 2 | 🔴 fire | 🔴 |  |\n"
        "| 3 | tinted |  | 🔴 **risk** |\n"
    )


def test_a_toned_item_label_is_preceded_by_its_dot() -> None:
    blocks = [
        {"type": "meter", "items": [{"label": "Disk", "value": 3, "max": 4, "tone": "warning"}]},
        {"type": "cards", "items": [{"label": "Errors", "value": "3", "tone": "danger"}]},
        {"type": "walkthrough", "steps": [{"label": "Stop", "tone": "danger", "detail": [TEXT_X_BLOCK]}]},
    ]

    assert markdown_of(blocks) == (
        "- 🟡 **Disk**: ████████░░ 75.0%\n\n| 🔴 Errors |\n| --- |\n| 3 |\n\n1. 🔴 **Stop**\n\n   x\n"
    )


@pytest.mark.parametrize(
    ("card", "written"),
    [
        pytest.param(
            {"label": "Err", "value": "3", "tone": "danger", "badges": ["API"]},
            "| 🔴 Err |\n| --- |\n| 3 🔵 **api** |\n",
            id="a-tone-unlike-the-badge-color-keeps-its-dot",
        ),
        pytest.param(
            {"label": "Err", "value": "3", "tone": "info", "badges": ["API"]},
            "| Err |\n| --- |\n| 3 🔵 **api** |\n",
            id="a-tone-like-the-badge-color-leaves-the-dot-to-the-badge",
        ),
        pytest.param(
            {"label": "Err", "value": "3", "tone": "info", "badges": ["RISK", "API"]},
            "| Err |\n| --- |\n| 3 🔴 **risk** 🔵 **api** |\n",
            id="a-tone-like-any-badge-color-leaves-the-dot-to-that-badge",
        ),
        pytest.param(
            {"label": "Err", "value": "3", "badges": ["API"]},
            "| Err |\n| --- |\n| 3 🔵 **api** |\n",
            id="a-badge-without-a-card-tone",
        ),
    ],
)
def test_a_card_dot_gives_way_to_a_badge_of_its_color(card: dict[str, Any], written: str) -> None:
    assert markdown_of([{"type": "cards", "items": [card]}], badges=API_AND_RISK_BADGES) == (
        API_LEGEND + written
    )


@pytest.mark.parametrize(
    ("card", "written"),
    [
        pytest.param(
            {"label": "Err", "value": "3", "tone": "danger", "delta": {"label": "up", "tone": "danger"}},
            "| Err |\n| --- |\n| 3 🔴 **up** |\n",
            id="a-tone-like-the-delta-chip-leaves-the-dot-to-the-chip",
        ),
        pytest.param(
            {"label": "Err", "value": "3", "tone": "danger", "delta": {"label": "up", "tone": "success"}},
            "| 🔴 Err |\n| --- |\n| 3 🟢 **up** |\n",
            id="a-tone-unlike-the-delta-chip-keeps-its-dot",
        ),
        pytest.param(
            {"label": "Err", "value": "3", "tone": "danger", "delta": {"label": "up"}},
            "| 🔴 Err |\n| --- |\n| 3 up |\n",
            id="a-delta-without-a-tone-leaves-the-dot-to-the-card",
        ),
    ],
)
def test_a_card_dot_gives_way_to_a_delta_chip_of_its_color(card: dict[str, Any], written: str) -> None:
    assert markdown_of([{"type": "cards", "items": [card]}]) == written


def test_a_muted_row_strikes_the_first_text_column() -> None:
    table = {
        "type": "table",
        "columns": [{"key": "note", "label": "Note", "kind": "rich"}, {"key": "a", "label": "Item"}],
        "rows": [{"note": "**see**", "a": "old", "tone": "muted"}],
    }

    assert markdown_of([table]) == "| Note | Item |\n| --- | --- |\n| **see** | ~~old~~ |\n"


def test_a_toned_meter_item_without_a_label_shows_no_dot() -> None:
    meter = {"type": "meter", "items": [{"label": "", "value": 3, "max": 4, "tone": "warning"}]}

    assert markdown_of([meter]) == "- ████████░░ 75.0%\n"


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

    assert markdown_of([comparison]) == "|  | A | ★ B |\n| --- | --- | --- |\n| **Risky** | 🟢 ✓ | 🔴 ✗ |\n"


def test_a_swimlane_bolds_each_lane_cell_as_a_whole_and_leaves_the_header_to_the_pipe_table() -> None:
    swimlane = {
        "type": "swimlane",
        "lanes": ["Ops"],
        "columns": [{"name": "Plan", "sub": "wk 1"}],
        "steps": [{"lane": "Ops", "col": "Plan", "n": "1", "label": "Draft", "value": 2}],
    }

    assert markdown_of([swimlane]) == (
        "| Lane | Plan<br>*wk 1* |\n| --- | --- |\n| **Ops (2)** | **1** Draft (2) |\n| **Total** | **2** |\n"
    )


@pytest.mark.parametrize(
    ("chart", "written"),
    [
        pytest.param(
            {
                "type": "chart",
                "variant": "donut",
                "slices": [{"label": "A", "value": 3, "tone": "success"}, {"label": "B", "value": 1.5}],
            },
            '```mermaid\npie\n    "A" : 3\n    "B" : 1.5\n```\n\n'
            "| Slice | Value | Share |\n| --- | --- | --- |\n| A | 3 | 67% |\n| B | 1.5 | 33% |\n"
            "| **Total** | **4.5** |  |\n",
            id="donut-slice",
        ),
        pytest.param(
            {
                "type": "chart",
                "variant": "line",
                "categories": ["Q1", "Q2"],
                "series": [{"label": "x", "tone": "danger", "values": [1, 2]}],
            },
            '```mermaid\nxychart-beta\n    x-axis ["Q1", "Q2"]\n    line [1, 2]\n```\n\n'
            "| Series | Q1 | Q2 |\n| --- | --- | --- |\n| x | 1 | 2 |\n",
            id="line-series",
        ),
    ],
)
def test_a_toned_chart_row_in_its_data_table_shows_no_dot(chart: dict[str, Any], written: str) -> None:
    assert markdown_of([chart]) == written


def test_a_swimlane_group_color_shows_no_dot() -> None:
    swimlane = {
        "type": "swimlane",
        "lanes": ["Ops"],
        "columns": [{"name": "Plan"}],
        "groups": [{"name": "Q1", "color": "red", "columns": ["Plan"]}],
        "steps": [
            {"lane": "Ops", "col": "Plan", "n": "1", "label": "Draft", "group": "Q1", "state": "blocked"}
        ],
    }

    assert markdown_of([swimlane]) == "| Lane | Plan<br>Q1 |\n| --- | --- |\n| **Ops** | ⛔ **1** Draft |\n"


def _text_cell(span: int, body: str, **overrides: Any) -> dict[str, Any]:
    return {"span": span, "blocks": [{"type": "text", "body": body}], **overrides}


def test_a_grid_of_up_to_three_plain_cells_is_a_raw_table_with_each_cell_width() -> None:
    grid = {"type": "grid", "cells": [_text_cell(2, "a"), _text_cell(4, "**b**")]}

    assert markdown_of([grid]) == (
        '<table>\n<tr>\n<td width="33%">\n\na\n\n</td>\n<td width="67%">\n\n**b**\n\n</td>\n</tr>\n</table>\n'
    )


def test_a_grid_of_four_cells_is_a_raw_table_without_widths() -> None:
    grid = {"type": "grid", "cells": [_text_cell(1, letter) for letter in "abcd"]}

    assert markdown_of([grid]) == (
        "<table>\n<tr>\n"
        "<td>\n\na\n\n</td>\n<td>\n\nb\n\n</td>\n<td>\n\nc\n\n</td>\n<td>\n\nd\n\n</td>\n"
        "</tr>\n</table>\n"
    )


def test_a_grid_cell_holding_a_table_is_a_raw_table_without_widths_around_a_pipe_table() -> None:
    inner = {
        "type": "table",
        "columns": [{"key": "a", "label": "A"}],
        "rows": [{"a": "x"}],
    }
    grid = {"type": "grid", "cells": [{"span": 3, "blocks": [inner]}, _text_cell(3, "b")]}

    assert markdown_of([grid]) == (
        "<table>\n<tr>\n<td>\n\n| A |\n| --- |\n| x |\n\n</td>\n<td>\n\nb\n\n</td>\n</tr>\n</table>\n"
    )


def test_a_toned_grid_cell_is_a_raw_table_without_widths_around_an_icon_led_quote() -> None:
    grid = {"type": "grid", "cells": [_text_cell(3, "a", tone="warning"), _text_cell(3, "b")]}

    assert markdown_of([grid]) == (
        "<table>\n<tr>\n<td>\n\n> ⚠️ a\n\n</td>\n<td>\n\nb\n\n</td>\n</tr>\n</table>\n"
    )


def test_a_callout_in_a_grid_cell_is_an_icon_led_quote_and_an_empty_cell_is_an_empty_td() -> None:
    callout = Callout("success", (Paragraph((Plain("done"),)),))
    grid = Columns((GridColumn(50, (callout,)), GridColumn(50, ())))

    assert render_markdown([grid]) == (
        '<table>\n<tr>\n<td width="50%">\n\n> ✅ done\n\n</td>\n<td width="50%"></td>\n</tr>\n</table>\n'
    )


def test_a_grid_inside_a_grid_cell_is_a_table_inside_the_td() -> None:
    inner = Columns(
        (GridColumn(50, (Paragraph((Plain("i"),)),)), GridColumn(50, (Paragraph((Plain("j"),)),)))
    )
    outer = Columns((GridColumn(50, (inner,)), GridColumn(50, (Paragraph((Plain("o"),)),))))

    assert render_markdown([outer]) == (
        '<table>\n<tr>\n<td width="50%">\n\n'
        '<table>\n<tr>\n<td width="50%">\n\ni\n\n</td>\n<td width="50%">\n\nj\n\n</td>\n</tr>\n</table>\n\n'
        '</td>\n<td width="50%">\n\no\n\n</td>\n</tr>\n</table>\n'
    )


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
        pytest.param("2024. was the year", "2024\\. was the year", id="year-ordinal"),
        pytest.param("123456789. x", "123456789\\. x", id="nine-digit-ordinal-is-a-list"),
    ],
)
def test_a_paragraph_that_starts_like_a_block_marker_stays_a_paragraph(body: str, line: str) -> None:
    assert markdown_of([{"type": "text", "body": body}]) == f"{line}\n"


def test_rich_text_that_fails_to_export_names_its_field() -> None:
    blocks = [{"type": "text", "body": "Intro."}, {"type": "list", "items": ["ok", "a [b]{tone=x} c"]}]

    with pytest.raises(ReportError) as raised:
        markdown_of(blocks)

    assert str(raised.value) == (
        "blocks.1.items.1: unknown tone 'x' in {tone=x}: a tone is one of neutral, info, success, warning, "
        "danger, accent, teal, sky, or a palette name slate, blue, green, amber, red, violet"
    )


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
    ],
)
def test_a_numbered_list_keeps_its_start_and_its_numbering(options: dict[str, object], markdown: str) -> None:
    block = {"type": "list", "style": "number", "items": ["c", {"text": "d", "items": ["e"]}], **options}

    assert markdown_of([block]) == markdown


def test_a_lettered_list_is_an_ol_of_type_a_with_each_item_set_apart_by_blank_lines() -> None:
    block = {"type": "list", "style": "number", "numbering": "letters", "items": ["c", "**d**"]}

    assert markdown_of([block]) == ('<ol type="a">\n<li>\n\nc\n\n</li>\n<li>\n\n**d**\n\n</li>\n</ol>\n')


def test_a_roman_list_is_an_ol_of_type_i_from_its_start_with_nested_lists_inside_its_items() -> None:
    block = {
        "type": "list",
        "style": "number",
        "numbering": "roman",
        "start": 4,
        "items": ["c", {"text": "d", "items": ["e"]}],
    }

    assert markdown_of([block]) == (
        '<ol type="i" start="4">\n'
        "<li>\n\nc\n\n</li>\n"
        '<li>\n\nd\n\n<ol type="i">\n<li>\n\ne\n\n</li>\n</ol>\n\n</li>\n'
        "</ol>\n"
    )


def test_an_ol_does_not_join_the_markdown_lists_around_it() -> None:
    lettered = ListNode("number", (ListEntry((Plain("b"),)),), numbering="letters")
    nodes = [
        ListNode("number", (ListEntry((Plain("a"),)),)),
        lettered,
        ListNode("number", (ListEntry((Plain("c"),)),)),
    ]

    assert render_markdown(nodes) == '1. a\n\n<ol type="a">\n<li>\n\nb\n\n</li>\n</ol>\n\n1. c\n'


def test_an_ol_item_holding_a_callout_keeps_the_icon_led_quote_and_a_blank_item_is_empty() -> None:
    inner = Callout("success", (Paragraph((Plain("done"),)),))
    lettered = ListNode(
        "number", (ListEntry((Plain("a"),), children=(inner,)), ListEntry(())), numbering="roman"
    )

    assert render_markdown([lettered]) == (
        '<ol type="i">\n<li>\n\na\n\n> ✅ done\n\n</li>\n<li></li>\n</ol>\n'
    )


@pytest.mark.parametrize(
    ("blocks", "markdown"),
    [
        pytest.param(
            [
                {
                    "type": "list",
                    "style": "number",
                    "start": 999_999_999,
                    "items": ["a", {"text": "b", "items": ["c"]}],
                }
            ],
            "999999999. a\n999999999. b\n           1. c\n",
            id="items-past-nine-digits-repeat-the-largest-marker",
        ),
        pytest.param(
            [
                {"type": "list", "items": ["x"]},
                {"type": "list", "style": "number", "start": 999_999_998, "items": ["a", "b", "c"]},
            ],
            "- x\n\n999999998. a\n999999999. b\n999999999. c\n",
            id="the-last-nine-digit-marker-counts-on-and-the-next-repeats-it",
        ),
    ],
)
def test_a_numbered_list_never_writes_a_marker_longer_than_nine_digits(
    blocks: list[dict[str, object]], markdown: str
) -> None:
    assert markdown_of(blocks) == markdown


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


def test_a_callout_led_by_a_list_has_a_blank_line_between_its_alert_line_and_the_list() -> None:
    callout = Callout("info", (ListNode("number", (ListEntry((Plain("a"),)),), start=3),))

    assert render_markdown([callout]) == "> [!NOTE]\n>\n> 3. a\n"


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


def _columns(*cells: tuple[Node, ...]) -> Columns:
    return Columns(tuple(GridColumn(100 // len(cells), cell) for cell in cells))


def _table_of(*cells: str) -> str:
    width = f' width="{100 // len(cells)}%"'
    opened = "".join(f"<td{width}>\n\n{cell}\n\n</td>\n" for cell in cells)
    return f"<table>\n<tr>\n{opened}</tr>\n</table>"


@pytest.mark.parametrize(
    ("nodes", "markdown"),
    [
        pytest.param(
            [make_bullets("a", "b"), _columns((make_bullets("c", "d"),), (make_paragraph("t"),))],
            "- a\n- b\n\n" + _table_of("- c\n- d", "t") + "\n",
            id="list-then-a-grid-opening-with-a-list",
        ),
        pytest.param(
            [_columns((make_paragraph("t"),), (make_bullets("c"),)), make_bullets("d")],
            _table_of("t", "- c") + "\n\n- d\n",
            id="grid-ending-with-a-list-then-a-list",
        ),
        pytest.param(
            [_columns((make_bullets("a"),)), _columns((make_bullets("b"),)), make_bullets("c")],
            _table_of("- a") + "\n\n" + _table_of("- b") + "\n\n- c\n",
            id="a-chain-of-lists-through-grids",
        ),
        pytest.param(
            [make_bullets("a"), _columns((make_paragraph(""),)), make_bullets("b")],
            "- a\n\n* b\n",
            id="a-grid-with-nothing-to-say-between-two-lists",
        ),
        pytest.param(
            [
                Tabs((Tab((Plain("A"),), (make_paragraph("a"),)), Tab((Plain("B"),), (make_bullets("x"),)))),
                make_bullets("z"),
            ],
            "<details open>\n<summary>A</summary>\n\na\n\n</details>\n\n"
            "<details>\n<summary>B</summary>\n\n- x\n\n</details>\n\n- z\n",
            id="tabs-ending-with-a-list-then-a-list",
        ),
        pytest.param(
            [
                make_bullets("a"),
                Tabs((Tab((Plain("A"),), (make_bullets("x"),)), Tab((Plain("B"),), (make_bullets("y"),)))),
            ],
            "- a\n\n<details open>\n<summary>A</summary>\n\n- x\n\n</details>\n\n"
            "<details>\n<summary>B</summary>\n\n- y\n\n</details>\n",
            id="a-details-block-already-separates-lists",
        ),
        pytest.param(
            [
                Diagram(Graph("LR", (GraphNode("s1", "A"),), (), "flow"), (make_bullets("p"),)),
                make_bullets("z"),
            ],
            '```mermaid\nflowchart LR\n    s1["A"]\n```\n\n- p\n\n* z\n',
            id="diagram-ending-with-a-list-then-a-list",
        ),
        pytest.param(
            [Toggle((Plain("T"),), None, (make_bullets("x"),)), make_bullets("z")],
            "<details>\n<summary>T</summary>\n\n- x\n\n</details>\n\n- z\n",
            id="toggle-ending-with-a-list-then-a-list",
        ),
        pytest.param(
            [
                ListNode("number", (ListEntry((Plain("a"),)),)),
                _columns((ListNode("number", (ListEntry((Plain("b"),)),)),)),
            ],
            "1. a\n\n" + _table_of("1. b") + "\n",
            id="ordered-lists-either-side-of-a-grid",
        ),
        pytest.param(
            [make_bullets("a"), _columns((Callout("info", (make_bullets("b"),)),)), make_bullets("c")],
            "- a\n\n" + _table_of("> 💡\n>\n> - b") + "\n\n- c\n",
            id="a-quoted-list-in-a-grid-separates-the-lists-around-it",
        ),
    ],
)
def test_lists_on_either_side_of_a_grid_tabs_toggle_or_diagram_stay_separate_lists(
    nodes: list[Node], markdown: str
) -> None:
    assert render_markdown(nodes) == markdown


def test_lists_around_an_authored_grid_stay_separate_lists_in_github() -> None:
    grid = {
        "type": "grid",
        "cells": [
            {"span": 3, "blocks": [{"type": "list", "items": ["c", "d"]}]},
            {"span": 3, "blocks": [{"type": "text", "body": "t"}]},
        ],
    }
    blocks = [{"type": "list", "items": ["a", "b"]}, grid, {"type": "list", "items": ["e"]}]

    assert markdown_of(blocks) == "- a\n- b\n\n" + _table_of("- c\n- d", "t") + "\n\n- e\n"


def test_a_callout_whose_first_paragraph_is_empty_keeps_its_icon_off_the_list_that_follows() -> None:
    callout = Callout("info", (Paragraph(()), make_bullets("first", "second")), icon="💡")

    assert render_markdown([callout]) == "> [!NOTE]\n> 💡\n>\n> - first\n> - second\n"


def test_a_callout_with_an_empty_first_paragraph_puts_its_icon_before_a_later_paragraph() -> None:
    callout = Callout("info", (Paragraph(()), make_paragraph("later")), icon="💡")

    assert render_markdown([callout]) == "> [!NOTE]\n> 💡 later\n"


def _github_html(markdown: str) -> str:
    return MarkdownIt("commonmark").enable("strikethrough").render(markdown)


def _spliced(*texts: str) -> ExportRich:
    return tuple(run for text in texts for run in parse_rich(text))


@pytest.mark.parametrize(
    ("runs", "markdown", "html"),
    [
        pytest.param(
            _spliced("**(bold)**", "t"),
            "<strong>(bold)</strong>t\n",
            "<p><strong>(bold)</strong>t</p>\n",
            id="bold-before-a-letter",
        ),
        pytest.param(
            _spliced("*(it)*", "u"),
            "<em>(it)</em>u\n",
            "<p><em>(it)</em>u</p>\n",
            id="italic-before-a-letter",
        ),
        pytest.param(
            _spliced("~~(b)~~", "c"),
            "<del>(b)</del>c\n",
            "<p><del>(b)</del>c</p>\n",
            id="strike-before-a-letter",
        ),
        pytest.param(
            _spliced("a", "**(x)** y"),
            "a<strong>(x)</strong> y\n",
            "<p>a<strong>(x)</strong> y</p>\n",
            id="bold-after-a-letter",
        ),
        pytest.param(
            (*parse_rich("**(bold)**"), TonedLabel("info", parse_rich("t"))),
            "<strong>(bold)</strong>🔵 t\n",
            "<p><strong>(bold)</strong>🔵 t</p>\n",
            id="bold-before-the-dot-of-a-toned-label",
        ),
        pytest.param(
            parse_rich("**(x)** y and **`api`**."),
            "**(x)** y and **`api`**.\n",
            "<p><strong>(x)</strong> y and <strong><code>api</code></strong>.</p>\n",
            id="markers-stay-when-the-neighbours-allow-them",
        ),
        pytest.param(
            _spliced("**a** ", "b"),
            "**a** b\n",
            "<p><strong>a</strong> b</p>\n",
            id="a-letter-after-a-space-changes-nothing",
        ),
        pytest.param(
            parse_rich("*a **(x)**[t](jira:AB-1)* z"),
            "*a <strong>(x)</strong>t* z\n",
            "<p><em>a <strong>(x)</strong>t</em> z</p>\n",
            id="nested-emphasis-falls-back-on-its-own",
        ),
        pytest.param(
            (Link(parse_rich("**(x)**[t](jira:AB-1)"), "https://x.io"),),
            "[<strong>(x)</strong>t](https://x.io)\n",
            '<p><a href="https://x.io"><strong>(x)</strong>t</a></p>\n',
            id="inside-a-link-label",
        ),
        pytest.param(
            parse_rich("**(x)**[t](date:2026-10-01) and [**(y)**](date:2026-10-02)z"),
            '**(x)**<time datetime="2026-10-01">t</time> and <time datetime="2026-10-02">**(y)**</time>z\n',
            '<p><strong>(x)</strong><time datetime="2026-10-01">t</time> and '
            '<time datetime="2026-10-02"><strong>(y)</strong></time>z</p>\n',
            id="markers-beside-a-date-chip-stay",
        ),
    ],
)
def test_emphasis_whose_markers_github_would_not_close_is_written_as_html_tags(
    runs: ExportRich, markdown: str, html: str
) -> None:
    written = render_markdown([Paragraph(runs)])

    assert (written, _github_html(written)) == (markdown, html)


@pytest.mark.parametrize(
    ("runs", "markdown", "html"),
    [
        pytest.param(
            _spliced("*(a)*", "**b**"),
            "*(a)*<strong>b</strong>\n",
            "<p><em>(a)</em><strong>b</strong></p>\n",
            id="italic-then-bold",
        ),
        pytest.param(
            _spliced("**(a)**", "*b*"),
            "**(a)**<em>b</em>\n",
            "<p><strong>(a)</strong><em>b</em></p>\n",
            id="bold-then-italic",
        ),
        pytest.param(
            _spliced("**(a)**", "**b**"),
            "**(a)**<strong>b</strong>\n",
            "<p><strong>(a)</strong><strong>b</strong></p>\n",
            id="bold-then-bold",
        ),
        pytest.param(
            _spliced("~~(a)~~", "~~b~~"),
            "~~(a)~~<del>b</del>\n",
            "<p><s>(a)</s><del>b</del></p>\n",
            id="strike-then-strike",
        ),
        pytest.param(
            _spliced("**(a)**", "~~b~~"),
            "**(a)**~~b~~\n",
            "<p><strong>(a)</strong><s>b</s></p>\n",
            id="different-marker-characters-do-not-merge",
        ),
        pytest.param(
            _spliced("**(a)** ", "**b**"),
            "**(a)** **b**\n",
            "<p><strong>(a)</strong> <strong>b</strong></p>\n",
            id="a-space-keeps-the-markers-apart",
        ),
    ],
)
def test_emphasis_written_straight_after_emphasis_never_merges_its_markers_into_one_run(
    runs: ExportRich, markdown: str, html: str
) -> None:
    written = render_markdown([Paragraph(runs)])

    assert (written, _github_html(written)) == (markdown, html)


@pytest.mark.parametrize(
    ("body", "markdown", "html"),
    [
        pytest.param("*_b_*", "*b*\n", "<p><em>b</em></p>\n", id="italic-in-italic-is-not-bold"),
        pytest.param("_*b* c_", "*b c*\n", "<p><em>b c</em></p>\n", id="italic-opening-an-italic"),
        pytest.param("**__b__**", "**b**\n", "<p><strong>b</strong></p>\n", id="bold-in-bold"),
        pytest.param("__**b** c__", "**b c**\n", "<p><strong>b c</strong></p>\n", id="bold-opening-a-bold"),
        pytest.param("~~~~b~~~~", "~~b~~\n", "<p><s>b</s></p>\n", id="strike-in-strike-opens-no-code-fence"),
        pytest.param(
            "*a **_b_ c** d*",
            "*a **b c** d*\n",
            "<p><em>a <strong>b c</strong> d</em></p>\n",
            id="italic-two-levels-down",
        ),
    ],
)
def test_emphasis_nested_in_the_same_emphasis_is_written_once(body: str, markdown: str, html: str) -> None:
    written = markdown_of([{"type": "text", "body": body}])

    assert (written, _github_html(written)) == (markdown, html)


@pytest.mark.parametrize(
    ("body", "markdown", "html"),
    [
        pytest.param(
            "**_a_ x*y*z**",
            "**<em>a</em> x*y*z**\n",
            "<p><strong><em>a</em> x<em>y</em>z</strong></p>\n",
            id="italic-opening-a-bold",
        ),
        pytest.param(
            "**x*y*z _a_**",
            "**x*y*z <em>a</em>**\n",
            "<p><strong>x<em>y</em>z <em>a</em></strong></p>\n",
            id="italic-closing-a-bold",
        ),
        pytest.param(
            "_**a** x**y**z_",
            "*<strong>a</strong> x**y**z*\n",
            "<p><em><strong>a</strong> x<strong>y</strong>z</em></p>\n",
            id="bold-opening-an-italic",
        ),
        pytest.param(
            "**_a_ ~~b~~**",
            "**<em>a</em> ~~b~~**\n",
            "<p><strong><em>a</em> <s>b</s></strong></p>\n",
            id="italic-opening-a-bold-that-ends-in-a-strike",
        ),
        pytest.param(
            "**~~a~~ b**",
            "**~~a~~ b**\n",
            "<p><strong><s>a</s> b</strong></p>\n",
            id="a-different-marker-character-keeps-its-markers",
        ),
        pytest.param(
            "**x _a_ y**",
            "**x *a* y**\n",
            "<p><strong>x <em>a</em> y</strong></p>\n",
            id="away-from-the-edge-keeps-its-markers",
        ),
        pytest.param(
            "**++*a*++**",
            "**<ins><em>a</em></ins>**\n",
            "<p><strong><ins><em>a</em></ins></strong></p>\n",
            id="italic-inside-an-underline-at-the-edge-of-a-bold",
        ),
    ],
)
def test_emphasis_at_the_edge_of_emphasis_sharing_its_marker_character_is_written_as_html_tags(
    body: str, markdown: str, html: str
) -> None:
    written = markdown_of([{"type": "text", "body": body}])

    assert (written, _github_html(written)) == (markdown, html)


COUNTS_HEADING: dict[str, Any] = {"type": "heading", "text": "Counts", "id": "counts"}


@pytest.mark.parametrize(
    ("body", "markdown", "html"),
    [
        pytest.param(
            "**[*a*](https://x.io)**",
            "**[*a*](https://x.io)**\n",
            '<p><strong><a href="https://x.io"><em>a</em></a></strong></p>\n',
            id="italic-in-a-link-label-in-a-bold",
        ),
        pytest.param(
            "*[_a_](https://x.io)*",
            "*[a](https://x.io)*\n",
            '<p><em><a href="https://x.io">a</a></em></p>\n',
            id="italic-in-a-link-label-in-an-italic",
        ),
        pytest.param(
            "**[*a*](#counts)**",
            "**[*a*](#counts)**\n",
            '<p><strong><a href="#counts"><em>a</em></a></strong></p>\n',
            id="italic-in-an-anchor-link-label-in-a-bold",
        ),
    ],
)
def test_emphasis_inside_a_link_label_keeps_its_markers_since_the_bracket_parts_it_from_the_enclosing_marker(
    body: str, markdown: str, html: str
) -> None:
    written = markdown_of([COUNTS_HEADING, {"type": "text", "body": body}]).split("\n\n", 1)[1]

    assert (written, _github_html(written)) == (markdown, html)


def test_the_label_of_an_anchor_link_to_no_heading_is_read_with_the_emphasis_around_it() -> None:
    italic_label = (Styled("italic", (Plain("a"),)),)
    paragraph = Paragraph((Styled("bold", (AnchorLink(italic_label, "nowhere"),)),))

    written = render_markdown([paragraph])

    assert (written, _github_html(written)) == ("**<em>a</em>**\n", "<p><strong><em>a</em></strong></p>\n")


@pytest.mark.parametrize(
    ("runs", "markdown", "html"),
    [
        pytest.param(
            (
                Styled(
                    "bold",
                    (Plain("x "), Styled("italic", (Plain("a"),)), Styled("italic", (Plain(" "),))),
                ),
            ),
            "**x <em>a</em>** \n",
            "<p><strong>x <em>a</em></strong></p>\n",
            id="italic-before-a-trailing-blank-italic-closes-the-bold",
        ),
        pytest.param(
            (Plain("x"), Styled("bold", (Plain("(a)"),)), Styled("bold", (Plain("b"),))),
            "x<strong>(a)</strong>**b**\n",
            "<p>x<strong>(a)</strong><strong>b</strong></p>\n",
            id="bold-straight-after-a-bold-written-as-tags-keeps-its-markers",
        ),
    ],
)
def test_emphasis_beside_emphasis_that_writes_no_marker_is_judged_on_what_is_written(
    runs: ExportRich, markdown: str, html: str
) -> None:
    written = render_markdown([Paragraph(runs)])

    assert (written, _github_html(written)) == (markdown, html)


@pytest.mark.parametrize(
    ("body", "markdown", "html"),
    [
        pytest.param(
            "“**(a)**” and —**(b)**—",
            "“**(a)**” and —**(b)**—\n",
            "<p>“<strong>(a)</strong>” and —<strong>(b)</strong>—</p>\n",
            id="non-ascii-punctuation",
        ),
    ],
)
def test_emphasis_beside_non_ascii_punctuation_keeps_its_markers(body: str, markdown: str, html: str) -> None:
    written = markdown_of([{"type": "text", "body": body}])

    assert (written, _github_html(written)) == (markdown, html)


@pytest.mark.parametrize(
    ("inner", "before", "after", "flanks"),
    [
        pytest.param("(a)", "€", "\n", False, id="a-currency-symbol-before-is-not-certain-punctuation"),
        pytest.param("(a)", "\n", "€", False, id="a-currency-symbol-after-is-not-certain-punctuation"),
        pytest.param("€a", "x", "\n", False, id="a-symbol-opening-the-text-needs-a-punctuation-neighbour"),
        pytest.param("€a", " ", "\n", True, id="a-symbol-opening-the-text-after-a-space"),
        pytest.param("a€", "\n", "x", False, id="a-symbol-closing-the-text-needs-a-neighbour"),
        pytest.param(" (a) ", "x", "y", True, id="spaces-inside-the-emphasis-count-as-its-neighbours"),
        pytest.param("(a)", "x", "y", False, id="no-spaces-inside-and-letters-around"),
        pytest.param("a", "x", "y", True, id="letters-inside-need-no-neighbour"),
        pytest.param("  ", "x", "y", True, id="only-spaces-has-no-marker-to-break"),
        pytest.param("(a)", "", "", False, id="an-empty-neighbour-is-not-punctuation"),
        pytest.param("(a)", "", " ", False, id="an-empty-neighbour-before-is-not-punctuation"),
        pytest.param("(a)", " ", "", False, id="an-empty-neighbour-after-is-not-punctuation"),
        pytest.param("a", "", "", True, id="letters-inside-need-no-neighbour-at-all"),
        pytest.param("(a)", "$", "!", True, id="ascii-punctuation-neighbours"),
        pytest.param(
            "(a)",
            "\N{LINE SEPARATOR}",
            "\n",
            False,
            id="a-line-separator-before-is-not-commonmark-whitespace",
        ),
        pytest.param(
            "(a)", "\n", "\N{NEXT LINE}", False, id="a-next-line-control-after-is-not-commonmark-whitespace"
        ),
        pytest.param(
            "(a)", "\N{IDEOGRAPHIC SPACE}", "\t", True, id="an-ideographic-space-and-a-tab-are-whitespace"
        ),
    ],
)
def test_markers_flank_only_when_the_neighbours_let_github_open_and_close_them(
    inner: str, before: str, after: str, flanks: bool
) -> None:
    assert markers_flank(inner, before, after) is flanks


@pytest.mark.parametrize(
    ("following", "written"),
    [
        pytest.param(".", "🔵 **(x)**.\n", id="before-punctuation"),
        pytest.param("y", "🔵 <strong>(x)</strong>y\n", id="before-a-letter"),
    ],
)
def test_a_bold_chip_directly_before_text_is_written_as_the_neighbour_allows(
    following: str, written: str
) -> None:
    assert render_markdown([Paragraph((Chip("(x)", "blue"), Plain(following)))]) == written


def test_a_table_of_contents_alternates_markers_with_the_bullet_lists_around_it() -> None:
    contents = TableOfContents((TocEntry("x", (Plain("Intro"),)),))

    assert render_markdown([make_bullets("a"), contents, make_bullets("b")]) == "- a\n\n* Intro\n\n- b\n"


def test_bold_after_a_dollar_sign_keeps_its_markers_because_ascii_punctuation_closes_the_gap() -> None:
    written = markdown_of([{"type": "text", "body": "$**(a)**"}])

    assert (written, _github_html(written)) == ("\\$**(a)**\n", "<p>$<strong>(a)</strong></p>\n")


@pytest.mark.parametrize(
    "nodes",
    [
        pytest.param(
            [make_bullets("a"), Toggle((), None, (make_bullets("x"),)), make_bullets("z")],
            id="toggle-with-an-empty-title",
        ),
        pytest.param(
            [make_bullets("a"), Tabs((Tab((), (make_bullets("x"),)),)), make_bullets("z")],
            id="tab-with-an-empty-title",
        ),
    ],
)
def test_a_list_either_side_of_a_block_with_an_empty_title_stays_a_separate_list(nodes: list[Node]) -> None:
    assert render_markdown(nodes) == "- a\n\n* x\n\n- z\n"


def test_a_tab_with_an_empty_title_passes_the_list_before_it_through() -> None:
    tabs = Tabs((Tab((), (make_bullets("y"),)),))

    assert render_markdown([make_bullets("x"), tabs]) == "- x\n\n* y\n"


def test_a_paragraph_nested_in_callouts_is_rendered_once(monkeypatch: pytest.MonkeyPatch) -> None:
    rendered: list[str] = []

    def spy(text: str) -> str:
        rendered.append(text)
        return text

    monkeypatch.setattr(markdown_module, "escape_block_start", spy)
    inner = Callout("info", (make_paragraph("deep"),))
    outer = Callout("info", (Callout("info", (inner,)),))

    render_markdown([outer])

    assert rendered == ["deep"]


@pytest.mark.parametrize(
    ("node", "markdown"),
    [
        pytest.param(
            Callout("info", (ListNode("bullet", ()),)), "> [!NOTE]\n", id="callout-with-nothing-to-say"
        ),
        pytest.param(
            Callout("warning", (Paragraph((Plain("careful"),)),)),
            "> [!WARNING]\n> careful\n",
            id="callout-paragraph",
        ),
        pytest.param(Quote((Paragraph((Plain("said"),)),)), "> said\n", id="quote"),
        pytest.param(
            Toggle((Plain("Legend"),), None, (Paragraph((Plain("x"),)),)),
            "<details>\n<summary>Legend</summary>\n\nx\n\n</details>\n",
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


def test_a_collapsed_toggle_is_a_details_block_with_its_title_as_the_summary() -> None:
    toggle = make_toggle({"type": "text", "body": "x"}, title="Raw counts")

    assert markdown_of([toggle]) == ("<details>\n<summary>Raw counts</summary>\n\nx\n\n</details>\n")


def test_an_open_toggle_is_a_details_block_that_starts_open() -> None:
    toggle = make_toggle({"type": "text", "body": "x"}, title="Raw counts", collapsed=False)

    assert markdown_of([toggle]) == ("<details open>\n<summary>Raw counts</summary>\n\nx\n\n</details>\n")


def test_toggles_nested_three_deep_are_nested_details_blocks() -> None:
    innermost = make_toggle({"type": "text", "body": "z"}, title="Third")
    middle = make_toggle(innermost, title="Second")
    outer = make_toggle(middle, title="First", collapsed=False)

    assert markdown_of([outer]) == (
        "<details open>\n<summary>First</summary>\n\n"
        "<details>\n<summary>Second</summary>\n\n"
        "<details>\n<summary>Third</summary>\n\nz\n\n</details>\n\n"
        "</details>\n\n"
        "</details>\n"
    )


def test_a_toggle_with_no_content_is_a_summary_alone() -> None:
    toggle = Toggle((Plain("Empty"),), None, ())

    assert render_markdown([toggle]) == "<details>\n<summary>Empty</summary>\n</details>\n"


def test_a_toggle_title_is_written_as_html_since_a_summary_reads_no_markdown() -> None:
    title = (
        Plain("a<b & "),
        Styled("bold", (Plain("c"),)),
        Plain(" "),
        Link((Plain("docs"),), "https://example.com/a b"),
        Plain(" "),
        Code("x"),
        Plain(" "),
        Tinted(None, "sky", (Plain("hot"),)),
    )
    toggle = Toggle(title, None, (Paragraph((Plain("x"),)),))

    assert render_markdown([toggle]) == (
        '<details>\n<summary>a&lt;b &amp; <strong>c</strong> <a href="https://example.com/a%20b">docs</a> '
        "<code>x</code> <mark>hot</mark></summary>\n\nx\n\n</details>\n"
    )


def _authored_tabs() -> dict[str, object]:
    return {
        "type": "tabs",
        "tabs": [
            {"label": "Floor", "tone": "warning", "blocks": [{"type": "text", "body": "a"}]},
            {"label": "System", "tone": "accent", "blocks": [{"type": "text", "body": "b"}]},
            {"label": "Vendor", "blocks": [{"type": "text", "body": "c"}]},
        ],
    }


def test_authored_tabs_are_a_details_block_per_tab_with_the_first_open_and_the_tone_icon_in_its_title() -> (
    None
):
    assert markdown_of([_authored_tabs()]) == (
        "<details open>\n<summary>⚠️ Floor</summary>\n\na\n\n</details>\n\n"
        "<details>\n<summary>System</summary>\n\nb\n\n</details>\n\n"
        "<details>\n<summary>Vendor</summary>\n\nc\n\n</details>\n"
    )


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


def test_a_web_image_is_a_markdown_image_with_its_caption_in_italics_below() -> None:
    block = {
        "type": "image",
        "src": "https://example.com/aisle.png",
        "alt": "Aisle 12",
        "caption": "Overflow bins",
    }

    assert markdown_of([block]) == "![Aisle 12](https://example.com/aisle.png)\n\n*Overflow bins*\n"


def test_a_web_image_without_a_caption_is_only_the_markdown_image() -> None:
    block = {"type": "image", "src": "https://example.com/a(1).png", "alt": "Aisle [12]"}

    assert markdown_of([block]) == "![Aisle \\[12\\]](https://example.com/a%281%29.png)\n"


@pytest.mark.parametrize(
    ("kind", "label"), [("video", "Video"), ("audio", "Audio"), ("file", "File"), ("pdf", "PDF")]
)
def test_a_media_block_is_a_labelled_link_to_its_url(kind: str, label: str) -> None:
    block = {"type": "media", "kind": kind, "src": "https://example.com/walk", "caption": "Dock walk"}

    assert markdown_of([block]) == f"{label}: [Dock walk](https://example.com/walk)\n"


def test_a_media_block_without_a_caption_links_its_own_url() -> None:
    block = {"type": "media", "kind": "pdf", "src": "https://example.com/sheet.pdf"}

    assert markdown_of([block]) == "PDF: [https://example.com/sheet.pdf](https://example.com/sheet.pdf)\n"


def test_a_media_url_is_percent_encoded_in_the_markdown_link() -> None:
    src = "https://example.com/a(1)?x=\"1\"&y=<2>&z='3'"
    block = {"type": "media", "kind": "file", "src": src, "caption": "Sheet"}

    assert markdown_of([block]) == "File: [Sheet](https://example.com/a%281%29?x=%221%22&y=%3C2%3E&z='3')\n"


@pytest.mark.parametrize(
    ("container", "heading"),
    [
        pytest.param(in_an_open_section, "## part\n\n", id="section"),
        pytest.param(in_a_grid_cell, "", id="grid"),
    ],
)
def test_a_web_image_and_a_media_block_nest_in_a_section_or_a_grid_cell(
    container: Callable[[list[dict[str, Any]]], dict[str, Any]], heading: str
) -> None:
    blocks = [
        {"type": "image", "src": "https://example.com/a.png", "alt": "A", "caption": "Cap"},
        {"type": "media", "kind": "pdf", "src": "https://example.com/s.pdf", "caption": "Sheet"},
    ]

    assert markdown_of([container(blocks)]) == (
        f"{heading}![A](https://example.com/a.png)\n\n*Cap*\n\nPDF: [Sheet](https://example.com/s.pdf)\n"
    )


def test_a_callout_is_an_alert_over_its_bold_title_and_body() -> None:
    callout = {"type": "callout", "tone": "warning", "title": "Heads up", "body": "one\n\ntwo"}

    assert markdown_of([callout]) == "> [!WARNING]\n> **Heads up**\n>\n> one\n>\n> two\n"


@pytest.mark.parametrize(
    ("tone", "alert"),
    [
        pytest.param("info", "NOTE", id="info"),
        pytest.param("sky", "NOTE", id="sky"),
        pytest.param("neutral", "NOTE", id="neutral"),
        pytest.param("success", "TIP", id="success"),
        pytest.param("teal", "TIP", id="teal"),
        pytest.param("warning", "WARNING", id="warning"),
        pytest.param("danger", "CAUTION", id="danger"),
        pytest.param("accent", "IMPORTANT", id="accent"),
    ],
)
def test_a_callout_tone_picks_its_alert_type(tone: ToneName, alert: str) -> None:
    assert render_markdown([Callout(tone, (Paragraph((Plain("x"),)),))]) == f"> [!{alert}]\n> x\n"


def test_a_note_is_a_note_alert() -> None:
    assert markdown_of([{"type": "note", "title": "Aside", "body": "text"}]) == (
        "> [!NOTE]\n> **Aside**\n>\n> text\n"
    )


def test_a_callout_and_a_note_icon_lead_the_alert_body() -> None:
    blocks = [
        {"type": "callout", "tone": "warning", "icon": "🚧", "title": "Heads up", "body": "one"},
        {"type": "note", "icon": "📌", "body": "aside"},
    ]

    assert markdown_of(blocks) == ("> [!WARNING]\n> 🚧 **Heads up**\n>\n> one\n\n> [!NOTE]\n> 📌 aside\n")


def test_an_icon_leads_an_alert_whose_first_block_is_a_list_on_a_line_of_its_own() -> None:
    callout = Callout("info", (ListNode("bullet", (ListEntry((Plain("a"),)),)),), icon="🚀")

    assert render_markdown([callout]) == "> [!NOTE]\n> 🚀\n>\n> - a\n"


def test_a_callout_with_nothing_inside_is_its_alert_line_alone() -> None:
    assert render_markdown([Callout("danger", ())]) == "> [!CAUTION]\n"


def test_a_callout_inside_a_list_item_or_a_callout_is_a_quote_led_by_its_icon() -> None:
    inner = Callout("success", (Paragraph((Plain("done"),)),))
    nodes = [
        ListNode("bullet", (ListEntry((Plain("step"),), children=(inner,)),)),
        Callout("warning", (Paragraph((Plain("outer"),)), inner)),
    ]

    assert render_markdown(nodes) == ("- step\n\n  > ✅ done\n\n> [!WARNING]\n> outer\n>\n> > ✅ done\n")


def test_a_callout_after_one_that_held_a_callout_is_an_alert_again() -> None:
    inner = Callout("success", (Paragraph((Plain("done"),)),))
    nodes = [Callout("warning", (inner,)), Callout("info", (Paragraph((Plain("later"),)),))]

    assert render_markdown(nodes) == "> [!WARNING]\n>\n> > ✅ done\n\n> [!NOTE]\n> later\n"


def test_a_quote_keeps_its_paragraphs_and_italic_cite() -> None:
    quote = {"type": "quote", "body": "first\n\nsecond", "cite": "Ops lead"}

    assert markdown_of([quote]) == "> first\n>\n> second\n>\n> *Ops lead*\n"


def test_list_lines_in_a_callout_body_become_a_list_inside_the_alert() -> None:
    callout = {"type": "callout", "tone": "info", "body": "Checks:\n- lint\n- test"}

    assert markdown_of([callout]) == "> [!NOTE]\n> Checks:\n>\n> - lint\n> - test\n"


def test_a_list_in_a_quote_is_a_markdown_list_inside_the_quote() -> None:
    quote = {"type": "quote", "body": "Said:\n- a\n- b\n\n2. c\n3. d", "cite": "Ops lead"}

    assert markdown_of([quote]) == ("> Said:\n>\n> - a\n> - b\n>\n> 2. c\n> 3. d\n>\n> *Ops lead*\n")


def test_a_nested_list_in_a_quote_nests_under_its_item() -> None:
    quote = {"type": "quote", "body": "- a\n  - b\n- c"}

    assert markdown_of([quote]) == "> - a\n>   - b\n> - c\n"


def test_a_list_in_a_table_cell_is_an_inline_ul_or_ol_after_the_cell_text() -> None:
    table = {
        "type": "table",
        "columns": [{"key": "a", "label": "A", "kind": "rich"}],
        "rows": [{"a": "Steps:\n\n2. one\n3. **two**"}, {"a": "- a | b\n  - c\n- d"}],
    }

    assert markdown_of([table]) == (
        "| A |\n| --- |\n"
        '| Steps:<br><ol start="2"><li>one</li><li>**two**</li></ol> |\n'
        "| <ul><li>a \\| b<ul><li>c</li></ul></li><li>d</li></ul> |\n"
    )


def test_a_toned_row_dots_a_cell_holding_a_list_and_strikes_its_text_when_muted() -> None:
    cell = TableCell(
        (), blocks=(Paragraph((Plain("Fix:"),)), ListNode("bullet", (ListEntry((Plain("one"),)),)))
    )
    table = TableNode(
        (TableCell((Plain("Steps"),)),), (TableRow((cell,), tone="danger"), TableRow((cell,), tone="muted"))
    )

    assert render_markdown([table]) == (
        "| Steps |\n| --- |\n"
        "| 🔴 Fix:<br><ul><li>one</li></ul> |\n"
        "| ~~Fix:~~<br><ul><li>~~one~~</li></ul> |\n"
    )


def test_a_collapsed_section_becomes_a_heading_with_its_content_below() -> None:
    section = {
        "type": "section",
        "title": "Appendix",
        "blocks": [{"type": "heading", "text": "Raw"}, {"type": "text", "body": "t"}],
    }

    assert markdown_of([section]) == "## Appendix\n\n### Raw\n\nt\n"


def test_a_panel_inside_a_section_becomes_a_callout_under_the_section_heading() -> None:
    panel = {"type": "panel", "title": "Card", "blocks": [{"type": "text", "body": "inside"}]}
    section = {"type": "section", "title": "Appendix", "blocks": [panel]}

    assert markdown_of([section]) == "## Appendix\n\n> **Card**\n>\n> inside\n"


def test_the_badge_legend_is_a_collapsed_details_block_over_its_list() -> None:
    row = {"type": "badge_row", "items": [{"key": "API"}]}

    assert markdown_of([row], badges=API_BADGES) == f"{API_LEGEND}🔵 **api**\n"


def test_every_badge_and_state_block_becomes_github_markdown() -> None:
    assert markdown_of(BADGE_AND_STATE_BLOCKS, badges=API_BADGES) == (
        f"{API_LEGEND}"
        "| Site | Owner |\n| --- | --- |\n| West | ops |\n\n"
        "- **Lead**: **Ana**\n\n"
        "<dl>\n<dt>Drift</dt>\n<dd>\n\nfirst\n\nsecond\n\n</dd>\n<dt>Gap</dt>\n<dd></dd>\n</dl>\n\n"
        "| Clean | Lag |\n| --- | --- |\n"
        "| 9 (90.0%) 🟢 **▲ +1** 🔵 **api**<br>since Monday | 3 days → flat |\n\n"
        "**Affects**: 🔵 **api** 🟢 **ops**\n\n"
        "- **Owners**: 🟣 **web**\n\n"
        "* ✅ Ship\n* ⏸️ Vendor\n\n"
        "- 🔵 **Mon**: Start 🔵 **api**\n\n  kick-off\n- Later\n\n"
        "* 🟡 **Zone**: ████░░░░░░ 42.9%\n"
    )


def test_a_fact_strip_is_a_one_row_pipe_table_with_its_labels_as_the_header() -> None:
    block = {
        "type": "fact_strip",
        "facts": [
            {"label": "Site:", "value": "West | dock"},
            {"label": "Owner", "value": "**ops**"},
            {"label": " ", "value": "no label"},
        ],
    }

    assert markdown_of([block]) == (
        "| Site | Owner |  |\n| --- | --- | --- |\n| West \\| dock | \\*\\*ops\\*\\* | no label |\n"
    )


def test_section_fields_are_a_one_row_pipe_table_under_the_heading() -> None:
    section = {
        "type": "section",
        "title": "Recount",
        "collapsed": False,
        "fields": {"status": "Open", "estimate": 3, "labels": ["a", "b"]},
        "blocks": [{"type": "text", "body": "Body."}],
    }

    assert markdown_of([section]) == (
        "## Recount\n\n| Status | Labels | Estimate |\n| --- | --- | --- |\n| Open | a, b | 3 |\n\nBody.\n"
    )


def test_cards_are_a_pipe_table_with_a_column_per_card_and_its_note_under_the_value() -> None:
    cards = {
        "type": "cards",
        "items": [
            {"label": "Clean:", "value": 9, "of": 10, "note": "since Monday", "tone": "success"},
            {"label": "Lag", "value": "3 | 4 days"},
            {"label": " ", "value": "unlabelled"},
            {"label": "Quiet", "value": ""},
        ],
    }

    assert markdown_of([cards]) == (
        "| 🟢 Clean | Lag |  | Quiet |\n| --- | --- | --- | --- |\n"
        "| 9 (90.0%)<br>since Monday | 3 \\| 4 days | unlabelled |  |\n"
    )


def test_a_derived_card_is_a_column_led_by_its_badge_chip() -> None:
    blocks = [
        {"type": "cards", "items": [{"badge": "API", "of_matrix": "m", "note": "live"}]},
        {
            "type": "matrix",
            "id": "m",
            "rows": ["r1", "r2"],
            "columns": ["c"],
            "cells": [{"row": "r1", "col": "c", "badge": "API"}],
        },
    ]

    assert markdown_of(blocks, badges=API_BADGES) == (
        f"{API_LEGEND}| 🔵 **api** |\n| --- |\n| 1 (50.0%)<br>live |\n\n"
        "|  | c |\n| --- | --- |\n| **r1** | 🔵 api |\n| **r2** |  |\n"
    )


def test_a_definition_list_is_a_dl_with_each_body_between_blank_lines_in_its_dd() -> None:
    block = {
        "type": "def_list",
        "items": [
            {"term": "Drift & gap:", "body": "first **bold**\n\n- a\n- b"},
            {"term": "Open", "body": " "},
        ],
    }

    assert markdown_of([block]) == (
        "<dl>\n<dt>Drift &amp; gap</dt>\n<dd>\n\nfirst **bold**\n\n- a\n- b\n\n</dd>\n"
        "<dt>Open</dt>\n<dd></dd>\n</dl>\n"
    )


def test_a_list_after_a_definition_list_starts_with_the_first_marker_again() -> None:
    blocks = [
        {"type": "list", "items": ["a"]},
        {"type": "def_list", "items": [{"term": "T", "body": "b"}]},
        {"type": "list", "items": ["c"]},
    ]

    assert markdown_of(blocks) == "- a\n\n<dl>\n<dt>T</dt>\n<dd>\n\nb\n\n</dd>\n</dl>\n\n- c\n"


def test_a_badge_is_its_dot_and_bold_label_and_a_label_colon_is_not_doubled() -> None:
    row = {"type": "badge_row", "label": "Affects:", "items": [{"label": "api", "tone": "blue"}]}

    assert markdown_of([row]) == "**Affects**: 🔵 **api**\n"


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
        pytest.param("x² ½ ①", "x--", id="other-numbers-go"),
        pytest.param("a⓪b", "ab", id="circled-zero-just-after-the-circled-letters-goes"),
        pytest.param("a⒵b", "ab", id="parenthesized-z-just-before-the-circled-letters-goes"),
        pytest.param("a🅊b", "ab", id="squared-letter-range-end-goes"),
        pytest.param("a🄯b", "ab", id="copyleft-just-before-the-squared-letters-goes"),
        pytest.param("a🅪b", "ab", id="raised-mc-sign-after-the-circled-negative-letters-goes"),
        pytest.param("a🆊b", "ab", id="crossed-negative-squared-p-after-the-negative-squared-letters-goes"),
        pytest.param("a🅏b", "ab", id="squared-wc-just-before-the-circled-negative-letters-goes"),
        pytest.param("a🅩b", "a🅩b", id="last-circled-negative-letter-stays"),
        pytest.param("a🅯b", "ab", id="circled-human-figure-after-the-circled-negative-letters-goes"),
        pytest.param("a🅐b", "a🅐b", id="first-circled-negative-letter-stays"),
        pytest.param("Step ① one", "step--one", id="circled-digit-goes"),
        pytest.param("Ⅻ and ٣", "ⅻ-and-٣", id="letter-numbers-and-decimal-digits-stay"),
        pytest.param("Ⓔⓘ 🄺", "ⓔⓘ-🄺", id="circled-and-squared-letters-stay"),
        pytest.param("Ⓐ-Ⓩ", "ⓐ-ⓩ", id="the-first-and-last-circled-capitals-stay"),
        pytest.param("🄰🅉 🅐🆉 🅰🆉", "🄰🅉-🅐🆉-🅰🆉", id="squared-and-negative-letters-stay"),
        pytest.param("a ☎ ✅ b", "a---b", id="other-symbols-go"),
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


def test_a_link_reaches_a_heading_inside_a_tab_and_a_same_named_heading_after_it_is_numbered() -> None:
    blocks = [
        {"type": "text", "body": "jump to [scan](#scan) or [the second](#scan-2)"},
        make_tabs(
            make_tab("Floor", {"type": "heading", "level": 3, "text": "Scan"}),
            make_tab("System", {"type": "text", "body": "sys"}),
        ),
        {"type": "heading", "text": "Scan"},
    ]

    assert markdown_of(blocks) == (
        "jump to [scan](#scan) or [the second](#scan-1)\n\n"
        "<details open>\n<summary>Floor</summary>\n\n### Scan\n\n</details>\n\n"
        "<details>\n<summary>System</summary>\n\nsys\n\n</details>\n\n## Scan\n"
    )


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
        {"type": "key_value", "pairs": [{"label": "Site", "value": "West"}]},
        {"type": "heading", "text": "A"},
    ]

    assert markdown_of(blocks, meta={"title": "T", "toc": True}) == "- [A](#a)\n\n* **Site**: West\n\n## A\n"


def test_a_page_with_no_toc_entries_drops_the_table_of_contents() -> None:
    assert markdown_of([{"type": "text", "body": "only"}], meta={"title": "T", "toc": True}) == "only\n"
