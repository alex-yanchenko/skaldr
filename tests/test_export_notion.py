import json
from collections.abc import Callable
from pathlib import Path

import pytest

from skaldr.export import EXPORT_MANIFEST, ExportResult, export_markdown, export_notion
from skaldr.export.markup import CALLOUT_ICON
from skaldr.export.notion import NotionChunks, chunk_notion, notion_inline, render_notion
from skaldr.export.tree import (
    Callout,
    Heading,
    ListEntry,
    ListKind,
    ListNode,
    Node,
    Paragraph,
    Quote,
    Toggle,
    ToneName,
)
from skaldr.models import parse_report
from skaldr.richtext import AnchorLink, Citation, Placeholder, Plain, Rich, parse_rich
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
    runs: Rich = (
        Citation("a", 1, "https://example.com/a (b)"),
        Plain(" "),
        Citation("b", 2),
        Plain(" "),
        Placeholder("owner"),
        Plain(" "),
        AnchorLink((Plain("method"),), "method"),
        Plain(" wow!"),
        *parse_rich("[img](https://e.com/x.png)"),
    )

    assert notion_inline(runs) == (
        r"[\[1\]](https://example.com/a%20%28b%29) \[2\] "
        '<span color="yellow_bg">\\{\\{owner\\}\\}</span> method wow\\![img](https://e.com/x.png)'
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
    assert json.loads((tmp_path / EXPORT_MANIFEST).read_text(encoding="utf-8")) == {
        "title": "Test Report",
        "files": left,
    }


def test_a_markdown_export_after_a_chunked_notion_one_in_the_same_folder_leaves_one_page(
    tmp_path: Path,
) -> None:
    report = parse_report(make_report(blocks=heading_sections(3, "w = 4\n" * 20)))
    export_notion(report, tmp_path, chunk=100)

    export_markdown(report, tmp_path)

    assert sorted(path.name for path in tmp_path.iterdir()) == [EXPORT_MANIFEST, "page.md"]


@pytest.mark.parametrize(
    "manifest",
    [
        pytest.param("not json", id="not-json"),
        pytest.param("[" * 100000, id="nested-too-deep-to-parse"),
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
        export_notion(report, tmp_path, chunk=100)
    monkeypatch.undo()

    export_notion(report, tmp_path)

    assert sorted(path.name for path in tmp_path.iterdir()) == [EXPORT_MANIFEST, "page.md"]


def test_a_hundred_chunks_or_more_are_numbered_so_they_sort_in_order(tmp_path: Path) -> None:
    report = parse_report(make_report(blocks=heading_sections(101, "v")))

    result = export_notion(report, tmp_path, chunk=1)

    assert [path.name for path in result.files] == [f"page.{index:03d}.md" for index in range(101)]
