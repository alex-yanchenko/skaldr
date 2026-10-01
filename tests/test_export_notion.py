import json
from pathlib import Path

import pytest

from skaldr.export import EXPORT_MANIFEST, ExportResult, export_notion
from skaldr.export.notion import NotionChunks, chunk_notion, notion_inline, render_notion
from skaldr.export.runs import Chip, ExportRich, Gauge, Mark
from skaldr.export.tree import (
    Callout,
    Heading,
    ListEntry,
    ListNode,
    Paragraph,
    Quote,
    Toggle,
)
from skaldr.models import parse_report
from skaldr.richtext import AnchorLink, Citation, Placeholder, Plain, parse_rich
from tests.factories import heading_sections, lowered, make_report, notion_of


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
        Mark("status", "blocked"),
        Gauge(3, 10),
        Plain(" wow!"),
        *parse_rich("[img](https://e.com/x.png)"),
    )

    assert notion_inline(runs) == (
        r"[\[1\]](https://example.com/a%20%28b%29) \[2\] "
        '<span color="yellow_bg">\\{\\{owner\\}\\}</span> '
        '<span color="yellow_bg">api</span> method⛔███░░░░░░░ wow\\![img](https://e.com/x.png)'
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


def test_block_nodes_become_notion_blocks() -> None:
    nodes = [
        Paragraph((Plain("muted"),), "muted"),
        ListNode("number", (ListEntry((Plain("one"),), tone="warning"),)),
        ListNode("check", (ListEntry((Plain("done"),), checked=True), ListEntry((Plain("open"),)))),
        Callout("info", (Paragraph((Plain("tip"),)),)),
        Quote(((Plain("said"),),)),
        Toggle((Plain("Legend"),), None, (Paragraph((Plain("x"),)),)),
        Toggle((Plain("Shut"),), 2, (Paragraph((Plain("y"),)),)),
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
    )


def test_a_page_with_a_table_of_contents_uses_the_notion_block() -> None:
    assert (
        notion_of([{"type": "heading", "text": "A"}], meta={"title": "T", "toc": True})
        == "<table_of_contents/>\n## A\n"
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

    assert chunk_notion(nodes, 20).oversized_sections == ("the opening section, before the first heading",)


def test_a_chunked_export_writes_one_numbered_file_per_chunk(tmp_path: Path) -> None:
    report = parse_report(make_report(meta={"title": "Count"}, blocks=heading_sections(2, "z = 3\n" * 20)))

    result = export_notion(report, tmp_path, chunk=200)

    assert result == ExportResult("Count", (tmp_path / "page.00.md", tmp_path / "page.01.md"))
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
def test_a_re_export_removes_only_the_pages_its_earlier_run_wrote(
    tmp_path: Path, first_chunk: int, second_chunk: int | None, left: list[str]
) -> None:
    report = parse_report(make_report(blocks=heading_sections(3, "w = 4\n" * 20)))
    export_notion(report, tmp_path, chunk=first_chunk)
    (tmp_path / "page.07.md").write_text("mine", encoding="utf-8")
    (tmp_path / "page.09.md").mkdir()

    export_notion(report, tmp_path, chunk=second_chunk)

    assert sorted(path.name for path in tmp_path.iterdir()) == sorted(
        [*left, "page.07.md", "page.09.md", EXPORT_MANIFEST]
    )
    assert json.loads((tmp_path / EXPORT_MANIFEST).read_text(encoding="utf-8")) == {"files": left}


def test_an_export_into_a_folder_without_a_manifest_deletes_nothing(tmp_path: Path) -> None:
    (tmp_path / "page.03.md").write_text("mine", encoding="utf-8")
    (tmp_path / EXPORT_MANIFEST).write_text("not json", encoding="utf-8")

    export_notion(parse_report(make_report()), tmp_path)

    assert (tmp_path / "page.03.md").read_text(encoding="utf-8") == "mine"
