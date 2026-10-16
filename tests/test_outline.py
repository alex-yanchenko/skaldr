import json
from pathlib import Path
from typing import Literal, cast

import pytest
import yaml

from skaldr.cli import main
from skaldr.outline import OutlineJson, OutlineRegionJson
from tests.factories import make_index_report

DOCUMENT = """version: 1
meta:
  title: Outline sample
blocks:
  - type: heading
    text: Overview
  - type: text
    body: Opening words.
  - type: heading
    text: Details
    level: 3
  # a comment inside the details region
  - type: section
    title: Evidence
    id: evidence
    # gathered on site
    blocks:
      - type: heading
        text: Inside
        level: 3
      - type: text
        body: |
          first line
          second line

  - type: heading
    text: Deep
    level: 4
  - type: heading
    text: Overview
  - !include fragment.yaml
  - type: grid
    cells:
      - span: 3
        blocks:
          - type: heading
            text: Cell note
            level: 3
          - type: text
            body: In a cell.
"""

FRAGMENT = """type: heading
text: Borrowed
level: 3
"""

ALIASED_ITEM = """version: 1
meta: {title: T}
blocks:
  - &h {type: heading, text: A}
  - *h
  - type: text
    body: x
"""

ALIASED_LAST_VALUE = """version: 1
meta: {title: T}
blocks:
  - type: text
    body: &b hello
  - type: section
    title: S
    blocks:
      - type: text
        body: *b
  - {type: heading, text: A}
  - {type: text, body: x}
"""

ONE_LINE_FLOW = """version: 1
meta: {title: T}
blocks: [{type: heading, text: A}, {type: text, body: x}, {type: heading, text: B}]
"""

MULTI_LINE_FLOW = """version: 1
meta: {title: T}
blocks: [
  {type: heading, text: A},
  {type: text, body: x},
  {type: heading, text: B}
]
"""

FLOW_ON_THE_KEY_LINE = """version: 1
meta: {title: T}
blocks: [{type: heading, text: A},
  {type: text, body: x},
  {type: heading, text: B}]
"""

TRAILING_COMMENTS = """version: 1
meta: {title: T}
blocks:
  - type: heading  # opens the page
    text: A  # the heading
  - type: text
    body: y  # the last value
"""

KEPT_BLANK_LINE = """version: 1
meta: {title: T}
blocks:
  - type: heading
    text: A
  - type: text
    body: |+
      kept

  # before B
  - type: heading
    text: B
"""

SIMPLE = """version: 1
meta: {title: T}
blocks:
  - type: heading
    text: A
"""

ALIAS_REASON = "is not written in place (it comes through a YAML alias or merge key)"


@pytest.fixture
def document(tmp_path: Path) -> Path:
    _write(tmp_path / "fragment.yaml", FRAGMENT)
    return _write(tmp_path / "doc.yaml", DOCUMENT)


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    return path


def _region(
    anchor: str,
    title: str,
    level: int | None,
    lines: tuple[int, int, int] | None,
    *,
    kind: Literal["heading", "section"] = "heading",
    author_set: bool = False,
) -> OutlineRegionJson:
    return {
        "anchor": anchor,
        "kind": kind,
        "level": level,
        "title": title,
        "author_set": author_set,
        "start_line": lines[0] if lines else None,
        "end_line": lines[1] if lines else None,
        "tokens": lines[2] if lines else None,
    }


def _outlined(path: Path, capsys: pytest.CaptureFixture[str]) -> tuple[int, OutlineJson]:
    exit_code = main(["outline", str(path), "--json"])
    return exit_code, cast("OutlineJson", json.loads(capsys.readouterr().out))


def _shown(region: str, capsys: pytest.CaptureFixture[str]) -> tuple[int, tuple[str, str]]:
    exit_code = main(["show", region])
    captured = capsys.readouterr()
    return exit_code, (captured.out, captured.err)


def test_outline_prints_one_row_per_anchor_with_its_lines_and_tokens(
    document: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main(["outline", str(document)])

    assert (exit_code, capsys.readouterr().out) == (
        0,
        "ANCHOR      KIND     LEVEL  ID       START  END  ~TOKENS  TITLE\n"
        "overview    heading  2      derived  5      28   111      Overview\n"
        "details     heading  3      derived  9      28   91       Details\n"
        "evidence    section         set      13     24   57       Evidence\n"
        "inside      heading  3      derived  18     24   35       Inside\n"
        "deep        heading  4      derived  26     28   12       Deep\n"
        "overview-2  heading  2      derived  29     40   63       Overview\n"
        "borrowed    heading  3      derived  -      -    -        Borrowed\n"
        "cell-note   heading  3      derived  36     40   32       Cell note\n"
        f"{document}: 40 lines, ~185 tokens\n",
    )


def test_outline_json_lists_every_region_in_document_order(
    document: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _outlined(document, capsys) == (
        0,
        {
            "file": str(document),
            "lines": 40,
            "tokens": 185,
            "regions": [
                _region("overview", "Overview", 2, (5, 28, 111)),
                _region("details", "Details", 3, (9, 28, 91)),
                _region("evidence", "Evidence", None, (13, 24, 57), kind="section", author_set=True),
                _region("inside", "Inside", 3, (18, 24, 35)),
                _region("deep", "Deep", 4, (26, 28, 12)),
                _region("overview-2", "Overview", 2, (29, 40, 63)),
                _region("borrowed", "Borrowed", 3, None),
                _region("cell-note", "Cell note", 3, (36, 40, 32)),
            ],
        },
    )


@pytest.mark.parametrize(
    "index", ["{parts: [one.yaml, two.yaml]}", "!include index-parts.yaml"], ids=["inline", "included"]
)
@pytest.mark.parametrize("command", ["outline", "show"])
def test_an_index_document_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], index: str, command: str
) -> None:
    _write(tmp_path / "index-parts.yaml", "parts: [one.yaml, two.yaml]\n")
    path = _write(tmp_path / "index.yaml", f"version: 1\nmeta: {{title: T}}\nindex: {index}\n")

    exit_code = main([command, str(path) if command == "outline" else f"{path}#a"])

    assert (exit_code, capsys.readouterr()) == (
        2,
        (
            "",
            f"error: {path} is an index document; "
            "outline each file it lists under `index.parts` on its own\n",
        ),
    )


def test_an_index_from_the_factory_is_refused(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = _write(tmp_path / "index.yaml", yaml.safe_dump(make_index_report(["one.yaml", "two.yaml"])))

    assert main(["outline", str(path)]) == 2
    assert capsys.readouterr().out == ""


def test_a_null_index_is_a_normal_document(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = _write(
        tmp_path / "doc.yaml",
        "version: 1\nmeta: {title: T}\nindex:\nblocks:\n  - type: heading\n    text: A\n",
    )

    assert _outlined(path, capsys) == (
        0,
        {"file": str(path), "lines": 6, "tokens": 19, "regions": [_region("a", "A", 2, (5, 6, 8))]},
    )


@pytest.mark.parametrize("command", ["outline", "show"])
@pytest.mark.parametrize(
    ("text", "message"),
    [
        pytest.param(
            "version: 1\nblocks: [\n",
            "invalid YAML in {path}: while parsing a flow node\n"
            "expected the node content, but found '<stream end>'\n"
            '  in "<unicode string>", line 3, column 1:\n'
            "    \n"
            "    ^",
            id="invalid-yaml",
        ),
        pytest.param(
            "version: 1\nmeta: {title: T}\nblocks:\n  - type: heading\n",
            "invalid content data: blocks.0.heading.text: Field required",
            id="schema-invalid",
        ),
        pytest.param(None, "file not found: {path}", id="missing"),
    ],
)
def test_a_file_that_does_not_load_fails_with_its_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], command: str, text: str | None, message: str
) -> None:
    path = tmp_path / "doc.yaml"
    if text is not None:
        _write(path, text)

    exit_code = main([command, str(path) if command == "outline" else f"{path}#a"])

    assert (exit_code, capsys.readouterr()) == (1, ("", f"error: {message.format(path=path)}\n"))


def test_show_prints_a_heading_region_word_for_word(
    document: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _shown(f"{document}#details", capsys) == (
        0,
        (
            "  - type: heading\n"
            "    text: Details\n"
            "    level: 3\n"
            "  # a comment inside the details region\n"
            "  - type: section\n"
            "    title: Evidence\n"
            "    id: evidence\n"
            "    # gathered on site\n"
            "    blocks:\n"
            "      - type: heading\n"
            "        text: Inside\n"
            "        level: 3\n"
            "      - type: text\n"
            "        body: |\n"
            "          first line\n"
            "          second line\n"
            "\n"
            "  - type: heading\n"
            "    text: Deep\n"
            "    level: 4\n",
            "",
        ),
    )


def test_show_prints_a_section_region_word_for_word(
    document: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _shown(f"{document}#evidence", capsys) == (
        0,
        (
            "  - type: section\n"
            "    title: Evidence\n"
            "    id: evidence\n"
            "    # gathered on site\n"
            "    blocks:\n"
            "      - type: heading\n"
            "        text: Inside\n"
            "        level: 3\n"
            "      - type: text\n"
            "        body: |\n"
            "          first line\n"
            "          second line\n",
            "",
        ),
    )


def test_show_keeps_the_files_own_line_breaks(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "crlf.yaml"
    path.write_bytes(
        b"version: 1\r\nmeta:\r\n  title: T\r\nblocks:\r\n"
        b"  - type: heading\r\n    text: One\r\n  - type: text\r\n    body: x\r\n"
    )

    assert _shown(f"{path}#one", capsys) == (
        0,
        ("  - type: heading\r\n    text: One\r\n  - type: text\r\n    body: x\r\n", ""),
    )


def test_a_heading_region_keeps_a_kept_blank_line_and_leaves_out_the_comment_after_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write(tmp_path / "doc.yaml", KEPT_BLANK_LINE)

    assert _outlined(path, capsys)[1]["regions"] == [
        _region("a", "A", 2, (4, 9, 18)),
        _region("b", "B", 2, (11, 12, 8)),
    ]
    assert _shown(f"{path}#a", capsys) == (
        0,
        ("  - type: heading\n    text: A\n  - type: text\n    body: |+\n      kept\n\n", ""),
    )


def test_an_aliased_item_is_not_written_in_place(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = _write(tmp_path / "doc.yaml", ALIASED_ITEM)

    assert _outlined(path, capsys) == (
        0,
        {
            "file": str(path),
            "lines": 7,
            "tokens": 26,
            "regions": [_region("a", "A", 2, (4, 4, 8)), _region("a-2", "A", 2, None)],
        },
    )
    assert _shown(f"{path}#a-2", capsys) == (
        1,
        ("", f"error: {path}#a-2 {ALIAS_REASON}, so {path} holds none of its lines\n"),
    )


def test_a_section_ending_in_an_alias_ends_on_the_aliass_own_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write(tmp_path / "doc.yaml", ALIASED_LAST_VALUE)

    assert _outlined(path, capsys)[1]["regions"] == [
        _region("s", "S", None, (6, 10, 20), kind="section"),
        _region("a", "A", 2, (11, 12, 14)),
    ]
    assert _shown(f"{path}#s", capsys) == (
        0,
        ("  - type: section\n    title: S\n    blocks:\n      - type: text\n        body: *b\n", ""),
    )


def test_blocks_written_on_one_flow_line_share_their_lines(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write(tmp_path / "doc.yaml", ONE_LINE_FLOW)

    assert _outlined(path, capsys)[1]["regions"] == [_region("a", "A", 2, None), _region("b", "B", 2, None)]
    assert _shown(f"{path}#a", capsys) == (
        1,
        ("", f"error: {path}#a shares its lines with the next block, so {path} holds none of its lines\n"),
    )
    assert _shown(f"{path}#b", capsys) == (
        1,
        (
            "",
            f"error: {path}#b shares its lines with the block before it, so {path} holds none of its lines\n",
        ),
    )


def test_blocks_that_share_a_line_with_the_list_around_them_have_no_lines(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write(tmp_path / "doc.yaml", FLOW_ON_THE_KEY_LINE)
    reason = "shares its lines with the list around it"

    assert _outlined(path, capsys)[1]["regions"] == [_region("a", "A", 2, None), _region("b", "B", 2, None)]
    assert [_shown(f"{path}#{anchor}", capsys) for anchor in ("a", "b")] == [
        (1, ("", f"error: {path}#{anchor} {reason}, so {path} holds none of its lines\n"))
        for anchor in ("a", "b")
    ]


def test_comments_after_a_regions_first_and_last_values_stay_in_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write(tmp_path / "doc.yaml", TRAILING_COMMENTS)

    assert _outlined(path, capsys) == (
        0,
        {"file": str(path), "lines": 7, "tokens": 36, "regions": [_region("a", "A", 2, (4, 7, 27))]},
    )


def test_a_flow_list_written_one_block_per_line_has_regions(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write(tmp_path / "doc.yaml", MULTI_LINE_FLOW)

    assert _outlined(path, capsys)[1]["regions"] == [
        _region("a", "A", 2, (4, 5, 14)),
        _region("b", "B", 2, (6, 6, 7)),
    ]
    assert _shown(f"{path}#a", capsys) == (0, ("  {type: heading, text: A},\n  {type: text, body: x},\n", ""))


def test_blocks_an_included_list_brings_in_have_no_lines(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write(tmp_path / "inner.yaml", "- type: heading\n  text: Inner\n")
    path = _write(
        tmp_path / "doc.yaml",
        "version: 1\nmeta: {title: T}\nblocks:\n  - type: section\n    title: Outer\n"
        "    blocks: !include inner.yaml\n  - type: text\n    body: x\n",
    )

    assert _outlined(path, capsys)[1]["regions"] == [
        _region("outer", "Outer", None, (4, 6, 17), kind="section"),
        _region("inner", "Inner", 2, None),
    ]


def test_a_yaml_next_line_character_breaks_a_line(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    next_line = chr(0x85)
    path = _write(
        tmp_path / "doc.yaml",
        "version: 1\nmeta: {title: T}\nblocks:\n  - type: text\n    body: |\n"
        f"      one{next_line}      two\n  - type: heading\n    text: After\n",
    )

    assert _outlined(path, capsys)[1]["regions"] == [_region("after", "After", 2, (8, 9, 9))]


def test_show_names_the_closest_anchors_for_an_unknown_one(
    document: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _shown(f"{document}#overveiw", capsys) == (
        1,
        ("", f"error: no anchor 'overveiw' in {document}; did you mean: overview, overview-2\n"),
    )


def test_show_points_to_the_outline_when_no_anchor_is_close(
    document: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _shown(f"{document}#zzz", capsys) == (
        1,
        ("", f"error: no anchor 'zzz' in {document}; `skaldr outline {document}` lists them\n"),
    )


def test_show_refuses_a_region_an_include_brings_in(
    document: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _shown(f"{document}#borrowed", capsys) == (
        1,
        (
            "",
            f"error: {document}#borrowed comes from `!include fragment.yaml` at line 31, "
            f"so {document} holds none of its lines\n",
        ),
    )


def test_show_reads_a_file_whose_path_holds_a_hash(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write(tmp_path / "dir#x" / "a.yaml", SIMPLE)

    assert _shown(f"{path}#a", capsys) == (0, ("  - type: heading\n    text: A\n", ""))


@pytest.mark.parametrize("region", ["doc.yaml", "doc.yaml#", "#a"])
def test_show_without_a_file_and_an_anchor_is_a_usage_error(
    capsys: pytest.CaptureFixture[str], region: str
) -> None:
    with pytest.raises(SystemExit) as exited:
        main(["show", region])

    assert (exited.value.code, capsys.readouterr().err.splitlines()[-1]) == (
        2,
        "skaldr show: error: name the region as FILE#ANCHOR; `skaldr outline FILE` lists the anchors",
    )
