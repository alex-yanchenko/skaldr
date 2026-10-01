from pathlib import Path

import pytest

from skaldr.export import ExportResult, export_markdown
from skaldr.export.markdown import github_heading_slugs, github_slug, render_markdown
from skaldr.export.markup import code_block_lines, code_span, styled
from skaldr.export.runs import ExportRich, Gauge, Mark
from skaldr.export.tree import (
    Callout,
    CodeBlock,
    Heading,
    ListEntry,
    ListNode,
    Paragraph,
    Quote,
    Toggle,
)
from skaldr.models import parse_report
from skaldr.richtext import AnchorLink, Citation, Link, Placeholder, Plain, Styled, parse_rich
from tests.factories import API_BADGES, make_report, markdown_of


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


def test_inline_runs_become_markdown() -> None:
    runs: ExportRich = (
        Citation("a", 1, "https://example.com/a b"),
        Plain(" "),
        Citation("b", 2),
        Plain(" "),
        Placeholder("owner"),
        Plain(" "),
        Styled("strike", (Plain("old"),)),
        Plain(" "),
        Link((Plain("paren"),), "https://example.com/(x)>"),
        Plain(" "),
        AnchorLink((Plain("method"),), "method"),
        Plain(" "),
        AnchorLink((Plain("gone"),), "nowhere"),
        Mark("delta", "up"),
        Gauge(10, 10),
        Plain(" see!"),
        Link((Plain("img"),), "https://e.com/x.png"),
    )
    nodes = [Heading(2, (Plain("How we count"),), "method"), Paragraph(runs)]

    assert render_markdown(nodes).split("\n\n")[1] == (
        r"[\[1\]](https://example.com/a%20b) \[2\] `{{owner}}` ~~old~~ "
        "[paren](https://example.com/%28x%29%3E) "
        "[method](#how-we-count) gone▲██████████ see\\![img](https://e.com/x.png)\n"
    )


@pytest.mark.parametrize(
    ("text", "span"),
    [
        pytest.param("plain", "`plain`", id="no-backtick"),
        pytest.param("a`b", "``a`b``", id="inner-backtick"),
        pytest.param("`edge", "`` `edge ``", id="leading-backtick"),
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


def test_styled_text_keeps_surrounding_spaces_outside_its_markers() -> None:
    assert (styled("bold", " x "), styled("italic", "  ")) == (" **x** ", "  ")


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


def test_a_check_list_becomes_a_task_list() -> None:
    block = {"type": "list", "style": "check", "items": [{"text": "done", "checked": True}, "open"]}

    assert markdown_of([block]) == "- [x] done\n- [ ] open\n"


def test_back_to_back_lists_switch_markers_so_they_stay_separate_lists() -> None:
    blocks = [
        {"type": "list", "items": ["a"]},
        {"type": "list", "items": ["b"]},
        {"type": "list", "style": "check", "items": ["c"]},
        {"type": "list", "style": "number", "items": ["d"]},
        {"type": "list", "style": "number", "items": ["e"]},
    ]

    assert markdown_of(blocks) == "- a\n\n* b\n\n- [ ] c\n\n1. d\n\n1) e\n"


def test_block_nodes_become_markdown_blocks() -> None:
    nodes = [
        Callout("info", (ListNode("bullet", ()),)),
        Callout("warning", (Paragraph((Plain("careful"),)),)),
        Quote(((Plain("said"),),)),
        Toggle((Plain("Legend"),), None, (Paragraph((Plain("x"),)),)),
        ListNode("bullet", (ListEntry((Plain("card"),), children=(Paragraph((Plain("note"),)),)),)),
    ]

    assert render_markdown(nodes) == "> 💡\n\n> ⚠️ careful\n\n> said\n\n**Legend**\n\nx\n\n- card\n\n  note\n"


def test_a_callout_is_a_blockquote_led_by_its_icon_and_bold_title() -> None:
    callout = {"type": "callout", "tone": "warning", "title": "Heads up", "body": "one\n\ntwo"}

    assert markdown_of([callout]) == "> ⚠️ **Heads up**\n>\n> one\n>\n> two\n"


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
        == "**api**\n\n**Legend: badges used on this page**\n\n- **api** the API\n"
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
    ],
)
def test_a_heading_slug_follows_github(heading: str, slug: str) -> None:
    assert github_slug(heading) == slug


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
