from pathlib import Path
from typing import Any

import pytest

from skaldr.export.adf import AdfUnsupportedError, render_adf
from skaldr.export.inline import plain
from skaldr.export.lower import lower_report
from skaldr.export.tree import Callout, Node, Paragraph, Tab, TableCell, TableNode, Tabs, Toggle
from skaldr.models import load_report
from tests.factories import (
    lowered,
    make_cell,
    make_grid,
    make_report,
    make_request,
    make_section,
    make_tab,
    make_tabs,
    make_toggle,
    write_index_document,
)

LINK_URL = "https://example.com/runbook"
COMPARISON = {
    "type": "comparison",
    "options": ["A", "B"],
    "rows": [{"feature": "Speed", "values": [True, False]}],
}
MATRIX = {
    "type": "matrix",
    "rows": ["r1"],
    "columns": ["c1"],
    "cells": [{"row": "r1", "col": "c1", "label": "yes"}],
}
SWIMLANE = {
    "type": "swimlane",
    "lanes": ["Ops"],
    "columns": ["Plan"],
    "steps": [{"lane": "Ops", "col": "Plan", "n": "1", "label": "Draft"}],
}
DONUT = {"type": "chart", "variant": "donut", "slices": [{"label": "A", "value": 3}]}
STACKED_BARS = {
    "type": "chart",
    "variant": "bar",
    "stacked": True,
    "categories": ["Q1"],
    "series": [{"label": "x", "values": [1]}, {"label": "y", "values": [2]}],
}
TABLE = {
    "type": "table",
    "columns": [{"key": "name", "label": "Name"}],
    "rows": [{"name": "a"}],
}


def _refusal(blocks: list[dict[str, Any]]) -> str:
    with pytest.raises(AdfUnsupportedError) as refused:
        render_adf(lowered(blocks))
    return str(refused.value)


def _in_a_panel(block: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"type": "panel", "title": "Plan", "blocks": [block]}]


@pytest.mark.parametrize(
    ("block", "named"),
    [
        pytest.param({"type": "link", "url": LINK_URL, "display": "card"}, "a link card", id="link-card"),
        pytest.param({"type": "link", "url": LINK_URL, "display": "embed"}, "a link embed", id="link-embed"),
        pytest.param({"type": "callout", "tone": "info", "body": "x"}, "a callout", id="callout"),
        pytest.param({"type": "note", "body": "x"}, "a note", id="note"),
        pytest.param(TABLE, "a table", id="table"),
        pytest.param(COMPARISON, "a comparison", id="comparison"),
        pytest.param(MATRIX, "a matrix", id="matrix"),
        pytest.param(SWIMLANE, "a swimlane", id="swimlane"),
        pytest.param(DONUT, "a chart", id="donut"),
        pytest.param(STACKED_BARS, "a chart", id="stacked-bars"),
        pytest.param(make_toggle(), "a toggle", id="toggle"),
        pytest.param(make_tabs(), "a set of tabs", id="tabs"),
        pytest.param(
            make_request(
                cases=[{"label": "a", "response": {"body": "1"}}, {"label": "b", "response": {"body": "2"}}]
            ),
            "a request",
            id="request-with-two-cases",
        ),
        pytest.param(
            make_request(cases=[{"label": "a", "verdict": "fine", "response": {"body": "1"}}]),
            "a request verdict",
            id="request-verdict",
        ),
    ],
)
def test_a_panel_refusing_a_block_names_the_block_the_author_wrote_and_its_path(
    block: dict[str, Any], named: str
) -> None:
    assert _refusal(_in_a_panel(block)) == (
        f"ADF cannot place {named} inside a panel, at blocks.0.panel.blocks.0.{block['type']}"
    )


def test_a_request_flow_step_with_two_cases_is_named_a_request_step() -> None:
    step = {
        "label": "Read",
        "method": "GET",
        "url": "https://api.example.com/widgets",
        "cases": [{"label": "a", "response": {"body": "1"}}, {"label": "b", "response": {"body": "2"}}],
    }
    flow = {"type": "request_flow", "label": "Walk", "steps": [step, step]}

    assert _refusal(_in_a_panel(flow)) == (
        "ADF cannot place a request step inside a panel, at blocks.0.panel.blocks.0.request_flow"
    )


def test_a_toned_grid_cell_holding_another_toned_cell_names_both_a_grid_cell() -> None:
    inner = make_grid([make_cell(6, [{"type": "text", "body": "x"}]) | {"tone": "info"}])
    outer = make_grid([make_cell(6, [inner]) | {"tone": "warning"}])

    assert _refusal([outer]) == (
        "ADF cannot place a grid cell inside a grid cell, at blocks.0.grid.cells.0.blocks.0.grid"
    )


def test_a_toggle_inside_a_toggle_inside_a_collapsed_section_names_the_section() -> None:
    section = make_section("plan", collapsed=True, blocks=[make_toggle(make_toggle())])

    assert _refusal([section]) == (
        "ADF cannot place a toggle inside a toggle that is itself inside a section, "
        "at blocks.0.section.blocks.0.toggle.blocks.0.toggle, under the heading 'plan'"
    )


def test_a_toggle_inside_a_toggle_inside_a_collapsed_part_names_the_part(tmp_path: Path) -> None:
    index = write_index_document(
        tmp_path,
        {"one.yaml": make_report(blocks=[make_toggle(make_toggle())])},
        index={"parts": ["one.yaml"], "collapsed": True},
    )

    with pytest.raises(AdfUnsupportedError) as refused:
        render_adf(lower_report(load_report(index)).body)

    assert str(refused.value) == (
        "ADF cannot place a toggle inside a toggle that is itself inside a part, "
        "at blocks.0.part.blocks.0.toggle.blocks.0.toggle, under the heading 'Test Report'"
    )


def test_a_lowered_node_with_no_authored_path_is_named_without_one() -> None:
    innermost = Toggle(plain("v"), None, ())
    nodes: tuple[Node, ...] = (Toggle(plain("t"), None, (Toggle(plain("u"), None, (innermost,)),)),)

    with pytest.raises(AdfUnsupportedError) as refused:
        render_adf(nodes)

    assert str(refused.value) == "ADF cannot place a toggle inside a toggle that is itself inside a toggle"


def test_a_container_with_no_authored_name_is_a_callout() -> None:
    nodes: tuple[Node, ...] = (Callout("info", (Callout("info", (Paragraph(plain("x")),)),)),)

    with pytest.raises(AdfUnsupportedError) as refused:
        render_adf(nodes)

    assert str(refused.value) == "ADF cannot place a callout inside a callout"


def test_a_container_authored_as_a_note_is_named_a_note() -> None:
    nodes: tuple[Node, ...] = (
        Callout("neutral", (Callout("info", (Paragraph(plain("x")),)),), authored_as="note"),
    )

    with pytest.raises(AdfUnsupportedError) as refused:
        render_adf(nodes)

    assert str(refused.value) == "ADF cannot place a callout inside a note"


def test_a_table_kind_block_inside_a_toggle_inside_a_toggle_inside_a_toggle_keeps_its_own_name() -> None:
    blocks = [make_toggle(make_toggle(make_toggle(COMPARISON)))]

    assert _refusal(blocks) == (
        "ADF cannot place a comparison inside a toggle that is itself inside a toggle, "
        "at blocks.0.toggle.blocks.0.toggle.blocks.0.toggle.blocks.0.comparison"
    )


def test_a_request_with_two_cases_inside_nested_toggles_is_named_a_request() -> None:
    request = make_request(
        cases=[{"label": "a", "response": {"body": "1"}}, {"label": "b", "response": {"body": "2"}}]
    )
    blocks = [make_toggle(make_toggle(make_toggle(request)))]

    assert _refusal(blocks) == (
        "ADF cannot place a request inside a toggle that is itself inside a toggle, "
        "at blocks.0.toggle.blocks.0.toggle.blocks.0.toggle.blocks.0.request"
    )


def test_a_tab_inside_a_toggle_names_the_set_of_tabs_as_the_container() -> None:
    blocks = [make_toggle(make_tabs(make_tab("a", COMPARISON), make_tab("b")))]

    assert _refusal(blocks) == (
        "ADF cannot place a comparison inside a set of tabs that is itself inside a toggle, "
        "at blocks.0.toggle.blocks.0.tabs.tabs.0.blocks.0.comparison"
    )


def test_a_toggle_inside_tabs_names_the_toggle_as_the_container_and_the_tabs_as_its_parent() -> None:
    blocks = [make_tabs(make_tab("a", make_toggle(COMPARISON)), make_tab("b"))]

    assert _refusal(blocks) == (
        "ADF cannot place a comparison inside a toggle that is itself inside a set of tabs, "
        "at blocks.0.tabs.tabs.0.blocks.0.toggle.blocks.0.comparison"
    )


def test_a_tab_group_authored_as_a_request_names_the_request_as_the_container() -> None:
    cases = Tabs((Tab(plain("a"), (TableNode((TableCell(plain("h")),), ()),)),), authored_as="request")
    nodes: tuple[Node, ...] = (Toggle(plain("t"), None, (cases,)),)

    with pytest.raises(AdfUnsupportedError) as refused:
        render_adf(nodes)

    assert str(refused.value) == "ADF cannot place a table inside a request that is itself inside a toggle"


def test_a_block_named_in_the_error_keeps_the_heading_above_it() -> None:
    blocks = [{"type": "heading", "text": "Plan"}, *_in_a_panel(COMPARISON)]

    assert _refusal(blocks) == (
        "ADF cannot place a comparison inside a panel, at blocks.1.panel.blocks.0.comparison, "
        "under the heading 'Plan'"
    )
