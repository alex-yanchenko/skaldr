import json
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import get_args

import pytest

from skaldr.export import EXPORT_MANIFEST, ExportResult, export_markdown, export_notion
from skaldr.export.markup import CALLOUT_ICON
from skaldr.export.notion import NotionChunks, chunk_notion, notion_inline, render_notion
from skaldr.export.runs import Break, Chip, ExportRich, Gauge, StatusMark
from skaldr.export.tree import (
    Callout,
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
    TableRow,
    Tabs,
    Toggle,
    ToneName,
)
from skaldr.models import (
    AnyBlock,
    BadgeColorLiteral,
    Grid,
    InnerGrid,
    Panel,
    Section,
    Walkthrough,
    load_report,
    parse_report,
)
from skaldr.richtext import AnchorLink, Citation, Placeholder, Plain, ScriptText, parse_rich
from tests.conftest import REPO_ROOT
from tests.factories import (
    API_BADGES,
    BADGE_AND_STATE_BLOCKS,
    folder_texts,
    heading_sections,
    lowered,
    make_command_request,
    make_report,
    notion_of,
)

EXAMPLE = REPO_ROOT / "data" / "example.yaml"
NOTION_GOLDEN = REPO_ROOT / "tests" / "golden" / "example.notion"
CHUNK_THAT_SPLITS_EVERY_SECTION = 100
CHUNK_THAT_HOLDS_THE_WHOLE_PAGE = 100_000
NESTING_TOO_DEEP_TO_PARSE = 100_000
NOTION_CHIP_COLOR: dict[str, str] = {
    "slate": "gray",
    "blue": "blue",
    "green": "green",
    "amber": "yellow",
    "red": "red",
    "violet": "purple",
    "teal": "green",
    "sky": "blue",
}


def _section_text(title: str, body: str, rows: int) -> str:
    return f"## {title}\n```\n" + f"{body}\n" * rows + "```\n"


@pytest.mark.parametrize(
    ("text", "notion"),
    [
        pytest.param("edit README.md first", "edit `README.md` first", id="markdown-file"),
        pytest.param("run scripts/setup.sh:12", "run `scripts/setup.sh:12`", id="shell-file-with-line"),
        pytest.param("see app.py", "see `app.py`", id="python-file"),
        pytest.param("`notes.md` stays one span", "`notes.md` stays one span", id="already-code"),
        pytest.param("a readme file", "a readme file", id="no-extension"),
    ],
)
def test_a_file_name_notion_would_turn_into_a_web_link_becomes_inline_code(text: str, notion: str) -> None:
    assert notion_inline(parse_rich(text)) == notion


def test_notion_special_characters_are_escaped_in_text_but_not_in_code_or_link_urls() -> None:
    text = r"cost $5 [x] <y> {z} a|b 2^3 ~n c:\d and `a|b [c]` via [x|y](https://example.com/a_b?q=[1])"

    assert notion_inline(parse_rich(text)) == (
        r"cost \$5 \[x\] \<y\> \{z\} a\|b 2\^3 \~n c:\\d and `a|b [c]` via [x\|y](https://example.com/a_b?q=[1])"
    )


def test_inline_runs_become_notion_spans() -> None:
    runs: ExportRich = (
        Citation("a", 1, "https://example.com/a (b)"),
        Plain(" "),
        Citation("b", 2),
        Plain(" "),
        Placeholder("owner"),
        Plain(" "),
        Chip("api", "amber"),
        Plain(" "),
        AnchorLink((Plain("method"),), "method"),
        Break(),
        StatusMark("blocked"),
        Gauge(3, 10),
        Plain(" wow!"),
        *parse_rich("[img](https://e.com/x.png)"),
    )

    assert notion_inline(runs) == (
        r"[\[1\]](https://example.com/a%20%28b%29) \[2\] "
        '<span color="yellow_bg">\\{\\{owner\\}\\}</span> '
        '<span color="yellow_bg">api</span> method<br>⛔███░░░░░░░ wow\\![img](https://e.com/x.png)'
    )


def test_underline_is_a_notion_underline_span_and_scripts_are_inline_math() -> None:
    assert notion_inline(parse_rich("++new *one*++ H~2~O at 10^3^")) == (
        '<span underline="true">new *one*</span> H$`_{\\text{2}}`$O at 10$`^{\\text{3}}`$'
    )


@pytest.mark.parametrize(
    ("run", "written"),
    [
        pytest.param(ScriptText("subscript", "a_b"), "$`_{\\text{a\\_b}}`$", id="underscore"),
        pytest.param(ScriptText("subscript", "{x}"), "$`_{\\text{\\{x\\}}}`$", id="braces"),
        pytest.param(
            ScriptText("superscript", "\\$&#%~"),
            "$`^{\\text{\\textbackslash{}\\$\\&\\#\\%\\textasciitilde{}}}`$",
            id="backslash-dollar-ampersand-hash-percent-tilde",
        ),
        pytest.param(ScriptText("subscript", "^"), "$`_{\\text{\\textasciicircum{}}}`$", id="caret"),
    ],
)
def test_a_latex_special_character_in_a_script_is_escaped_inside_its_text_command(
    run: ScriptText, written: str
) -> None:
    assert notion_inline((run,)) == written


@pytest.mark.parametrize(
    ("text", "notion"),
    [
        pytest.param("[late]{tone=danger}", '<span color="red">late</span>', id="color"),
        pytest.param("[due]{bg=amber}", '<span color="yellow_bg">due</span>', id="highlight"),
        pytest.param(
            "[**now** a|b]{tone=accent bg=sky}",
            '<span color="purple"><span color="blue_bg">**now** a\\|b</span></span>',
            id="color-around-highlight",
        ),
        pytest.param(
            "[x]{y} [z] {tone=info}", "\\[x\\]\\{y\\} \\[z\\] \\{tone=info\\}", id="no-span-stays-prose"
        ),
        pytest.param(
            "[[a]{tone=danger}](https://x.io)",
            '[<span color="red">a</span>](https://x.io)',
            id="span-inside-a-link-label",
        ),
    ],
)
def test_an_attribute_span_is_a_notion_color_span(text: str, notion: str) -> None:
    assert notion_inline(parse_rich(text)) == notion


def test_inline_math_is_notion_inline_math_while_prose_dollars_stay_escaped() -> None:
    assert notion_inline(parse_rich("costs $5, so $`x_i < 2`$ holds")) == "costs \\$5, so $`x_i < 2`$ holds"


def test_a_math_block_is_a_notion_equation_block_indented_inside_a_callout() -> None:
    callout = {"type": "callout", "tone": "info", "body": "Rate"}
    math = {"type": "math", "expression": "a\n\n  b\n"}

    assert notion_of([math, {"type": "panel", "title": "P", "blocks": [callout, math]}]) == (
        "$$\na\n  b\n$$\n"
        '<callout icon="📝" color="gray_bg">\n\t**P**\n'
        '\t<callout icon="💡" color="blue_bg">\n\t\tRate\n\t</callout>\n'
        "\t$$\n\ta\n\t  b\n\t$$\n</callout>\n"
    )


def test_marker_characters_that_form_no_mark_stay_escaped_prose_in_notion() -> None:
    assert notion_inline(parse_rich("C++ in ~5 days, 2^10 and a ++ b ++ c")) == (
        "C++ in \\~5 days, 2\\^10 and a ++ b ++ c"
    )


def test_code_with_a_backtick_becomes_escaped_text_because_notion_has_no_longer_code_fence() -> None:
    assert notion_of([{"type": "code", "label": "a`b", "content": "x"}]) == "a\\`b\n```\nx\n```\n"


def test_a_code_block_containing_a_fence_gets_a_longer_one() -> None:
    assert notion_of([{"type": "code", "content": "```\ninner\n```"}]) == "````\n```\ninner\n```\n````\n"


@pytest.mark.parametrize(
    ("body", "line"),
    [
        pytest.param("- not a list", "\\- not a list", id="dash"),
        pytest.param("# not a heading", "\\# not a heading", id="hash"),
        pytest.param("1. not a list", "1\\. not a list", id="ordered"),
        pytest.param("--- not a rule", "\\--- not a rule", id="rule"),
    ],
)
def test_a_paragraph_that_starts_like_a_block_marker_stays_a_paragraph(body: str, line: str) -> None:
    assert notion_of([{"type": "text", "body": body}]) == f"{line}\n"


def test_list_entries_and_quote_lines_escape_a_leading_block_marker() -> None:
    blocks = [
        {"type": "list", "items": ["# not a heading"]},
        {"type": "quote", "body": "- not a list\n\n# nor a heading", "cite": "Ops"},
    ]

    assert notion_of(blocks) == "- \\# not a heading\n> \\- not a list<br>\\# nor a heading<br>*Ops*\n"


@pytest.mark.parametrize("tone", [pytest.param(tone, id=tone) for tone in get_args(BadgeColorLiteral)])
def test_every_badge_color_has_a_notion_chip_color(tone: BadgeColorLiteral) -> None:
    color = NOTION_CHIP_COLOR.get(tone)

    assert notion_inline((Chip("a*b", tone),)) == f'<span color="{color}_bg">a\\*b</span>'


def test_a_chip_label_that_names_a_file_is_inline_code_so_notion_does_not_link_it() -> None:
    assert notion_inline((Chip("README.md", "blue"),)) == '<span color="blue_bg">`README.md`</span>'


def test_every_badge_and_state_block_becomes_notion_markdown() -> None:
    assert notion_of(BADGE_AND_STATE_BLOCKS, badges=API_BADGES) == (
        "<details>\n<summary>Legend: badges used on this page</summary>\n"
        '\t- <span color="blue_bg">api</span> the API\n</details>\n'
        "- **Site**: West\n- **Owner**: ops\n<empty-block/>\n"
        "- **Lead**: **Ana**\n<empty-block/>\n"
        "- **Drift**: first\n\tsecond\n- **Gap**\n<empty-block/>\n"
        '- **Clean**: 9 (90.0%) <span color="green_bg">▲ +1</span> <span color="blue_bg">api</span>'
        ' {color="green"}\n\tsince Monday {color="gray"}\n'
        "- **Lag**: 3 days → flat\n"
        '**Affects**: <span color="blue_bg">api</span> <span color="green_bg">ops</span>\n'
        '- **Owners**: <span color="purple_bg">web</span>\n<empty-block/>\n'
        "- ✅ Ship\n- ⛔ Vendor\n<empty-block/>\n"
        '- 🔵 **Mon**: Start <span color="blue_bg">api</span>\n\tkick-off\n- Later\n<empty-block/>\n'
        '- **Zone**: ████░░░░░░ 42.9% {color="yellow"}\n'
        'Jan to Dec {color="gray"}\n'
        '- **Q1**: 25.0%, slow {color="red"}\n- **Rest**: 75.0%\n'
    )


def test_the_notion_legend_is_a_toggle_of_colored_chips_before_the_content() -> None:
    row = {"type": "badge_row", "items": [{"key": "API"}]}

    assert notion_of([row], badges=API_BADGES) == (
        "<details>\n<summary>Legend: badges used on this page</summary>\n"
        '\t- <span color="blue_bg">api</span> the API\n</details>\n'
        '<span color="blue_bg">api</span>\n'
    )


def test_block_nodes_become_notion_blocks() -> None:
    nodes = [
        Paragraph((Plain("muted"),), "muted"),
        ListNode("number", (ListEntry((Plain("one"),), tone="warning"),)),
        ListNode("check", (ListEntry((Plain("done"),), checked=True), ListEntry((Plain("open"),)))),
        Callout("info", (Paragraph((Plain("tip"),)),)),
        Quote(((Plain("said"),),)),
        Toggle((Plain("Legend"),), None, (Paragraph((Plain("x"),)),)),
        Toggle((Plain("Shut"),), 2, (Paragraph((Plain("y"),)),)),
        Tabs((Tab((Plain("plain"),), (Paragraph((Plain("z"),)),)),)),
        Diagram(Graph("LR", (GraphNode("s1", "A"),), ()), (Paragraph((Plain("detail"),)),)),
    ]

    assert render_notion(nodes) == (
        'muted {color="gray"}\n'
        '1. one {color="yellow"}\n'
        "- [x] done\n"
        "- [ ] open\n"
        '<callout icon="💡" color="blue_bg">\n\ttip\n</callout>\n'
        "> said\n"
        "<details>\n<summary>Legend</summary>\n\tx\n</details>\n"
        '## Shut {toggle="true"}\n\ty\n'
        "<tabs>\n\t<tab>\n\t\tplain\n\t\tz\n\t</tab>\n</tabs>\n"
        '```mermaid\nflowchart LR\n    s1["A"]\n```\ndetail\n'
    )


def _block_types_in(blocks: Sequence[AnyBlock]) -> set[str]:
    seen: set[str] = set()
    for block in blocks:
        seen.add(block.type)
        if isinstance(block, Section | Panel):
            seen |= _block_types_in(block.blocks)
        if isinstance(block, Grid | InnerGrid):
            for cell in block.cells:
                seen |= _block_types_in(cell.blocks)
        if isinstance(block, Walkthrough):
            for step in block.steps:
                seen |= _block_types_in(step.detail)
    return seen


def _every_block_type() -> set[str]:
    return {get_args(model.model_fields["type"].annotation)[0] for model in get_args(AnyBlock)}


def test_the_export_fixture_uses_every_block_type() -> None:
    assert _block_types_in(load_report(EXAMPLE).blocks) == _every_block_type()


def test_the_example_exports_to_the_notion_golden_regenerated_by_the_export_command(tmp_path: Path) -> None:
    export_notion(load_report(EXAMPLE), tmp_path)

    assert folder_texts(tmp_path) == folder_texts(NOTION_GOLDEN)


def test_a_flow_becomes_a_mermaid_diagram_with_readable_labels() -> None:
    flow = {
        "type": "flow",
        "numbered": False,
        "steps": [{"label": "Scan", "tone": "info"}, {"label": 'Say "hi"', "note": "then **stop**"}],
    }

    assert notion_of([flow]) == (
        "```mermaid\n"
        "flowchart LR\n"
        '    s1["Scan"]:::info\n'
        '    s2["Say #quot;hi#quot;<br>then stop"]\n'
        "    s1 --> s2\n"
        "    classDef info fill:#e8f0fe,stroke:#1a73e8,color:#1f2328\n"
        "```\n"
    )


def test_a_request_with_several_cases_becomes_notion_tabs() -> None:
    cases = [
        {"label": "finding", "tone": "warning", "response": {"body": "[]"}},
        {"label": "control", "tone": "info", "response": {"body": "none"}},
    ]
    request = make_command_request(cases=cases, command="list-tiers")

    assert notion_of([request]) == (
        "**Tier mappings on the partner API**\n"
        "<tabs>\n"
        '\t<tab icon="⚠️">\n'
        "\t\tfinding\n"
        "\t\t```bash\n\t\tlist-tiers\n\t\t```\n"
        "\t\t**Recorded output**\n"
        "\t\t```json\n\t\t[]\n\t\t```\n"
        "\t</tab>\n"
        '\t<tab icon="💡">\n'
        "\t\tcontrol\n"
        "\t\t```bash\n\t\tlist-tiers\n\t\t```\n"
        "\t\t**Recorded output**\n"
        "\t\t```\n\t\tnone\n\t\t```\n"
        "\t</tab>\n"
        "</tabs>\n"
    )


@pytest.mark.parametrize(
    ("title", "written"),
    [
        pytest.param("1. expired token", "1\\. expired token", id="ordinal-is-not-a-list"),
        pytest.param("# 404 path", "\\# 404 path", id="hash-is-not-a-heading"),
    ],
)
def test_a_tab_title_that_starts_like_a_block_stays_text(title: str, written: str) -> None:
    tabs = Tabs((Tab((Plain(title),), (Paragraph((Plain("z"),)),)),))

    assert render_notion([tabs]) == f"<tabs>\n\t<tab>\n\t\t{written}\n\t\tz\n\t</tab>\n</tabs>\n"


@pytest.mark.parametrize(
    ("tone", "opening"),
    [
        pytest.param("success", '<tab icon="✅">', id="success"),
        pytest.param("info", '<tab icon="💡">', id="info"),
        pytest.param("warning", '<tab icon="⚠️">', id="warning"),
        pytest.param("danger", '<tab icon="🛑">', id="danger"),
        pytest.param("neutral", "<tab>", id="neutral-has-no-icon"),
        pytest.param(None, "<tab>", id="no-tone"),
    ],
)
def test_a_notion_tab_carries_the_icon_of_its_case_tone(tone: ToneName | None, opening: str) -> None:
    tabs = Tabs((Tab((Plain("t"),), (Paragraph((Plain("z"),)),), tone),))

    assert render_notion([tabs]) == f"<tabs>\n\t{opening}\n\t\tt\n\t\tz\n\t</tab>\n</tabs>\n"


def test_a_diagram_with_nothing_beside_it_is_its_fence_alone() -> None:
    diagram = Diagram(Graph("LR", (GraphNode("s1", "A"),), ()))

    assert render_notion([diagram, Paragraph((Plain("after"),))]) == (
        '```mermaid\nflowchart LR\n    s1["A"]\n```\nafter\n'
    )


def test_a_page_with_a_table_of_contents_uses_the_notion_block() -> None:
    assert (
        notion_of([{"type": "heading", "text": "A"}], meta={"title": "T", "toc": True})
        == "<table_of_contents/>\n## A\n"
    )


def test_a_table_cell_of_code_plus_text_stays_a_cell_not_a_bullet() -> None:
    table = {
        "type": "table",
        "columns": [{"key": "a", "label": "A"}, {"key": "b", "label": "B"}, {"key": "c", "label": "C"}],
        "rows": [{"a": "`flag` + default", "b": "- leading dash", "c": "1 + 1 and a+b"}],
    }

    assert notion_of([table]) == (
        '<table fit-page-width="true" header-row="true">\n'
        "\t<tr>\n\t\t<td>**A**</td>\n\t\t<td>**B**</td>\n\t\t<td>**C**</td>\n\t</tr>\n"
        "\t<tr>\n"
        "\t\t<td>`flag` \N{FULLWIDTH PLUS SIGN} default</td>\n"
        "\t\t<td>\\- leading dash</td>\n"
        "\t\t<td>1 + 1 and a+b</td>\n"
        "\t</tr>\n"
        "</table>\n"
    )


def test_table_row_and_cell_tones_become_backgrounds_and_a_total_row_is_bold() -> None:
    table = TableNode(
        (TableCell((Plain("Name"),)), TableCell(())),
        (
            TableRow((TableCell((Plain("group"),)), TableCell(())), emphasis="group"),
            TableRow((TableCell((Plain("x"),), "danger"), TableCell((Plain("y"),), "teal")), "sky"),
            TableRow((TableCell((Plain("9"),)), TableCell(())), emphasis="total"),
        ),
        header_column=True,
    )

    assert render_notion([table]) == (
        '<table fit-page-width="true" header-row="true" header-column="true">\n'
        "\t<tr>\n\t\t<td>**Name**</td>\n\t\t<td></td>\n\t</tr>\n"
        '\t<tr color="gray_bg">\n\t\t<td>**group**</td>\n\t\t<td></td>\n\t</tr>\n'
        '\t<tr color="blue_bg">\n'
        '\t\t<td color="red_bg">**x**</td>\n\t\t<td color="green_bg">y</td>\n'
        "\t</tr>\n"
        "\t<tr>\n\t\t<td>**9**</td>\n\t\t<td></td>\n\t</tr>\n"
        "</table>\n"
    )


def test_a_group_row_with_its_own_tone_keeps_that_background() -> None:
    table = TableNode(
        (TableCell((Plain("Name"),)),),
        (TableRow((TableCell((Plain("group"),)),), "warning", emphasis="group"),),
    )

    assert render_notion([table]) == (
        '<table fit-page-width="true" header-row="true">\n'
        "\t<tr>\n\t\t<td>**Name**</td>\n\t</tr>\n"
        '\t<tr color="yellow_bg">\n\t\t<td>**group**</td>\n\t</tr>\n'
        "</table>\n"
    )


def test_a_swimlane_header_and_lane_cells_are_bold_as_a_whole() -> None:
    swimlane = {
        "type": "swimlane",
        "lanes": ["Ops"],
        "columns": [{"name": "Plan", "sub": "wk 1"}],
        "groups": [{"name": "Q1", "color": "blue", "columns": ["Plan"]}],
        "steps": [{"lane": "Ops", "col": "Plan", "n": "1", "label": "Draft", "value": 2}],
    }

    assert notion_of([swimlane]) == (
        '<table fit-page-width="true" header-row="true" header-column="true">\n'
        "\t<tr>\n\t\t<td>**Lane**</td>\n\t\t<td>**Plan<br>*wk 1*<br>Q1 (2)**</td>\n\t</tr>\n"
        "\t<tr>\n\t\t<td>**Ops (2)**</td>\n\t\t<td>⚪ **1** Draft (2)</td>\n\t</tr>\n"
        "\t<tr>\n\t\t<td>**Total**</td>\n\t\t<td>**2**</td>\n\t</tr>\n"
        "</table>\n"
    )


def test_a_grouped_table_bolds_its_group_rows_and_its_totals_row_as_a_whole() -> None:
    table = {
        "type": "table",
        "columns": [{"key": "a", "label": "Issue"}, {"key": "n", "label": "Units", "kind": "number"}],
        "totals": {"column": "n"},
        "groups": [{"name": "Ours", "rows": [{"a": "x", "n": 2}]}],
    }

    assert notion_of([table]) == (
        '<table fit-page-width="true" header-row="true">\n'
        "\t<tr>\n\t\t<td>**Issue**</td>\n\t\t<td>**Units**</td>\n\t</tr>\n"
        '\t<tr color="gray_bg">\n\t\t<td>**Ours (2)**</td>\n\t\t<td></td>\n\t</tr>\n'
        "\t<tr>\n\t\t<td>x</td>\n\t\t<td>2</td>\n\t</tr>\n"
        "\t<tr>\n\t\t<td>**Total**</td>\n\t\t<td>**2**</td>\n\t</tr>\n"
        "</table>\n"
    )


def test_a_grid_becomes_columns_and_a_grid_inside_a_cell_stacks() -> None:
    inner = {
        "type": "grid",
        "cells": [
            {"span": 3, "blocks": [{"type": "text", "body": "b"}]},
            {"span": 3, "blocks": [{"type": "text", "body": "c"}]},
        ],
    }
    grid = {
        "type": "grid",
        "cells": [{"span": 2, "blocks": [{"type": "text", "body": "a"}]}, {"span": 4, "blocks": [inner]}],
    }

    assert notion_of([grid]) == (
        "<columns>\n"
        '\t<column ratio="33">\n\t\ta\n\t</column>\n'
        '\t<column ratio="67">\n\t\tb\n\t\tc\n\t</column>\n'
        "</columns>\n"
    )


def test_nested_list_children_are_indented_with_tabs() -> None:
    block = {
        "type": "list",
        "items": [{"text": "parent", "items": ["child", {"text": "mid", "items": ["leaf"]}]}],
    }

    assert notion_of([block]) == "- parent\n\t- child\n\t- mid\n\t\t- leaf\n"


def test_a_collapsed_section_becomes_a_toggle_heading_and_an_open_one_a_plain_heading() -> None:
    blocks = [
        {"type": "section", "title": "Appendix", "blocks": [{"type": "text", "body": "raw"}]},
        {
            "type": "section",
            "title": "Status",
            "collapsed": False,
            "blocks": [{"type": "text", "body": "now"}],
        },
    ]

    assert notion_of(blocks) == '## Appendix {toggle="true"}\n\traw\n## Status\nnow\n'


def test_chunks_split_only_at_a_top_level_heading_and_stay_under_the_limit() -> None:
    assert chunk_notion(lowered(heading_sections(4, "x = 1\n" * 20)), 400) == NotionChunks(
        (
            _section_text("Part 0", "x = 1", 20) + _section_text("Part 1", "x = 1", 20),
            _section_text("Part 2", "x = 1", 20) + _section_text("Part 3", "x = 1", 20),
        ),
        (),
    )


def test_a_collapsed_section_starts_a_chunk_and_a_level_three_heading_does_not() -> None:
    blocks = [
        {"type": "heading", "text": "Open"},
        {"type": "heading", "text": "Inner", "level": 3},
        {"type": "section", "title": "Shut", "blocks": [{"type": "text", "body": "x"}]},
    ]

    assert chunk_notion(lowered(blocks), 30) == NotionChunks(
        ("## Open\n### Inner\n", '## Shut {toggle="true"}\n\tx\n'), ()
    )


def test_a_section_exactly_at_the_limit_fits_one_chunk() -> None:
    assert chunk_notion(lowered([{"type": "heading", "text": "A"}]), len("## A\n")) == NotionChunks(
        ("## A\n",), ()
    )


def test_a_section_longer_than_the_chunk_stays_whole_and_is_reported_by_its_heading() -> None:
    assert chunk_notion(lowered(heading_sections(2, "y = 2\n" * 40)), 100) == NotionChunks(
        (_section_text("Part 0", "y = 2", 40), _section_text("Part 1", "y = 2", 40)),
        ("## Part 0", "## Part 1"),
    )


def test_an_oversized_opening_before_the_first_heading_is_named_as_the_opening_section() -> None:
    nodes = (Paragraph((Plain("x" * 50),)), Heading(2, (Plain("A"),)))

    assert chunk_notion(nodes, 20) == NotionChunks(
        ("x" * 50 + "\n", "## A\n"), ("the opening section, before the first level 1 or 2 heading",)
    )


def test_an_oversized_section_is_named_by_its_heading_text_not_its_markup() -> None:
    nodes = (Toggle((Plain("Q3 [draft]"),), 2, (Paragraph((Plain("y" * 50),)),)),)

    assert chunk_notion(nodes, 20).oversized_sections == ("## Q3 [draft]",)


def test_two_sections_that_exactly_fill_the_limit_share_one_chunk() -> None:
    nodes = (Heading(2, (Plain("A"),)), Heading(2, (Plain("B"),)))

    assert chunk_notion(nodes, len("## A\n## B\n")) == NotionChunks(("## A\n## B\n",), ())


def test_an_empty_paragraph_writes_no_line() -> None:
    assert render_notion([Paragraph(()), Paragraph((Plain("x"),))]) == "x\n"


@pytest.mark.parametrize(
    ("tone", "color"),
    [
        pytest.param("neutral", "gray", id="neutral"),
        pytest.param("muted", "gray", id="muted"),
        pytest.param("info", "blue", id="info"),
        pytest.param("success", "green", id="success"),
        pytest.param("warning", "yellow", id="warning"),
        pytest.param("danger", "red", id="danger"),
        pytest.param("accent", "purple", id="accent"),
        pytest.param("teal", "green", id="teal"),
        pytest.param("sky", "blue", id="sky"),
    ],
)
def test_every_tone_has_a_notion_block_color(tone: ToneName, color: str) -> None:
    assert render_notion([Paragraph((Plain("p"),), tone), Callout(tone, ())]) == (
        f'p {{color="{color}"}}\n<callout icon="{CALLOUT_ICON[tone]}" color="{color}_bg">\n</callout>\n'
    )


def test_back_to_back_lists_of_one_kind_get_an_empty_block_between_them_so_they_stay_two_lists() -> None:
    blocks = [
        {"type": "list", "style": "number", "items": ["a"]},
        {"type": "list", "style": "number", "items": ["b"]},
        {"type": "list", "style": "check", "items": ["c"]},
        {"type": "list", "items": ["d"]},
        {"type": "list", "items": ["e"]},
    ]

    assert notion_of(blocks) == "1. a\n<empty-block/>\n1. b\n- [ ] c\n- d\n<empty-block/>\n- e\n"


def _one_entry_list(kind: ListKind, text: str, children: tuple[Node, ...] = ()) -> ListNode:
    return ListNode(kind, (ListEntry((Plain(text),), children=children),))


@pytest.mark.parametrize(
    ("nodes", "notion"),
    [
        pytest.param(
            (_one_entry_list("check", "a"), _one_entry_list("bullet", "b")),
            "- [ ] a\n- b\n",
            id="check-then-bullet",
        ),
        pytest.param(
            (_one_entry_list("bullet", "a"), _one_entry_list("number", "b")),
            "- a\n1. b\n",
            id="bullet-then-number",
        ),
        pytest.param(
            (_one_entry_list("bullet", "a"), Paragraph(()), _one_entry_list("bullet", "b")),
            "- a\n<empty-block/>\n- b\n",
            id="an-empty-paragraph-between-writes-nothing",
        ),
        pytest.param(
            (_one_entry_list("bullet", "a"), Paragraph((Plain("p"),)), _one_entry_list("bullet", "b")),
            "- a\np\n- b\n",
            id="a-paragraph-between-keeps-them-apart",
        ),
        pytest.param(
            (
                _one_entry_list(
                    "bullet", "p", (_one_entry_list("number", "a"), _one_entry_list("number", "b"))
                ),
            ),
            "- p\n\t1. a\n\t<empty-block/>\n\t1. b\n",
            id="inside-a-list-entry",
        ),
        pytest.param(
            (Callout("info", (_one_entry_list("check", "a"), _one_entry_list("check", "b"))),),
            '<callout icon="💡" color="blue_bg">\n\t- [ ] a\n\t<empty-block/>\n\t- [ ] b\n</callout>\n',
            id="inside-a-callout",
        ),
    ],
)
def test_an_empty_block_separates_only_lists_of_the_same_kind_that_notion_would_merge(
    nodes: tuple[Node, ...], notion: str
) -> None:
    assert render_notion(nodes) == notion


OPENING_THAT_RENDERS_NOTHING = (Paragraph(()), Heading(2, (Plain("A"),)), Paragraph((Plain("a"),)))
SECTIONS_WITH_LISTS = (
    _one_entry_list("bullet", "intro"),
    Heading(2, (Plain("A"),)),
    _one_entry_list("bullet", "a"),
    _one_entry_list("bullet", "b"),
    Toggle((Plain("B"),), 2, (Paragraph(()),)),
    Heading(1, (Plain("C"),)),
)


@pytest.mark.parametrize(
    "nodes",
    [
        pytest.param(OPENING_THAT_RENDERS_NOTHING, id="opening-renders-nothing"),
        pytest.param((), id="empty-body"),
        pytest.param((Paragraph(()),), id="body-renders-nothing"),
        pytest.param(SECTIONS_WITH_LISTS, id="sections-with-lists"),
        pytest.param(lowered(heading_sections(4, "x = 1\n" * 20)), id="code-sections"),
    ],
)
@pytest.mark.parametrize(
    "limit", [pytest.param(limit, id=f"limit-{limit}") for limit in (1, 20, 400, 100000)]
)
def test_the_chunks_joined_are_the_whole_page(nodes: tuple[Node, ...], limit: int) -> None:
    assert "".join(chunk_notion(nodes, limit).chunks) == render_notion(nodes)


def test_a_chunked_export_writes_one_numbered_file_per_chunk(tmp_path: Path) -> None:
    report = parse_report(make_report(meta={"title": "Count"}, blocks=heading_sections(2, "z = 3\n" * 20)))

    result = export_notion(report, tmp_path, chunk=200)

    assert result == ExportResult("Count", (tmp_path / "page.00.md", tmp_path / "page.01.md"))
    assert {path.name: path.read_text(encoding="utf-8") for path in result.files} == {
        "page.00.md": _section_text("Part 0", "z = 3", 20),
        "page.01.md": _section_text("Part 1", "z = 3", 20),
    }


@pytest.mark.parametrize(
    ("first_chunk", "second_chunk", "remaining_pages"),
    [
        pytest.param(CHUNK_THAT_SPLITS_EVERY_SECTION, None, ["page.md"], id="chunked-then-whole"),
        pytest.param(
            CHUNK_THAT_SPLITS_EVERY_SECTION,
            CHUNK_THAT_HOLDS_THE_WHOLE_PAGE,
            ["page.00.md"],
            id="many-chunks-then-one",
        ),
    ],
)
def test_a_re_export_removes_only_the_pages_its_earlier_run_wrote(
    tmp_path: Path, first_chunk: int, second_chunk: int | None, remaining_pages: list[str]
) -> None:
    report = parse_report(make_report(blocks=heading_sections(3, "w = 4\n" * 20)))
    export_notion(report, tmp_path, chunk=first_chunk)
    (tmp_path / "page.07.md").write_text("mine", encoding="utf-8")
    (tmp_path / "page.09.md").mkdir()

    export_notion(report, tmp_path, chunk=second_chunk)

    assert sorted(path.name for path in tmp_path.iterdir()) == sorted(
        [*remaining_pages, "page.07.md", "page.09.md", EXPORT_MANIFEST]
    )
    assert json.loads((tmp_path / EXPORT_MANIFEST).read_text(encoding="utf-8")) == {
        "title": "Test Report",
        "files": remaining_pages,
    }


def test_a_markdown_export_after_a_chunked_notion_one_in_the_same_folder_leaves_one_page(
    tmp_path: Path,
) -> None:
    report = parse_report(make_report(blocks=heading_sections(3, "w = 4\n" * 20)))
    export_notion(report, tmp_path, chunk=CHUNK_THAT_SPLITS_EVERY_SECTION)

    export_markdown(report, tmp_path)

    assert sorted(path.name for path in tmp_path.iterdir()) == [EXPORT_MANIFEST, "page.md"]


@pytest.mark.parametrize(
    "manifest",
    [
        pytest.param("not json", id="not-json"),
        pytest.param("[" * NESTING_TOO_DEEP_TO_PARSE, id="nested-too-deep-to-parse"),
        pytest.param('["page.03.md"]', id="not-an-object"),
        pytest.param('{"files": ["page.03.md"]}', id="no-title"),
        pytest.param('{"title": "T", "files": ["page.03.md"], "pages": 1}', id="unknown-key"),
        pytest.param('{"title": "T", "files": "page.03.md"}', id="files-not-a-list"),
        pytest.param('{"title": "T", "files": [3, null]}', id="entries-not-names"),
        pytest.param('{"title": "T", "files": ["page.03.md", 3]}', id="names-mixed-with-non-names"),
        pytest.param('{"title": "T", "files": ["README.md", "notes.txt"]}', id="names-skaldr-never-writes"),
        pytest.param(
            '{"title": "T", "files": ["../page.03.md", "sub/page.03.md"]}', id="paths-outside-the-folder"
        ),
    ],
)
def test_a_manifest_skaldr_did_not_write_deletes_nothing_and_is_reported(
    tmp_path: Path, manifest: str
) -> None:
    out_dir = tmp_path / "out"
    (out_dir / "sub").mkdir(parents=True)
    kept = [out_dir / "page.03.md", out_dir / "README.md", out_dir / "notes.txt", tmp_path / "page.03.md"]
    kept.append(out_dir / "sub" / "page.03.md")
    for path in kept:
        path.write_text("mine", encoding="utf-8")
    (out_dir / EXPORT_MANIFEST).write_text(manifest, encoding="utf-8")

    result = export_notion(parse_report(make_report()), out_dir)

    assert ([path.read_text(encoding="utf-8") for path in kept], result) == (
        ["mine"] * len(kept),
        ExportResult("Test Report", (out_dir / "page.md",), unreadable_manifest=True),
    )


@pytest.mark.parametrize(
    "name",
    [
        pytest.param("page.03.md.bak", id="extra-suffix"),
        pytest.param("xpage.md", id="extra-prefix"),
        pytest.param("page.1.md", id="one-digit"),
        pytest.param("page.٠٣.md", id="non-ascii-digits"),
        pytest.param("page.03.md\n", id="trailing-newline"),
    ],
)
def test_a_manifest_naming_a_file_skaldr_never_writes_leaves_that_file_alone(
    tmp_path: Path, name: str
) -> None:
    (tmp_path / name).write_text("mine", encoding="utf-8")
    (tmp_path / EXPORT_MANIFEST).write_text(json.dumps({"title": "T", "files": [name]}), encoding="utf-8")

    result = export_notion(parse_report(make_report()), tmp_path)

    assert ((tmp_path / name).read_text(encoding="utf-8"), result.unreadable_manifest) == ("mine", True)


def _leave_absent(_path: Path) -> None:
    return None


@pytest.mark.parametrize(
    ("make_it_not_a_file", "expected_names"),
    [
        pytest.param(_leave_absent, [EXPORT_MANIFEST, "page.md"], id="deleted-by-hand"),
        pytest.param(Path.mkdir, [EXPORT_MANIFEST, "page.03.md", "page.md"], id="replaced-by-a-folder"),
    ],
)
def test_a_listed_page_that_is_no_longer_a_file_is_skipped_and_kept(
    tmp_path: Path, make_it_not_a_file: Callable[[Path], object], expected_names: list[str]
) -> None:
    make_it_not_a_file(tmp_path / "page.03.md")
    (tmp_path / EXPORT_MANIFEST).write_text('{"title": "T", "files": ["page.03.md"]}', encoding="utf-8")

    result = export_notion(parse_report(make_report()), tmp_path)

    assert (sorted(path.name for path in tmp_path.iterdir()), result) == (
        sorted(expected_names),
        ExportResult("Test Report", (tmp_path / "page.md",)),
    )


def test_a_page_name_that_is_a_symlink_is_replaced_and_its_target_left_alone(tmp_path: Path) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_text("keep me", encoding="utf-8")
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    (out_dir / "page.md").symlink_to(outside)
    (out_dir / EXPORT_MANIFEST).symlink_to(outside)

    export_notion(parse_report(make_report()), out_dir)

    assert (
        outside.read_text(encoding="utf-8"),
        (out_dir / "page.md").is_symlink(),
        (out_dir / "page.md").read_text(encoding="utf-8"),
        (out_dir / EXPORT_MANIFEST).is_symlink(),
    ) == ("keep me", False, "Hello.\n", False)


def test_a_replaced_page_keeps_the_permissions_it_had(tmp_path: Path) -> None:
    page = tmp_path / "page.md"
    page.write_text("old", encoding="utf-8")
    page.chmod(0o600)

    export_notion(parse_report(make_report()), tmp_path)

    assert (page.read_text(encoding="utf-8"), page.stat().st_mode & 0o777) == ("Hello.\n", 0o600)


def test_a_run_that_fails_partway_still_lets_the_next_run_remove_what_it_wrote(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = parse_report(make_report(blocks=heading_sections(4, "w = 4\n" * 20)))
    write_text = Path.write_text

    def fail_on_the_third_page(path: Path, text: str, encoding: str | None = None) -> int:
        if path.name == "page.02.md":
            raise OSError("disk full")
        return write_text(path, text, encoding=encoding)

    monkeypatch.setattr(Path, "write_text", fail_on_the_third_page)
    with pytest.raises(OSError, match="disk full"):
        export_notion(report, tmp_path, chunk=CHUNK_THAT_SPLITS_EVERY_SECTION)
    monkeypatch.undo()

    export_notion(report, tmp_path)

    assert sorted(path.name for path in tmp_path.iterdir()) == [EXPORT_MANIFEST, "page.md"]


def test_a_hundred_chunks_or_more_are_numbered_so_they_sort_in_order(tmp_path: Path) -> None:
    report = parse_report(make_report(blocks=heading_sections(101, "v")))

    result = export_notion(report, tmp_path, chunk=1)

    assert [path.name for path in result.files] == [f"page.{index:03d}.md" for index in range(101)]
