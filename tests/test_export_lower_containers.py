from typing import Any

import pytest

from skaldr.export.inline import bold, italic, plain
from skaldr.export.runs import TonedLabel
from skaldr.export.tree import (
    Callout,
    Columns,
    GridColumn,
    Heading,
    ListEntry,
    ListNode,
    Node,
    Paragraph,
    Tab,
    Tabs,
    Toggle,
)
from skaldr.richtext import Plain, Styled
from tests.factories import (
    lowered,
    lowered_as_written_today,
    make_cell,
    make_grid,
    make_tab,
    make_tabs,
    make_toggle,
)


def test_a_walkthrough_step_with_no_sub_is_its_bold_label() -> None:
    walkthrough = {
        "type": "walkthrough",
        "steps": [{"label": "Go", "detail": [{"type": "text", "body": "d"}]}],
    }

    assert lowered([walkthrough]) == (
        ListNode("number", (ListEntry(bold("Go"), children=(Paragraph((Plain("d"),)),)),)),
    )


def test_a_level_four_heading_inside_a_section_moves_down_to_level_five() -> None:
    section = {
        "type": "section",
        "title": "Open",
        "collapsed": False,
        "blocks": [{"type": "heading", "text": "Deep", "level": 4}],
    }

    assert lowered([section]) == (Heading(2, (Plain("Open"),), "open"), Heading(5, (Plain("Deep"),), "deep"))


def test_an_open_section_is_a_heading_and_a_level_three_heading_inside_it_moves_to_level_four() -> None:
    section = {
        "type": "section",
        "title": "Open",
        "collapsed": False,
        "blocks": [{"type": "heading", "text": "Deep", "level": 3}],
    }

    assert lowered([section]) == (Heading(2, (Plain("Open"),), "open"), Heading(4, (Plain("Deep"),), "deep"))


def test_a_collapsed_section_is_a_toggle_heading_with_its_updated_line() -> None:
    section = {
        "type": "section",
        "title": "Raw",
        "updated": "1 Jan",
        "blocks": [{"type": "text", "body": "x"}],
    }

    assert lowered([section]) == (
        Toggle(
            (Plain("Raw"),),
            2,
            (Paragraph(italic(plain("updated 1 Jan")), "muted"), Paragraph((Plain("x"),))),
            "raw",
        ),
    )


def test_a_panel_and_a_walkthrough_carry_their_content() -> None:
    blocks = [
        {"type": "panel", "title": "Next", "blocks": [{"type": "text", "body": "p"}]},
        {
            "type": "walkthrough",
            "steps": [
                {"label": "Go", "sub": "first", "tone": "info", "detail": [{"type": "text", "body": "d"}]}
            ],
        },
    ]

    assert lowered(blocks) == (
        Callout("neutral", (Paragraph(bold("Next")), Paragraph((Plain("p"),))), shows_icon=False),
        ListNode(
            "number",
            (
                ListEntry(
                    (TonedLabel("info", (*bold("Go"), Plain(" "), Styled("italic", (Plain("first"),)))),),
                    children=(Paragraph((Plain("d"),)),),
                ),
            ),
        ),
    )


def test_a_collapsed_toggle_is_a_plain_toggle_with_no_heading_or_anchor() -> None:
    toggle = {"type": "toggle", "title": "Raw counts", "blocks": [{"type": "text", "body": "x"}]}

    assert lowered([toggle]) == (Toggle((Plain("Raw counts"),), None, (Paragraph((Plain("x"),)),)),)


def test_an_open_toggle_is_a_toggle_marked_open() -> None:
    toggle = {
        "type": "toggle",
        "title": "Raw counts",
        "collapsed": False,
        "blocks": [{"type": "text", "body": "x"}],
    }

    assert lowered([toggle]) == (
        Toggle(plain("Raw counts"), None, (Paragraph((Plain("x"),)),), authored_as="toggle", open=True),
    )


def test_an_open_toggle_is_written_as_its_bold_title_over_its_content() -> None:
    toggle = {
        "type": "toggle",
        "title": "Raw counts",
        "collapsed": False,
        "blocks": [{"type": "text", "body": "x"}],
    }

    assert lowered_as_written_today([toggle]) == (Paragraph(bold("Raw counts")), Paragraph((Plain("x"),)))


def test_a_heading_in_a_top_level_toggle_keeps_its_level_and_anchor() -> None:
    toggle = make_toggle({"type": "heading", "level": 3, "text": "Deep", "id": "deep"})

    assert lowered([toggle]) == (Toggle((Plain("More"),), None, (Heading(3, (Plain("Deep"),), "deep"),)),)


def test_a_heading_in_a_toggle_inside_a_section_moves_down_with_the_section_and_keeps_its_anchor() -> None:
    toggle = make_toggle({"type": "heading", "level": 3, "text": "Deep", "id": "deep"})
    section = {"type": "section", "title": "Open", "collapsed": False, "blocks": [toggle]}

    assert lowered([section]) == (
        Heading(2, (Plain("Open"),), "open"),
        Toggle((Plain("More"),), None, (Heading(4, (Plain("Deep"),), "deep"),)),
    )


RAW_COUNTS_TOGGLE = make_toggle({"type": "text", "body": "x"}, title="Raw counts")


RAW_COUNTS_TOGGLE_NODE = Toggle((Plain("Raw counts"),), None, (Paragraph((Plain("x"),)),))


@pytest.mark.parametrize(
    ("block", "nodes"),
    [
        pytest.param(
            make_grid([make_cell(6, [RAW_COUNTS_TOGGLE])]), (RAW_COUNTS_TOGGLE_NODE,), id="grid-cell"
        ),
        pytest.param(
            make_tabs(make_tab("Floor", RAW_COUNTS_TOGGLE), make_tab("System")),
            (
                Tabs(
                    (
                        Tab((Plain("Floor"),), (RAW_COUNTS_TOGGLE_NODE,)),
                        Tab((Plain("System"),), (Paragraph((Plain("System"),)),)),
                    )
                ),
            ),
            id="tab",
        ),
    ],
)
def test_a_toggle_inside_a_grid_cell_or_a_tab_lowers_like_a_top_level_toggle(
    block: dict[str, Any], nodes: tuple[Node, ...]
) -> None:
    assert lowered([block]) == nodes


def test_a_toned_grid_cell_becomes_a_callout_column_and_a_one_cell_grid_flattens() -> None:
    two = {
        "type": "grid",
        "cells": [
            {"span": 1, "tone": "info", "blocks": [{"type": "text", "body": "a"}]},
            {"span": 3, "blocks": [{"type": "text", "body": "b"}]},
        ],
    }
    one = {"type": "grid", "cells": [{"span": 6, "blocks": [{"type": "text", "body": "c"}]}]}

    assert lowered([two, one]) == (
        Columns(
            (
                GridColumn(25, (Callout("info", (Paragraph((Plain("a"),)),)),)),
                GridColumn(75, (Paragraph((Plain("b"),)),)),
            )
        ),
        Paragraph((Plain("c"),)),
    )


@pytest.mark.parametrize(
    ("spans", "ratios"),
    [
        pytest.param((2, 2, 2), (34, 33, 33), id="three-equal-cells-give-the-one-left-over-to-the-first"),
        pytest.param((1,) * 6, (17, 17, 17, 17, 16, 16), id="six-equal-cells-spread-the-four-left-over"),
        pytest.param(
            (1, 1, 1, 3), (17, 17, 16, 50), id="unequal-cells-give-the-left-over-to-the-largest-remainders"
        ),
    ],
)
def test_grid_cells_get_largest_remainder_ratios_that_add_up_to_a_hundred(
    spans: tuple[int, ...], ratios: tuple[int, ...]
) -> None:
    bodies = "abcdef"[: len(spans)]
    grid = {
        "type": "grid",
        "cells": [
            {"span": span, "blocks": [{"type": "text", "body": body}]}
            for span, body in zip(spans, bodies, strict=True)
        ],
    }

    assert lowered([grid]) == (
        Columns(
            tuple(
                GridColumn(ratio, (Paragraph((Plain(body),)),))
                for ratio, body in zip(ratios, bodies, strict=True)
            )
        ),
    )


def test_a_grid_inside_a_grid_cell_lays_its_cells_one_after_another() -> None:
    inner = {
        "type": "grid",
        "cells": [{"span": 3, "blocks": [{"type": "text", "body": body}]} for body in "bc"],
    }
    grid = {
        "type": "grid",
        "cells": [{"span": 2, "blocks": [{"type": "text", "body": "a"}]}, {"span": 4, "blocks": [inner]}],
    }

    assert lowered([grid]) == (
        Columns(
            (
                GridColumn(33, (Paragraph((Plain("a"),)),)),
                GridColumn(67, (Paragraph((Plain("b"),)), Paragraph((Plain("c"),)))),
            )
        ),
    )


def test_a_toned_one_cell_grid_becomes_its_callout() -> None:
    grid = make_grid([{**make_cell(6, [{"type": "text", "body": "a"}]), "tone": "warning"}])

    assert lowered([grid]) == (Callout("warning", (Paragraph((Plain("a"),)),)),)


def test_a_toned_cell_of_an_inner_grid_becomes_a_callout_inside_the_outer_column() -> None:
    inner = make_grid(
        [
            {**make_cell(3, [{"type": "text", "body": "b"}]), "tone": "danger"},
            make_cell(3, [{"type": "text", "body": "c"}]),
        ]
    )
    grid = make_grid([make_cell(2, [{"type": "text", "body": "a"}]), make_cell(4, [inner])])

    assert lowered([grid]) == (
        Columns(
            (
                GridColumn(33, (Paragraph((Plain("a"),)),)),
                GridColumn(67, (Callout("danger", (Paragraph((Plain("b"),)),)), Paragraph((Plain("c"),)))),
            )
        ),
    )
