from pathlib import Path
from typing import Any

import pytest

from skaldr.export import export_markdown
from skaldr.export.inline import InlineContext, parse_rich
from skaldr.export.lower import lower_report
from skaldr.export.markdown import code_span, github_slug, markdown_inline, render_markdown
from skaldr.models import load_report, parse_report
from tests.conftest import REPO_ROOT
from tests.factories import make_command_request, make_report

EXAMPLE = REPO_ROOT / "data" / "example.yaml"
MARKDOWN_GOLDEN = REPO_ROOT / "tests" / "golden" / "example.markdown"
NO_CONTEXT = InlineContext(citation_numbers={}, citation_urls={}, anchor_ids=frozenset())


def _markdown(blocks: list[dict[str, Any]], **meta: Any) -> str:
    return render_markdown(lower_report(parse_report(make_report(blocks=blocks, **meta))))


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

    assert markdown_inline(parse_rich(text, NO_CONTEXT)) == (
        r"a *b* c\_d \[x\] \<y\> \~n c:\\d and `a*b [c]` via [x\_y](https://example.com/a_b?q=[1])"
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
        pytest.param("1. not a list", "1\\. not a list", id="ordered"),
        pytest.param("# not a heading", "\\# not a heading", id="hash"),
        pytest.param("--- not a rule", "\\--- not a rule", id="rule"),
        pytest.param("-5 degrees", "-5 degrees", id="negative-number"),
    ],
)
def test_a_paragraph_that_starts_like_a_block_marker_stays_a_paragraph(body: str, line: str) -> None:
    assert _markdown([{"type": "text", "body": body}]) == f"{line}\n"


def test_a_heading_ending_in_hashes_keeps_them() -> None:
    assert _markdown([{"type": "heading", "text": "Issue #"}]) == "## Issue \\#\n"


def test_a_table_is_a_pipe_table_with_pipes_escaped_in_text_and_code() -> None:
    table = {
        "type": "table",
        "columns": [{"key": "a", "label": "Name"}, {"key": "n", "label": "Units", "kind": "number"}],
        "rows": [{"a": "a|b and `x|y`", "n": 2}, {"a": "two\n\nlines", "n": 3}],
        "totals": {"column": "n"},
    }

    assert _markdown([table]).splitlines() == [
        "| Name | Units |",
        "| --- | --- |",
        "| a\\|b and `x\\|y` | 2 |",
        "| two<br>lines | 3 |",
        "| **Total** | **5** |",
    ]


def test_nested_list_children_indent_to_the_content_column_of_their_marker() -> None:
    block = {
        "type": "list",
        "style": "number",
        "items": [{"text": "parent", "items": ["child", {"text": "mid", "items": ["leaf"]}]}],
    }

    assert _markdown([block]) == "1. parent\n   1. child\n   2. mid\n      1. leaf\n"


def test_a_check_list_becomes_a_task_list() -> None:
    block = {"type": "list", "style": "check", "items": [{"text": "done", "checked": True}, "open"]}

    assert _markdown([block]) == "- [x] done\n- [ ] open\n"


def test_back_to_back_lists_of_one_kind_switch_markers_so_they_stay_two_lists() -> None:
    blocks = [
        {"type": "list", "items": ["a"]},
        {"type": "list", "items": ["b"]},
        {"type": "list", "items": ["c"]},
        {"type": "list", "style": "number", "items": ["d"]},
        {"type": "list", "style": "number", "items": ["e"]},
    ]

    assert _markdown(blocks) == "- a\n\n* b\n\n- c\n\n1. d\n\n1) e\n"


def test_a_callout_is_a_blockquote_led_by_its_icon_and_bold_title() -> None:
    callout = {"type": "callout", "tone": "warning", "title": "Heads up", "body": "one\n\ntwo"}

    assert _markdown([callout]) == "> ⚠️ **Heads up**\n>\n> one\n>\n> two\n"


def test_a_quote_keeps_its_paragraphs_and_italic_cite() -> None:
    quote = {"type": "quote", "body": "first\n\nsecond", "cite": "Ops lead"}

    assert _markdown([quote]) == "> first\n>\n> second\n>\n> *Ops lead*\n"


def test_a_collapsed_section_becomes_a_heading_with_its_content_below() -> None:
    section = {
        "type": "section",
        "title": "Appendix",
        "blocks": [{"type": "heading", "text": "Raw"}, {"type": "text", "body": "t"}],
    }

    assert _markdown([section]) == "## Appendix\n\n### Raw\n\nt\n"


def test_the_badge_legend_is_a_bold_title_over_its_list() -> None:
    badges = {"API": {"label": "api", "tone": "blue", "legend": "the API"}}
    row = {"type": "badge_row", "items": [{"key": "API"}]}

    assert _markdown([row], badges=badges).split("\n\n")[1:] == [
        "**Legend: badges used on this page**",
        "- **api** the API\n",
    ]


def test_a_request_with_several_cases_lists_each_case_under_a_bold_title() -> None:
    cases = [
        {"label": "finding", "tone": "warning", "response": {"body": "[]"}},
        {"label": "control", "tone": "success", "response": {"body": "[1]"}},
    ]

    lines = _markdown([make_command_request(cases=cases)]).splitlines()

    assert [line for line in lines if line.startswith("**⚠️") or line.startswith("**✅")] == [
        "**⚠️ finding**",
        "**✅ control**",
    ]


def test_a_grid_becomes_its_cells_in_order() -> None:
    grid = {
        "type": "grid",
        "cells": [
            {"span": 2, "blocks": [{"type": "text", "body": "a"}]},
            {"span": 4, "blocks": [{"type": "text", "body": "b"}]},
        ],
    }

    assert _markdown([grid]) == "a\n\nb\n"


def test_a_flow_keeps_its_mermaid_and_the_detail_mermaid_cannot_show() -> None:
    flow = {
        "type": "flow",
        "numbered": False,
        "steps": [{"label": "Scan", "points": ["by aisle"]}, {"label": "Fix"}],
    }

    assert _markdown([flow]) == (
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


def test_a_badge_is_a_bold_label() -> None:
    row = {"type": "badge_row", "label": "Affects:", "items": [{"label": "api", "tone": "blue"}]}

    assert _markdown([row]) == "**Affects**: **api**\n"


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


def test_the_table_of_contents_links_each_heading_with_repeats_numbered() -> None:
    blocks = [
        {"type": "heading", "text": "Overview"},
        {"type": "heading", "text": "Detail", "level": 3},
        {"type": "heading", "text": "Overview"},
    ]

    text = _markdown(blocks, meta={"title": "T", "toc": True})

    assert text.split("\n\n")[0].splitlines() == [
        "- [Overview](#overview)",
        "  - [Detail](#detail)",
        "- [Overview](#overview-1)",
    ]


def test_a_list_right_after_the_table_of_contents_stays_its_own_list() -> None:
    blocks = [
        {"type": "fact_strip", "facts": [{"label": "Site", "value": "West"}]},
        {"type": "heading", "text": "A"},
    ]

    assert _markdown(blocks, meta={"title": "T", "toc": True}).split("\n\n")[:2] == [
        "- [A](#a)",
        "* **Site**: West",
    ]


def test_a_page_with_no_headings_drops_the_table_of_contents() -> None:
    assert _markdown([{"type": "text", "body": "only"}], meta={"title": "T", "toc": True}) == "only\n"
