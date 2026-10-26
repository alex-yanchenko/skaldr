import re

import pytest

from skaldr.errors import ReportError
from skaldr.models import Cards, Flow, Timeline, parse_report
from tests.factories import (
    make_cell,
    make_grid,
    make_reconciled_table,
    make_report,
    make_tab,
    make_table,
    make_tabs,
    make_toggle,
)
from tests.factories.models_factory import in_a_tab, make_matrix, make_rollup_table


def test_an_undeclared_badge_key_is_refused_with_the_path_of_the_cell_that_names_it() -> None:
    table = make_table(
        [{"key": "item", "label": "I"}, {"key": "s", "label": "S", "kind": "badge", "placement": "cell"}],
        groups=[{"name": "g", "rows": [{"item": "a", "s": "OK"}, {"item": "b", "s": ["OK", "NOPE"]}]}],
    )
    badges = {"OK": {"label": "Ok", "tone": "green", "legend": "fine"}}

    with pytest.raises(ReportError) as excinfo:
        parse_report(make_report(badges=badges, blocks=[in_a_tab(table)]))

    assert str(excinfo.value) == (
        "invalid content data: Value error, badge key(s) not declared in `badges`: ['NOPE'], at "
        "blocks.0.tabs.tabs.0.blocks.0.table.groups.0.rows.1.s.1 ('NOPE'); add them to the badges map"
    )


def test_undeclared_badge_reference_is_rejected() -> None:
    table = make_reconciled_table(
        columns=[
            {"key": "issue", "label": "Issue", "kind": "text"},
            {"key": "tag", "label": "", "kind": "badge"},
            {"key": "count", "label": "Count", "kind": "number"},
        ],
        groups=[{"name": "Our side", "rows": [{"issue": "Dupes", "tag": "MADE_UP", "count": 10}]}],
    )

    with pytest.raises(ReportError, match=r"badge key\(s\) not declared.*MADE_UP"):
        parse_report(make_report(blocks=[table]))


def test_padded_badge_key_on_a_card_is_still_rejected_as_undeclared() -> None:
    block = {"type": "cards", "items": [{"label": "Load", "value": 3, "badges": [" OPS "]}]}
    badges = {"OPS": {"label": "Ops", "tone": "blue", "legend": "Operations."}}

    with pytest.raises(
        ReportError,
        match=re.escape(
            "badge key(s) not declared in `badges`: [' OPS '], at blocks.0.cards.items.0.badges.0 (' OPS '); "
            "add them to the badges map"
        ),
    ):
        parse_report(make_report(badges=badges, blocks=[block]))


def test_badge_row_needs_exactly_one_of_items_or_groups() -> None:
    with pytest.raises(ReportError, match=r"a badge row needs exactly one of 'items' or 'groups'"):
        parse_report(make_report(blocks=[{"type": "badge_row"}]))


def test_badge_row_rejects_both_items_and_groups() -> None:
    block = {
        "type": "badge_row",
        "items": [{"label": "X", "tone": "amber"}],
        "groups": [{"label": "G", "items": [{"label": "Y", "tone": "blue"}]}],
    }
    with pytest.raises(ReportError, match=r"a badge row needs exactly one of 'items' or 'groups'"):
        parse_report(make_report(blocks=[block]))


def test_badge_row_label_may_not_accompany_groups() -> None:
    """`label` is a flat-row affordance; pairing it with `groups` is rejected, not silently dropped."""
    block = {
        "type": "badge_row",
        "label": "Affects:",
        "groups": [{"label": "G", "items": [{"label": "Y", "tone": "blue"}]}],
    }
    with pytest.raises(ReportError, match=r"badge row 'label' applies to a flat 'items' row, not 'groups'"):
        parse_report(make_report(blocks=[block]))


@pytest.mark.parametrize(
    ("group", "message"),
    [
        pytest.param(
            {"label": "Sev", "items": []},
            "items: List should have at least 1 item after validation, not 0",
            id="empty-items",
        ),
        pytest.param(
            {"label": "", "items": [{"label": "X", "tone": "blue"}]},
            "label: String should have at least 1 character",
            id="blank-label",
        ),
    ],
)
def test_badge_group_rejects_empty_items_and_blank_label(group: dict[str, object], message: str) -> None:
    with pytest.raises(ReportError) as raised:
        parse_report(make_report(blocks=[{"type": "badge_row", "groups": [group]}]))

    assert str(raised.value) == f"invalid content data: blocks.0.badge_row.groups.0.{message}"


def test_undeclared_badge_reference_inside_a_group_is_rejected() -> None:
    """A grouped ref must feed the same walker as a flat one, or an undeclared key would slip through."""
    block = {"type": "badge_row", "groups": [{"label": "Sev", "items": [{"key": "MADE_UP"}]}]}
    with pytest.raises(ReportError, match=r"badge key\(s\) not declared.*MADE_UP"):
        parse_report(make_report(blocks=[block]))


def test_undeclared_ref_among_multiple_group_items_is_caught() -> None:
    """The walker must reach every item in a multi-item group — the bad ref sits last, after a literal."""
    block = {
        "type": "badge_row",
        "groups": [
            {
                "label": "Mix",
                "items": [{"key": "OK"}, {"label": "X", "tone": "blue"}, {"key": "MADE_UP"}],
            }
        ],
    }
    with pytest.raises(ReportError, match=r"badge key\(s\) not declared.*MADE_UP"):
        parse_report(
            make_report(badges={"OK": {"label": "ok", "tone": "green", "legend": "l"}}, blocks=[block])
        )


def test_declared_badge_reference_passes() -> None:
    table = make_reconciled_table(
        columns=[
            {"key": "issue", "label": "Issue", "kind": "text"},
            {"key": "tag", "label": "", "kind": "badge"},
            {"key": "count", "label": "Count", "kind": "number"},
        ],
        groups=[{"name": "Our side", "rows": [{"issue": "Dupes", "tag": "OUR", "count": 10}]}],
    )

    report = parse_report(
        make_report(badges={"OUR": {"label": "Our", "tone": "amber", "legend": "ours"}}, blocks=[table])
    )

    assert report.badges["OUR"].tone == "amber"


def test_card_of_requires_numeric_value() -> None:
    block = {"type": "cards", "items": [{"label": "x", "value": "HEALTHY", "of": 100}]}

    with pytest.raises(ReportError, match=r"blocks\.0\.cards\.items\.0.*numeric"):
        parse_report(make_report(blocks=[block]))


def test_normal_card_still_requires_a_value() -> None:
    block = {"type": "cards", "items": [{"label": "x"}]}

    with pytest.raises(ReportError, match=r"a card needs a `value`"):
        parse_report(make_report(blocks=[block]))


def test_normal_card_still_requires_a_label() -> None:
    block = {"type": "cards", "items": [{"value": 5}]}

    with pytest.raises(ReportError, match=r"a card needs a `label`"):
        parse_report(make_report(blocks=[block]))


def _report_with_derived_card(card: dict[str, object], *, matrix_id: str = "cov") -> dict[str, object]:
    matrix = {
        "type": "matrix",
        "id": matrix_id,
        "rows": ["A"],
        "columns": ["X"],
        "cells": [{"row": "A", "col": "X", "badge": "HAVE"}],
    }
    return make_report(
        blocks=[{"type": "cards", "items": [card]}, matrix],
        badges={"HAVE": {"label": "Have", "tone": "green", "legend": "x"}},
    )


def test_derived_card_without_badge_is_rejected() -> None:
    with pytest.raises(ReportError) as raised:
        parse_report(_report_with_derived_card({"of_matrix": "cov"}))

    assert str(raised.value) == (
        "invalid content data: blocks.0.cards.items.0: Value error, "
        "a derived card (`of_matrix`/`of_tables`) needs a `badge` to count"
    )


def test_derived_card_with_an_authored_value_is_rejected() -> None:
    with pytest.raises(ReportError, match=r"computes its value; don't set `value`"):
        parse_report(_report_with_derived_card({"badge": "HAVE", "of_matrix": "cov", "value": 5}))


def test_derived_card_with_an_authored_of_is_rejected() -> None:
    with pytest.raises(ReportError, match=r"computes its percentage; don't set `of`"):
        parse_report(_report_with_derived_card({"badge": "HAVE", "of_matrix": "cov", "of": 10}))


def test_card_badge_without_of_matrix_is_rejected() -> None:
    block = {"type": "cards", "items": [{"label": "x", "value": 1, "badge": "HAVE"}]}
    report = make_report(blocks=[block], badges={"HAVE": {"label": "H", "tone": "green", "legend": "x"}})
    with pytest.raises(ReportError, match=r"`badge` on a card requires `of_matrix`"):
        parse_report(report)


def test_derived_card_referencing_an_unknown_matrix_is_rejected() -> None:
    with pytest.raises(ReportError, match=r"card of_matrix names 'ghost', which is not the id of any matrix"):
        parse_report(_report_with_derived_card({"badge": "HAVE", "of_matrix": "ghost"}))


def test_derived_card_with_an_undeclared_badge_is_rejected() -> None:
    # a derived card's `badge` feeds the report-wide declared-badge check (iter_referenced_badge_keys)
    matrix = {
        "type": "matrix",
        "id": "cov",
        "rows": ["A"],
        "columns": ["X"],
        "cells": [{"row": "A", "col": "X", "label": "x"}],
    }
    block = {"type": "cards", "items": [{"badge": "GHOST", "of_matrix": "cov"}]}
    with pytest.raises(ReportError, match=r"badge key\(s\) not declared in `badges`: \['GHOST'\]"):
        parse_report(make_report(blocks=[block, matrix]))


def test_derived_card_with_extra_badges_is_rejected() -> None:
    with pytest.raises(ReportError, match=r"shows its own badge chip; don't also set `badges`"):
        parse_report(_report_with_derived_card({"badge": "HAVE", "of_matrix": "cov", "badges": ["HAVE"]}))


def test_derived_card_with_a_delta_is_rejected() -> None:
    with pytest.raises(ReportError, match=r"a derived card has no `delta`; its value is a live count"):
        parse_report(
            _report_with_derived_card({"badge": "HAVE", "of_matrix": "cov", "delta": {"label": "+1"}})
        )


def test_duplicate_matrix_ids_are_rejected() -> None:
    matrix = make_matrix([{"row": "r1", "col": "c1", "label": "x"}], id="dup")
    with pytest.raises(ReportError, match=r"matrix id\(s\) used more than once: \['dup'\]"):
        parse_report(make_report(blocks=[matrix, {**matrix}]))


def _report_with_of_tables_card(
    card: dict[str, object], tables: list[dict[str, object]]
) -> dict[str, object]:
    return make_report(
        blocks=[{"type": "cards", "items": [card]}, *tables],
        badges={"HAVE": {"label": "Have", "tone": "green", "legend": "x"}},
    )


OF_TABLES_IN_A_TAB = "blocks.0.tabs.tabs.0.blocks.0.cards.items.0.of_tables"


@pytest.mark.parametrize(
    ("tables", "message"),
    [
        pytest.param(
            [make_rollup_table("tier1")],
            f"card of_tables names 'ghost', which is not the id of any table, at {OF_TABLES_IN_A_TAB}.1",
            id="unknown-table",
        ),
        pytest.param(
            [make_rollup_table("tier1"), make_rollup_table("ghost", rollup=False)],
            f"card of_tables names 'ghost', which is a table with no `rollup`, at {OF_TABLES_IN_A_TAB}.1; "
            "of_tables counts a badge with each table's rollup column, so the table must declare one",
            id="table-without-a-rollup",
        ),
    ],
)
def test_an_of_tables_reference_that_cannot_be_counted_is_refused_at_its_path(
    tables: list[dict[str, object]], message: str
) -> None:
    cards = {"type": "cards", "items": [{"badge": "HAVE", "of_tables": ["tier1", "ghost"]}]}
    report = make_report(
        blocks=[in_a_tab(cards), *tables],
        badges={"HAVE": {"label": "Have", "tone": "green", "legend": "x"}},
    )

    with pytest.raises(ReportError) as raised:
        parse_report(report)

    assert str(raised.value) == f"invalid content data: Value error, {message}"


def test_of_tables_and_of_matrix_together_are_rejected() -> None:
    matrix = make_matrix([{"row": "r1", "col": "c1", "badge": "HAVE"}], id="cov")
    report = make_report(
        blocks=[
            {"type": "cards", "items": [{"badge": "HAVE", "of_matrix": "cov", "of_tables": ["tier1"]}]},
            matrix,
            make_rollup_table("tier1"),
        ],
        badges={"HAVE": {"label": "Have", "tone": "green", "legend": "x"}},
    )
    with pytest.raises(
        ReportError, match=r"counts a matrix \(`of_matrix`\) OR tables \(`of_tables`\), not both"
    ):
        parse_report(report)


def test_of_tables_empty_list_is_rejected() -> None:
    report = _report_with_of_tables_card({"badge": "HAVE", "of_tables": []}, [make_rollup_table("tier1")])
    with pytest.raises(ReportError, match=r"`of_tables` must name at least one table"):
        parse_report(report)


def test_of_tables_with_a_duplicate_id_is_rejected() -> None:
    # a table listed twice would double-count in numerator and denominator — reject it outright
    report = _report_with_of_tables_card(
        {"badge": "HAVE", "of_tables": ["tier1", "tier1"]}, [make_rollup_table("tier1")]
    )
    with pytest.raises(ReportError, match=r"`of_tables` lists a table id more than once"):
        parse_report(report)


def test_of_tables_card_without_a_badge_is_rejected() -> None:
    report = _report_with_of_tables_card({"of_tables": ["tier1"]}, [make_rollup_table("tier1")])
    with pytest.raises(ReportError, match=r"needs a `badge` to count"):
        parse_report(report)


def test_duplicate_table_ids_are_rejected() -> None:
    report = make_report(
        blocks=[make_rollup_table("dup"), make_rollup_table("dup")],
        badges={"HAVE": {"label": "Have", "tone": "green", "legend": "x"}},
    )
    with pytest.raises(ReportError, match=r"table id\(s\) used more than once: \['dup'\]"):
        parse_report(report)


def test_a_badge_used_only_inside_a_toggle_must_be_declared() -> None:
    row = {"type": "badge_row", "items": [{"key": "OPS"}]}

    with pytest.raises(ReportError) as raised:
        parse_report(make_report(blocks=[{"type": "section", "title": "S", "blocks": [make_toggle(row)]}]))

    assert str(raised.value) == (
        "invalid content data: Value error, badge key(s) not declared in `badges`: ['OPS'], at "
        "blocks.0.section.blocks.0.toggle.blocks.0.badge_row.items.0.key ('OPS'); add them to the badges map"
    )


def test_a_badge_used_only_inside_a_tab_must_be_declared() -> None:
    row = {"type": "badge_row", "items": [{"key": "OPS"}]}

    with pytest.raises(ReportError) as raised:
        parse_report(make_report(blocks=[make_tabs(make_tab("Floor", row), make_tab("System"))]))

    assert str(raised.value) == (
        "invalid content data: Value error, badge key(s) not declared in `badges`: ['OPS'], at "
        "blocks.0.tabs.tabs.0.blocks.0.badge_row.items.0.key ('OPS'); add them to the badges map"
    )


def test_badge_legend_false_parses_as_a_legend_optout() -> None:
    report = parse_report(
        make_report(
            badges={"X": {"label": "x", "tone": "blue", "legend": False}},
            blocks=[{"type": "badge_row", "items": [{"key": "X"}]}],
        )
    )

    assert report.badges["X"].legend is False


def test_fan_spoke_badge_reference_must_be_declared() -> None:
    block = {
        "type": "fan",
        "hub": {"label": "H"},
        "spokes": [{"label": "A", "badges": ["GHOST"]}, {"label": "B"}],
    }

    with pytest.raises(ReportError, match=r"badge key\(s\) not declared.*GHOST"):
        parse_report(make_report(blocks=[block]))


def test_walkthrough_badge_referenced_in_a_step_detail_must_be_declared() -> None:
    card = {"type": "cards", "items": [{"label": "A", "value": 1, "badges": ["GHOST"]}]}
    step = {"label": "S", "detail": [card]}

    with pytest.raises(ReportError, match=r"badge key\(s\) not declared.*GHOST"):
        parse_report(make_report(blocks=[{"type": "walkthrough", "steps": [step]}]))


def test_container_badge_reference_must_be_declared() -> None:
    block = {"type": "cards", "items": [{"label": "A", "value": 1, "badges": ["GHOST"]}]}

    with pytest.raises(ReportError, match=r"badge key\(s\) not declared.*GHOST"):
        parse_report(make_report(blocks=[block]))


def test_container_badge_nested_in_a_section_is_still_validated() -> None:
    """Guards the recursion-composition path: the badge walker must reach container badges nested
    inside a section/grid, not just top-level ones."""
    inner = {"type": "cards", "items": [{"label": "A", "value": 1, "badges": ["GHOST"]}]}
    section = {"type": "section", "title": "s", "blocks": [inner]}

    with pytest.raises(ReportError, match=r"badge key\(s\) not declared.*GHOST"):
        parse_report(make_report(blocks=[section]))


def test_declared_container_badges_pass_on_card_timeline_and_flow() -> None:
    badges = {"OK": {"label": "OK", "tone": "green", "legend": "fine"}}
    blocks = [
        {"type": "cards", "items": [{"label": "A", "value": 1, "badges": ["OK"]}]},
        {"type": "timeline", "items": [{"title": "T", "badges": ["OK"]}]},
        {"type": "flow", "steps": [{"label": "A", "badges": ["OK"]}, {"label": "B"}]},
    ]

    report = parse_report(make_report(badges=badges, blocks=blocks))

    cards, timeline, flow = report.blocks
    assert isinstance(cards, Cards)
    assert isinstance(timeline, Timeline)
    assert isinstance(flow, Flow)
    assert cards.items[0].badges == ["OK"]
    assert timeline.items[0].badges == ["OK"]
    assert flow.steps[0].badges == ["OK"]


def test_card_of_must_be_positive() -> None:
    with pytest.raises(ReportError, match=r"greater than 0"):
        parse_report(make_report(blocks=[{"type": "cards", "items": [{"label": "x", "value": 5, "of": 0}]}]))


def test_badge_row_undeclared_key_rejected() -> None:
    with pytest.raises(ReportError, match=r"not declared.*MADE_UP"):
        parse_report(make_report(blocks=[{"type": "badge_row", "items": [{"key": "MADE_UP"}]}]))


def test_badge_row_declared_key_passes() -> None:
    report = parse_report(
        make_report(
            badges={"OK": {"label": "Ok", "tone": "green", "legend": "l"}},
            blocks=[{"type": "badge_row", "items": [{"key": "OK"}]}],
        )
    )

    assert report.blocks[0].type == "badge_row"


def test_card_value_rejects_boolean() -> None:
    with pytest.raises(ReportError, match=r"value\b.*must be a number, not a boolean"):
        parse_report(make_report(blocks=[{"type": "cards", "items": [{"label": "x", "value": True}]}]))


def test_card_value_rejects_non_finite() -> None:
    block = {"type": "cards", "items": [{"label": "x", "value": float("inf")}]}

    with pytest.raises(ReportError, match=r"value\b.*must be a finite number"):
        parse_report(make_report(blocks=[block]))


def test_card_of_rejects_boolean() -> None:
    block = {"type": "cards", "items": [{"label": "x", "value": 5, "of": True}]}

    with pytest.raises(ReportError, match=r"of\b.*must be a number, not a boolean"):
        parse_report(make_report(blocks=[block]))


def test_undeclared_badge_nested_in_section_is_rejected() -> None:
    table = make_reconciled_table(
        columns=[
            {"key": "issue", "label": "I", "kind": "text"},
            {"key": "tag", "label": "", "kind": "badge"},
            {"key": "count", "label": "C", "kind": "number"},
        ],
        groups=[{"name": "g", "rows": [{"issue": "x", "tag": "NOPE", "count": 10}]}],
    )
    section = {"type": "section", "title": "Appendix", "blocks": [table]}

    with pytest.raises(ReportError, match=r"not declared.*NOPE"):
        parse_report(make_report(blocks=[section]))


def test_cell_badge_undeclared_key_in_a_list_still_fails() -> None:
    table = make_table(
        [
            {"key": "a", "label": "A", "kind": "text"},
            {"key": "acc", "label": "Access", "kind": "badge", "placement": "cell"},
        ],
        rows=[{"a": "one", "acc": ["W", "GHOST"]}],
    )
    with pytest.raises(ReportError, match=r"badge key\(s\) not declared"):
        parse_report(
            make_report(badges={"W": {"label": "Write", "tone": "green", "legend": "rw"}}, blocks=[table])
        )


def _badge_table(tag: str) -> dict[str, object]:
    return make_reconciled_table(
        columns=[
            {"key": "issue", "label": "I", "kind": "text"},
            {"key": "tag", "label": "", "kind": "badge"},
            {"key": "count", "label": "C", "kind": "number"},
        ],
        groups=[{"name": "g", "rows": [{"issue": "x", "tag": tag, "count": 10}]}],
    )


def test_undeclared_badge_in_grid_table_is_rejected() -> None:
    grid = make_grid([make_cell(6, [_badge_table("NOPE")])])

    with pytest.raises(ReportError, match=r"not declared.*NOPE"):
        parse_report(make_report(blocks=[grid]))


def test_undeclared_badge_in_nested_grid_table_is_rejected() -> None:
    inner = make_grid([make_cell(6, [_badge_table("DEEP_NOPE")])])
    grid = make_grid([make_cell(6, [inner])])

    with pytest.raises(ReportError, match=r"not declared.*DEEP_NOPE"):
        parse_report(make_report(blocks=[grid]))
