from collections.abc import Sequence
from pathlib import Path
from typing import get_args

import pytest

from skaldr.export import export_notion
from skaldr.export.lower import lower_report
from skaldr.export.notion import NotionChunks, chunk_notion, notion_inline, render_notion
from skaldr.export.tree import (
    Callout,
    ListEntry,
    ListNode,
    Paragraph,
    Quote,
    Table,
    TableCell,
    TableRow,
    Toggle,
)
from skaldr.models import AnyBlock, Grid, InnerGrid, Panel, Section, Walkthrough, load_report, parse_report
from skaldr.richtext import Chip, Citation, Placeholder, Plain, parse_rich
from tests.conftest import REPO_ROOT
from tests.factories import heading_sections, make_command_request, make_report, notion_of

EXAMPLE = REPO_ROOT / "data" / "example.yaml"
NOTION_GOLDEN = REPO_ROOT / "tests" / "golden" / "example.notion"


def _block_types_in(blocks: Sequence[AnyBlock]) -> set[str]:
    seen: set[str] = set()
    for block in blocks:
        seen.add(block.type)
        if isinstance(block, (Section, Panel)):
            seen |= _block_types_in(block.blocks)
        if isinstance(block, (Grid, InnerGrid)):
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
    export_notion(load_report(EXAMPLE), tmp_path, chunk=None)

    assert {path.name: path.read_text(encoding="utf-8") for path in sorted(tmp_path.iterdir())} == {
        path.name: path.read_text(encoding="utf-8") for path in sorted(NOTION_GOLDEN.iterdir())
    }


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
    runs = (
        Citation("a", 1, "https://example.com/a"),
        Plain(" "),
        Citation("b", 2),
        Plain(" "),
        Placeholder("owner"),
        Plain(" "),
        Chip("api", "amber"),
    )

    assert notion_inline(runs) == (
        r'[\[1\]](https://example.com/a) \[2\] <span color="yellow_bg">\{\{owner\}\}</span> '
        '<span color="yellow_bg">api</span>'
    )


def test_code_with_a_backtick_becomes_escaped_text_because_notion_has_no_longer_code_fence() -> None:
    assert notion_of([{"type": "code", "label": "a`b", "content": "x"}]) == "a\\`b\n```\nx\n```\n"


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
    table = Table(
        (TableCell((Plain("Name"),)),),
        (
            TableRow((TableCell((Plain("group"),)),), emphasis="group"),
            TableRow((TableCell((Plain("x"),), "danger"),), "success"),
            TableRow((TableCell((Plain("9"),)),), emphasis="total"),
        ),
        header_column=True,
    )

    assert render_notion([table]) == (
        '<table fit-page-width="true" header-row="true" header-column="true">\n'
        "\t<tr>\n\t\t<td>**Name**</td>\n\t</tr>\n"
        '\t<tr color="gray_bg">\n\t\t<td>group</td>\n\t</tr>\n'
        '\t<tr color="green_bg">\n\t\t<td color="red_bg">x</td>\n\t</tr>\n'
        "\t<tr>\n\t\t<td>**9**</td>\n\t</tr>\n"
        "</table>\n"
    )


def test_block_nodes_become_notion_blocks() -> None:
    nodes = [
        Paragraph((Plain("muted"),), "muted"),
        ListNode("number", (ListEntry((Plain("one"),), tone="warning"),)),
        ListNode("check", (ListEntry((Plain("done"),), checked=True), ListEntry((Plain("open"),)))),
        Callout("info", (Paragraph((Plain("tip"),)),)),
        Quote(((Plain("said"),),)),
        Toggle((Plain("Legend"),), None, (Paragraph((Plain("x"),)),)),
    ]

    assert render_notion(nodes) == (
        'muted {color="gray"}\n'
        '1. one {color="yellow"}\n'
        "- [x] done\n"
        "- [ ] open\n"
        '<callout icon="💡" color="blue_bg">\n\ttip\n</callout>\n'
        "> said\n"
        "<details>\n<summary>Legend</summary>\n\tx\n</details>\n"
    )


def test_a_page_with_a_table_of_contents_uses_the_notion_block() -> None:
    blocks = [{"type": "heading", "text": "A"}]

    assert notion_of(blocks, meta={"title": "T", "toc": True}) == "<table_of_contents/>\n## A\n"


def test_nested_list_children_are_indented_with_tabs() -> None:
    block = {
        "type": "list",
        "items": [{"text": "parent", "items": ["child", {"text": "mid", "items": ["leaf"]}]}],
    }

    assert notion_of([block]) == "- parent\n\t- child\n\t- mid\n\t\t- leaf\n"


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
        {"label": "control", "tone": "success", "response": {"body": "none"}},
    ]
    request = make_command_request(cases=cases, command="list-tiers")

    assert notion_of([request]) == (
        "**Tier mappings on the partner API**\n"
        "<tabs>\n"
        '\t<tab icon="⚠️">\n'
        "\t\tfinding\n"
        "\t\t```bash\n\t\tlist-tiers\n\t\t```\n"
        "\t\t**Output**\n"
        "\t\t```json\n\t\t[]\n\t\t```\n"
        "\t</tab>\n"
        '\t<tab icon="✅">\n'
        "\t\tcontrol\n"
        "\t\t```bash\n\t\tlist-tiers\n\t\t```\n"
        "\t\t**Output**\n"
        "\t\t```\n\t\tnone\n\t\t```\n"
        "\t</tab>\n"
        "</tabs>\n"
    )


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


def _section_text(title: str, body: str, rows: int) -> str:
    return f"## {title}\n```\n" + f"{body}\n" * rows + "```\n"


def test_chunks_split_only_at_a_top_level_heading_and_stay_under_the_limit() -> None:
    nodes = lower_report(parse_report(make_report(blocks=heading_sections(4, "x = 1\n" * 20))))

    assert chunk_notion(nodes, 400) == NotionChunks(
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
    nodes = lower_report(parse_report(make_report(blocks=blocks)))

    assert chunk_notion(nodes, 30) == NotionChunks(
        ("## Open\n### Inner\n", '## Shut {toggle="true"}\n\tx\n'),
        (),
    )


def test_a_section_exactly_at_the_limit_fits_one_chunk() -> None:
    nodes = lower_report(parse_report(make_report(blocks=[{"type": "heading", "text": "A"}])))

    assert chunk_notion(nodes, len("## A\n")) == NotionChunks(("## A\n",), ())


def test_a_section_longer_than_the_chunk_stays_whole_and_is_reported() -> None:
    nodes = lower_report(parse_report(make_report(blocks=heading_sections(2, "y = 2\n" * 40))))

    assert chunk_notion(nodes, 100) == NotionChunks(
        (_section_text("Part 0", "y = 2", 40), _section_text("Part 1", "y = 2", 40)),
        ("## Part 0", "## Part 1"),
    )


def test_a_chunked_export_writes_one_numbered_file_per_chunk(tmp_path: Path) -> None:
    report = parse_report(make_report(blocks=heading_sections(2, "z = 3\n" * 20)))

    result = export_notion(report, tmp_path, chunk=200)

    assert {path.name: path.read_text(encoding="utf-8") for path in result.files} == {
        "page.00.md": _section_text("Part 0", "z = 3", 20),
        "page.01.md": _section_text("Part 1", "z = 3", 20),
    }


@pytest.mark.parametrize(
    ("first_chunk", "second_chunk", "left"),
    [
        pytest.param(100, None, ["page.md"], id="chunked-then-whole"),
        pytest.param(100, 100000, ["page.00.md"], id="many-chunks-then-one"),
    ],
)
def test_a_re_export_leaves_no_page_from_the_earlier_run(
    tmp_path: Path, first_chunk: int, second_chunk: int | None, left: list[str]
) -> None:
    report = parse_report(make_report(blocks=heading_sections(3, "w = 4\n" * 20)))
    (tmp_path / "notes.txt").write_text("mine", encoding="utf-8")

    export_notion(report, tmp_path, chunk=first_chunk)
    export_notion(report, tmp_path, chunk=second_chunk)

    assert sorted(path.name for path in tmp_path.iterdir()) == sorted([*left, "notes.txt"])
