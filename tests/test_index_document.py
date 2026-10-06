import json
from pathlib import Path
from typing import Any

import pytest

from skaldr import compute
from skaldr.errors import ReportError
from skaldr.export.inline import plain
from skaldr.export.lower import lower_report
from skaldr.export.notion import render_notion
from skaldr.export.tree import Heading, Paragraph, TableOfContents, TocEntry, Toggle
from skaldr.models import Report, content_files, load_report, parse_report
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

BADGE_UP = {"label": "up", "tone": "success", "legend": "service is up"}
BADGE_DOWN = {"label": "down", "tone": "danger", "legend": "service is down"}


def _text(body: str) -> dict[str, Any]:
    return {"type": "text", "body": body}


def _part(title: str, *bodies: str, **overrides: Any) -> dict[str, Any]:
    return make_report(meta={"title": title}, blocks=[_text(body) for body in bodies], **overrides)


def _dumped_text(body: str) -> dict[str, Any]:
    return {"type": "text", "body": body, "muted": False, "span": None}


def _dumped_part(title: str, *bodies: str, collapsed: bool = False) -> dict[str, Any]:
    return {
        "type": "part",
        "title": title,
        "collapsed": collapsed,
        "blocks": [_dumped_text(body) for body in bodies],
    }


def _two_part_index(tmp_path: Path, **overrides: Any) -> Path:
    return write_index_document(
        tmp_path,
        {"one.yaml": _part("Part one", "first"), "two.yaml": _part("Part two", "second")},
        **overrides,
    )


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


def test_badges_from_the_index_and_every_part_merge(tmp_path: Path) -> None:
    up_part = _part("Up", "first", badges={"UP": BADGE_UP})
    down_part = _part("Down", "second", badges={"DOWN": BADGE_DOWN, "UP": BADGE_UP})
    index = write_index_document(tmp_path, {"one.yaml": up_part, "two.yaml": down_part})

    badges = load_report(index).model_dump(mode="json")["badges"]

    assert badges == {"UP": {**BADGE_UP, "tone": "green"}, "DOWN": {**BADGE_DOWN, "tone": "red"}}


def test_one_badge_key_declared_differently_in_two_files_names_both_files(tmp_path: Path) -> None:
    other_up = {**BADGE_UP, "tone": "info"}
    index = write_index_document(
        tmp_path,
        {
            "one.yaml": _part("A", "a", badges={"UP": BADGE_UP}),
            "two.yaml": _part("B", "b", badges={"UP": other_up}),
        },
    )

    with pytest.raises(ReportError) as raised:
        load_report(index)

    assert str(raised.value) == (
        f"badge 'UP' is declared differently in {tmp_path / 'one.yaml'} and {tmp_path / 'two.yaml'}; "
        "an index merges every part's badges, so give it one label, tone and legend or rename one key"
    )


def test_an_id_repeated_across_parts_is_refused_like_a_repeat_in_one_file(tmp_path: Path) -> None:
    index = write_index_document(
        tmp_path,
        {
            "one.yaml": make_report(meta={"title": "A"}, blocks=[make_section("shared")]),
            "two.yaml": make_report(meta={"title": "B"}, blocks=[make_section("shared")]),
        },
    )

    with pytest.raises(ReportError, match=r"heading/section id\(s\) used more than once: \['shared'\]"):
        load_report(index)


def test_a_part_that_fails_validation_is_named_with_its_field_path(tmp_path: Path) -> None:
    index = write_index_document(
        tmp_path, {"one.yaml": make_report(meta={"title": "A"}, blocks=[{"type": "text"}])}
    )

    with pytest.raises(ReportError) as raised:
        load_report(index)

    assert str(raised.value) == (
        f"in part {tmp_path / 'one.yaml'}: invalid content data: blocks.0.text.body: Field required"
    )


def test_a_missing_part_file_is_named(tmp_path: Path) -> None:
    index = write_report(tmp_path, make_index_report(["gone.yaml"]), "index.yaml")

    with pytest.raises(ReportError, match=r"file not found: .*gone\.yaml"):
        load_report(index)


def test_a_part_that_is_itself_an_index_is_refused(tmp_path: Path) -> None:
    write_report(tmp_path, _part("Leaf", "x"), "leaf.yaml")
    write_report(tmp_path, make_index_report(["leaf.yaml"]), "inner.yaml")
    index = write_report(tmp_path, make_index_report(["inner.yaml"]), "index.yaml")

    with pytest.raises(ReportError) as raised:
        load_report(index)

    assert str(raised.value) == (
        f"part {tmp_path / 'inner.yaml'} is itself an index; an index lists document files, not other indexes"
    )


@pytest.mark.parametrize(
    ("index", "message"),
    [
        pytest.param(
            {"parts": []},
            "invalid content data: index.parts: List should have at least 1 item after validation, not 0",
            id="no-parts",
        ),
        pytest.param(
            {"parts": ["/abs/part.yaml"]},
            "invalid content data: index.parts.0: Value error, a part path is relative to the index file, "
            "not absolute: /abs/part.yaml",
            id="absolute",
        ),
        pytest.param(
            {"parts": ["a.yaml"], "layout": "child_pages"},
            "invalid content data: index.layout: Input should be 'one_page'",
            id="child-pages-not-yet",
        ),
    ],
)
def test_an_invalid_index_block_is_refused_naming_the_field(
    tmp_path: Path, index: dict[str, Any], message: str
) -> None:
    path = write_report(tmp_path, make_index_report([], index=index), "index.yaml")

    with pytest.raises(ReportError) as raised:
        load_report(path)

    assert str(raised.value) == message


def test_a_written_part_block_is_refused_outside_an_index() -> None:
    data = make_report(blocks=[{"type": "part", "title": "By hand", "blocks": [_text("x")]}])

    with pytest.raises(ReportError) as raised:
        parse_report(data)

    assert str(raised.value) == (
        "invalid content data: blocks.0.part: Value error, a `part` block is built by an `index`, "
        "not written by hand; list the file under `index.parts`, or use a `section` or a `heading`"
    )


def test_the_published_schema_documents_index_and_leaves_part_out() -> None:
    schema = json.dumps(Report.model_json_schema())

    assert '"index"' in schema
    assert '"Index"' in schema
    assert '"part"' not in schema
    assert '"Part"' not in schema


def test_an_index_with_a_publish_block_is_refused(tmp_path: Path) -> None:
    index = _two_part_index(tmp_path, publish={"doc_id": "plan", "targets": [make_notion_target()]})

    with pytest.raises(ReportError) as raised:
        load_report(index)

    assert str(raised.value) == (
        "invalid content data: Value error, an index document cannot carry `publish` yet; publish each part "
        "file on its own"
    )


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

    assert '<section class="part" id="details"><h1 class="part-title">Details</h1>' in html
    assert html.index('class="part-title">Overview<') < html.index("Inside one") < html.index("Details")


def test_a_collapsed_part_renders_as_a_closed_disclosure_that_expand_opens(tmp_path: Path) -> None:
    report = _combined(tmp_path, index={"parts": ["one.yaml", "two.yaml"], "collapsed": True})

    closed = '<details class="part" id="details"><summary><span class="part-title">Details</span></summary>'
    opened = (
        '<details class="part" id="details" open><summary><span class="part-title">Details</span></summary>'
    )
    assert closed in render_html(report)
    assert opened in render_html(report, expand=True)


def test_an_open_part_lowers_to_a_level_one_heading_before_its_blocks(tmp_path: Path) -> None:
    body = lower_report(_combined(tmp_path)).body

    assert body[-2:] == (Heading(1, plain("Details"), "details"), Paragraph(plain("second")))


def test_a_collapsed_part_lowers_to_a_level_one_toggle_heading(tmp_path: Path) -> None:
    report = _combined(tmp_path, index={"parts": ["one.yaml", "two.yaml"], "collapsed": True})

    assert lower_report(report).body[-1] == Toggle(
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
