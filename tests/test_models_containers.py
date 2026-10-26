from collections.abc import Callable
from typing import Any, get_args

import pytest

from skaldr.errors import ReportError
from skaldr.models import (
    MAX_STRIP_LABELS,
    FullWidthBlock,
    Grid,
    InnerBlock,
    InnerToggle,
    Panel,
    Report,
    Section,
    SectionBlock,
    Tab,
    Tabs,
    Text,
    Toggle,
    Walkthrough,
    WalkthroughStep,
    parse_report,
    walk_blocks,
)
from tests.factories import (
    make_cell,
    make_command_request,
    make_flow,
    make_grid,
    make_report,
    make_request,
    make_section,
    make_step,
    make_tab,
    make_tabs,
    make_toggle,
)
from tests.factories.models_factory import in_a_tab, make_rollup_table


def test_section_may_not_contain_a_section() -> None:
    inner = {"type": "section", "title": "inner", "blocks": [{"type": "text", "body": "x"}]}
    outer = {"type": "section", "title": "outer", "blocks": [inner]}

    with pytest.raises(ReportError, match=r"blocks\.0\.section\.blocks\.0"):
        parse_report(make_report(blocks=[outer]))


@pytest.mark.parametrize("bad_id", ["Bad_ID", "has space", "trailing-", "-leading", "double--hyphen"])
def test_heading_id_with_a_non_slug_shape_is_rejected(bad_id: str) -> None:
    block = {"type": "heading", "text": "H", "id": bad_id}

    with pytest.raises(ReportError, match=r"blocks\.0\.heading\.id"):
        parse_report(make_report(blocks=[block]))


def test_section_accepts_a_slug_shaped_author_id() -> None:
    block = {
        "type": "section",
        "title": "Appendix",
        "id": "raw-data",
        "blocks": [{"type": "text", "body": "x"}],
    }

    report = parse_report(make_report(blocks=[block]))

    section = report.blocks[0]
    assert isinstance(section, Section)
    assert section.id == "raw-data"


def test_panel_parses_to_whole_model() -> None:
    block = {"type": "panel", "title": "Slide 1", "blocks": [{"type": "text", "body": "Hi."}]}

    report = parse_report(make_report(blocks=[block]))

    assert report.blocks[0] == Panel(type="panel", title="Slide 1", blocks=[Text(type="text", body="Hi.")])


def test_panel_with_no_blocks_is_rejected() -> None:
    with pytest.raises(ReportError, match=r"blocks\.0\.panel\.blocks"):
        parse_report(make_report(blocks=[{"type": "panel", "title": "Empty", "blocks": []}]))


def test_a_toggle_parses_to_whole_model_starting_collapsed() -> None:
    block = {"type": "toggle", "title": "Raw counts", "blocks": [{"type": "text", "body": "x"}]}

    report = parse_report(make_report(blocks=[block]))

    assert report.blocks[0] == Toggle(
        type="toggle", title="Raw counts", collapsed=True, blocks=[Text(type="text", body="x")]
    )


@pytest.mark.parametrize(
    "container",
    [
        pytest.param({"type": "section", "title": "S", "blocks": [make_toggle()]}, id="section"),
        pytest.param({"type": "panel", "title": "P", "blocks": [make_toggle()]}, id="panel"),
        pytest.param(make_grid([make_cell(6, [make_toggle()])]), id="grid-cell"),
        pytest.param(
            make_grid([make_cell(6, [make_grid([make_cell(3, [make_toggle()])])])]), id="inner-grid-cell"
        ),
        pytest.param(
            {"type": "walkthrough", "steps": [{"label": "Go", "detail": [make_toggle()]}]},
            id="walkthrough-detail",
        ),
        pytest.param(make_toggle(make_toggle()), id="another-toggle"),
    ],
)
def test_a_toggle_is_accepted_wherever_a_leaf_block_is(container: dict[str, Any]) -> None:
    parsed = parse_report(make_report(blocks=[container])).blocks[0]

    assert parsed.model_dump(exclude_defaults=True) == container


def test_a_toggle_with_no_blocks_is_rejected() -> None:
    with pytest.raises(ReportError) as raised:
        parse_report(make_report(blocks=[{"type": "toggle", "title": "Empty", "blocks": []}]))

    assert str(raised.value) == (
        "invalid content data: blocks.0.toggle.blocks: "
        "List should have at least 1 item after validation, not 0"
    )


def test_a_toggle_in_a_grid_cell_parses_to_the_inner_toggle_holding_leaf_blocks() -> None:
    grid = parse_report(make_report(blocks=[make_grid([make_cell(6, [make_toggle()])])])).blocks[0]

    assert isinstance(grid, Grid)
    assert grid.cells[0].blocks == [
        InnerToggle(type="toggle", title="More", collapsed=True, blocks=[Text(type="text", body="x")])
    ]


@pytest.mark.parametrize(
    ("block", "location"),
    [
        pytest.param(make_toggle(title="  "), "blocks.0.toggle.title", id="toggle"),
        pytest.param(
            make_grid([make_cell(6, [make_toggle(title="\t")])]),
            "blocks.0.grid.cells.0.blocks.0.toggle.title",
            id="inner-toggle",
        ),
    ],
)
def test_a_toggle_with_a_blank_title_is_rejected(block: dict[str, Any], location: str) -> None:
    with pytest.raises(ReportError) as raised:
        parse_report(make_report(blocks=[block]))

    assert str(raised.value) == f"invalid content data: {location}: String should match pattern '\\S'"


@pytest.mark.parametrize(
    ("block", "location"),
    [
        pytest.param(make_request(label=" "), "blocks.0.request.label", id="request"),
        pytest.param(
            make_request(cases=[{"label": "\t", "response": {"status": 200, "body": "[]"}}]),
            "blocks.0.request.cases.0.label",
            id="request-case",
        ),
        pytest.param(make_flow(label=" "), "blocks.0.request_flow.label", id="request-flow"),
        pytest.param(
            make_flow(steps=[make_step(label=" ")]), "blocks.0.request_flow.steps.0.label", id="flow-step"
        ),
        pytest.param(make_tabs(make_tab(" ")), "blocks.0.tabs.tabs.0.label", id="tab"),
        pytest.param(
            {
                "type": "comparison",
                "options": ["A", "B"],
                "rows": [{"feature": " ", "values": [True, False]}],
            },
            "blocks.0.comparison.rows.0.feature",
            id="comparison-feature",
        ),
    ],
)
def test_a_label_that_is_blank_is_rejected(block: dict[str, Any], location: str) -> None:
    with pytest.raises(ReportError) as raised:
        parse_report(make_report(blocks=[block]))

    assert str(raised.value) == f"invalid content data: {location}: String should match pattern '\\S'"


@pytest.mark.parametrize(
    ("definition", "field", "schema"),
    [
        pytest.param(
            "Toggle",
            "title",
            {
                "description": "Summary label shown on the collapsible.",
                "minLength": 1,
                "pattern": r"\S",
                "title": "Title",
                "type": "string",
            },
            id="toggle-title",
        ),
        pytest.param(
            "InnerToggle",
            "title",
            {
                "description": "Summary label shown on the collapsible.",
                "minLength": 1,
                "pattern": r"\S",
                "title": "Title",
                "type": "string",
            },
            id="inner-toggle-title",
        ),
        pytest.param(
            "Tab",
            "label",
            {
                "description": "The tab's label in the strip, and its heading on paper.",
                "minLength": 1,
                "pattern": r"\S",
                "title": "Label",
                "type": "string",
            },
            id="tab-label",
        ),
    ],
)
def test_the_schema_refuses_a_blank_toggle_title_or_tab_label_as_the_build_does(
    definition: str, field: str, schema: dict[str, object]
) -> None:
    assert Report.model_json_schema()["$defs"][definition]["properties"][field] == schema


def _union_tags(union: object) -> str:
    return ", ".join(
        f"'{get_args(model.model_fields['type'].annotation)[0]}'" for model in get_args(get_args(union)[0])
    )


def test_a_toggle_where_a_section_block_can_go_refuses_a_section_inside_it() -> None:
    inner_section = {"type": "section", "title": "S", "blocks": [{"type": "text", "body": "x"}]}

    with pytest.raises(ReportError) as raised:
        parse_report(make_report(blocks=[make_toggle(inner_section)]))

    assert str(raised.value) == (
        "invalid content data: blocks.0.toggle.blocks.0: Input tag 'section' found using 'type' does not "
        f"match any of the expected tags: {_union_tags(SectionBlock)}"
    )


@pytest.mark.parametrize(
    "container",
    [
        pytest.param(make_toggle(make_request()), id="top-level"),
        pytest.param({"type": "section", "title": "S", "blocks": [make_toggle(make_flow())]}, id="section"),
        pytest.param(
            {"type": "panel", "title": "P", "blocks": [make_toggle(make_command_request())]}, id="panel"
        ),
        pytest.param(make_toggle(make_toggle(make_request())), id="toggle-in-a-toggle"),
    ],
)
def test_a_toggle_where_a_section_block_can_go_holds_a_request(container: dict[str, Any]) -> None:
    parsed = parse_report(make_report(blocks=[container])).blocks[0]

    assert parsed.model_dump(exclude_defaults=True) == container


PANEL = {"type": "panel", "title": "P", "blocks": [{"type": "text", "body": "x"}]}


@pytest.mark.parametrize(
    "container",
    [
        pytest.param({"type": "section", "title": "S", "blocks": [PANEL]}, id="section"),
        pytest.param(make_toggle(PANEL), id="top-level-toggle"),
        pytest.param(
            {"type": "section", "title": "S", "blocks": [make_toggle(PANEL)]}, id="toggle-in-a-section"
        ),
        pytest.param(
            {"type": "panel", "title": "Outer", "blocks": [make_toggle(PANEL)]}, id="toggle-in-a-panel"
        ),
    ],
)
def test_a_panel_is_accepted_in_a_section_and_in_a_toggle_where_a_section_block_can_go(
    container: dict[str, Any],
) -> None:
    parsed = parse_report(make_report(blocks=[container])).blocks[0]

    assert parsed.model_dump(exclude_defaults=True) == container


def test_a_panel_directly_inside_a_panel_is_refused() -> None:
    with pytest.raises(ReportError) as raised:
        parse_report(make_report(blocks=[{"type": "panel", "title": "Outer", "blocks": [PANEL]}]))

    assert str(raised.value) == (
        "invalid content data: blocks.0.panel.blocks.0: Input tag 'panel' found using 'type' does not "
        f"match any of the expected tags: {_union_tags(FullWidthBlock)}"
    )


def _in_a_grid_cell_toggle(block: dict[str, Any]) -> dict[str, Any]:
    return make_grid([make_cell(6, [make_toggle(block)])])


@pytest.mark.parametrize(
    ("container", "location"),
    [
        pytest.param(
            _in_a_grid_cell_toggle, "blocks.0.grid.cells.0.blocks.0.toggle.blocks.0", id="inner-toggle"
        ),
        pytest.param(in_a_tab, "blocks.0.tabs.tabs.0.blocks.0", id="tab"),
    ],
)
@pytest.mark.parametrize(
    ("refused", "tag"),
    [
        pytest.param(make_section("s"), "section", id="section"),
        pytest.param(
            {"type": "panel", "title": "P", "blocks": [{"type": "text", "body": "x"}]}, "panel", id="panel"
        ),
        pytest.param(make_grid([make_cell(6)]), "grid", id="grid"),
        pytest.param(
            {"type": "walkthrough", "steps": [{"label": "Go", "detail": [{"type": "text", "body": "x"}]}]},
            "walkthrough",
            id="walkthrough",
        ),
        pytest.param(make_request(), "request", id="request"),
        pytest.param(make_flow(), "request_flow", id="request-flow"),
    ],
)
def test_a_toggle_in_a_cell_and_a_tab_refuse_every_block_wider_than_a_leaf(
    container: Callable[[dict[str, Any]], dict[str, Any]], location: str, refused: dict[str, Any], tag: str
) -> None:
    with pytest.raises(ReportError) as raised:
        parse_report(make_report(blocks=[container(refused)]))

    assert str(raised.value) == (
        f"invalid content data: {location}: Input tag '{tag}' found using 'type' does not match any of the "
        f"expected tags: {_union_tags(InnerBlock)}"
    )


def test_a_tabs_block_parses_to_whole_model() -> None:
    block = make_tabs(make_tab("Floor", tone="amber"), make_tab("System"))

    report = parse_report(make_report(blocks=[block]))

    assert report.blocks[0] == Tabs(
        type="tabs",
        tabs=[
            Tab(label="Floor", tone="warning", blocks=[Text(type="text", body="Floor")]),
            Tab(label="System", tone=None, blocks=[Text(type="text", body="System")]),
        ],
    )


@pytest.mark.parametrize(
    "container",
    [
        pytest.param({"type": "section", "title": "S", "blocks": [make_tabs()]}, id="section"),
        pytest.param({"type": "panel", "title": "P", "blocks": [make_tabs()]}, id="panel"),
        pytest.param(make_grid([make_cell(6, [make_tabs()])]), id="grid-cell"),
        pytest.param(
            make_grid([make_cell(6, [make_grid([make_cell(3, [make_tabs()])])])]), id="inner-grid-cell"
        ),
        pytest.param(
            {"type": "walkthrough", "steps": [{"label": "Go", "detail": [make_tabs()]}]},
            id="walkthrough-detail",
        ),
        pytest.param(make_toggle(make_tabs()), id="toggle"),
        pytest.param(make_tabs(make_tab("Outer", make_tabs()), make_tab("Other")), id="another-tabs-block"),
    ],
)
def test_a_tabs_block_is_accepted_wherever_a_leaf_block_is(container: dict[str, Any]) -> None:
    parsed = parse_report(make_report(blocks=[container])).blocks[0]

    assert parsed.model_dump(exclude_defaults=True) == container


@pytest.mark.parametrize(
    ("block", "message"),
    [
        pytest.param(
            make_tabs(make_tab("Only")),
            "invalid content data: blocks.0.tabs.tabs: List should have at least 2 items after validation, "
            "not 1",
            id="one-tab",
        ),
        pytest.param(
            make_tabs(*(make_tab(f"t{number}") for number in range(MAX_STRIP_LABELS + 1))),
            f"invalid content data: blocks.0.tabs.tabs: List should have at most {MAX_STRIP_LABELS} items "
            f"after validation, not {MAX_STRIP_LABELS + 1}",
            id="past-the-cap",
        ),
        pytest.param(
            make_tabs(make_tab("Floor"), make_tab("Floor")),
            "invalid content data: blocks.0.tabs: Value error, tabs repeat a label: Floor",
            id="repeated-label",
        ),
        pytest.param(
            make_tabs(
                make_tab("System"),
                make_tab("Floor"),
                make_tab("System"),
                make_tab("Vendor"),
                make_tab("Floor"),
            ),
            "invalid content data: blocks.0.tabs: Value error, tabs repeat a label: Floor, System",
            id="several-repeated-labels",
        ),
        pytest.param(
            make_tabs(make_tab("  ", {"type": "text", "body": "x"}), make_tab("System")),
            "invalid content data: blocks.0.tabs.tabs.0.label: String should match pattern '\\S'",
            id="blank-label",
        ),
        pytest.param(
            make_tabs(make_tab("\t \n", {"type": "text", "body": "x"}), make_tab("System")),
            "invalid content data: blocks.0.tabs.tabs.0.label: String should match pattern '\\S'",
            id="whitespace-label",
        ),
        pytest.param(
            make_tabs(make_tab("", {"type": "text", "body": "x"}), make_tab("System")),
            "invalid content data: blocks.0.tabs.tabs.0.label: String should have at least 1 character",
            id="empty-label",
        ),
        pytest.param(
            make_tabs(make_tab("Floor", tone="purple"), make_tab("System")),
            "invalid content data: blocks.0.tabs.tabs.0.tone: Input should be 'neutral', 'info', "
            "'success', 'warning', 'danger', 'accent', 'teal' or 'sky'",
            id="unknown-tone",
        ),
    ],
)
def test_a_tabs_block_refuses_a_malformed_tab_set(block: dict[str, Any], message: str) -> None:
    with pytest.raises(ReportError) as raised:
        parse_report(make_report(blocks=[block]))

    assert str(raised.value) == message


def test_a_tabs_block_at_the_strip_cap_is_accepted() -> None:
    labels = [f"t{number}" for number in range(MAX_STRIP_LABELS)]

    parsed = parse_report(make_report(blocks=[make_tabs(*(make_tab(label) for label in labels))])).blocks[0]

    assert isinstance(parsed, Tabs)
    assert [tab.label for tab in parsed.tabs] == labels


_DUPLICATE_MATRIX = {
    "type": "matrix",
    "id": "dup",
    "rows": ["r1"],
    "columns": ["c1"],
    "cells": [{"row": "r1", "col": "c1", "label": "x"}],
}


_GHOST_MATRIX_CARD = {"type": "cards", "items": [{"badge": "HAVE", "of_matrix": "ghost"}]}


@pytest.mark.parametrize(
    ("container", "inside"),
    [
        pytest.param(make_toggle, "blocks.1.toggle.blocks.0", id="toggle"),
        pytest.param(
            _in_a_grid_cell_toggle, "blocks.1.grid.cells.0.blocks.0.toggle.blocks.0", id="inner-toggle"
        ),
        pytest.param(in_a_tab, "blocks.1.tabs.tabs.0.blocks.0", id="tab"),
    ],
)
@pytest.mark.parametrize(
    ("beside", "nested", "message"),
    [
        pytest.param(
            _DUPLICATE_MATRIX,
            _DUPLICATE_MATRIX,
            "matrix id(s) used more than once: ['dup'], at blocks.0.matrix.id, {inside}.matrix.id; "
            "matrix ids must be unique",
            id="matrix-id",
        ),
        pytest.param(
            make_rollup_table("dup"),
            make_rollup_table("dup"),
            "table id(s) used more than once: ['dup'], at blocks.0.table.id, {inside}.table.id; "
            "table ids must be unique",
            id="table-id",
        ),
        pytest.param(
            {"type": "text", "body": "x"},
            _GHOST_MATRIX_CARD,
            "card of_matrix names 'ghost', which is not the id of any matrix, at "
            "{inside}.cards.items.0.of_matrix",
            id="card-matrix-reference",
        ),
    ],
)
def test_a_reference_check_reaches_into_every_toggle_and_tab(
    container: Callable[[dict[str, Any]], dict[str, Any]],
    inside: str,
    beside: dict[str, Any],
    nested: dict[str, Any],
    message: str,
) -> None:
    badges = {"HAVE": {"label": "H", "tone": "green", "legend": "x"}}

    with pytest.raises(ReportError) as raised:
        parse_report(make_report(badges=badges, blocks=[beside, container(nested)]))

    assert str(raised.value) == f"invalid content data: Value error, {message.format(inside=inside)}"


def test_walk_blocks_visits_every_block_depth_first_in_document_order() -> None:
    blocks = [
        {
            "type": "section",
            "title": "S",
            "blocks": [make_toggle({"type": "divider"}), {"type": "text", "body": "a"}],
        },
        make_grid(
            [
                make_cell(3, [make_tabs(make_tab("A", {"type": "note", "body": "n"}), make_tab("B"))]),
                make_cell(3, [make_grid([make_cell(6, [{"type": "quote", "body": "q"}])])]),
            ]
        ),
        {
            "type": "walkthrough",
            "steps": [{"label": "Go", "detail": [make_toggle({"type": "code", "content": "c"})]}],
        },
        {"type": "panel", "title": "P", "blocks": [make_flow()]},
    ]

    report = parse_report(make_report(blocks=blocks))

    assert [block.type for block in walk_blocks(report.blocks)] == [
        "section",
        "toggle",
        "divider",
        "text",
        "grid",
        "tabs",
        "note",
        "text",
        "grid",
        "quote",
        "walkthrough",
        "toggle",
        "code",
        "panel",
        "request_flow",
    ]


def test_walkthrough_parses_to_whole_model_with_default_step_span() -> None:
    block = {
        "type": "walkthrough",
        "steps": [{"label": "Step one", "detail": [{"type": "text", "body": "do it"}]}],
    }

    report = parse_report(make_report(blocks=[block]))

    assert report.blocks[0] == Walkthrough(
        type="walkthrough",
        steps=[WalkthroughStep(label="Step one", detail=[Text(type="text", body="do it")])],
        step_span=2,
    )


def test_walkthrough_requires_at_least_one_step() -> None:
    with pytest.raises(ReportError, match=r"blocks\.0\.walkthrough\.steps.*at least 1"):
        parse_report(make_report(blocks=[{"type": "walkthrough", "steps": []}]))


def test_walkthrough_step_requires_at_least_one_detail_block() -> None:
    step: dict[str, object] = {"label": "S", "detail": []}

    with pytest.raises(ReportError, match=r"walkthrough\.steps\.0\.detail.*at least 1"):
        parse_report(make_report(blocks=[{"type": "walkthrough", "steps": [step]}]))


def test_walkthrough_step_label_must_not_be_blank() -> None:
    block = {"type": "walkthrough", "steps": [{"label": "  ", "detail": [{"type": "text", "body": "x"}]}]}

    with pytest.raises(
        ReportError, match=r"blocks\.0\.walkthrough\.steps\.0\.label: String should match pattern '\\S'$"
    ):
        parse_report(make_report(blocks=[block]))


def test_walkthrough_step_span_above_five_is_rejected() -> None:
    block = {
        "type": "walkthrough",
        "step_span": 6,
        "steps": [{"label": "S", "detail": [{"type": "text", "body": "x"}]}],
    }

    with pytest.raises(ReportError, match=r"blocks\.0\.walkthrough\.step_span"):
        parse_report(make_report(blocks=[block]))


def test_walkthrough_step_span_below_one_is_rejected() -> None:
    block = {
        "type": "walkthrough",
        "step_span": 0,
        "steps": [{"label": "S", "detail": [{"type": "text", "body": "x"}]}],
    }

    with pytest.raises(ReportError, match=r"blocks\.0\.walkthrough\.step_span"):
        parse_report(make_report(blocks=[block]))


def test_grid_cell_tone_parses_and_rejects_an_unknown_value() -> None:
    ok = make_grid([{"span": 6, "tone": "accent", "blocks": [{"type": "text", "body": "x"}]}])
    block = parse_report(make_report(blocks=[ok])).blocks[0]
    assert isinstance(block, Grid)
    assert block.cells[0].tone == "accent"

    bad = make_grid([{"span": 6, "tone": "bogus", "blocks": [{"type": "text", "body": "x"}]}])
    with pytest.raises(ReportError, match=r"blocks\.0\.grid\.cells\.0\.tone"):
        parse_report(make_report(blocks=[bad]))


def test_grid_parses() -> None:
    grid = make_grid([make_cell(2), make_cell(4)])

    report = parse_report(make_report(blocks=[grid]))

    assert report.blocks[0].type == "grid"


def test_grid_spans_under_six_leave_trailing_space() -> None:
    grid = make_grid([make_cell(2), make_cell(2)])  # sum 4 ≤ 6 — allowed

    report = parse_report(make_report(blocks=[grid]))

    assert report.blocks[0].type == "grid"


def test_grid_spans_exactly_six_are_allowed() -> None:
    grid = make_grid([make_cell(3), make_cell(3)])

    assert parse_report(make_report(blocks=[grid])).blocks[0].type == "grid"


def test_grid_spans_over_six_are_rejected() -> None:
    grid = make_grid([make_cell(4), make_cell(4)])

    with pytest.raises(ReportError, match=r"cell spans sum to 8; must total at most 6"):
        parse_report(make_report(blocks=[grid]))


def test_grid_span_out_of_range_is_rejected() -> None:
    grid = make_grid([make_cell(7)])

    with pytest.raises(ReportError, match=r"span\b.*less than or equal to 6"):
        parse_report(make_report(blocks=[grid]))


def test_grid_span_rejects_boolean() -> None:
    grid = make_grid([make_cell(True)])

    with pytest.raises(ReportError, match=r"span\b.*must be a number, not a boolean"):
        parse_report(make_report(blocks=[grid]))


@pytest.mark.parametrize(
    "grid",
    [
        pytest.param(make_grid([]), id="no-cells"),
        pytest.param(make_grid([make_cell(2, [])]), id="empty-cell-blocks"),
    ],
)
def test_grid_requires_cells_and_cell_blocks(grid: dict[str, Any]) -> None:
    with pytest.raises(ReportError, match=r"at least|too_short|length"):
        parse_report(make_report(blocks=[grid]))


def test_grid_nesting_is_capped_at_depth_two() -> None:
    # Depth 3 (grid → grid → grid) is unrepresentable: the innermost grid's cells accept only leaf
    # blocks, so a third nested grid there fails validation.
    depth3 = make_grid([make_cell(6, [make_grid([make_cell(6, [make_grid([make_cell(6)])])])])])

    with pytest.raises(ReportError, match=r"blocks\.0"):
        parse_report(make_report(blocks=[depth3]))


def test_grid_depth_two_is_allowed() -> None:
    grid = make_grid([make_cell(6, [make_grid([make_cell(6, [{"type": "text", "body": "deep"}])])])])

    assert parse_report(make_report(blocks=[grid])).blocks[0].type == "grid"


def test_inner_grid_span_sum_over_six_is_rejected() -> None:
    inner = make_grid([make_cell(4), make_cell(4)])
    grid = make_grid([make_cell(6, [inner])])

    with pytest.raises(ReportError, match=r"cell spans sum to 8; must total at most 6"):
        parse_report(make_report(blocks=[grid]))


def test_inner_grid_span_out_of_range_is_rejected() -> None:
    inner = make_grid([make_cell(7)])
    grid = make_grid([make_cell(6, [inner])])

    with pytest.raises(ReportError, match=r"span\b.*less than or equal to 6"):
        parse_report(make_report(blocks=[grid]))


def test_grid_may_not_contain_a_section() -> None:
    section = {"type": "section", "title": "s", "blocks": [{"type": "text", "body": "x"}]}
    grid = make_grid([make_cell(6, [section])])

    with pytest.raises(ReportError, match=r"blocks\.0"):
        parse_report(make_report(blocks=[grid]))


def test_section_may_not_contain_a_grid() -> None:
    section = {"type": "section", "title": "s", "blocks": [make_grid([make_cell(6)])]}

    with pytest.raises(ReportError, match=r"blocks\.0"):
        parse_report(make_report(blocks=[section]))
