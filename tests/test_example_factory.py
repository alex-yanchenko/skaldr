from pathlib import Path

import pytest

from tests.factories.example_factory import (
    GOLDEN_REWRITE_VARIABLE_FOR,
    edited_once,
    golden_of,
    golden_or_scratch_folder,
)


def test_an_edit_replaces_the_one_place_the_example_holds_its_text() -> None:
    assert edited_once("the [lots]{tone=danger} stay", "[lots]{tone=danger}", "lots") == "the lots stay"


@pytest.mark.parametrize(
    ("text", "times"),
    [pytest.param("the lots stay", 0, id="missing"), pytest.param("[a] and [a]", 2, id="twice")],
)
def test_an_edit_whose_text_the_example_does_not_hold_exactly_once_fails(text: str, times: int) -> None:
    with pytest.raises(ValueError) as raised:
        edited_once(text, "[a]", "a")

    assert str(raised.value) == (
        f"data/example.yaml holds '[a]' {times} times, not once; update EXAMPLE_EDITS_FOR"
    )


def test_each_target_names_the_variable_that_rewrites_its_golden() -> None:
    assert GOLDEN_REWRITE_VARIABLE_FOR == {
        "markdown": "SKALDR_WRITE_MARKDOWN_GOLDEN",
        "notion": "SKALDR_WRITE_NOTION_GOLDEN",
        "adf": "SKALDR_WRITE_ADF_GOLDEN",
        "slack": "SKALDR_WRITE_SLACK_GOLDEN",
    }


def test_the_golden_is_rewritten_only_while_its_variable_is_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SKALDR_WRITE_ADF_GOLDEN", raising=False)
    scratch_while_unset = golden_or_scratch_folder("adf", tmp_path)
    monkeypatch.setenv("SKALDR_WRITE_ADF_GOLDEN", "1")

    assert (scratch_while_unset, golden_or_scratch_folder("adf", tmp_path)) == (tmp_path, golden_of("adf"))
