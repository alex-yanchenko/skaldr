import pytest

from skaldr.prose_blocks import ProseBlock, ProseList, paragraphs, prose_blocks, rendered_strings


@pytest.mark.parametrize(
    ("text", "parts"),
    [
        pytest.param("a\n\nb", ["a", "b"], id="blank-line"),
        pytest.param("a\n\n\n\nb", ["a", "b"], id="run-of-blank-lines"),
        pytest.param("  a \n\n  \n", ["a"], id="trimmed-and-whitespace-dropped"),
        pytest.param("one\nline", ["one\nline"], id="single-newline-stays"),
        pytest.param("\n\n", [], id="only-blank-lines"),
    ],
)
def test_paragraphs_split_on_blank_lines_and_drop_empty_ones(text: str, parts: list[str]) -> None:
    assert paragraphs(text) == parts


@pytest.mark.parametrize(
    ("text", "blocks"),
    [
        pytest.param("One line.", ["One line."], id="a-paragraph"),
        pytest.param("First.\n\nSecond.", ["First.", "Second."], id="blank-line-paragraphs"),
        pytest.param("a\nb", ["a\nb"], id="a-single-newline-stays-inside-the-paragraph"),
        pytest.param("- a\n- b", [ProseList(("a", "b"))], id="bullets"),
        pytest.param("* a\n* b", [ProseList(("a", "b"))], id="star-bullets"),
        pytest.param("1. a\n2. b", [ProseList(("a", "b"), 1)], id="numbers"),
        pytest.param("3) a\n9) b", [ProseList(("a", "b"), 3)], id="numbers-keep-the-first-number"),
        pytest.param(
            "Intro:\n- a\n- b\nOutro.",
            ["Intro:", ProseList(("a", "b")), "Outro."],
            id="a-list-between-lines-of-one-paragraph",
        ),
        pytest.param(
            "- a\n  more of a\n- b",
            [ProseList(("a more of a", "b"))],
            id="an-indented-line-continues-the-item",
        ),
        pytest.param(
            "- a\n- b\n1. c\n2. d",
            [ProseList(("a", "b")), ProseList(("c", "d"), 1)],
            id="a-change-of-marker-starts-a-list",
        ),
        pytest.param(
            "- a\n- b\n\n- c\n- d", [ProseList(("a", "b")), ProseList(("c", "d"))], id="blank-line-ends"
        ),
        pytest.param("-a\n*italic* b\n1.5 kg", ["-a\n*italic* b\n1.5 kg"], id="no-space-after-the-marker"),
        pytest.param(
            "  indented\n- a\n- b", ["indented", ProseList(("a", "b"))], id="leading-space-is-trimmed"
        ),
        pytest.param("- `code` a\n- b", [ProseList(("`code` a", "b"))], id="item-text-is-rich-text"),
        pytest.param("- leading dash", ["- leading dash"], id="one-marked-line-stays-text"),
        pytest.param("2024. was the year", ["2024. was the year"], id="a-year-at-the-start-stays-text"),
        pytest.param("Intro\n- only\nEnd", ["Intro\n- only\nEnd"], id="a-one-item-run-rejoins-its-paragraph"),
        pytest.param("- a\n1. b", ["- a\n1. b"], id="two-one-item-runs-stay-text"),
        pytest.param("", [], id="empty"),
    ],
)
def test_prose_splits_into_paragraphs_and_lists(text: str, blocks: list[ProseBlock]) -> None:
    assert prose_blocks(text) == blocks


def test_rendered_strings_are_each_paragraph_and_each_list_item() -> None:
    assert rendered_strings("Intro:\n- a\n  more\n- b\n\nEnd.") == ["Intro:", "a more", "b", "End."]
