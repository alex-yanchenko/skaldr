import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import IO, Any, Literal

import pytest
import yaml
from pydantic import TypeAdapter
from yaml.composer import Composer

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

ALIAS_OF_A_NESTED_BLOCK = """version: 1
meta: {title: T}
blocks:
  - type: heading
    text: H
  - type: section
    title: S
    blocks:
      - &x {type: text, body: one}
      - type: text
        body: two
      - type: text
        body: three
  - *x
"""

ALIASED_GRID_CELL = """version: 1
meta: {title: T}
blocks:
  - type: grid
    cells:
      - &c
        span: 3
        blocks:
          - type: heading
            text: G1
          - type: text
            body: a
      - *c
  - type: heading
    text: B
"""

DUPLICATE_BLOCKS_KEY = """version: 1
meta: {title: T}
blocks:
  - type: section
    title: S
    blocks:
      - type: heading
        text: X
      - type: text
        body: a
    blocks:
      - type: heading
        text: Y
      - type: text
        body: b
"""

DASH_ON_ITS_OWN_LINE = """version: 1
meta: {title: T}
blocks:
  - type: heading
    text: A
  - type: text
    body: x
  -
    type: heading
    text: B
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

STRIPPED_AT_THE_END_OF_THE_FILE = """version: 1
meta: {title: T}
blocks:
  - type: heading
    text: A
  - type: text
    body: |-
      last"""

FOLDED_THEN_BLANK_LINES = """version: 1
meta: {title: T}
blocks:
  - type: heading
    text: A
  - type: text
    body: >
      folded


  - type: heading
    text: B
"""

NO_HEADINGS = """version: 1
meta: {title: T}
blocks:
  - type: text
    body: x
"""

SIMPLE = """version: 1
meta: {title: T}
blocks:
  - type: heading
    text: A
"""

SPACES_KEPT_AS_CONTENT = (
    "version: 1\nmeta: {title: T}\nblocks:\n  - type: heading\n    text: A\n  - type: text\n"
    "    body: |\n      text\n" + " " * 9 + "\n  - type: heading\n    text: B\n"
)

ALIASED_TYPE = """version: 1
meta: {title: T}
blocks:
  - type: &t heading
    text: A
  - type: *t
    text: B
"""
HEADINGS_IN_TABS = """version: 1
meta: {title: T}
blocks:
  - type: tabs
    tabs:
      - label: One
        blocks:
          - type: heading
            text: In tab one
          - type: text
            body: first tab
      - label: Two
        blocks:
          - type: heading
            text: In tab two
          - type: text
            body: second tab
"""
HEADING_IN_A_WALKTHROUGH_STEP = """version: 1
meta: {title: T}
blocks:
  - type: walkthrough
    steps:
      - label: Parse
        detail:
          - type: heading
            text: Step heading
            level: 3
          - type: text
            body: detail text
      - label: Ship
        detail:
          - type: text
            body: no heading here
"""

ALIAS_REASON = "is not written in place (it comes through a YAML alias or merge key)"
UNCHECKED_REASON = "could not be checked against the file"
OUTLINE_AND_SHOW = [
    pytest.param(("outline", "{path}"), id="outline"),
    pytest.param(("show", "{path}#a"), id="show"),
]
_OUTLINE_JSON = TypeAdapter(OutlineJson)


@pytest.fixture
def document(tmp_path: Path) -> Path:
    _write(tmp_path / "fragment.yaml", FRAGMENT)
    return _write(tmp_path / "doc.yaml", DOCUMENT)


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    return path


def _node_tree(node: yaml.Node | None) -> object:
    if isinstance(node, yaml.MappingNode):
        return node.tag, [(_node_tree(key), _node_tree(value)) for key, value in node.value]
    if isinstance(node, yaml.SequenceNode):
        return node.tag, [_node_tree(item) for item in node.value]
    return None if node is None else (node.tag, node.value)


def _write_bytes_that_are_not_utf_8(path: Path) -> None:
    path.write_bytes(b"\xffversion: 1\n")


def _region(
    anchor: str,
    title: str,
    level: int | None,
    span: tuple[int, int, int] | None,
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
        "start_line": span[0] if span else None,
        "end_line": span[1] if span else None,
        "tokens": span[2] if span else None,
    }


def _argv(template: tuple[str, str], path: Path) -> list[str]:
    return [part.format(path=path) for part in template]


def _outlined(path: Path, capsys: pytest.CaptureFixture[str]) -> tuple[int, OutlineJson]:
    exit_code = main(["outline", str(path), "--json"])
    return exit_code, _OUTLINE_JSON.validate_json(capsys.readouterr().out)


def _shown(region: str, capsys: pytest.CaptureFixture[str]) -> tuple[int, tuple[str, str]]:
    exit_code = main(["show", region])
    captured = capsys.readouterr()
    return exit_code, (captured.out, captured.err)


def _none_of_its_lines(path: Path, anchor: str, reason: str) -> tuple[int, tuple[str, str]]:
    return 1, ("", f"error: {path}#{anchor} {reason}, so {path} holds none of its lines\n")


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


def test_a_document_without_headings_or_sections_outlines_to_an_empty_table(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write(tmp_path / "doc.yaml", NO_HEADINGS)

    exit_code = main(["outline", str(path)])

    assert (exit_code, capsys.readouterr().out) == (
        0,
        f"ANCHOR  KIND  LEVEL  ID  START  END  ~TOKENS  TITLE\n{path}: 5 lines, ~16 tokens\n",
    )


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("version: 1\nmeta: {title: T}\nindex: {parts: [one.yaml, two.yaml]}\n", id="inline"),
        pytest.param("version: 1\nmeta: {title: T}\nindex: !include index-parts.yaml\n", id="included"),
        pytest.param(yaml.safe_dump(make_index_report(["one.yaml", "two.yaml"])), id="factory"),
    ],
)
@pytest.mark.parametrize("template", OUTLINE_AND_SHOW)
def test_an_index_document_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], text: str, template: tuple[str, str]
) -> None:
    _write(tmp_path / "index-parts.yaml", "parts: [one.yaml, two.yaml]\n")
    path = _write(tmp_path / "index.yaml", text)

    exit_code = main(_argv(template, path))

    assert (exit_code, capsys.readouterr()) == (
        2,
        (
            "",
            f"error: {path} is an index document; "
            "outline each file it lists under `index.parts` on its own\n",
        ),
    )


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        pytest.param(
            "version: 1\nmeta: {title: T}\nindex:\nblocks:\n  - type: heading\n    text: A\n",
            (6, 19, (5, 6, 8)),
            id="null",
        ),
        pytest.param(
            "version: 1\nmeta: {title: T}\nblocks:\n"
            "  - type: heading\n    id: &n ~\n    text: A\nindex: *n\n",
            (7, 23, (4, 6, 11)),
            id="alias-to-null",
        ),
    ],
)
def test_an_index_that_is_null_is_a_normal_document(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    text: str,
    expected: tuple[int, int, tuple[int, int, int]],
) -> None:
    path = _write(tmp_path / "doc.yaml", text)
    lines, tokens, span = expected

    assert _outlined(path, capsys) == (
        0,
        {"file": str(path), "lines": lines, "tokens": tokens, "regions": [_region("a", "A", 2, span)]},
    )


@pytest.mark.parametrize("template", OUTLINE_AND_SHOW)
def test_an_empty_file_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], template: tuple[str, str]
) -> None:
    path = _write(tmp_path / "doc.yaml", "")

    exit_code = main(_argv(template, path))

    assert (exit_code, capsys.readouterr()) == (
        1,
        ("", "error: invalid content data: Input should be a valid dictionary or instance of Report\n"),
    )


@pytest.mark.parametrize("template", OUTLINE_AND_SHOW)
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
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    template: tuple[str, str],
    text: str | None,
    message: str,
) -> None:
    path = tmp_path / "doc.yaml"
    if text is not None:
        _write(path, text)

    exit_code = main(_argv(template, path))

    assert (exit_code, capsys.readouterr()) == (1, ("", f"error: {message.format(path=path)}\n"))


@pytest.mark.parametrize("template", OUTLINE_AND_SHOW)
@pytest.mark.parametrize(
    ("make", "message"),
    [
        pytest.param(
            Path.mkdir, "could not read {path}: [Errno 21] Is a directory: '{path}'", id="directory"
        ),
        pytest.param(
            _write_bytes_that_are_not_utf_8,
            "could not read {path}: 'utf-8' codec can't decode byte 0xff in position 0: invalid start byte",
            id="invalid-utf-8",
        ),
    ],
)
def test_a_file_that_cannot_be_read_fails_with_its_error(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    template: tuple[str, str],
    make: Callable[[Path], object],
    message: str,
) -> None:
    path = tmp_path / "doc.yaml"
    make(path)

    exit_code = main(_argv(template, path))

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


def test_show_writes_the_region_bytes_unchanged_to_stdout(tmp_path: Path) -> None:
    path = tmp_path / "crlf.yaml"
    path.write_bytes(
        "version: 1\r\nmeta: {title: T}\r\nblocks:\r\n  - type: heading\r\n    text: Résumé\r\n".encode()
    )

    shown = subprocess.run(
        [
            sys.executable,
            "-c",
            "from skaldr.cli import main; raise SystemExit(main())",
            "show",
            f"{path}#résumé",
        ],
        capture_output=True,
        check=False,
    )

    assert (shown.returncode, shown.stdout, shown.stderr) == (
        0,
        "  - type: heading\r\n    text: Résumé\r\n".encode(),
        b"",
    )


def test_a_heading_region_keeps_a_kept_blank_line_and_leaves_out_the_comment_after_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write(tmp_path / "doc.yaml", KEPT_BLANK_LINE)

    exit_code, outlined = _outlined(path, capsys)

    assert (exit_code, outlined["regions"]) == (
        0,
        [_region("a", "A", 2, (4, 9, 18)), _region("b", "B", 2, (11, 12, 8))],
    )
    assert _shown(f"{path}#a", capsys) == (
        0,
        ("  - type: heading\n    text: A\n  - type: text\n    body: |+\n      kept\n\n", ""),
    )


@pytest.mark.parametrize(
    ("header", "tail", "regions", "shown"),
    [
        pytest.param(
            "&x |+",
            "\n  - type: heading\n    text: B\n",
            [_region("a", "A", 2, (4, 9, 18)), _region("b", "B", 2, (10, 11, 8))],
            "  - type: heading\n    text: A\n  - type: text\n    body: &x |+\n      x\n\n",
            id="anchor",
        ),
        pytest.param(
            "!!str |+",
            "\n  - type: heading\n    text: B\n",
            [_region("a", "A", 2, (4, 9, 19)), _region("b", "B", 2, (10, 11, 8))],
            "  - type: heading\n    text: A\n  - type: text\n    body: !!str |+\n      x\n\n",
            id="tag",
        ),
        pytest.param(
            "&x >+",
            "\n\n",
            [_region("a", "A", 2, (4, 10, 18))],
            "  - type: heading\n    text: A\n  - type: text\n    body: &x >+\n      x\n\n\n",
            id="anchor-folded-at-the-end",
        ),
    ],
)
def test_a_kept_string_behind_an_anchor_or_a_tag_keeps_its_blank_lines(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    header: str,
    tail: str,
    regions: list[OutlineRegionJson],
    shown: str,
) -> None:
    path = _write(
        tmp_path / "doc.yaml",
        "version: 1\nmeta: {title: T}\nblocks:\n  - type: heading\n    text: A\n  - type: text\n"
        f"    body: {header}\n      x\n{tail}",
    )

    exit_code, outlined = _outlined(path, capsys)

    assert (exit_code, outlined["regions"]) == (0, regions)
    assert _shown(f"{path}#a", capsys) == (0, (shown, ""))


def test_a_string_stripped_at_the_end_of_the_file_ends_its_region(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write(tmp_path / "doc.yaml", STRIPPED_AT_THE_END_OF_THE_FILE)

    exit_code, outlined = _outlined(path, capsys)

    assert (exit_code, outlined["regions"]) == (0, [_region("a", "A", 2, (4, 8, 17))])
    assert _shown(f"{path}#a", capsys) == (
        0,
        ("  - type: heading\n    text: A\n  - type: text\n    body: |-\n      last", ""),
    )


def test_blank_lines_after_a_folded_string_belong_to_no_region(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write(tmp_path / "doc.yaml", FOLDED_THEN_BLANK_LINES)

    exit_code, outlined = _outlined(path, capsys)

    assert (exit_code, outlined["regions"]) == (
        0,
        [_region("a", "A", 2, (4, 8, 18)), _region("b", "B", 2, (11, 12, 8))],
    )


def test_an_item_whose_dash_stands_alone_starts_on_the_dash_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write(tmp_path / "doc.yaml", DASH_ON_ITS_OWN_LINE)

    exit_code, outlined = _outlined(path, capsys)

    assert (exit_code, outlined["regions"]) == (
        0,
        [_region("a", "A", 2, (4, 7, 15)), _region("b", "B", 2, (8, 10, 9))],
    )
    assert _shown(f"{path}#b", capsys) == (0, ("  -\n    type: heading\n    text: B\n", ""))


def test_a_region_whose_text_does_not_read_back_as_its_blocks_has_no_lines(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write(tmp_path / "doc.yaml", SPACES_KEPT_AS_CONTENT)

    exit_code, outlined = _outlined(path, capsys)

    assert (exit_code, outlined["regions"]) == (
        0,
        [_region("a", "A", 2, None), _region("b", "B", 2, (10, 11, 8))],
    )
    assert _shown(f"{path}#a", capsys) == _none_of_its_lines(path, "a", UNCHECKED_REASON)


def test_show_reads_the_file_once_and_checks_only_the_region_it_prints(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _write(tmp_path / "doc.yaml", SPACES_KEPT_AS_CONTENT)
    whole_file = _node_tree(yaml.SafeLoader(SPACES_KEPT_AS_CONTENT).get_single_node())
    region_b = _node_tree(yaml.SafeLoader("  - type: heading\n    text: B\n").get_single_node())
    composed: list[object] = []
    compose_one_document = Composer.get_single_node

    def record_what_was_composed(loader: Composer) -> yaml.Node | None:
        node = compose_one_document(loader)
        composed.append(_node_tree(node))
        return node

    monkeypatch.setattr(Composer, "get_single_node", record_what_was_composed)
    opened: list[Path] = []
    open_a_path = Path.open

    def record_the_opened_path(
        self: Path,
        mode: str = "r",
        buffering: int = -1,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
    ) -> IO[Any]:
        opened.append(self)
        return open_a_path(self, mode, buffering, encoding, errors, newline)

    monkeypatch.setattr(Path, "open", record_the_opened_path)

    assert _shown(f"{path}#b", capsys) == (0, ("  - type: heading\n    text: B\n", ""))
    assert (sorted(composed, key=repr), opened) == (
        sorted([whole_file, whole_file, region_b], key=repr),
        [path],
    )


def test_a_block_whose_type_comes_through_an_alias_is_not_written_in_place(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write(tmp_path / "doc.yaml", ALIASED_TYPE)

    exit_code, outlined = _outlined(path, capsys)

    assert (exit_code, outlined["regions"]) == (
        0,
        [_region("a", "A", 2, (4, 5, 9)), _region("b", "B", 2, None)],
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
    assert _shown(f"{path}#a-2", capsys) == _none_of_its_lines(path, "a-2", ALIAS_REASON)


def test_a_section_ending_in_an_alias_ends_on_the_alias_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write(tmp_path / "doc.yaml", ALIASED_LAST_VALUE)

    exit_code, outlined = _outlined(path, capsys)

    assert (exit_code, outlined["regions"]) == (
        0,
        [_region("s", "S", None, (6, 10, 20), kind="section"), _region("a", "A", 2, (11, 12, 14))],
    )
    assert _shown(f"{path}#s", capsys) == (
        0,
        ("  - type: section\n    title: S\n    blocks:\n      - type: text\n        body: *b\n", ""),
    )


def test_an_alias_of_a_nested_block_ends_the_heading_region_on_its_own_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write(tmp_path / "doc.yaml", ALIAS_OF_A_NESTED_BLOCK)

    exit_code, outlined = _outlined(path, capsys)

    assert (exit_code, outlined["regions"]) == (
        0,
        [_region("h", "H", 2, (4, 14, 48)), _region("s", "S", None, (6, 13, 39), kind="section")],
    )


def test_an_aliased_grid_cell_is_not_written_in_place(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write(tmp_path / "doc.yaml", ALIASED_GRID_CELL)

    exit_code, outlined = _outlined(path, capsys)

    assert (exit_code, outlined["regions"]) == (
        0,
        [
            _region("g1", "G1", 2, (9, 12, 23)),
            _region("g1-2", "G1", 2, None),
            _region("b", "B", 2, (14, 15, 8)),
        ],
    )
    assert _shown(f"{path}#g1-2", capsys) == _none_of_its_lines(path, "g1-2", ALIAS_REASON)


def test_a_repeated_key_reads_the_last_value_as_the_document_does(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write(tmp_path / "doc.yaml", DUPLICATE_BLOCKS_KEY)

    exit_code, outlined = _outlined(path, capsys)

    assert (exit_code, outlined["regions"]) == (
        0,
        [_region("s", "S", None, (4, 15, 51), kind="section"), _region("y", "Y", 2, (12, 15, 19))],
    )
    assert _shown(f"{path}#y", capsys) == (
        0,
        ("      - type: heading\n        text: Y\n      - type: text\n        body: b\n", ""),
    )


def test_blocks_written_on_one_flow_line_share_their_lines(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write(tmp_path / "doc.yaml", ONE_LINE_FLOW)

    exit_code, outlined = _outlined(path, capsys)

    assert (exit_code, outlined["regions"]) == (0, [_region("a", "A", 2, None), _region("b", "B", 2, None)])
    assert _shown(f"{path}#a", capsys) == _none_of_its_lines(
        path, "a", "shares its lines with the next block"
    )
    assert _shown(f"{path}#b", capsys) == _none_of_its_lines(
        path, "b", "shares its lines with the block before it"
    )


def test_blocks_that_share_a_line_with_the_list_around_them_have_no_lines(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write(tmp_path / "doc.yaml", FLOW_ON_THE_KEY_LINE)
    reason = "shares its lines with the list around it"

    exit_code, outlined = _outlined(path, capsys)

    assert (exit_code, outlined["regions"]) == (0, [_region("a", "A", 2, None), _region("b", "B", 2, None)])
    assert [_shown(f"{path}#{anchor}", capsys) for anchor in ("a", "b")] == [
        _none_of_its_lines(path, anchor, reason) for anchor in ("a", "b")
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

    exit_code, outlined = _outlined(path, capsys)

    assert (exit_code, outlined["regions"]) == (
        0,
        [_region("a", "A", 2, (4, 5, 14)), _region("b", "B", 2, (6, 6, 7))],
    )
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

    exit_code, outlined = _outlined(path, capsys)

    assert (exit_code, outlined["regions"]) == (
        0,
        [_region("outer", "Outer", None, (4, 6, 17), kind="section"), _region("inner", "Inner", 2, None)],
    )


def test_a_yaml_next_line_character_breaks_a_line(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    next_line = chr(0x85)
    path = _write(
        tmp_path / "doc.yaml",
        "version: 1\nmeta: {title: T}\nblocks:\n  - type: text\n    body: |\n"
        f"      one{next_line}      two\n  - type: heading\n    text: After\n",
    )

    exit_code, outlined = _outlined(path, capsys)

    assert (exit_code, outlined["regions"]) == (0, [_region("after", "After", 2, (8, 9, 9))])


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
    assert _shown(f"{document}#borrowed", capsys) == _none_of_its_lines(
        document, "borrowed", "comes from `!include fragment.yaml` at line 31"
    )


@pytest.mark.parametrize("written_type", ["", "    type: heading\n"], ids=["merged-type", "own-type"])
def test_a_heading_with_a_merge_key_is_not_written_in_place(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], written_type: str
) -> None:
    path = _write(
        tmp_path / "doc.yaml",
        "version: 1\nmeta: {title: T}\nblocks:\n  - &h {type: heading, text: A}\n"
        f"  - <<: *h\n{written_type}    text: B\n",
    )

    exit_code, outlined = _outlined(path, capsys)

    assert (exit_code, outlined["regions"]) == (
        0,
        [_region("a", "A", 2, (4, 4, 8)), _region("b", "B", 2, None)],
    )
    assert _shown(f"{path}#b", capsys) == _none_of_its_lines(path, "b", ALIAS_REASON)


def test_a_section_with_a_merge_key_is_not_written_in_place(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write(
        tmp_path / "doc.yaml",
        "version: 1\nmeta: {title: T}\nblocks:\n  - &s\n    type: section\n    title: S\n    blocks:\n"
        "      - type: text\n        body: x\n  - <<: *s\n    type: section\n    title: T\n",
    )

    exit_code, outlined = _outlined(path, capsys)

    assert (exit_code, outlined["regions"]) == (
        0,
        [_region("s", "S", None, (4, 9, 22), kind="section"), _region("t", "T", None, None, kind="section")],
    )


@pytest.mark.parametrize(
    ("text", "regions", "shown"),
    [
        pytest.param(
            "version: 1\nmeta: {title: T}\nblocks:\n  - # note\n    type: heading\n    text: A\n"
            "  - # other\n    type: text\n    body: z\n  - type: heading\n    text: B\n",
            [_region("a", "A", 2, (4, 9, 20)), _region("b", "B", 2, (10, 11, 8))],
            "  - # note\n    type: heading\n    text: A\n  - # other\n    type: text\n    body: z\n",
            id="comment-on-the-dash",
        ),
        pytest.param(
            "version: 1\nmeta: {title: T}\nblocks:\n"
            "  - # note\n\n    # more\n    type: heading\n    text: A\n",
            [_region("a", "A", 2, (4, 8, 14))],
            "  - # note\n\n    # more\n    type: heading\n    text: A\n",
            id="blank-and-comment-lines-after-the-dash",
        ),
    ],
)
def test_an_item_whose_dash_carries_a_comment_starts_on_the_dash_line(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    text: str,
    regions: list[OutlineRegionJson],
    shown: str,
) -> None:
    path = _write(tmp_path / "doc.yaml", text)

    exit_code, outlined = _outlined(path, capsys)

    assert (exit_code, outlined["regions"]) == (0, regions)
    assert _shown(f"{path}#a", capsys) == (0, (shown, ""))


def test_a_key_written_as_an_alias_never_stands_for_a_field(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write(
        tmp_path / "doc.yaml",
        "version: 1\nmeta: {title: T}\nblocks:\n  - type: heading\n    &blocks id: my-id\n    text: A\n"
        "  - type: section\n    title: S\n    blocks:\n      - type: heading\n        text: Inner\n"
        "    *blocks : sect-id\n  - type: heading\n    text: Tail\n",
    )

    exit_code, outlined = _outlined(path, capsys)

    assert (exit_code, outlined["regions"]) == (
        0,
        [
            _region("my-id", "A", 2, (4, 12, 40), author_set=True),
            _region("sect-id", "S", None, (7, 12, 27), kind="section", author_set=True),
            _region("inner", "Inner", 2, (10, 11, 11)),
            _region("tail", "Tail", 2, (13, 14, 9)),
        ],
    )


def test_a_kept_string_whose_anchor_stands_on_the_line_before_keeps_its_blank_lines(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write(
        tmp_path / "doc.yaml",
        "version: 1\nmeta: {title: T}\nblocks:\n  - type: heading\n    text: A\n  - type: text\n"
        "    body: &k\n      |+\n      keep\n\n\n  - type: heading\n    text: B\n",
    )

    exit_code, outlined = _outlined(path, capsys)

    assert (exit_code, outlined["regions"]) == (
        0,
        [_region("a", "A", 2, (4, 11, 20)), _region("b", "B", 2, (12, 13, 8))],
    )
    assert _shown(f"{path}#a", capsys) == (
        0,
        ("  - type: heading\n    text: A\n  - type: text\n    body: &k\n      |+\n      keep\n\n\n", ""),
    )


def test_a_heading_ending_in_an_empty_value_keeps_its_lines(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write(
        tmp_path / "doc.yaml",
        "version: 1\nmeta: {title: T}\nblocks:\n  - type: heading\n    text: A\n    id:\n"
        "  - type: heading\n    text: B\n",
    )

    exit_code, outlined = _outlined(path, capsys)

    assert (exit_code, outlined["regions"]) == (
        0,
        [_region("a", "A", 2, (4, 6, 10)), _region("b", "B", 2, (7, 8, 8))],
    )


def test_a_heading_in_a_tab_ends_at_the_end_of_its_own_tab(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write(tmp_path / "doc.yaml", HEADINGS_IN_TABS)

    exit_code, outlined = _outlined(path, capsys)

    assert (exit_code, outlined["regions"]) == (
        0,
        [
            _region("in-tab-one", "In tab one", 2, (8, 11, 27)),
            _region("in-tab-two", "In tab two", 2, (14, 17, 27)),
        ],
    )
    assert _shown(f"{path}#in-tab-two", capsys) == (
        0,
        (
            "          - type: heading\n"
            "            text: In tab two\n"
            "          - type: text\n"
            "            body: second tab\n",
            "",
        ),
    )


def test_a_heading_in_a_walkthrough_step_ends_at_the_end_of_its_step(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write(tmp_path / "doc.yaml", HEADING_IN_A_WALKTHROUGH_STEP)

    exit_code, outlined = _outlined(path, capsys)

    assert (exit_code, outlined["regions"]) == (0, [_region("step-heading", "Step heading", 3, (8, 12, 33))])
    assert _shown(f"{path}#step-heading", capsys) == (
        0,
        (
            "          - type: heading\n"
            "            text: Step heading\n"
            "            level: 3\n"
            "          - type: text\n"
            "            body: detail text\n",
            "",
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
