from typing import Any

import pytest

from skaldr.export.folds import quote_lines
from skaldr.export.runs import Break, Chip, DecisionMark
from skaldr.export.tree import (
    Definition,
    DefinitionList,
    ListEntry,
    ListNode,
    Paragraph,
    Quote,
    TableCell,
    TableNode,
    TableRow,
    TextNumbering,
)
from skaldr.richtext import Plain
from tests.factories import API_BADGES, lowered, lowered_as_written_today, make_table
from tests.factories.lower_factory import cell_texts_of


def test_a_definition_list_lowers_to_each_term_over_the_prose_of_its_body() -> None:
    block = {
        "type": "def_list",
        "items": [{"term": "Fix", "body": "first\n\n- one\n- two"}, {"term": "Gap", "body": " "}],
    }

    assert lowered([block]) == (
        DefinitionList(
            (
                Definition(
                    "Fix",
                    (
                        Paragraph((Plain("first"),)),
                        ListNode("bullet", (ListEntry((Plain("one"),)), ListEntry((Plain("two"),)))),
                    ),
                ),
                Definition("Gap", ()),
            )
        ),
    )


@pytest.mark.parametrize(
    "options",
    [pytest.param({}, id="numbering-left-out"), pytest.param({"numbering": "decimal"}, id="decimal")],
)
def test_a_decimal_list_keeps_its_start_and_its_nested_list_counts_from_one(options: dict[str, Any]) -> None:
    block = {
        "type": "list",
        "style": "number",
        "start": 3,
        "items": [{"text": "a", "items": ["b"]}],
        **options,
    }

    assert lowered([block]) == (
        ListNode(
            "number",
            (ListEntry((Plain("a"),), children=(ListNode("number", (ListEntry((Plain("b"),)),)),)),),
            start=3,
        ),
    )


@pytest.mark.parametrize("numbering", ["roman", "letters"])
def test_a_letter_or_roman_list_is_a_numbered_list_naming_its_numbering_at_every_level(
    numbering: TextNumbering,
) -> None:
    block = {
        "type": "list",
        "style": "number",
        "start": 4,
        "numbering": numbering,
        "items": ["a", {"text": "b", "items": ["c"]}],
    }

    assert lowered([block]) == (
        ListNode(
            "number",
            (
                ListEntry((Plain("a"),)),
                ListEntry(
                    (Plain("b"),),
                    children=(ListNode("number", (ListEntry((Plain("c"),)),), numbering=numbering),),
                ),
            ),
            start=4,
            numbering=numbering,
        ),
    )


@pytest.mark.parametrize(
    ("numbering", "labels"),
    [
        pytest.param("roman", ("iv. ", "v. ", "i. "), id="roman"),
        pytest.param("letters", ("d. ", "e. ", "a. "), id="letters"),
    ],
)
def test_a_letter_or_roman_list_is_written_as_bullets_led_by_its_labels_and_a_nested_list_starts_over(
    numbering: str, labels: tuple[str, str, str]
) -> None:
    block = {
        "type": "list",
        "style": "number",
        "start": 4,
        "numbering": numbering,
        "items": ["a", {"text": "b", "items": ["c"]}],
    }
    first, second, nested = labels

    assert lowered_as_written_today([block]) == (
        ListNode(
            "bullet",
            (
                ListEntry((Plain(first), Plain("a"))),
                ListEntry(
                    (Plain(second), Plain("b")),
                    children=(ListNode("bullet", (ListEntry((Plain(nested), Plain("c"))),)),),
                ),
            ),
        ),
    )


def test_a_checklist_entry_holds_only_its_nested_checklist() -> None:
    block = {
        "type": "list",
        "style": "check",
        "items": [{"text": "a", "checked": True, "items": [{"text": "b", "items": ["c"]}]}],
    }

    assert lowered([block]) == (
        ListNode(
            "check",
            (
                ListEntry(
                    (Plain("a"),),
                    checked=True,
                    children=(
                        ListNode(
                            "check",
                            (
                                ListEntry(
                                    (Plain("b"),), children=(ListNode("check", (ListEntry((Plain("c"),)),)),)
                                ),
                            ),
                        ),
                    ),
                ),
            ),
        ),
    )


def test_a_decision_list_is_a_bullet_list_led_by_a_decision_mark_at_every_level() -> None:
    block = {
        "type": "list",
        "style": "decision",
        "items": ["open", {"text": "done", "decided": True, "items": ["sub"]}],
    }

    assert lowered([block]) == (
        ListNode(
            "bullet",
            (
                ListEntry((DecisionMark(decided=False), Plain(" "), Plain("open"))),
                ListEntry(
                    (DecisionMark(decided=True), Plain(" "), Plain("done")),
                    children=(
                        ListNode(
                            "bullet", (ListEntry((DecisionMark(decided=False), Plain(" "), Plain("sub"))),)
                        ),
                    ),
                ),
            ),
        ),
    )


QUOTE_WITH_LISTS = "Said:\n- a\n  - x\n  - y\n- b\n\n3. c\n4. d"


def test_a_quote_holds_the_lists_of_its_body_as_list_nodes() -> None:
    block = {"type": "quote", "body": QUOTE_WITH_LISTS, "cite": "Ops"}
    nested = ListNode("bullet", (ListEntry((Plain("x"),)), ListEntry((Plain("y"),))))

    assert lowered([block]) == (
        Quote(
            (
                Paragraph((Plain("Said:"),)),
                ListNode("bullet", (ListEntry((Plain("a"),), children=(nested,)), ListEntry((Plain("b"),)))),
                ListNode("number", (ListEntry((Plain("c"),)), ListEntry((Plain("d"),))), start=3),
            ),
            (Plain("Ops"),),
        ),
    )


def test_a_quote_with_lists_is_written_as_text_lines_led_by_their_markers() -> None:
    (quote,) = lowered([{"type": "quote", "body": QUOTE_WITH_LISTS}])
    assert isinstance(quote, Quote)

    assert quote_lines(quote) == (
        (Plain("Said:"),),
        (Plain("• "), Plain("a")),
        (Plain("◦ "), Plain("x")),
        (Plain("◦ "), Plain("y")),
        (Plain("• "), Plain("b")),
        (Plain("3. "), Plain("c")),
        (Plain("4. "), Plain("d")),
    )


def test_a_table_cell_holding_a_list_holds_its_prose_as_paragraphs_and_lists() -> None:
    table = make_table(
        [
            {"key": "a", "label": "Issue"},
            {"key": "tag", "label": "", "kind": "badge", "placement": "title"},
            {"key": "b", "label": "Steps"},
        ],
        rows=[
            {
                "a": "Fix:\n- one\n- two",
                "tag": "API",
                "b": "- x\n- y",
                "subrows": [{"label": "s", "value": 2}],
            },
            {"a": "Plain", "tag": "", "b": "Count"},
        ],
    )

    assert lowered([table], badges=API_BADGES)[1] == TableNode(
        cell_texts_of("Issue", "Steps"),
        (
            TableRow(
                (
                    TableCell(
                        (),
                        blocks=(
                            Paragraph((Plain("Fix:"),)),
                            ListNode(
                                "bullet",
                                (
                                    ListEntry((Plain("one"),)),
                                    ListEntry((Plain("two"), Plain(" "), Chip("api", "blue"))),
                                ),
                            ),
                            Paragraph((Plain("s"), Plain(": 2"))),
                        ),
                    ),
                    TableCell(
                        (), blocks=(ListNode("bullet", (ListEntry((Plain("x"),)), ListEntry((Plain("y"),)))),)
                    ),
                )
            ),
            TableRow((TableCell((Plain("Plain"),)), TableCell((Plain("Count"),)))),
        ),
    )


def test_a_title_cells_badges_follow_a_closing_paragraph_after_its_list() -> None:
    table = make_table(
        [{"key": "a", "label": "Issue"}, {"key": "tag", "label": "", "kind": "badge", "placement": "title"}],
        rows=[{"a": "- one\n- two\n\nEnd", "tag": "API"}],
    )

    assert lowered([table], badges=API_BADGES)[1] == TableNode(
        cell_texts_of("Issue"),
        (
            TableRow(
                (
                    TableCell(
                        (),
                        blocks=(
                            ListNode("bullet", (ListEntry((Plain("one"),)), ListEntry((Plain("two"),)))),
                            Paragraph((Plain("End"), Plain(" "), Chip("api", "blue"))),
                        ),
                    ),
                )
            ),
        ),
    )


def test_a_table_cell_holding_a_list_is_written_as_text_lines_joined_by_breaks() -> None:
    table = make_table(
        [
            {"key": "a", "label": "Issue"},
            {"key": "tag", "label": "", "kind": "badge", "placement": "title"},
            {"key": "b", "label": "Steps"},
        ],
        rows=[
            {
                "a": "Fix:\n- one\n- two\n  - x\n  - y",
                "tag": "API",
                "b": "",
                "subrows": [{"label": "s", "value": 2}],
            }
        ],
    )

    assert lowered_as_written_today([table], badges=API_BADGES)[1] == TableNode(
        cell_texts_of("Issue", "Steps"),
        (
            TableRow(
                (
                    TableCell(
                        (
                            Plain("Fix:"),
                            Break(),
                            Plain("• "),
                            Plain("one"),
                            Break(),
                            Plain("• "),
                            Plain("two"),
                            Break(),
                            Plain("◦ "),
                            Plain("x"),
                            Break(),
                            Plain("◦ "),
                            Plain("y"),
                            Plain(" "),
                            Chip("api", "blue"),
                            Break(),
                            Plain("s"),
                            Plain(": 2"),
                        )
                    ),
                    TableCell(()),
                )
            ),
        ),
    )
