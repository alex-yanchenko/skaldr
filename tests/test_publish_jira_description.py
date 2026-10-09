import re

import pytest
from pydantic import JsonValue

from skaldr.errors import ConnectorError
from skaldr.export.adf import compact_adf_length
from skaldr.publish.jira.description import (
    UNKEYED_SECTION,
    Layout,
    LayoutSection,
    blocks_of,
    comparable_node,
    comparable_section,
    description_doc,
    description_length,
    layout_of,
    section_blocks,
    section_text,
    split_description,
)


def _words(text: str) -> JsonValue:
    return {"type": "paragraph", "content": [{"type": "text", "text": text}]}


INTRO = _words("Welcome.")
TOOLS = _words("Spade.")
RAKE = _words("Rake.")
PLANTING = _words("Sow in spring.")
SECTIONS: dict[str, list[JsonValue]] = {"intro": [INTRO], "tools": [TOOLS, RAKE], "planting": [PLANTING]}


def test_a_section_is_its_blocks_as_sorted_indented_json_and_reads_back_whole() -> None:
    text = section_text([{"type": "rule"}, {"type": "paragraph", "attrs": {"b": 1, "a": 2}}])

    assert (text, section_blocks(text)) == (
        '[\n  {\n    "type": "rule"\n  },\n  {\n    "attrs": {\n      "a": 2,\n      "b": 1\n    },\n'
        '    "type": "paragraph"\n  }\n]\n',
        [{"type": "rule"}, {"type": "paragraph", "attrs": {"a": 2, "b": 1}}],
    )


def test_a_section_with_no_blocks_is_empty_text() -> None:
    assert (section_text([]), section_blocks(""), section_blocks("  \n")) == ("", [], [])


@pytest.mark.parametrize(
    "text", ['{"type": "rule"}', "Welcome.\n", '["text"'], ids=["object", "prose", "cut"]
)
def test_a_section_that_is_not_a_list_of_adf_blocks_is_refused(text: str) -> None:
    with pytest.raises(
        ConnectorError,
        match=f"^{re.escape('a Jira section holds a JSON list of ADF blocks, and this one does not: ')}",
    ):
        section_blocks(text)


def test_the_comparable_form_drops_what_jira_adds_or_reorders_and_keeps_the_rest() -> None:
    node: JsonValue = {
        "type": "table",
        "attrs": {"isNumberColumnEnabled": True, "layout": "wide", "localId": "jira-0001"},
        "content": [
            {
                "type": "tableRow",
                "content": [
                    {
                        "type": "tableCell",
                        "attrs": {"localId": "jira-0002", "background": None},
                        "content": [
                            {"type": "paragraph", "content": []},
                            {
                                "type": "paragraph",
                                "content": [
                                    {
                                        "type": "text",
                                        "text": "Shed",
                                        "marks": [{"type": "strong"}, {"type": "em"}],
                                    },
                                    {"type": "text", "text": " key", "marks": []},
                                ],
                            },
                        ],
                    }
                ],
            }
        ],
    }

    assert comparable_node(node) == {
        "type": "table",
        "attrs": {"isNumberColumnEnabled": True, "layout": "wide"},
        "content": [
            {
                "type": "tableRow",
                "content": [
                    {
                        "type": "tableCell",
                        "content": [
                            {"type": "paragraph"},
                            {
                                "type": "paragraph",
                                "content": [
                                    {
                                        "type": "text",
                                        "text": "Shed",
                                        "marks": [{"type": "em"}, {"type": "strong"}],
                                    },
                                    {"type": "text", "text": " key"},
                                ],
                            },
                        ],
                    }
                ],
            }
        ],
    }


def test_the_comparable_form_drops_default_attributes_and_keeps_widths_skaldr_never_writes() -> None:
    cell: JsonValue = {"type": "tableCell", "content": [_words("Shed")]}
    saved: JsonValue = [
        {
            "type": "table",
            "attrs": {
                "isNumberColumnEnabled": False,
                "layout": "center",
                "width": 760,
                "displayMode": "default",
            },
            "content": [
                {
                    "type": "tableRow",
                    "content": [{**cell, "attrs": {"colspan": 1, "rowspan": 1, "colwidth": [120]}}],
                }
            ],
        },
        {"type": "orderedList", "attrs": {"order": 1}, "content": []},
        {"type": "orderedList", "attrs": {"order": 4}},
        {"type": "tableCell", "attrs": {"colspan": 2}},
    ]

    assert comparable_node(saved) == [
        {
            "type": "table",
            "attrs": {"width": 760},
            "content": [{"type": "tableRow", "content": [{**cell, "attrs": {"colwidth": [120]}}]}],
        },
        {"type": "orderedList"},
        {"type": "orderedList", "attrs": {"order": 4}},
        {"type": "tableCell", "attrs": {"colspan": 2}},
    ]


def test_a_comparable_section_is_the_section_text_of_its_comparable_blocks() -> None:
    task: JsonValue = {"type": "taskList", "attrs": {"localId": "skaldr-task-list-1"}, "content": []}

    assert comparable_section(section_text([task, INTRO])) == section_text([{"type": "taskList"}, INTRO])


def test_the_description_is_one_adf_document_of_every_block_or_nothing_when_empty() -> None:
    assert (description_doc([INTRO, TOOLS]), description_doc([])) == (
        {"version": 1, "type": "doc", "content": [INTRO, TOOLS]},
        None,
    )


def test_the_blocks_of_a_description_are_its_content_and_none_for_an_empty_one() -> None:
    assert (
        blocks_of({"version": 1, "type": "doc", "content": [INTRO]}),
        blocks_of(None),
        blocks_of({"version": 1, "type": "doc"}),
    ) == ([INTRO], [], [])


def test_a_description_that_is_not_an_adf_document_is_refused() -> None:
    with pytest.raises(ConnectorError, match=r"^the description Jira returned is not an ADF document$"):
        blocks_of("Welcome.")


def test_joined_sections_that_are_not_adf_block_lists_are_refused() -> None:
    with pytest.raises(
        ConnectorError,
        match=f"^{re.escape('a Jira section holds a JSON list of ADF blocks, and this one does not: ')}",
    ):
        description_length(section_text([INTRO]) + "Welcome.\n")


def test_the_description_limit_measures_the_compact_document_of_the_joined_sections() -> None:
    joined = section_text([INTRO]) + "" + section_text([TOOLS, RAKE])

    assert (description_length(joined), description_length("")) == (
        compact_adf_length({"version": 1, "type": "doc", "content": [INTRO, TOOLS, RAKE]}),
        0,
    )


def test_the_layout_names_each_section_and_a_digest_of_each_of_its_blocks() -> None:
    layout = layout_of({"intro": [INTRO], "empty": [], "tools": [TOOLS, RAKE]})

    assert [(section.key, len(section.blocks)) for section in layout.sections] == [("intro", 1), ("tools", 2)]


def test_a_block_jira_numbered_has_the_digest_of_the_block_skaldr_sent() -> None:
    sent: JsonValue = {"type": "taskList", "attrs": {"localId": "skaldr-task-list-1"}}
    stored: JsonValue = {"type": "taskList", "attrs": {"localId": "jira-0001"}}

    assert layout_of({"tasks": [sent]}) == layout_of({"tasks": [stored]})


def _split(*blocks: JsonValue) -> dict[str, list[JsonValue]]:
    return split_description(list(blocks), layout_of(SECTIONS))


def test_an_unchanged_description_splits_back_into_its_sections() -> None:
    assert _split(INTRO, TOOLS, RAKE, PLANTING) == SECTIONS


def test_an_edited_block_stays_in_the_section_it_replaced() -> None:
    hoe = _words("Hoe.")

    assert _split(INTRO, hoe, RAKE, PLANTING) == {
        "intro": [INTRO],
        "tools": [hoe, RAKE],
        "planting": [PLANTING],
    }


def test_an_edited_first_block_of_a_section_stays_in_that_section() -> None:
    sow = _words("Sow in June.")

    assert _split(INTRO, TOOLS, RAKE, sow) == {"intro": [INTRO], "tools": [TOOLS, RAKE], "planting": [sow]}


def test_a_block_added_between_sections_joins_the_section_before_it() -> None:
    added = _words("Gloves.")

    assert _split(INTRO, TOOLS, RAKE, added, PLANTING) == {
        "intro": [INTRO],
        "tools": [TOOLS, RAKE, added],
        "planting": [PLANTING],
    }


def test_a_block_added_before_everything_joins_the_first_section() -> None:
    added = _words("Read me first.")

    assert _split(added, INTRO, TOOLS, RAKE, PLANTING) == {
        "intro": [added, INTRO],
        "tools": [TOOLS, RAKE],
        "planting": [PLANTING],
    }


def test_a_section_whose_blocks_were_deleted_is_left_out() -> None:
    assert _split(INTRO, PLANTING) == {"intro": [INTRO], "planting": [PLANTING]}


def test_without_a_layout_the_whole_description_is_one_section_under_a_key_no_block_can_have() -> None:
    assert (UNKEYED_SECTION, split_description([INTRO, TOOLS], None)) == (
        "(description)",
        {"(description)": [INTRO, TOOLS]},
    )


def test_sections_moved_around_in_jira_keep_their_own_blocks_in_the_order_jira_has_them() -> None:
    split = _split(PLANTING, TOOLS, RAKE, INTRO)

    assert (list(split), split) == (
        ["planting", "tools", "intro"],
        {"planting": [PLANTING], "tools": [TOOLS, RAKE], "intro": [INTRO]},
    )


def test_a_moved_section_whose_first_block_was_also_edited_joins_the_section_before_it() -> None:
    hoe = _words("Hoe.")

    assert _split(PLANTING, hoe, RAKE, INTRO) == {"planting": [PLANTING, hoe, RAKE], "intro": [INTRO]}


def test_an_empty_description_has_no_sections() -> None:
    assert (split_description([], layout_of(SECTIONS)), split_description([], None)) == ({}, {})


def test_two_sections_with_the_same_text_keep_their_own_blocks() -> None:
    layout = Layout(
        sections=[
            LayoutSection(key="spring", blocks=layout_of({"x": [INTRO]}).sections[0].blocks),
            LayoutSection(key="autumn", blocks=layout_of({"x": [INTRO]}).sections[0].blocks),
        ]
    )

    assert split_description([INTRO, INTRO], layout) == {"spring": [INTRO], "autumn": [INTRO]}
