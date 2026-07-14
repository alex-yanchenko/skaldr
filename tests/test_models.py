from pathlib import Path
from typing import Any

import pytest

from skaldr.errors import ReportError
from skaldr.models import (
    Cards,
    Fan,
    Flow,
    FlowStep,
    Grid,
    Meta,
    Report,
    Table,
    Text,
    Timeline,
    Walkthrough,
    WalkthroughStep,
    load_report,
    parse_report,
    read_text_file,
)
from tests.factories import make_cell, make_grid, make_reconciled_table, make_report, make_table


def test_valid_minimal_report_parses_to_whole_model() -> None:
    report = parse_report(make_report())

    assert report == Report(
        version=1,
        meta=Meta(title="Test Report"),
        blocks=[Text(type="text", body="Hello.")],
    )


def test_unknown_version_is_rejected() -> None:
    with pytest.raises(ReportError, match=r"version"):
        parse_report(make_report(version=2))


def test_unknown_block_type_is_rejected_with_path() -> None:
    with pytest.raises(ReportError, match=r"blocks\.0"):
        parse_report(make_report(blocks=[{"type": "bogus", "body": "x"}]))


def test_unknown_field_is_rejected_with_path() -> None:
    with pytest.raises(ReportError, match=r"blocks\.0\.text\.oops.*not permitted"):
        parse_report(make_report(blocks=[{"type": "text", "body": "hi", "oops": 1}]))


def test_reconciliation_failure_names_the_delta() -> None:
    table = make_reconciled_table(
        reconcile={"total": 100, "column": "count", "handled": {"label": "Clean", "value": 80}},
    )

    with pytest.raises(ReportError) as excinfo:
        parse_report(make_report(blocks=[table]))

    assert str(excinfo.value) == (
        "RECONCILIATION FAILED: handled (80) + count (10) = 90, but declared total is 100 "
        "(off by -10). A category is wrong, double-counted, or missing."
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


def test_meter_value_out_of_bounds_is_rejected() -> None:
    block = {"type": "meter", "items": [{"label": "x", "value": 120, "max": 100}]}

    with pytest.raises(ReportError, match=r"blocks\.0\.meter\.items\.0.*between 0 and"):
        parse_report(make_report(blocks=[block]))


def test_image_src_must_be_data_uri() -> None:
    block = {"type": "image", "src": "https://example.com/x.png", "alt": "x"}

    with pytest.raises(ReportError, match=r"blocks\.0.*data: URI"):
        parse_report(make_report(blocks=[block]))


def test_section_may_not_contain_a_section() -> None:
    inner = {"type": "section", "title": "inner", "blocks": [{"type": "text", "body": "x"}]}
    outer = {"type": "section", "title": "outer", "blocks": [inner]}

    with pytest.raises(ReportError, match=r"blocks\.0\.section\.blocks\.0"):
        parse_report(make_report(blocks=[outer]))


def test_flow_arrow_parses_to_whole_model_with_defaults() -> None:
    block = {"type": "flow", "steps": [{"label": "Source"}, {"label": "Deliver", "tone": "success"}]}

    report = parse_report(make_report(blocks=[block]))

    assert report.blocks[0] == Flow(
        type="flow",
        style="arrow",
        loop=False,
        numbered=True,
        steps=[FlowStep(label="Source"), FlowStep(label="Deliver", tone="success")],
    )


def test_flow_requires_at_least_two_steps() -> None:
    block = {"type": "flow", "steps": [{"label": "solo"}]}

    with pytest.raises(ReportError, match=r"blocks\.0\.flow\.steps.*at least 2"):
        parse_report(make_report(blocks=[block]))


def test_flow_step_label_must_not_be_blank() -> None:
    block = {"type": "flow", "steps": [{"label": "  "}, {"label": "B"}]}

    with pytest.raises(ReportError, match=r"flow step label must not be blank"):
        parse_report(make_report(blocks=[block]))


def test_flow_unknown_style_is_rejected() -> None:
    block = {"type": "flow", "style": "zigzag", "steps": [{"label": "A"}, {"label": "B"}]}

    with pytest.raises(ReportError, match=r"blocks\.0\.flow\.style"):
        parse_report(make_report(blocks=[block]))


def test_flow_unknown_field_is_rejected_with_path() -> None:
    block = {"type": "flow", "steps": [{"label": "A"}, {"label": "B"}], "oops": 1}

    with pytest.raises(ReportError, match=r"blocks\.0\.flow\.oops.*not permitted"):
        parse_report(make_report(blocks=[block]))


def test_fan_parses_to_whole_model_with_default_direction_in() -> None:
    block = {"type": "fan", "hub": {"label": "H"}, "spokes": [{"label": "A"}, {"label": "B"}]}

    report = parse_report(make_report(blocks=[block]))

    assert report.blocks[0] == Fan(
        type="fan",
        hub=FlowStep(label="H"),
        spokes=[FlowStep(label="A"), FlowStep(label="B")],
        direction="in",
    )


def test_fan_requires_at_least_two_spokes() -> None:
    block = {"type": "fan", "hub": {"label": "H"}, "spokes": [{"label": "solo"}]}

    with pytest.raises(ReportError, match=r"blocks\.0\.fan\.spokes.*at least 2"):
        parse_report(make_report(blocks=[block]))


def test_fan_requires_a_hub() -> None:
    block = {"type": "fan", "spokes": [{"label": "A"}, {"label": "B"}]}

    with pytest.raises(ReportError, match=r"blocks\.0\.fan\.hub"):
        parse_report(make_report(blocks=[block]))


def test_fan_unknown_direction_is_rejected() -> None:
    block = {
        "type": "fan",
        "direction": "sideways",
        "hub": {"label": "H"},
        "spokes": [{"label": "A"}, {"label": "B"}],
    }

    with pytest.raises(ReportError, match=r"blocks\.0\.fan\.direction"):
        parse_report(make_report(blocks=[block]))


def test_fan_spoke_badge_reference_must_be_declared() -> None:
    block = {
        "type": "fan",
        "hub": {"label": "H"},
        "spokes": [{"label": "A", "badges": ["GHOST"]}, {"label": "B"}],
    }

    with pytest.raises(ReportError, match=r"badge key\(s\) not declared.*GHOST"):
        parse_report(make_report(blocks=[block]))


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

    with pytest.raises(ReportError, match=r"walkthrough step label must not be blank"):
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


def test_row_tone_is_a_reserved_key_not_an_unknown_column() -> None:
    table = make_table(
        columns=[{"key": "a", "label": "A", "kind": "text"}], rows=[{"a": "x", "tone": "muted"}]
    )

    block = parse_report(make_report(blocks=[table])).blocks[0]

    assert isinstance(block, Table)
    assert block.rows == [{"a": "x", "tone": "muted"}]  # tone kept, not tripping the unknown-key guard


def test_row_tone_rejects_an_unknown_value() -> None:
    table = make_table(
        columns=[{"key": "a", "label": "A", "kind": "text"}], rows=[{"a": "x", "tone": "bogus"}]
    )

    with pytest.raises(ReportError, match=r"tone: row tone must be 'muted' or 'danger'"):
        parse_report(make_report(blocks=[table]))


def test_grid_cell_tone_parses_and_rejects_an_unknown_value() -> None:
    ok = make_grid([{"span": 6, "tone": "accent", "blocks": [{"type": "text", "body": "x"}]}])
    block = parse_report(make_report(blocks=[ok])).blocks[0]
    assert isinstance(block, Grid)
    assert block.cells[0].tone == "accent"

    bad = make_grid([{"span": 6, "tone": "bogus", "blocks": [{"type": "text", "body": "x"}]}])
    with pytest.raises(ReportError, match=r"blocks\.0\.grid\.cells\.0\.tone"):
        parse_report(make_report(blocks=[bad]))


def test_table_column_key_may_not_collide_with_a_reserved_row_key() -> None:
    table = make_table(columns=[{"key": "tone", "label": "Tone", "kind": "text"}], rows=[{"tone": "warm"}])

    with pytest.raises(ReportError, match=r"reserved row keys"):
        parse_report(make_report(blocks=[table]))


def _indicator_table(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return make_table(
        columns=[
            {"key": "a", "label": "A", "kind": "text"},
            {"key": "r", "label": "Risk", "kind": "indicator"},
        ],
        rows=rows,
    )


def test_indicator_column_rejects_a_non_tone_value() -> None:
    with pytest.raises(ReportError, match=r"indicator value must be a tone"):
        parse_report(make_report(blocks=[_indicator_table([{"a": "x", "r": "purple"}])]))


def test_indicator_column_accepts_a_tone_or_blank() -> None:
    block = parse_report(
        make_report(blocks=[_indicator_table([{"a": "x", "r": "danger"}, {"a": "y", "r": ""}])])
    ).blocks[0]

    assert isinstance(block, Table)
    assert block.rows == [{"a": "x", "r": "danger"}, {"a": "y", "r": ""}]


def test_table_row_missing_a_column_is_rejected() -> None:
    table = make_reconciled_table(groups=[{"name": "g", "rows": [{"issue": "only"}]}])

    with pytest.raises(ReportError, match=r"missing column value"):
        parse_report(make_report(blocks=[table]))


def test_table_row_with_unknown_key_is_rejected() -> None:
    table = make_reconciled_table(
        groups=[{"name": "g", "rows": [{"issue": "x", "count": 10, "extra": 1}]}],
        reconcile={"total": 10, "column": "count"},
    )

    with pytest.raises(ReportError, match=r"unknown key"):
        parse_report(make_report(blocks=[table]))


def test_reconcile_total_must_be_positive() -> None:
    table = make_reconciled_table(
        reconcile={"total": 0, "column": "count", "handled": {"label": "c", "value": 0}},
        groups=[{"name": "g", "rows": [{"issue": "x", "count": 0}]}],
    )

    with pytest.raises(ReportError, match=r"greater than 0"):
        parse_report(make_report(blocks=[table]))


def test_number_column_rejects_non_numeric_value() -> None:
    table = make_reconciled_table(groups=[{"name": "g", "rows": [{"issue": "x", "count": "ten"}]}])

    with pytest.raises(ReportError, match=r"count: number column needs a numeric value"):
        parse_report(make_report(blocks=[table]))


def test_badge_column_rejects_non_string_value() -> None:
    table = make_reconciled_table(
        columns=[
            {"key": "issue", "label": "I", "kind": "text"},
            {"key": "tag", "label": "", "kind": "badge"},
            {"key": "count", "label": "C", "kind": "number"},
        ],
        groups=[{"name": "g", "rows": [{"issue": "x", "tag": 123, "count": 10}]}],
    )

    with pytest.raises(ReportError, match=r"tag: badge column needs a string value"):
        parse_report(make_report(blocks=[table]))


def test_all_badge_table_is_rejected() -> None:
    table = {
        "type": "table",
        "columns": [{"key": "tag", "label": "", "kind": "badge"}],
        "groups": [{"name": "g", "rows": [{"tag": "X"}]}],
    }

    with pytest.raises(ReportError, match=r"at least one text or rich column"):
        parse_report(
            make_report(badges={"X": {"label": "x", "tone": "amber", "legend": "l"}}, blocks=[table])
        )


def test_card_of_must_be_positive() -> None:
    with pytest.raises(ReportError, match=r"greater than 0"):
        parse_report(make_report(blocks=[{"type": "cards", "items": [{"label": "x", "value": 5, "of": 0}]}]))


def test_meter_max_must_be_positive() -> None:
    with pytest.raises(ReportError, match=r"greater than 0"):
        parse_report(make_report(blocks=[{"type": "meter", "items": [{"label": "x", "value": 0, "max": 0}]}]))


def test_duplicate_column_keys_rejected() -> None:
    table = make_reconciled_table(
        columns=[
            {"key": "issue", "label": "I", "kind": "text"},
            {"key": "count", "label": "A", "kind": "number"},
            {"key": "count", "label": "B", "kind": "number"},
        ],
        reconcile={"total": 10, "column": "count"},
        groups=[{"name": "g", "rows": [{"issue": "x", "count": 10}]}],
    )

    with pytest.raises(ReportError, match=r"column keys must be unique"):
        parse_report(make_report(blocks=[table]))


def test_reconcile_column_must_be_a_number_column() -> None:
    table = make_reconciled_table(
        reconcile={"total": 10, "column": "issue", "handled": {"label": "c", "value": 0}},
    )

    with pytest.raises(ReportError, match=r"reconcile.column 'issue' must be a number column"):
        parse_report(make_report(blocks=[table]))


def test_ungrouped_rows_mode_parses() -> None:
    table = {
        "type": "table",
        "columns": [{"key": "issue", "label": "I", "kind": "text"}],
        "rows": [{"issue": "x"}],
    }

    report = parse_report(make_report(blocks=[table]))

    assert report.blocks[0].type == "table"


def test_both_groups_and_rows_rejected() -> None:
    table = {
        "type": "table",
        "columns": [{"key": "issue", "label": "I", "kind": "text"}],
        "groups": [{"name": "g", "rows": [{"issue": "x"}]}],
        "rows": [{"issue": "x"}],
    }

    with pytest.raises(ReportError, match=r"exactly one of 'groups' or 'rows'"):
        parse_report(make_report(blocks=[table]))


def test_neither_groups_nor_rows_rejected() -> None:
    table = {"type": "table", "columns": [{"key": "issue", "label": "I", "kind": "text"}]}

    with pytest.raises(ReportError, match=r"exactly one of 'groups' or 'rows'"):
        parse_report(make_report(blocks=[table]))


def test_subrows_must_be_a_list() -> None:
    table = make_reconciled_table(
        reconcile={"total": 10, "column": "count"},
        groups=[{"name": "g", "rows": [{"issue": "x", "count": 10, "subrows": "nope"}]}],
    )

    with pytest.raises(ReportError, match=r"subrows: must be a list"):
        parse_report(make_report(blocks=[table]))


def test_subrow_shape_is_enforced() -> None:
    table = make_reconciled_table(
        reconcile={"total": 10, "column": "count"},
        groups=[{"name": "g", "rows": [{"issue": "x", "count": 10, "subrows": [{"label": "a"}]}]}],
    )

    with pytest.raises(ReportError, match=r"must be \{label, value\}"):
        parse_report(make_report(blocks=[table]))


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


def test_blank_heading_is_rejected() -> None:
    with pytest.raises(ReportError, match=r"must not be blank"):
        parse_report(make_report(blocks=[{"type": "heading", "text": "   "}]))


def test_reconcile_without_handled_bucket_passes() -> None:
    table = make_reconciled_table(
        reconcile={"total": 10, "column": "count"},
        groups=[{"name": "g", "rows": [{"issue": "x", "count": 10}]}],
    )

    report = parse_report(make_report(blocks=[table]))

    assert report.blocks[0].type == "table"


def test_number_column_rejects_non_finite_value() -> None:
    table = make_reconciled_table(groups=[{"name": "g", "rows": [{"issue": "x", "count": float("inf")}]}])

    with pytest.raises(ReportError, match=r"count: number column must be finite"):
        parse_report(make_report(blocks=[table]))


def test_number_column_rejects_boolean_value() -> None:
    table = make_reconciled_table(groups=[{"name": "g", "rows": [{"issue": "x", "count": True}]}])

    with pytest.raises(ReportError, match=r"count: number column needs a numeric value"):
        parse_report(make_report(blocks=[table]))


def test_float_reconcile_tolerates_ieee754_noise() -> None:
    # 33.1 + 33.2 + 33.7 == 100.00000000000001 — exact `==` would wrongly fail this.
    table = make_reconciled_table(
        reconcile={"total": 100, "column": "count"},
        groups=[
            {
                "name": "g",
                "rows": [
                    {"issue": "a", "count": 33.1},
                    {"issue": "b", "count": 33.2},
                    {"issue": "c", "count": 33.7},
                ],
            }
        ],
    )

    report = parse_report(make_report(blocks=[table]))

    assert report.blocks[0].type == "table"


def test_float_reconcile_still_fails_a_real_discrepancy() -> None:
    table = make_reconciled_table(
        reconcile={"total": 100, "column": "count"},
        groups=[{"name": "g", "rows": [{"issue": "a", "count": 33.1}, {"issue": "b", "count": 33.2}]}],
    )

    with pytest.raises(ReportError, match=r"RECONCILIATION FAILED"):
        parse_report(make_report(blocks=[table]))


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


def test_meter_rejects_non_finite_value() -> None:
    block = {"type": "meter", "items": [{"label": "x", "value": float("inf"), "max": 100}]}

    with pytest.raises(ReportError, match=r"value\b.*must be a finite number"):
        parse_report(make_report(blocks=[block]))


def test_meter_rejects_non_finite_max() -> None:
    block = {"type": "meter", "items": [{"label": "x", "value": 1, "max": float("inf")}]}

    with pytest.raises(ReportError, match=r"max\b.*must be a finite number"):
        parse_report(make_report(blocks=[block]))


def test_meter_rejects_boolean_value() -> None:
    block = {"type": "meter", "items": [{"label": "x", "value": True, "max": 100}]}

    with pytest.raises(ReportError, match=r"value\b.*must be a number, not a boolean"):
        parse_report(make_report(blocks=[block]))


def test_subrow_value_rejects_non_finite() -> None:
    row = {"issue": "x", "count": 10, "subrows": [{"label": "a", "value": float("nan")}]}
    table = make_reconciled_table(
        reconcile={"total": 10, "column": "count"}, groups=[{"name": "g", "rows": [row]}]
    )

    with pytest.raises(ReportError, match=r"subrows\.0\.value: number must be finite"):
        parse_report(make_report(blocks=[table]))


def test_table_requires_a_text_or_rich_column() -> None:
    table = {
        "type": "table",
        "columns": [
            {"key": "count", "label": "C", "kind": "number"},
            {"key": "tag", "label": "", "kind": "badge"},
        ],
        "rows": [{"count": 10, "tag": "X"}],
    }

    with pytest.raises(ReportError, match=r"at least one text or rich column"):
        parse_report(
            make_report(badges={"X": {"label": "x", "tone": "amber", "legend": "l"}}, blocks=[table])
        )


def test_pct_of_total_without_reconcile_is_rejected() -> None:
    table = {
        "type": "table",
        "columns": [
            {"key": "issue", "label": "I", "kind": "text"},
            {"key": "count", "label": "C", "kind": "number", "pct_of_total": True},
        ],
        "rows": [{"issue": "x", "count": 10}],
    }

    with pytest.raises(ReportError, match=r"pct_of_total requires a reconcile total"):
        parse_report(make_report(blocks=[table]))


def test_totals_column_must_be_a_number_column() -> None:
    table = {
        "type": "table",
        "columns": [{"key": "issue", "label": "I", "kind": "text"}],
        "rows": [{"issue": "x"}],
        "totals": {"column": "issue"},
    }

    with pytest.raises(ReportError, match=r"totals.column 'issue' must be a number column"):
        parse_report(make_report(blocks=[table]))


def test_meter_negative_value_is_rejected() -> None:
    block = {"type": "meter", "items": [{"label": "x", "value": -5, "max": 100}]}

    with pytest.raises(ReportError, match=r"between 0 and"):
        parse_report(make_report(blocks=[block]))


def test_empty_badge_cell_is_allowed() -> None:
    table = make_reconciled_table(
        columns=[
            {"key": "issue", "label": "I", "kind": "text"},
            {"key": "tag", "label": "", "kind": "badge"},
            {"key": "count", "label": "C", "kind": "number"},
        ],
        groups=[{"name": "g", "rows": [{"issue": "x", "tag": "", "count": 10}]}],
    )

    report = parse_report(make_report(blocks=[table]))

    assert report.blocks[0].type == "table"


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


def test_malformed_yaml_is_a_report_error(tmp_path: Path) -> None:
    data_path = tmp_path / "broken.yaml"
    data_path.write_text("blocks: [unclosed\nversion: 1", encoding="utf-8")

    with pytest.raises(ReportError, match=r"invalid YAML in .*broken\.yaml"):
        load_report(data_path)


def test_missing_file_is_a_report_error(tmp_path: Path) -> None:
    with pytest.raises(ReportError, match=r"file not found: .*nope\.yaml"):
        load_report(tmp_path / "nope.yaml")


def test_unreadable_file_is_a_report_error(tmp_path: Path) -> None:
    with pytest.raises(ReportError, match=r"could not read .*"):
        read_text_file(tmp_path)


def test_non_mapping_payload_is_a_report_error() -> None:
    with pytest.raises(ReportError, match=r"Input should be a valid dictionary"):
        parse_report(["not", "a", "mapping"])


def test_subrow_label_must_be_a_string() -> None:
    table = make_reconciled_table(
        reconcile={"total": 10, "column": "count"},
        groups=[{"name": "g", "rows": [{"issue": "x", "count": 10, "subrows": [{"label": 1, "value": 2}]}]}],
    )

    with pytest.raises(ReportError, match=r"subrows\.0\.label: must be a string"):
        parse_report(make_report(blocks=[table]))


def test_subrow_value_must_be_number_or_string() -> None:
    row = {"issue": "x", "count": 10, "subrows": [{"label": "a", "value": [1]}]}
    table = make_reconciled_table(
        reconcile={"total": 10, "column": "count"}, groups=[{"name": "g", "rows": [row]}]
    )

    with pytest.raises(ReportError, match=r"subrows\.0\.value: must be a number or string"):
        parse_report(make_report(blocks=[table]))


def test_subrow_value_rejects_boolean() -> None:
    row = {"issue": "x", "count": 10, "subrows": [{"label": "a", "value": True}]}
    table = make_reconciled_table(
        reconcile={"total": 10, "column": "count"}, groups=[{"name": "g", "rows": [row]}]
    )

    with pytest.raises(ReportError, match=r"subrows\.0\.value: must be a number or string"):
        parse_report(make_report(blocks=[table]))


def test_fact_strip_rejects_more_than_eight_facts() -> None:
    facts = [{"label": f"l{i}", "value": f"v{i}"} for i in range(9)]

    with pytest.raises(ReportError, match=r"facts"):
        parse_report(make_report(blocks=[{"type": "fact_strip", "facts": facts}]))


def test_table_column_widths_are_read_onto_every_column() -> None:
    table = make_table(
        [
            {"key": "a", "label": "A", "kind": "text", "width": 2},
            {"key": "b", "label": "B", "kind": "number", "width": 4},
        ],
        rows=[{"a": "x", "b": 10}],
    )

    block = parse_report(make_report(blocks=[table])).blocks[0]

    assert isinstance(block, Table)
    assert [column.width for column in block.columns] == [2, 4]


def test_table_mixed_widths_are_rejected() -> None:
    table = make_table(
        [
            {"key": "a", "label": "A", "kind": "text", "width": 2},
            {"key": "b", "label": "B", "kind": "number"},
        ],
        rows=[{"a": "x", "b": 10}],
    )

    with pytest.raises(ReportError, match=r"set width on every non-badge column, or none"):
        parse_report(make_report(blocks=[table]))


def test_badge_column_cannot_take_a_width() -> None:
    table = make_table(
        [
            {"key": "a", "label": "A", "kind": "text"},
            {"key": "t", "label": "", "kind": "badge", "width": 2},
        ],
        rows=[{"a": "x", "t": "OK"}],
    )

    with pytest.raises(ReportError, match=r"badge column\(s\).*can't take a width"):
        parse_report(
            make_report(badges={"OK": {"label": "Ok", "tone": "green", "legend": "l"}}, blocks=[table])
        )


@pytest.mark.parametrize(
    ("width", "message"),
    [
        pytest.param(7, r"width\b.*less than or equal to 6", id="above-range"),
        pytest.param(0, r"width\b.*greater than or equal to 1", id="below-range"),
        pytest.param(True, r"width\b.*must be a number, not a boolean", id="boolean"),
    ],
)
def test_column_width_bad_values_are_rejected(width: object, message: str) -> None:
    table = make_table([{"key": "a", "label": "A", "kind": "text", "width": width}], rows=[{"a": "x"}])

    with pytest.raises(ReportError, match=message):
        parse_report(make_report(blocks=[table]))


def _badge_table(tag: str) -> dict[str, object]:
    return make_reconciled_table(
        columns=[
            {"key": "issue", "label": "I", "kind": "text"},
            {"key": "tag", "label": "", "kind": "badge"},
            {"key": "count", "label": "C", "kind": "number"},
        ],
        groups=[{"name": "g", "rows": [{"issue": "x", "tag": tag, "count": 10}]}],
    )


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


def test_undeclared_badge_in_grid_table_is_rejected() -> None:
    grid = make_grid([make_cell(6, [_badge_table("NOPE")])])

    with pytest.raises(ReportError, match=r"not declared.*NOPE"):
        parse_report(make_report(blocks=[grid]))


def test_undeclared_badge_in_nested_grid_table_is_rejected() -> None:
    inner = make_grid([make_cell(6, [_badge_table("DEEP_NOPE")])])
    grid = make_grid([make_cell(6, [inner])])

    with pytest.raises(ReportError, match=r"not declared.*DEEP_NOPE"):
        parse_report(make_report(blocks=[grid]))


def test_chart_series_values_must_match_category_count() -> None:
    block = {
        "type": "chart",
        "variant": "bar",
        "categories": ["a", "b", "c"],
        "series": [{"label": "X", "values": [1, 2]}],
    }
    with pytest.raises(ReportError, match=r"2 values but there are 3 categories"):
        parse_report(make_report(blocks=[block]))


def test_chart_bar_requires_categories() -> None:
    with pytest.raises(ReportError, match=r"needs 'categories'"):
        parse_report(make_report(blocks=[{"type": "chart", "variant": "bar"}]))


def test_chart_bar_requires_series() -> None:
    # categories present but no series — reaches the series guard (past the categories check)
    with pytest.raises(ReportError, match=r"needs at least one entry in 'series'"):
        parse_report(make_report(blocks=[{"type": "chart", "variant": "bar", "categories": ["a"]}]))


def test_chart_bar_rejects_negative_values() -> None:
    block = {
        "type": "chart",
        "variant": "bar",
        "categories": ["a"],
        "series": [{"label": "X", "values": [-1]}],
    }
    with pytest.raises(ReportError, match=r"negative value; bar/line values must be >= 0"):
        parse_report(make_report(blocks=[block]))


def test_chart_bar_rejects_donut_slices() -> None:
    block = {
        "type": "chart",
        "variant": "bar",
        "categories": ["a"],
        "series": [{"label": "X", "values": [1]}],
        "slices": [{"label": "s", "value": 1}],
    }
    with pytest.raises(ReportError, match=r"'slices' is only for variant: donut"):
        parse_report(make_report(blocks=[block]))


def test_chart_donut_rejects_bar_line_fields() -> None:
    block = {
        "type": "chart",
        "variant": "donut",
        "series": [{"label": "X", "values": [1]}],
        "slices": [{"label": "s", "value": 1}],
    }
    with pytest.raises(ReportError, match=r"'categories'/'series' are for variant: bar/line"):
        parse_report(make_report(blocks=[block]))


def test_chart_donut_requires_slices() -> None:
    with pytest.raises(ReportError, match=r"variant 'donut' needs"):
        parse_report(make_report(blocks=[{"type": "chart", "variant": "donut"}]))


def test_chart_donut_slice_value_must_be_positive() -> None:
    block = {"type": "chart", "variant": "donut", "slices": [{"label": "s", "value": 0}]}
    with pytest.raises(ReportError, match=r"donut slice 's' value must be greater than 0"):
        parse_report(make_report(blocks=[block]))


def test_comparison_row_values_must_match_option_count() -> None:
    block = {
        "type": "comparison",
        "options": ["A", "B", "C"],
        "rows": [{"feature": "X", "values": [True, False]}],
    }
    with pytest.raises(ReportError, match=r"has 2 values but there are 3 options"):
        parse_report(make_report(blocks=[block]))


def test_comparison_requires_at_least_two_options() -> None:
    block = {"type": "comparison", "options": ["only"], "rows": [{"feature": "X", "values": ["a"]}]}
    with pytest.raises(ReportError, match=r"blocks\.0\.comparison\.options.*at least 2"):
        parse_report(make_report(blocks=[block]))


def test_comparison_highlight_out_of_range_is_rejected() -> None:
    block = {
        "type": "comparison",
        "options": ["A", "B"],
        "highlight": 5,
        "rows": [{"feature": "X", "values": [True, False]}],
    }
    with pytest.raises(ReportError, match=r"highlight index 5 is out of range"):
        parse_report(make_report(blocks=[block]))


def test_chart_stacked_only_applies_to_bar() -> None:
    block = {
        "type": "chart",
        "variant": "line",
        "categories": ["a", "b"],
        "series": [{"label": "X", "values": [1, 2]}],
        "stacked": True,
    }
    with pytest.raises(ReportError, match=r"'stacked' applies only to variant: bar"):
        parse_report(make_report(blocks=[block]))


def test_references_rejects_duplicate_keys_within_a_block() -> None:
    block = {
        "type": "references",
        "items": [
            {"key": "a", "text": "First"},
            {"key": "b", "text": "Second"},
            {"key": "a", "text": "Clash"},
        ],
    }
    with pytest.raises(ReportError, match=r"reference key\(s\) declared more than once: \['a'\]"):
        parse_report(make_report(blocks=[block]))


def test_references_rejects_a_key_reused_across_separate_blocks() -> None:
    first = {"type": "references", "items": [{"key": "a", "text": "First"}]}
    second = {"type": "references", "items": [{"key": "a", "text": "Clash"}]}
    with pytest.raises(ReportError, match=r"reference key\(s\) declared more than once: \['a'\]"):
        parse_report(make_report(blocks=[first, second]))


def test_references_rejects_key_with_disallowed_characters() -> None:
    block = {"type": "references", "items": [{"key": "has space", "text": "x"}]}
    with pytest.raises(ReportError, match=r"blocks\.0\.references\.items\.0\.key"):
        parse_report(make_report(blocks=[block]))


def test_references_rejects_url_with_a_disallowed_scheme() -> None:
    block = {"type": "references", "items": [{"key": "a", "text": "x", "url": "javascript:alert(1)"}]}
    with pytest.raises(ReportError, match=r"'url' must be an http://, https://, or mailto: link"):
        parse_report(make_report(blocks=[block]))


def test_references_requires_at_least_one_item() -> None:
    with pytest.raises(ReportError, match=r"blocks\.0\.references\.items.*at least 1"):
        parse_report(make_report(blocks=[{"type": "references", "items": []}]))
