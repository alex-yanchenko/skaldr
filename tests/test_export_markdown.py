from pathlib import Path

import pytest

from skaldr.export import export_markdown
from skaldr.export.markdown import github_heading_slugs, github_slug, markdown_inline, render_markdown
from skaldr.export.markup import code_span
from skaldr.export.tree import Callout, Heading, ListNode, Paragraph, Quote, Toggle
from skaldr.models import load_report, parse_report
from skaldr.richtext import AnchorLink, Citation, Link, Placeholder, Plain, Styled, parse_rich
from tests.conftest import REPO_ROOT
from tests.factories import make_command_request, make_report, markdown_of

EXAMPLE = REPO_ROOT / "data" / "example.yaml"
MARKDOWN_GOLDEN = REPO_ROOT / "tests" / "golden" / "example.markdown"


def test_the_example_exports_to_the_markdown_golden_regenerated_by_the_export_command(tmp_path: Path) -> None:
    export_markdown(load_report(EXAMPLE), tmp_path)

    assert {path.name: path.read_text(encoding="utf-8") for path in sorted(tmp_path.iterdir())} == {
        path.name: path.read_text(encoding="utf-8") for path in sorted(MARKDOWN_GOLDEN.iterdir())
    }


def test_the_page_starts_with_the_title_as_its_only_top_level_heading(tmp_path: Path) -> None:
    report = parse_report(make_report(meta={"title": "Q3 *count*"}))

    (page,) = export_markdown(report, tmp_path).files

    assert page.read_text(encoding="utf-8") == "# Q3 \\*count\\*\n\nHello.\n"


def test_markdown_special_characters_are_escaped_in_text_but_not_in_code_or_link_urls() -> None:
    text = r"a *b* c_d [x] <y> ~n c:\d and `a*b [c]` via [x_y](https://example.com/a_b?q=[1])"

    assert markdown_inline(parse_rich(text)) == (
        r"a *b* c\_d \[x\] \<y\> \~n c:\\d and `a*b [c]` via [x\_y](https://example.com/a_b?q=[1])"
    )


def test_inline_runs_become_markdown() -> None:
    runs = (
        Citation("a", 1, "https://example.com/a b"),
        Plain(" "),
        Citation("b", 2),
        Plain(" "),
        Placeholder("owner"),
        Plain(" "),
        Styled("strike", (Plain("old"),)),
        Plain(" "),
        Link((Plain("paren"),), "https://example.com/(x)"),
        Plain(" "),
        AnchorLink((Plain("method"),), "method"),
        Plain(" "),
        AnchorLink((Plain("gone"),), "nowhere"),
    )

    assert markdown_inline(runs, {"method": "how-we-count"}) == (
        r"[\[1\]](<https://example.com/a b>) \[2\] `{{owner}}` ~~old~~ [paren](<https://example.com/(x)>) "
        "[method](#how-we-count) gone"
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


def test_a_heading_ending_in_hashes_keeps_them() -> None:
    assert markdown_of([{"type": "heading", "text": "Issue #"}]) == "## Issue \\#\n"


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
    ]

    assert render_markdown(nodes) == "> 💡\n\n> ⚠️ careful\n\n> said\n\n**Legend**\n\nx\n"


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
    badges = {"API": {"label": "api", "tone": "blue", "legend": "the API"}}
    row = {"type": "badge_row", "items": [{"key": "API"}]}

    assert (
        markdown_of([row], badges=badges)
        == "**api**\n\n**Legend: badges used on this page**\n\n- **api** the API\n"
    )


def test_a_request_with_several_cases_lists_each_case_under_a_bold_title() -> None:
    cases = [
        {"label": "finding", "tone": "warning", "response": {"body": "[]"}},
        {"label": "control", "tone": "success", "response": {"body": "none"}},
    ]
    request = make_command_request(cases=cases, command="list-tiers")

    assert markdown_of([request]) == (
        "**Tier mappings on the partner API**\n\n"
        "**⚠️ finding**\n\n```bash\nlist-tiers\n```\n\n**Output**\n\n```json\n[]\n```\n\n"
        "**✅ control**\n\n```bash\nlist-tiers\n```\n\n**Output**\n\n```\nnone\n```\n"
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
