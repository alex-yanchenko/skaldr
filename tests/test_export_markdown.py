from pathlib import Path

import pytest

from skaldr.export import ExportResult, export_markdown
from skaldr.export.markdown import github_heading_slugs, github_slug, render_markdown
from skaldr.export.markup import code_block_lines, code_span, styled
from skaldr.export.tree import (
    Callout,
    CodeBlock,
    Heading,
    ListEntry,
    ListKind,
    ListNode,
    Paragraph,
    Quote,
    TableOfContents,
    TocEntry,
    Toggle,
)
from skaldr.models import parse_report
from skaldr.richtext import AnchorLink, Citation, Link, Placeholder, Plain, Rich, Run, Styled, parse_rich
from tests.factories import make_report, markdown_of


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
    runs: Rich = (
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
        Plain(" see!"),
        Link((Plain("img"),), "https://e.com/x.png"),
    )
    nodes = [Heading(2, (Plain("How we count"),), "method"), Paragraph(runs)]

    assert render_markdown(nodes) == (
        "## How we count\n\n"
        r"[\[1\]](https://example.com/a%20b) \[2\] `{{owner}}` ~~old~~ "
        "[paren](https://example.com/%28x%29%3E) "
        "[method](#how-we-count) gone see\\![img](https://e.com/x.png)\n"
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


def test_a_bang_ending_text_is_escaped_even_with_nothing_after_it() -> None:
    assert markdown_of([{"type": "text", "body": "Done!"}]) == "Done\\!\n"


def test_a_backslash_in_a_link_target_is_percent_encoded_so_it_stays_in_the_url() -> None:
    assert render_markdown([Paragraph((Link((Plain("x"),), "https://e.com/a\\"),))]) == (
        "[x](https://e.com/a%5C)\n"
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
    blocks = [{"type": "list", "items": ["West"]}, {"type": "heading", "text": "A"}]

    assert markdown_of(blocks, meta={"title": "T", "toc": True}) == "- [A](#a)\n\n* West\n\n## A\n"


def test_a_page_with_no_toc_entries_drops_the_table_of_contents() -> None:
    assert markdown_of([{"type": "text", "body": "only"}], meta={"title": "T", "toc": True}) == "only\n"
