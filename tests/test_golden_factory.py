import json
from pathlib import Path

import pytest

from tests.factories.golden_factory import assert_matches_golden, golden_mismatch

HTML = (
    '<!doctype html>\n<main>\n<section class="rq">\n<p>one</p>\n</section>\n'
    '<div class="callout tone-warning">\n<p>two</p>\n</div>\n</main>\n'
)
MARKDOWN = "intro\n\n# Plan\n\nfirst\n\n## Risks\n\nsecond\n"
ADF = {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "a"}]}]}


def _json(document: object) -> str:
    return json.dumps(document, indent=2)


def test_a_file_equal_to_its_golden_has_no_mismatch() -> None:
    assert [
        golden_mismatch("page.adf.json", _json(ADF), _json(ADF)),
        golden_mismatch("example.html", HTML, HTML),
        golden_mismatch("page.md", MARKDOWN, MARKDOWN),
    ] == [None, None, None]


def test_an_adf_difference_is_named_by_its_json_path() -> None:
    written = {**ADF, "content": [{"type": "paragraph", "content": [{"type": "text", "text": "b"}]}]}

    assert golden_mismatch("page.adf.json", _json(ADF), _json(written)) == (
        "page.adf.json differs from the golden in 1 place:\n"
        "  $.content[0].content[0].text: expected 'a', got 'b'"
    )


def test_an_adf_node_added_removed_or_retyped_is_named_by_its_json_path() -> None:
    written = {
        "type": "doc",
        "version": 1,
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": "a"}, {"type": "hardBreak"}]},
            {"type": "rule"},
        ],
    }
    expected = {**ADF, "extra": True}

    assert golden_mismatch("page.adf.json", _json(expected), _json(written)) == (
        "page.adf.json differs from the golden in 4 places:\n"
        "  $.content: expected 1 items, got 2\n"
        "  $.content[0].content: expected 1 items, got 2\n"
        "  $.extra: missing from the output\n"
        "  $.version: not in the golden"
    )


def test_an_html_difference_is_named_by_the_component_it_sits_in() -> None:
    written = HTML.replace("<p>two</p>", "<p>three</p>")

    assert golden_mismatch("example.html", HTML, written) == (
        "example.html differs from the golden in 1 place:\n"
        '  in <div class="callout tone-warning"> (golden line 7):\n'
        "    - <p>two</p>\n"
        "    + <p>three</p>"
    )


def test_a_markdown_difference_is_named_by_the_heading_it_sits_under() -> None:
    written = MARKDOWN.replace("second", "2nd")

    assert golden_mismatch("page.md", MARKDOWN, written) == (
        "page.md differs from the golden in 1 place:\n"
        "  under '## Risks' (golden line 9):\n"
        "    - second\n"
        "    + 2nd"
    )


def test_a_difference_before_any_heading_says_so() -> None:
    written = MARKDOWN.replace("intro", "preface")

    assert golden_mismatch("page.md", MARKDOWN, written) == (
        "page.md differs from the golden in 1 place:\n"
        "  before the first heading (golden line 1):\n"
        "    - intro\n"
        "    + preface"
    )


def test_more_than_ten_differences_are_cut_off_with_a_count() -> None:
    expected = {"items": list(range(15))}
    written = {"items": [number + 100 for number in range(15)]}

    mismatch = golden_mismatch("page.adf.json", _json(expected), _json(written))

    assert mismatch is not None
    assert (mismatch.splitlines()[0], mismatch.splitlines()[-1], len(mismatch.splitlines())) == (
        "page.adf.json differs from the golden in 15 places:",
        "  ... and 5 more",
        12,
    )


def _folders(tmp_path: Path, golden: dict[str, str], written: dict[str, str]) -> tuple[Path, Path]:
    golden_folder = tmp_path / "golden"
    written_folder = tmp_path / "written"
    for folder, files in ((golden_folder, golden), (written_folder, written)):
        folder.mkdir()
        for name, text in files.items():
            (folder / name).write_text(text, encoding="utf-8")
    return golden_folder, written_folder


def test_a_folder_that_matches_its_golden_passes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SKALDR_WRITE_SLACK_GOLDEN", raising=False)
    golden, written = _folders(tmp_path, {"page.md": MARKDOWN}, {"page.md": MARKDOWN})

    assert assert_matches_golden("slack", written, golden) is None


def test_a_folder_that_differs_from_its_golden_fails_with_the_per_block_difference(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SKALDR_WRITE_SLACK_GOLDEN", raising=False)
    golden, written = _folders(tmp_path, {"page.md": MARKDOWN}, {"page.md": MARKDOWN.replace("first", "1st")})

    with pytest.raises(AssertionError) as failure:
        assert_matches_golden("slack", written, golden)

    assert str(failure.value) == (
        "page.md differs from the golden in 1 place:\n"
        "  under '# Plan' (golden line 5):\n"
        "    - first\n"
        "    + 1st"
    )


def test_a_folder_with_other_files_than_its_golden_fails_naming_both_lists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SKALDR_WRITE_SLACK_GOLDEN", raising=False)
    golden, written = _folders(
        tmp_path, {"page.md": MARKDOWN}, {"page.md": MARKDOWN, "image-1.svg": "<svg/>"}
    )

    with pytest.raises(AssertionError) as failure:
        assert_matches_golden("slack", written, golden)

    assert (
        str(failure.value) == "the golden holds ['page.md'] but the export wrote ['image-1.svg', 'page.md']"
    )


def test_a_golden_rewrite_run_ends_in_a_failure_even_when_the_rewritten_golden_matches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SKALDR_WRITE_SLACK_GOLDEN", "1")
    golden, written = _folders(tmp_path, {"page.md": MARKDOWN}, {"page.md": MARKDOWN})

    with pytest.raises(pytest.fail.Exception) as failure:
        assert_matches_golden("slack", written, golden)

    assert str(failure.value) == (
        "SKALDR_WRITE_SLACK_GOLDEN is set, so the slack golden was rewritten from this run and "
        "nothing was compared; review the golden's diff, then run again without the variable"
    )
