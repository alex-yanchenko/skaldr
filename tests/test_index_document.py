import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from skaldr import compute
from skaldr.cli import main
from skaldr.errors import ReportError
from skaldr.export.inline import plain
from skaldr.export.lower import lower_report
from skaldr.export.markdown import render_markdown
from skaldr.export.notion import render_notion
from skaldr.export.tree import Heading, Paragraph, TableOfContents, TocEntry, Toggle
from skaldr.models import Person, Report, Text, content_files, load_report, parse_report
from skaldr.render import render_html
from tests.factories import (
    make_index_report,
    make_notion_target,
    make_publish_report,
    make_report,
    make_section,
    write_index_document,
    write_report,
)

SITE = "https://example.atlassian.net"
BADGE_UP = {"label": "up", "tone": "success", "legend": "service is up"}
BADGE_DOWN = {"label": "down", "tone": "danger", "legend": "service is down"}
PART_BY_HAND = (
    "a `part` block is built by an `index`, not written by hand; list the file under `index.parts`, "
    "or use a `section` or a `heading`"
)


def _text(body: str) -> dict[str, Any]:
    return {"type": "text", "body": body}


def _part(title: str, *bodies: str, **overrides: Any) -> dict[str, Any]:
    return make_report(meta={"title": title}, blocks=[_text(body) for body in bodies], **overrides)


def _dumped_text(body: str) -> dict[str, Any]:
    return Text(type="text", body=body).model_dump(mode="json")


def _dumped_part(
    title: str, *bodies: str, collapsed: bool = False, doc_id: str | None = None
) -> dict[str, Any]:
    return {
        "type": "part",
        "title": title,
        "doc_id": doc_id,
        "collapsed": collapsed,
        "blocks": [_dumped_text(body) for body in bodies],
    }


def _two_part_index(tmp_path: Path, **overrides: Any) -> Path:
    return write_index_document(
        tmp_path,
        {"one.yaml": _part("Part one", "first"), "two.yaml": _part("Part two", "second")},
        **overrides,
    )


def _refusal(path: Path) -> str:
    with pytest.raises(ReportError) as raised:
        load_report(path)
    return str(raised.value)


def test_an_index_combines_its_intro_and_one_part_per_file_in_order(tmp_path: Path) -> None:
    index = _two_part_index(tmp_path, blocks=[_text("intro")])

    report = load_report(index)

    assert report.model_dump(mode="json")["blocks"] == [
        _dumped_text("intro"),
        _dumped_part("Part one", "first"),
        _dumped_part("Part two", "second"),
    ]


def test_an_index_needs_no_intro_blocks(tmp_path: Path) -> None:
    report = load_report(_two_part_index(tmp_path))

    assert report.model_dump(mode="json")["blocks"] == [
        _dumped_part("Part one", "first"),
        _dumped_part("Part two", "second"),
    ]


def test_an_index_with_collapsed_set_collapses_every_part(tmp_path: Path) -> None:
    index = write_index_document(
        tmp_path, {"one.yaml": _part("Part one", "first")}, index={"parts": ["one.yaml"], "collapsed": True}
    )

    report = load_report(index)

    assert report.model_dump(mode="json")["blocks"] == [_dumped_part("Part one", "first", collapsed=True)]


def test_a_document_with_a_null_index_is_an_ordinary_document(tmp_path: Path) -> None:
    path = write_report(tmp_path, make_report(index=None, blocks=[_text("plain")]))

    assert load_report(path).model_dump(mode="json")["blocks"] == [_dumped_text("plain")]


def test_the_combined_page_carries_no_index_so_its_emitted_json_is_refused_rather_than_expanded_twice(
    tmp_path: Path,
) -> None:
    report = load_report(_two_part_index(tmp_path))
    emitted = write_report(tmp_path, report.model_dump(mode="json"), "emitted.yaml")

    assert report.index is None
    assert _refusal(emitted) == (
        f"invalid content data: blocks.0.part: Value error, {PART_BY_HAND}; "
        f"blocks.1.part: Value error, {PART_BY_HAND}"
    )


def test_part_paths_resolve_against_the_index_file_not_the_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_report(tmp_path / "docs" / "parts", _part("Nested", "deep"), "a.yaml")
    index = write_report(tmp_path / "docs", make_index_report(["parts/a.yaml"]), "index.yaml")
    monkeypatch.chdir(tmp_path)

    report = load_report(index)

    assert report.model_dump(mode="json")["blocks"] == [_dumped_part("Nested", "deep")]


def test_a_part_is_loaded_with_its_own_includes(tmp_path: Path) -> None:
    (tmp_path / "parts").mkdir()
    (tmp_path / "parts" / "body.yaml").write_text("- type: text\n  body: included\n", encoding="utf-8")
    (tmp_path / "parts" / "a.yaml").write_text(
        "version: 1\nmeta:\n  title: A\nblocks: !include body.yaml\n", encoding="utf-8"
    )
    index = write_report(tmp_path, make_index_report(["parts/a.yaml"]), "index.yaml")

    assert load_report(index).model_dump(mode="json")["blocks"] == [_dumped_part("A", "included")]
    assert content_files(index) == (
        index.resolve(),
        (tmp_path / "parts" / "a.yaml").resolve(),
        (tmp_path / "parts" / "body.yaml").resolve(),
    )


def test_content_files_lists_the_index_then_every_part(tmp_path: Path) -> None:
    index = _two_part_index(tmp_path)

    assert content_files(index) == (
        index.resolve(),
        (tmp_path / "one.yaml").resolve(),
        (tmp_path / "two.yaml").resolve(),
    )


def test_content_files_lists_a_part_that_does_not_validate(tmp_path: Path) -> None:
    index = write_index_document(
        tmp_path, {"one.yaml": make_report(meta={"title": "A"}, blocks=[{"type": "text"}])}
    )

    assert content_files(index) == (index.resolve(), (tmp_path / "one.yaml").resolve())


def _shift_mtime(path: Path, seconds: float) -> None:
    mtime = path.stat().st_mtime + seconds
    os.utime(path, (mtime, mtime))


def _watch_through(
    index: Path, monkeypatch: pytest.MonkeyPatch, edits: list[Callable[[], None]]
) -> list[str]:
    renders: list[str] = []
    pending = iter(edits)

    def record_render(*_args: object, **_kwargs: object) -> int:
        renders.append("render")
        return 0

    def next_edit_or_stop(_seconds: float) -> None:
        edit = next(pending, None)
        if edit is None:
            raise KeyboardInterrupt
        edit()

    monkeypatch.setattr("skaldr.cli._render_once", record_render)
    monkeypatch.setattr("time.sleep", next_edit_or_stop)
    assert main(["--watch", str(index), "-o", str(index.parent / "out.html")]) == 0
    return renders


def test_watch_re_renders_when_a_part_changes_and_names_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    index = _two_part_index(tmp_path)
    part = tmp_path / "two.yaml"

    renders = _watch_through(index, monkeypatch, [lambda: _shift_mtime(part, 10)])

    assert renders == ["render", "render"]
    assert f"\n{part} changed, re-rendering:" in capsys.readouterr().out


def test_watch_sees_a_part_replaced_by_an_older_copy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    index = _two_part_index(tmp_path)

    renders = _watch_through(index, monkeypatch, [lambda: _shift_mtime(tmp_path / "one.yaml", -100)])

    assert renders == ["render", "render"]


def test_watch_keeps_following_the_parts_while_one_cannot_be_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    index = _two_part_index(tmp_path)
    part = tmp_path / "two.yaml"
    good = part.read_text(encoding="utf-8")

    def break_the_part() -> None:
        part.write_text("blocks: [unclosed\n", encoding="utf-8")
        _shift_mtime(part, 10)

    def mend_the_part() -> None:
        part.write_text(good, encoding="utf-8")
        _shift_mtime(part, 10)

    renders = _watch_through(index, monkeypatch, [break_the_part, mend_the_part])

    assert renders == ["render", "render", "render"]


def test_badges_from_every_part_merge(tmp_path: Path) -> None:
    up_part = _part("Up", "first", badges={"UP": BADGE_UP})
    down_part = _part("Down", "second", badges={"DOWN": BADGE_DOWN, "UP": BADGE_UP})
    index = write_index_document(tmp_path, {"one.yaml": up_part, "two.yaml": down_part})

    badges = load_report(index).model_dump(mode="json")["badges"]

    assert badges == {"UP": {**BADGE_UP, "tone": "green"}, "DOWN": {**BADGE_DOWN, "tone": "red"}}


def test_the_index_own_badges_merge_with_the_parts_and_a_twin_tone_is_the_same_badge(tmp_path: Path) -> None:
    index = write_index_document(
        tmp_path,
        {"one.yaml": _part("A", "a", badges={"DOWN": BADGE_DOWN, "UP": {**BADGE_UP, "tone": "green"}})},
        badges={"UP": BADGE_UP},
    )

    badges = load_report(index).model_dump(mode="json")["badges"]

    assert badges == {"UP": {**BADGE_UP, "tone": "green"}, "DOWN": {**BADGE_DOWN, "tone": "red"}}


def test_a_badge_used_inside_a_part_reaches_the_page_legend(tmp_path: Path) -> None:
    user = make_report(
        meta={"title": "Uses"},
        blocks=[{"type": "badge_row", "items": [{"key": "UP"}]}],
        badges={"UP": BADGE_UP, "DOWN": BADGE_DOWN},
    )
    index = write_index_document(tmp_path, {"one.yaml": user})

    assert [key for key, _ in compute.used_badges(load_report(index))] == ["UP"]


@pytest.mark.parametrize(
    ("index_badges", "part_badges", "first", "second"),
    [
        pytest.param({}, {"UP": {**BADGE_UP, "tone": "info"}}, "one.yaml", "two.yaml", id="two-parts"),
        pytest.param({"UP": {**BADGE_UP, "tone": "info"}}, {}, "index.yaml", "one.yaml", id="index-and-part"),
    ],
)
def test_one_badge_key_declared_differently_in_two_files_names_both_files(
    tmp_path: Path, index_badges: dict[str, Any], part_badges: dict[str, Any], first: str, second: str
) -> None:
    index = write_index_document(
        tmp_path,
        {
            "one.yaml": _part("A", "a", badges={"UP": BADGE_UP}),
            "two.yaml": _part("B", "b", badges=part_badges),
        },
        badges=index_badges,
    )

    assert _refusal(index) == (
        f"badge 'UP' is declared differently in {tmp_path / first} and {tmp_path / second}; "
        "an index merges every part's badges, so give it one label, tone and legend or rename one key"
    )


def test_an_id_repeated_across_parts_names_the_file_behind_each_part(tmp_path: Path) -> None:
    index = write_index_document(
        tmp_path,
        {
            "one.yaml": make_report(meta={"title": "A"}, blocks=[make_section("shared")]),
            "two.yaml": make_report(meta={"title": "B"}, blocks=[make_section("shared")]),
        },
        blocks=[_text("intro")],
    )

    assert _refusal(index) == (
        "invalid content data: Value error, heading/section id(s) used more than once: ['shared'], at "
        "blocks.1.part.blocks.0.section.id, blocks.2.part.blocks.0.section.id; heading and section ids must "
        f"be unique; in this index, blocks.1 is {tmp_path / 'one.yaml'} "
        f"and blocks.2 is {tmp_path / 'two.yaml'}"
    )


def test_a_page_wide_error_names_only_the_parts_it_points_at(tmp_path: Path) -> None:
    index = write_index_document(
        tmp_path,
        {
            "one.yaml": make_report(meta={"title": "A"}, blocks=[make_section("shared")]),
            "two.yaml": _part("B", "b"),
            "three.yaml": make_report(meta={"title": "C"}, blocks=[make_section("shared")]),
        },
    )

    assert _refusal(index).endswith(
        f"; in this index, blocks.0 is {tmp_path / 'one.yaml'} and blocks.2 is {tmp_path / 'three.yaml'}"
    )


def test_a_page_wide_error_across_three_parts_lists_them_in_order(tmp_path: Path) -> None:
    index = write_index_document(
        tmp_path,
        {
            name: make_report(meta={"title": name}, blocks=[make_section("shared")])
            for name in ("a.yaml", "b.yaml", "c.yaml")
        },
    )

    assert _refusal(index).endswith(
        f"; in this index, blocks.0 is {tmp_path / 'a.yaml'}, blocks.1 is {tmp_path / 'b.yaml'} "
        f"and blocks.2 is {tmp_path / 'c.yaml'}"
    )


def test_a_page_wide_error_between_the_intro_and_one_part_names_that_part(tmp_path: Path) -> None:
    index = write_index_document(
        tmp_path,
        {"one.yaml": make_report(meta={"title": "A"}, blocks=[make_section("shared")])},
        blocks=[make_section("shared")],
    )

    assert _refusal(index).endswith(f"; in this index, blocks.1 is {tmp_path / 'one.yaml'}")


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        pytest.param(
            {"blocks": [make_section("shared"), make_section("shared")]},
            "invalid content data: Value error, heading/section id(s) used more than once: ['shared'], at "
            "blocks.0.section.id, blocks.1.section.id; heading and section ids must be unique",
            id="intro-only",
        ),
        pytest.param(
            {"meta": {"subtitle": ["no title"]}},
            "invalid content data: meta.title: Field required",
            id="index-meta",
        ),
    ],
)
def test_an_error_that_points_at_no_part_names_no_part(
    tmp_path: Path, overrides: dict[str, Any], message: str
) -> None:
    index = write_index_document(tmp_path, {"one.yaml": _part("A", "a")}, **overrides)

    assert _refusal(index) == message


def test_parsing_index_data_without_loading_its_file_is_refused() -> None:
    with pytest.raises(ReportError) as raised:
        parse_report(make_index_report(["one.yaml"]))

    assert str(raised.value) == (
        "invalid content data: Value error, `index` is read when its file is loaded, which brings in every "
        "part; load the index file rather than its parsed data"
    )


def test_a_part_that_fails_validation_is_named_with_its_field_path(tmp_path: Path) -> None:
    index = write_index_document(
        tmp_path, {"one.yaml": make_report(meta={"title": "A"}, blocks=[{"type": "text"}])}
    )

    assert _refusal(index) == (
        f"in part {tmp_path / 'one.yaml'}: invalid content data: blocks.0.text.body: Field required"
    )


def test_a_missing_part_file_is_named(tmp_path: Path) -> None:
    index = write_report(tmp_path, make_index_report(["gone.yaml"]), "index.yaml")

    assert _refusal(index) == f"file not found: {tmp_path / 'gone.yaml'}"


def test_a_part_that_is_itself_an_index_is_refused(tmp_path: Path) -> None:
    write_report(tmp_path, _part("Leaf", "x"), "leaf.yaml")
    write_report(tmp_path, make_index_report(["leaf.yaml"]), "inner.yaml")
    index = write_report(tmp_path, make_index_report(["inner.yaml"]), "index.yaml")

    assert _refusal(index) == (
        f"part {tmp_path / 'inner.yaml'} is itself an index; an index lists document files, not other indexes"
    )


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        pytest.param(
            {"index": {"parts": []}},
            "invalid content data: index.parts: List should have at least 1 item after validation, not 0",
            id="no-parts",
        ),
        pytest.param(
            {"index": {"parts": ["/abs/part.yaml"]}},
            "invalid content data: index.parts.0: Value error, a part path is relative to the index file, "
            "not absolute: /abs/part.yaml",
            id="absolute",
        ),
        pytest.param(
            {"index": {"parts": ["one.yaml", "two.yaml", "one.yaml"]}},
            "invalid content data: index.parts: Value error, a part is listed more than once: one.yaml; "
            "list each part once",
            id="listed-twice",
        ),
        pytest.param(
            {"index": {"parts": ["  "]}},
            "invalid content data: index.parts.0: String should match pattern '\\S'",
            id="blank-path",
        ),
        pytest.param(
            {"index": {"parts": ["one.yaml"], "layout": "child_pages"}},
            "invalid content data: index.layout: Input should be 'one_page'",
            id="child-pages-not-yet",
        ),
        pytest.param(
            {"index": ["one.yaml"]},
            "invalid content data: index: Input should be a valid dictionary or instance of Index",
            id="index-is-a-list",
        ),
        pytest.param(
            {"blocks": "hello"},
            "invalid content data: blocks: Input should be a valid list",
            id="intro-is-not-a-list",
        ),
        pytest.param(
            {"badges": {"UP": {**BADGE_UP, "tone": "nope"}}},
            "invalid content data: badges.UP.tone: Input should be 'slate', 'blue', 'green', 'amber', 'red', "
            "'violet', 'teal' or 'sky'",
            id="index-badge",
        ),
        pytest.param(
            {"blocks": [_text("intro"), {"type": "part", "title": "By hand", "blocks": [_text("x")]}]},
            f"invalid content data: blocks.1.part: Value error, {PART_BY_HAND}",
            id="part-in-the-intro",
        ),
        pytest.param(
            {"publish": {"doc_id": "plan", "targets": [make_notion_target()]}},
            "an index document cannot carry `publish` yet; publish each part file on its own",
            id="publish",
        ),
    ],
)
def test_an_invalid_index_document_is_refused_naming_the_field(
    tmp_path: Path, overrides: dict[str, Any], message: str
) -> None:
    index = write_index_document(tmp_path, {"one.yaml": _part("A", "a")}, **overrides)

    assert _refusal(index) == message


def test_a_written_part_block_is_refused_outside_an_index() -> None:
    data = make_report(blocks=[{"type": "part", "title": "By hand", "blocks": [_text("x")]}])

    with pytest.raises(ReportError) as raised:
        parse_report(data)

    assert str(raised.value) == f"invalid content data: blocks.0.part: Value error, {PART_BY_HAND}"


def test_the_published_schema_documents_index_and_leaves_part_out() -> None:
    schema = Report.model_json_schema()
    block_types = schema["properties"]["blocks"]["items"]["discriminator"]["mapping"]

    assert "Index" in schema["$defs"]
    assert "index" in schema["properties"]
    assert "Part" not in schema["$defs"]
    assert "part" not in block_types
    assert "section" in block_types


def test_a_parts_own_publish_block_is_left_out_of_the_combined_page(tmp_path: Path) -> None:
    publishing = make_publish_report({"doc_id": "plan", "targets": [make_notion_target(split=["st1"])]})
    index = write_index_document(tmp_path, {"one.yaml": publishing})

    assert load_report(index).publish is None


def test_a_document_with_no_blocks_and_no_index_is_refused() -> None:
    data = make_report()
    del data["blocks"]

    with pytest.raises(ReportError) as raised:
        parse_report(data)

    assert str(raised.value) == (
        "invalid content data: Value error, `blocks` needs at least one block; "
        "only an index document may leave it out"
    )


def _combined(tmp_path: Path, **overrides: Any) -> Report:
    parts = {
        "one.yaml": make_report(
            meta={"title": "Overview"},
            blocks=[{"type": "heading", "text": "Inside one"}, make_section("inner", title="Inner")],
        ),
        "two.yaml": _part("Details", "second"),
    }
    return load_report(write_index_document(tmp_path, parts, **overrides))


def _collapsed(tmp_path: Path) -> Report:
    return _combined(tmp_path, index={"parts": ["one.yaml", "two.yaml"], "collapsed": True})


def test_the_toc_lists_intro_headings_then_one_entry_per_part(tmp_path: Path) -> None:
    report = _combined(
        tmp_path, meta={"title": "Combined", "toc": True}, blocks=[{"type": "heading", "text": "Overview"}]
    )

    assert compute.toc_entries(report, compute.anchor_slugs(report)) == [
        ("overview", "Overview"),
        ("overview-2", "Overview"),
        ("details", "Details"),
    ]


def test_an_open_part_renders_as_a_titled_region_with_its_blocks(tmp_path: Path) -> None:
    html = render_html(_combined(tmp_path))

    assert (
        '<section class="part" id="details"><h1 class="part-title">Details</h1><p class="text">second</p>'
        in html
    )
    assert html.index('class="part-title">Overview<') < html.index("Inside one") < html.index("Details")


def test_a_collapsed_part_renders_as_a_closed_disclosure_holding_its_blocks(tmp_path: Path) -> None:
    html = render_html(_collapsed(tmp_path))

    assert (
        '<details class="part" id="details"><summary><span class="part-title">Details</span></summary>'
        '<div class="part-body"><p class="text">second</p></div></details>'
    ) in html


def test_expand_opens_a_collapsed_part(tmp_path: Path) -> None:
    html = render_html(_collapsed(tmp_path), expand=True)

    assert '<details class="part" id="details" open><summary>' in html


@pytest.mark.parametrize("collapsed", [False, True])
def test_a_part_title_is_escaped_in_the_html(tmp_path: Path, collapsed: bool) -> None:
    index = write_index_document(
        tmp_path,
        {"one.yaml": _part('A <b> & "c"', "x")},
        index={"parts": ["one.yaml"], "collapsed": collapsed},
    )

    html = render_html(load_report(index))

    assert 'class="part-title">A &lt;b&gt; &amp; &#34;c&#34;</' in html


def test_an_open_part_lowers_to_a_level_one_heading_before_its_blocks(tmp_path: Path) -> None:
    body = lower_report(_combined(tmp_path)).body

    assert body[-2:] == (Heading(1, plain("Details"), "details"), Paragraph(plain("second")))


def test_a_collapsed_part_lowers_to_a_level_one_toggle_heading(tmp_path: Path) -> None:
    assert lower_report(_collapsed(tmp_path)).body[-1] == Toggle(
        plain("Details"), 1, (Paragraph(plain("second")),), "details"
    )


def test_sections_inside_a_part_keep_their_level_two_heading_under_the_part(tmp_path: Path) -> None:
    body = lower_report(_combined(tmp_path)).body

    assert body[:3] == (
        Heading(1, plain("Overview"), "overview"),
        Heading(2, plain("Inside one"), "inside-one"),
        Toggle(plain("Inner"), 2, (Paragraph(plain("x")),), "inner"),
    )


def test_the_export_toc_has_one_entry_per_part(tmp_path: Path) -> None:
    body = lower_report(_combined(tmp_path, meta={"title": "Combined", "toc": True})).body

    assert body[0] == TableOfContents(
        (TocEntry("overview", plain("Overview")), TocEntry("details", plain("Details")))
    )


def test_the_notion_export_writes_each_part_title_as_a_level_one_heading(tmp_path: Path) -> None:
    page = render_notion(lower_report(_combined(tmp_path)).body)

    assert page == '# Overview\n## Inside one\n## Inner {toggle="true"}\n\tx\n# Details\nsecond\n'


def test_the_github_export_writes_an_open_or_collapsed_part_title_as_a_level_one_heading(
    tmp_path: Path,
) -> None:
    open_page = render_markdown(lower_report(_combined(tmp_path / "open")).body)
    collapsed_page = render_markdown(lower_report(_collapsed(tmp_path / "collapsed")).body)

    assert open_page.endswith("\n# Details\n\nsecond\n")
    assert collapsed_page.endswith("\n# Details\n\nsecond\n")


def test_emit_json_of_an_index_prints_the_combined_page(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    index = _two_part_index(tmp_path)

    assert main([str(index), "--emit-json"]) == 0
    assert json.loads(capsys.readouterr().out)["blocks"] == [
        _dumped_part("Part one", "first"),
        _dumped_part("Part two", "second"),
    ]


def _linking_part(title: str, **meta: Any) -> dict[str, Any]:
    return make_report(meta={"title": title, **meta}, blocks=[_text("[Ada](user:ada)")])


def test_an_index_merges_the_people_and_the_jira_site_its_parts_declare(tmp_path: Path) -> None:
    index = write_index_document(
        tmp_path,
        {
            "one.yaml": _linking_part("One", people={"ada": {"jira": "acct-1"}}, jira_site=f"{SITE}/"),
            "two.yaml": _linking_part("Two", people={"bo": {}}, jira_site=SITE),
        },
        meta={"title": "Combined", "people": {"cy": {}}},
    )

    report = load_report(index)

    assert (report.meta.people, report.meta.jira_site) == (
        {"cy": Person(), "ada": Person(jira="acct-1"), "bo": Person()},
        SITE,
    )
    assert '<span class="person-chip" data-person="ada">Ada</span>' in render_html(report)


def test_the_same_person_declared_the_same_way_in_two_parts_merges(tmp_path: Path) -> None:
    people = {"ada": {"jira": "acct-1"}}
    index = write_index_document(
        tmp_path,
        {"one.yaml": _linking_part("One", people=people), "two.yaml": _linking_part("Two", people=people)},
    )

    assert load_report(index).meta.people == {"ada": Person(jira="acct-1")}


@pytest.mark.parametrize(
    ("index_people", "part_people", "first", "second"),
    [
        pytest.param({}, {"ada": {"jira": "acct-2"}}, "one.yaml", "two.yaml", id="two-parts"),
        pytest.param({"ada": {"jira": "acct-2"}}, {}, "index.yaml", "one.yaml", id="index-and-part"),
    ],
)
def test_one_person_key_declared_differently_in_two_files_names_both_files(
    tmp_path: Path, index_people: dict[str, Any], part_people: dict[str, Any], first: str, second: str
) -> None:
    index = write_index_document(
        tmp_path,
        {
            "one.yaml": _linking_part("One", people={"ada": {"jira": "acct-1"}}),
            "two.yaml": _linking_part("Two", people=part_people),
        },
        meta={"title": "Combined", "people": index_people},
    )

    assert _refusal(index) == (
        f"person 'ada' is declared differently in {tmp_path / first} and {tmp_path / second}; "
        "an index merges every part's people, so give it one Notion and Jira id or rename one key"
    )


def test_two_parts_with_different_jira_sites_name_both_files(tmp_path: Path) -> None:
    index = write_index_document(
        tmp_path,
        {
            "one.yaml": _part("One", "a"),
            "two.yaml": make_report(meta={"title": "Two", "jira_site": SITE}, blocks=[_text("b")]),
            "three.yaml": make_report(
                meta={"title": "Three", "jira_site": "https://other.example.net"}, blocks=[_text("c")]
            ),
        },
    )

    assert _refusal(index) == (
        f"jira_site is declared differently in {tmp_path / 'two.yaml'} and {tmp_path / 'three.yaml'}; "
        "an index points every issue link at one site, so give each part the same address"
    )


def _index_with_a_linked_part(tmp_path: Path, intro: str) -> Path:
    publishing = make_publish_report(
        {"doc_id": "onboarding-plan", "targets": [make_notion_target()]}, section_ids=("st1", "st2")
    )
    return write_index_document(tmp_path, {"plan.yaml": publishing}, blocks=[_text(intro)])


def test_a_document_link_to_a_part_of_the_index_is_an_in_page_anchor(tmp_path: Path) -> None:
    intro = "[the plan](doc:onboarding-plan#st2) and [all of it](doc:onboarding-plan)"
    report = load_report(_index_with_a_linked_part(tmp_path, intro))

    html = render_html(report)
    body = lower_report(report).body

    assert 'href="#st2">the plan</a>' in html
    assert 'href="#test-report">all of it</a>' in html
    assert render_markdown(body).startswith("[the plan](#st2) and [all of it](#test-report)\n")
    assert render_notion(body).startswith("the plan and all of it\n")


def test_a_document_link_to_a_document_outside_the_index_stays_a_file_link(tmp_path: Path) -> None:
    report = load_report(_index_with_a_linked_part(tmp_path, "[other](doc:elsewhere#s1)"))

    assert 'href="elsewhere.html#s1">other</a>' in render_html(report)


def test_a_document_link_to_a_section_the_part_lacks_fails_naming_it(tmp_path: Path) -> None:
    report = load_report(_index_with_a_linked_part(tmp_path, "[x](doc:onboarding-plan#nope)"))

    with pytest.raises(ReportError) as raised:
        render_html(report)

    assert str(raised.value) == (
        "blocks.0.body: rich text links to unknown section 'nope' of document 'onboarding-plan'"
    )
