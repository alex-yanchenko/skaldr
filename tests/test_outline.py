import json
import math
from pathlib import Path
from typing import Any

import pytest
import yaml

from skaldr.cli import main
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


@pytest.fixture
def document(tmp_path: Path) -> Path:
    (tmp_path / "fragment.yaml").write_text(FRAGMENT, encoding="utf-8")
    path = tmp_path / "doc.yaml"
    path.write_text(DOCUMENT, encoding="utf-8")
    return path


def _source(start: int, end: int) -> str:
    return "".join(DOCUMENT.splitlines(keepends=True)[start - 1 : end])


def _tokens(start: int, end: int) -> int:
    return math.ceil(len(_source(start, end)) / 4)


def _region(
    anchor: str, title: str, level: int | None, lines: tuple[int, int] | None, **overrides: Any
) -> dict[str, Any]:
    region: dict[str, Any] = {
        "anchor": anchor,
        "kind": "heading",
        "level": level,
        "title": title,
        "author_set": False,
        "start_line": lines[0] if lines else None,
        "end_line": lines[1] if lines else None,
        "tokens": _tokens(*lines) if lines else None,
    }
    region.update(overrides)
    return region


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
    exit_code = main(["outline", str(document), "--json"])

    assert (exit_code, json.loads(capsys.readouterr().out)) == (
        0,
        {
            "file": str(document),
            "lines": 40,
            "tokens": math.ceil(len(DOCUMENT) / 4),
            "regions": [
                _region("overview", "Overview", 2, (5, 28)),
                _region("details", "Details", 3, (9, 28)),
                _region("evidence", "Evidence", None, (13, 24), kind="section", author_set=True),
                _region("inside", "Inside", 3, (18, 24)),
                _region("deep", "Deep", 4, (26, 28)),
                _region("overview-2", "Overview", 2, (29, 40)),
                _region("borrowed", "Borrowed", 3, None),
                _region("cell-note", "Cell note", 3, (36, 40)),
            ],
        },
    )


def test_outline_refuses_an_index_document(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "index.yaml"
    path.write_text(yaml.safe_dump(make_index_report(["one.yaml", "two.yaml"])), encoding="utf-8")

    exit_code = main(["outline", str(path)])

    assert (exit_code, capsys.readouterr()) == (
        2,
        (
            "",
            f"error: {path} is an index document; "
            "outline each file it lists under `index.parts` on its own\n",
        ),
    )


def test_show_prints_a_heading_region_word_for_word(
    document: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main(["show", f"{document}#details"])

    assert (exit_code, capsys.readouterr()) == (0, (_source(9, 28), ""))


def test_show_prints_a_section_region_word_for_word(
    document: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main(["show", f"{document}#evidence"])

    assert (exit_code, capsys.readouterr()) == (
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

    exit_code = main(["show", f"{path}#one"])

    assert (exit_code, capsys.readouterr()) == (
        0,
        ("  - type: heading\r\n    text: One\r\n  - type: text\r\n    body: x\r\n", ""),
    )


def test_show_names_the_closest_anchors_for_an_unknown_one(
    document: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main(["show", f"{document}#overveiw"])

    assert (exit_code, capsys.readouterr()) == (
        1,
        ("", f"error: no anchor 'overveiw' in {document}; did you mean: overview, overview-2\n"),
    )


def test_show_points_to_the_outline_when_no_anchor_is_close(
    document: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main(["show", f"{document}#zzz"])

    assert (exit_code, capsys.readouterr()) == (
        1,
        ("", f"error: no anchor 'zzz' in {document}; `skaldr outline {document}` lists them\n"),
    )


def test_show_refuses_a_region_an_include_brings_in(
    document: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main(["show", f"{document}#borrowed"])

    assert (exit_code, capsys.readouterr()) == (
        1,
        (
            "",
            f"error: {document}#borrowed comes from `!include fragment.yaml` at line 31, "
            f"so {document} holds none of its lines\n",
        ),
    )


def test_show_without_an_anchor_is_a_usage_error(document: Path, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exited:
        main(["show", str(document)])

    assert (exited.value.code, capsys.readouterr().err.splitlines()[-1]) == (
        2,
        "skaldr show: error: name the region as FILE#ANCHOR; `skaldr outline FILE` lists the anchors",
    )
