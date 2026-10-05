import pytest

from skaldr.prose_blocks import ProseBlock, ProseItem, ProseList, prose_blocks, rendered_strings


def bullets(*texts: str) -> ProseList:
    return ProseList(tuple(ProseItem(text) for text in texts))


def numbers(start: int, *texts: str) -> ProseList:
    return ProseList(tuple(ProseItem(text) for text in texts), start)


@pytest.mark.parametrize(
    ("text", "blocks"),
    [
        pytest.param("One line.", ["One line."], id="a-paragraph"),
        pytest.param("First.\n\nSecond.", ["First.", "Second."], id="blank-line-paragraphs"),
        pytest.param("a\n\n\n\nb", ["a", "b"], id="a-run-of-blank-lines"),
        pytest.param("  a \n\n  \n", ["a"], id="trimmed-and-whitespace-dropped"),
        pytest.param("a\nb", ["a\nb"], id="a-single-newline-stays-inside-the-paragraph"),
        pytest.param("- a\n- b", [bullets("a", "b")], id="bullets"),
        pytest.param("* a\n* b", [bullets("a", "b")], id="star-bullets"),
        pytest.param("1. a\n2. b", [numbers(1, "a", "b")], id="numbers"),
        pytest.param("3) a\n9) b", [numbers(3, "a", "b")], id="numbers-keep-the-first-number"),
        pytest.param("- a\r\n- b", [bullets("a", "b")], id="crlf-line-endings"),
        pytest.param("  - a\n  - b", [bullets("a", "b")], id="an-indented-list"),
        pytest.param(
            "Intro:\n- a\n- b\n\nOutro.",
            ["Intro:", bullets("a", "b"), "Outro."],
            id="a-list-right-under-a-line-and-a-blank-line-after-it",
        ),
        pytest.param(
            "- a\n- b\nmore of b",
            [bullets("a", "b\nmore of b")],
            id="a-line-right-after-an-item-continues-it",
        ),
        pytest.param(
            "- a\n  more of a\n- b", [bullets("a\nmore of a", "b")], id="an-indented-line-continues"
        ),
        pytest.param(
            "- a\n- b\n* c\n* d",
            [bullets("a", "b"), bullets("c", "d")],
            id="a-change-of-bullet-starts-a-list",
        ),
        pytest.param(
            "- a\n- b\n1. c\n2. d", [bullets("a", "b"), numbers(1, "c", "d")], id="bullets-then-numbers"
        ),
        pytest.param(
            "- a\n- b\n \n- c\n- d",
            [bullets("a", "b", "c", "d")],
            id="a-blank-line-between-items-keeps-one-list",
        ),
        pytest.param(
            "- a\n- b\n  - x\n  - y",
            [ProseList((ProseItem("a"), ProseItem("b", (bullets("x", "y"),))))],
            id="a-nested-list",
        ),
        pytest.param(
            "- a\n- b\n  - x",
            [ProseList((ProseItem("a"), ProseItem("b", (bullets("x"),))))],
            id="a-one-item-list-inside-a-list-stays-a-list",
        ),
        pytest.param("-a\n*italic* b\n1.5 kg", ["-a\n*italic* b\n1.5 kg"], id="no-space-after-the-marker"),
        pytest.param("  indented\n- a\n- b", ["indented", bullets("a", "b")], id="leading-space-is-trimmed"),
        pytest.param("- leading dash", ["- leading dash"], id="one-marked-line-stays-text"),
        pytest.param("2024. was the year", ["2024. was the year"], id="a-year-at-the-start-stays-text"),
        pytest.param(
            "Intro\n- only\nEnd", ["Intro\n- only\nEnd"], id="a-one-item-list-rejoins-its-paragraph"
        ),
        pytest.param("- note\n\nAfter", ["- note", "After"], id="a-one-item-list-keeps-its-blank-line"),
        pytest.param("- a\n1. b", ["- a\n1. b"], id="two-one-item-lists-stay-text"),
        pytest.param("\\- a\n\\- b", ["\\- a\n\\- b"], id="an-escaped-marker-is-text"),
        pytest.param(
            "1234567890. x\n1234567891. y", ["1234567890. x\n1234567891. y"], id="ten-digits-is-no-number"
        ),
        pytest.param(
            "\N{ARABIC-INDIC DIGIT ONE}. a\n\N{ARABIC-INDIC DIGIT TWO}. b",
            ["\N{ARABIC-INDIC DIGIT ONE}. a\n\N{ARABIC-INDIC DIGIT TWO}. b"],
            id="only-ascii-digits-number-a-list",
        ),
        pytest.param(
            "# no heading\n> no quote\n---", ["# no heading\n> no quote\n---"], id="other-markdown-is-text"
        ),
        pytest.param("", [], id="empty"),
    ],
)
def test_prose_splits_into_paragraphs_and_lists(text: str, blocks: list[ProseBlock]) -> None:
    assert prose_blocks(text) == blocks


def test_rendered_strings_are_each_paragraph_and_each_list_item_at_every_depth() -> None:
    text = "Intro:\n- a\n  more\n- b\n  - c\n  - d\n\nEnd."

    assert rendered_strings(text) == ["Intro:", "a\nmore", "b", "c", "d", "End."]
