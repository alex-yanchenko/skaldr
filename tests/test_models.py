from pathlib import Path
from typing import Any

import pytest

from skaldr.errors import ReportError
from skaldr.models import (
    Callout,
    Cards,
    Fan,
    Flow,
    FlowStep,
    Grid,
    Meta,
    Report,
    Swimlane,
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


def test_block_span_defaults_to_none() -> None:
    block = parse_report(make_report(blocks=[{"type": "text", "body": "x"}])).blocks[0]
    assert isinstance(block, Text)
    assert block.span is None


def test_block_span_accepts_one_through_six() -> None:
    for span in range(1, 7):
        block = parse_report(make_report(blocks=[{"type": "text", "body": "x", "span": span}])).blocks[0]
        assert isinstance(block, Text)
        assert block.span == span


@pytest.mark.parametrize("span", [0, 7])
def test_block_span_out_of_range_is_rejected(span: int) -> None:
    with pytest.raises(ReportError, match=r"blocks\.0\.text\.span"):
        parse_report(make_report(blocks=[{"type": "text", "body": "x", "span": span}]))


def test_block_span_rejects_a_boolean() -> None:
    """`span` is a Count, so a bool (an int subclass pydantic would coerce to 1) is rejected."""
    with pytest.raises(ReportError, match=r"blocks\.0\.text\.span.*number, not a boolean"):
        parse_report(make_report(blocks=[{"type": "text", "body": "x", "span": True}]))


def test_meta_rejects_an_authored_width() -> None:
    """Width is reader-only — there is no meta.width. Authoring one fails the strict extra-key guard."""
    with pytest.raises(ReportError, match=r"meta\.width.*not permitted"):
        parse_report(make_report(meta={"title": "T", "width": "full"}))


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
    "group",
    [
        pytest.param({"label": "Sev", "items": []}, id="empty-items"),
        pytest.param({"label": "", "items": [{"label": "X", "tone": "blue"}]}, id="blank-label"),
    ],
)
def test_badge_group_rejects_empty_items_and_blank_label(group: dict[str, object]) -> None:
    with pytest.raises(ReportError, match=r"at least 1 (item|character)"):
        parse_report(make_report(blocks=[{"type": "badge_row", "groups": [group]}]))


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


def test_status_list_unknown_state_is_rejected() -> None:
    block = {"type": "status_list", "items": [{"state": "in_progress", "text": "x"}]}

    with pytest.raises(ReportError, match=r"blocks\.0\.status_list\.items\.0\.state"):
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


def test_rollup_by_a_non_badge_column_is_rejected() -> None:
    table = make_table(
        columns=[
            {"key": "item", "label": "I", "kind": "text"},
            {"key": "n", "label": "N", "kind": "number"},
        ],
        rows=[{"item": "a", "n": 1}],
        rollup={"by": "n"},
    )

    with pytest.raises(ReportError, match=r"rollup.by 'n' must be a badge column"):
        parse_report(make_report(blocks=[table]))


def test_rollup_by_an_unknown_column_is_rejected() -> None:
    table = make_table(
        columns=[{"key": "item", "label": "I", "kind": "text"}],
        rows=[{"item": "a"}],
        rollup={"by": "nope"},
    )

    with pytest.raises(ReportError, match=r"rollup.by 'nope' must be a badge column"):
        parse_report(make_report(blocks=[table]))


def test_rollup_by_a_badge_column_no_row_populates_is_rejected() -> None:
    table = make_table(
        columns=[
            {"key": "item", "label": "I", "kind": "text"},
            {"key": "tag", "label": "", "kind": "badge"},
        ],
        rows=[{"item": "a", "tag": ""}, {"item": "b", "tag": ""}],
        rollup={"by": "tag"},
    )

    with pytest.raises(ReportError, match=r"rollup.by 'tag' has no values to count"):
        parse_report(make_report(blocks=[table]))


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


def test_row_tone_alias_that_is_not_a_row_tone_is_still_rejected() -> None:
    """`blue` aliases to `info`, a real tone — but not a ROW tone (only muted/danger). It must still
    reject after normalisation, not slip through."""
    table = make_table(
        columns=[{"key": "a", "label": "A", "kind": "text"}], rows=[{"a": "x", "tone": "blue"}]
    )

    with pytest.raises(ReportError, match=r"tone: row tone must be 'muted' or 'danger'"):
        parse_report(make_report(blocks=[table]))


@pytest.mark.parametrize(
    ("palette", "semantic"),
    [
        ("slate", "neutral"),
        ("blue", "info"),
        ("green", "success"),
        ("amber", "warning"),
        ("red", "danger"),
        ("violet", "accent"),
    ],
)
def test_tone_and_badge_colour_alias_in_both_directions(palette: str, semantic: str) -> None:
    """A tone field normalises a palette name to its semantic twin; a badge colour normalises a
    semantic name to its palette twin. Full 6-pair map, both directions."""
    report = parse_report(
        make_report(blocks=[{"type": "cards", "items": [{"label": "x", "value": 1, "tone": palette}]}])
    )
    card = report.blocks[0]
    assert isinstance(card, Cards)
    assert card.items[0].tone == semantic

    badged = parse_report(
        make_report(
            badges={"K": {"label": "K", "tone": semantic, "legend": "x"}},
            blocks=[{"type": "text", "body": "h"}],
        )
    )
    assert badged.badges["K"].tone == palette


def test_callout_accepts_a_palette_alias_but_rejects_a_non_semantic_tone() -> None:
    """callout is semantic-only: a palette alias of one of its four tones works (green→success), but
    accent/neutral/teal/sky are not callout tones."""
    ok = parse_report(make_report(blocks=[{"type": "callout", "tone": "green", "body": "b"}]))
    callout = ok.blocks[0]
    assert isinstance(callout, Callout)
    assert callout.tone == "success"

    with pytest.raises(ReportError, match=r"blocks\.0\.callout\.tone"):
        parse_report(make_report(blocks=[{"type": "callout", "tone": "teal", "body": "b"}]))


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


def test_range_segment_span_must_be_positive() -> None:
    with pytest.raises(ReportError, match=r"segment 'span' must be greater than 0"):
        parse_report(make_report(blocks=[{"type": "range", "segments": [{"label": "x", "span": 0}]}]))


def test_range_segment_span_rejects_boolean() -> None:
    with pytest.raises(ReportError, match=r"must be a number, not a boolean"):
        parse_report(make_report(blocks=[{"type": "range", "segments": [{"label": "x", "span": True}]}]))


def test_range_segment_span_rejects_non_finite() -> None:
    block = {"type": "range", "segments": [{"label": "x", "span": float("inf")}]}
    with pytest.raises(ReportError, match=r"must be a finite number"):
        parse_report(make_report(blocks=[block]))


def test_range_segment_label_must_not_be_blank() -> None:
    with pytest.raises(ReportError, match=r"range segment label must not be blank"):
        parse_report(make_report(blocks=[{"type": "range", "segments": [{"label": "   ", "span": 1}]}]))


def test_range_needs_at_least_one_segment() -> None:
    with pytest.raises(ReportError, match=r"blocks\.0\.range\.segments.*at least 1"):
        parse_report(make_report(blocks=[{"type": "range", "segments": []}]))


def test_range_axis_needs_at_least_one_of_min_or_max() -> None:
    block: dict[str, object] = {"type": "range", "axis": {}, "segments": [{"label": "x", "span": 1}]}
    with pytest.raises(ReportError, match=r"range axis needs at least one of 'min' or 'max'"):
        parse_report(make_report(blocks=[block]))


def test_range_axis_rejects_blank_only_labels() -> None:
    block: dict[str, object] = {
        "type": "range",
        "axis": {"min": "  ", "max": ""},
        "segments": [{"label": "x", "span": 1}],
    }
    with pytest.raises(ReportError, match=r"range axis needs at least one of 'min' or 'max'"):
        parse_report(make_report(blocks=[block]))


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


_MAIN_WITH_INCLUDE = "version: 1\nmeta:\n  title: T\nblocks: !include blocks.yaml\n"


def test_include_splices_a_fragment(tmp_path: Path) -> None:
    (tmp_path / "blocks.yaml").write_text("- type: text\n  body: from fragment\n", encoding="utf-8")
    (tmp_path / "main.yaml").write_text(_MAIN_WITH_INCLUDE, encoding="utf-8")

    report = load_report(tmp_path / "main.yaml")

    assert report.model_dump(mode="json")["blocks"] == [
        {"type": "text", "body": "from fragment", "muted": False, "span": None}
    ]


def test_include_of_a_single_item_inside_a_sequence(tmp_path: Path) -> None:
    (tmp_path / "one.yaml").write_text("type: text\nbody: just me\n", encoding="utf-8")
    (tmp_path / "main.yaml").write_text(
        "version: 1\nmeta:\n  title: T\nblocks:\n  - !include one.yaml\n", encoding="utf-8"
    )

    report = load_report(tmp_path / "main.yaml")

    assert report.model_dump(mode="json")["blocks"] == [
        {"type": "text", "body": "just me", "muted": False, "span": None}
    ]


def test_include_resolves_paths_relative_to_each_including_file(tmp_path: Path) -> None:
    # main includes shared/frag.yaml; frag then includes deep.yaml, which lives next to FRAG (in
    # shared/), not next to main — so the path must resolve relative to frag's own dir, not the cwd
    # or the top file's dir.
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "deep.yaml").write_text("- type: text\n  body: deep\n", encoding="utf-8")
    (shared / "frag.yaml").write_text("!include deep.yaml\n", encoding="utf-8")
    (tmp_path / "main.yaml").write_text(
        "version: 1\nmeta:\n  title: T\nblocks: !include shared/frag.yaml\n", encoding="utf-8"
    )

    report = load_report(tmp_path / "main.yaml")

    assert report.model_dump(mode="json")["blocks"] == [
        {"type": "text", "body": "deep", "muted": False, "span": None}
    ]


def test_missing_include_target_is_a_report_error(tmp_path: Path) -> None:
    (tmp_path / "main.yaml").write_text(_MAIN_WITH_INCLUDE, encoding="utf-8")

    with pytest.raises(ReportError, match=r"file not found: .*blocks\.yaml"):
        load_report(tmp_path / "main.yaml")


def test_circular_include_is_a_report_error(tmp_path: Path) -> None:
    (tmp_path / "a.yaml").write_text("!include b.yaml\n", encoding="utf-8")
    (tmp_path / "b.yaml").write_text("!include a.yaml\n", encoding="utf-8")

    with pytest.raises(ReportError, match=r"circular !include:.*a\.yaml.*b\.yaml.*a\.yaml"):
        load_report(tmp_path / "a.yaml")


def test_self_include_is_a_report_error(tmp_path: Path) -> None:
    (tmp_path / "loop.yaml").write_text("!include loop.yaml\n", encoding="utf-8")

    with pytest.raises(ReportError, match=r"circular !include"):
        load_report(tmp_path / "loop.yaml")


def test_include_of_a_non_scalar_is_a_report_error(tmp_path: Path) -> None:
    (tmp_path / "main.yaml").write_text("version: 1\nblocks: !include [a, b]\n", encoding="utf-8")

    with pytest.raises(ReportError, match=r"!include in .*main\.yaml takes a single file path"):
        load_report(tmp_path / "main.yaml")


def test_include_with_no_path_is_a_report_error(tmp_path: Path) -> None:
    (tmp_path / "main.yaml").write_text('version: 1\nblocks: !include ""\n', encoding="utf-8")

    with pytest.raises(ReportError, match=r"!include in .*main\.yaml needs a file path"):
        load_report(tmp_path / "main.yaml")


def test_absolute_include_path_is_a_report_error(tmp_path: Path) -> None:
    # an absolute target would read outside the fragment set and silently break "relative to the
    # including file" — path.parent / "/abs" collapses to "/abs" — so it's rejected up front.
    (tmp_path / "main.yaml").write_text("version: 1\nblocks: !include /nope/abs.yaml\n", encoding="utf-8")

    with pytest.raises(ReportError, match=r"must be a relative path, not absolute: /nope/abs\.yaml"):
        load_report(tmp_path / "main.yaml")


def test_include_reuses_one_fragment_from_two_sites(tmp_path: Path) -> None:
    (tmp_path / "frag.yaml").write_text("type: text\nbody: reused\n", encoding="utf-8")
    (tmp_path / "main.yaml").write_text(
        "version: 1\nmeta:\n  title: T\nblocks:\n  - !include frag.yaml\n  - !include frag.yaml\n",
        encoding="utf-8",
    )

    report = load_report(tmp_path / "main.yaml")

    reused = {"type": "text", "body": "reused", "muted": False, "span": None}
    assert report.model_dump(mode="json")["blocks"] == [reused, reused]


def test_include_works_under_a_non_blocks_key(tmp_path: Path) -> None:
    (tmp_path / "meta.yaml").write_text("title: From Fragment\n", encoding="utf-8")
    (tmp_path / "main.yaml").write_text(
        "version: 1\nmeta: !include meta.yaml\nblocks:\n  - type: text\n    body: x\n", encoding="utf-8"
    )

    report = load_report(tmp_path / "main.yaml")

    assert report.model_dump(mode="json")["meta"]["title"] == "From Fragment"


def test_empty_included_fragment_is_a_report_error(tmp_path: Path) -> None:
    # an empty fragment parses to None; splicing None in for `blocks` must fail validation cleanly,
    # not raise a raw exception downstream.
    (tmp_path / "blocks.yaml").write_text("", encoding="utf-8")
    (tmp_path / "main.yaml").write_text(_MAIN_WITH_INCLUDE, encoding="utf-8")

    with pytest.raises(ReportError, match=r"blocks:.*valid list"):
        load_report(tmp_path / "main.yaml")


def test_include_chain_deeper_than_the_cap_is_a_report_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # a very deep non-cyclic chain must surface as a ReportError, not a raw RecursionError
    monkeypatch.setattr("skaldr.models._MAX_INCLUDE_DEPTH", 1)
    (tmp_path / "a.yaml").write_text("!include b.yaml\n", encoding="utf-8")
    (tmp_path / "b.yaml").write_text("- type: text\n  body: x\n", encoding="utf-8")

    with pytest.raises(ReportError, match=r"nested more than 1 deep"):
        load_report(tmp_path / "a.yaml")


def test_symlink_loop_is_a_report_error(tmp_path: Path) -> None:
    # a symlink loop must surface as a typed ReportError, never a raw traceback. The message is
    # version-dependent: on Python <=3.12 Path.resolve() raises on the loop (→ "could not resolve");
    # 3.13+ tolerates it, so the broken link is caught downstream as "file not found".
    (tmp_path / "a.yaml").symlink_to(tmp_path / "b.yaml")
    (tmp_path / "b.yaml").symlink_to(tmp_path / "a.yaml")

    with pytest.raises(ReportError, match=r"could not resolve|file not found"):
        load_report(tmp_path / "a.yaml")


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

    with pytest.raises(ReportError, match=r"set width on every in-cell column, or none"):
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


def test_placement_cell_is_only_for_badge_columns() -> None:
    table = make_table(
        [{"key": "a", "label": "A", "kind": "text", "placement": "cell"}],
        rows=[{"a": "x"}],
    )
    with pytest.raises(ReportError, match=r"placement 'cell' is only for badge columns"):
        parse_report(make_report(blocks=[table]))


def test_cell_badge_column_takes_a_width_and_accepts_a_key_or_list() -> None:
    """A placement:cell badge is an in-cell column: it may take a width, and its cell value is a single
    key or a list of keys."""
    table = make_table(
        [
            {"key": "a", "label": "A", "kind": "text", "width": 2},
            {"key": "acc", "label": "Access", "kind": "badge", "placement": "cell", "width": 1},
        ],
        rows=[{"a": "one", "acc": "W"}, {"a": "two", "acc": ["W", "R"]}],
    )
    report = parse_report(
        make_report(
            badges={
                "W": {"label": "Write", "tone": "green", "legend": "rw"},
                "R": {"label": "Read", "tone": "blue", "legend": "ro"},
            },
            blocks=[table],
        )
    )
    parsed = report.blocks[0]
    assert isinstance(parsed, Table)
    assert [row["acc"] for row in parsed.all_rows()] == ["W", ["W", "R"]]


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


@pytest.mark.parametrize("bad_value", [[], ["W", 123]])
def test_cell_badge_value_must_be_a_key_or_nonempty_string_list(bad_value: object) -> None:
    table = make_table(
        [
            {"key": "a", "label": "A", "kind": "text"},
            {"key": "acc", "label": "Access", "kind": "badge", "placement": "cell"},
        ],
        rows=[{"a": "x", "acc": bad_value}],
    )
    with pytest.raises(ReportError, match=r"cell badge needs a key or a non-empty list of keys"):
        parse_report(
            make_report(badges={"W": {"label": "Write", "tone": "green", "legend": "rw"}}, blocks=[table])
        )


def test_mixed_widths_rejected_when_a_cell_badge_column_is_in_the_set() -> None:
    """A cell-placement badge joins the in-cell width set, so widthing it but not a sibling still fails."""
    table = make_table(
        [
            {"key": "a", "label": "A", "kind": "text"},  # no width
            {"key": "acc", "label": "Access", "kind": "badge", "placement": "cell", "width": 1},
        ],
        rows=[{"a": "x", "acc": "W"}],
    )
    with pytest.raises(ReportError, match=r"set width on every in-cell column, or none"):
        parse_report(
            make_report(badges={"W": {"label": "Write", "tone": "green", "legend": "rw"}}, blocks=[table])
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


def test_comparison_polarity_length_must_match_option_count() -> None:
    block = {
        "type": "comparison",
        "options": ["A", "B"],
        "polarity": ["positive"],
        "rows": [{"feature": "X", "values": [True, False]}],
    }
    with pytest.raises(ReportError, match=r"polarity has 1 entries but there are 2 options"):
        parse_report(make_report(blocks=[block]))


def _swimlane(**overrides: object) -> dict[str, object]:
    block: dict[str, object] = {
        "type": "swimlane",
        "lanes": ["A", "B"],
        "columns": ["C1", "C2"],
        "steps": [
            {"lane": "A", "col": "C1", "n": "1", "label": "x"},
            {"lane": "B", "col": "C2", "n": "2", "label": "y"},
        ],
    }
    block.update(overrides)
    return block


def _swimlane_block(report: object) -> Swimlane:
    parsed = parse_report(report)
    block = parsed.blocks[0]
    assert isinstance(block, Swimlane)
    return block


def test_swimlane_step_lane_must_be_a_declared_lane() -> None:
    block = _swimlane(
        lanes=["A"], columns=["C1"], steps=[{"lane": "Ghost", "col": "C1", "n": "1", "label": "x"}]
    )
    with pytest.raises(ReportError, match=r"swimlane step lane 'Ghost' is not one of the declared lanes"):
        parse_report(make_report(blocks=[block]))


def test_swimlane_step_col_must_be_a_declared_column() -> None:
    block = _swimlane(
        lanes=["A"], columns=["C1"], steps=[{"lane": "A", "col": "Ghost", "n": "1", "label": "x"}]
    )
    with pytest.raises(ReportError, match=r"swimlane step col 'Ghost' is not one of the declared columns"):
        parse_report(make_report(blocks=[block]))


def test_swimlane_step_value_accepts_int_and_float_and_defaults_to_none() -> None:
    block = _swimlane(
        lanes=["A"],
        columns=["C1", "C2"],
        steps=[
            {"lane": "A", "col": "C1", "n": "1", "label": "x", "value": 3},
            {"lane": "A", "col": "C2", "n": "2", "label": "y", "value": 0.5},
            {"lane": "A", "col": "C1", "n": "3", "label": "z"},
        ],
    )
    parsed = _swimlane_block(make_report(blocks=[block]))
    assert [step.value for step in parsed.steps] == [3, 0.5, None]


def test_swimlane_step_value_rejects_a_boolean() -> None:
    """`value` is a Number, so a bool (an int subclass pydantic would coerce) is rejected."""
    block = _swimlane(
        lanes=["A"], columns=["C1"], steps=[{"lane": "A", "col": "C1", "n": "1", "label": "x", "value": True}]
    )
    with pytest.raises(ReportError, match=r"steps\.0\.value.*number, not a boolean"):
        parse_report(make_report(blocks=[block]))


def test_swimlane_step_url_rejects_an_unsafe_scheme() -> None:
    """A step `url` is gated to http/https/mailto so a `javascript:` link can't reach the href."""
    block = _swimlane(
        lanes=["A"],
        columns=["C1"],
        steps=[{"lane": "A", "col": "C1", "n": "1", "label": "x", "url": "javascript:alert(1)"}],
    )
    with pytest.raises(ReportError, match=r"steps\.0.*url must be an http://, https://, or mailto: link"):
        parse_report(make_report(blocks=[block]))


def test_swimlane_step_state_rejects_an_unknown_value() -> None:
    block = _swimlane(
        lanes=["A"],
        columns=["C1"],
        steps=[{"lane": "A", "col": "C1", "n": "1", "label": "x", "state": "urgent"}],
    )
    with pytest.raises(ReportError, match=r"steps\.0\.state"):
        parse_report(make_report(blocks=[block]))


def test_swimlane_step_id_must_be_a_safe_slug() -> None:
    """A step `id` is a safe slug (ASCII letters/digits/_/-) so `depends_on` can reference it cleanly."""
    block = _swimlane(
        lanes=["A"],
        columns=["C1"],
        steps=[{"lane": "A", "col": "C1", "n": "1", "label": "x", "id": "bad id"}],
    )
    with pytest.raises(ReportError, match=r"steps\.0\.id"):
        parse_report(make_report(blocks=[block]))


def test_swimlane_step_id_and_depends_on_are_retained() -> None:
    block = _swimlane(
        lanes=["A"],
        columns=["C1", "C2"],
        steps=[
            {"lane": "A", "col": "C1", "n": "1", "label": "a", "id": "x"},
            {"lane": "A", "col": "C2", "n": "2", "label": "b", "id": "y", "depends_on": ["x"]},
        ],
    )
    parsed = _swimlane_block(make_report(blocks=[block]))
    assert [(step.id, step.depends_on) for step in parsed.steps] == [("x", []), ("y", ["x"])]


def test_swimlane_step_ids_must_be_unique() -> None:
    block = _swimlane(
        lanes=["A"],
        columns=["C1", "C2"],
        steps=[
            {"lane": "A", "col": "C1", "n": "1", "label": "x", "id": "dup"},
            {"lane": "A", "col": "C2", "n": "2", "label": "y", "id": "dup"},
        ],
    )
    with pytest.raises(ReportError, match=r"swimlane step ids must be unique"):
        parse_report(make_report(blocks=[block]))


def test_swimlane_depends_on_must_reference_a_known_id() -> None:
    block = _swimlane(
        lanes=["A"],
        columns=["C1"],
        steps=[{"lane": "A", "col": "C1", "n": "1", "label": "x", "depends_on": ["ghost"]}],
    )
    with pytest.raises(ReportError, match=r"depends_on references unknown step id 'ghost'"):
        parse_report(make_report(blocks=[block]))


def test_swimlane_step_cannot_depend_on_itself() -> None:
    block = _swimlane(
        lanes=["A"],
        columns=["C1"],
        steps=[{"lane": "A", "col": "C1", "n": "1", "label": "x", "id": "a", "depends_on": ["a"]}],
    )
    with pytest.raises(ReportError, match=r"'a' cannot depend on itself"):
        parse_report(make_report(blocks=[block]))


def test_swimlane_lane_and_column_ids_decouple_reference_from_display() -> None:
    """A lane/column may carry an id (the reference key) distinct from its display name; a bare string
    is shorthand for name-as-key. Columns also carry an optional `sub` caption."""
    block = {
        "type": "swimlane",
        "lanes": [{"id": "eng", "name": "Engineering"}],
        "columns": ["S1", {"id": "s2", "name": "Sprint 2", "sub": "→ MVP demo"}],
        "steps": [
            {"lane": "eng", "col": "S1", "n": "1", "label": "a"},
            {"lane": "eng", "col": "s2", "n": "2", "label": "b"},
        ],
    }
    parsed = _swimlane_block(make_report(blocks=[block]))
    assert [(lane.key, lane.name) for lane in parsed.lanes] == [("eng", "Engineering")]
    assert [(col.key, col.name, col.sub) for col in parsed.columns] == [
        ("S1", "S1", None),  # bare string → key == name, no sub
        ("s2", "Sprint 2", "→ MVP demo"),
    ]


def test_swimlane_column_ids_must_be_unique() -> None:
    block = {
        "type": "swimlane",
        "lanes": ["A"],
        "columns": [{"id": "x", "name": "First"}, {"id": "x", "name": "Second"}],
        "steps": [{"lane": "A", "col": "x", "n": "1", "label": "a"}],
    }
    with pytest.raises(ReportError, match=r"swimlane columns must be unique"):
        parse_report(make_report(blocks=[block]))


def test_swimlane_lane_id_must_be_a_safe_slug() -> None:
    block = {
        "type": "swimlane",
        "lanes": [{"id": "bad id", "name": "X"}],
        "columns": ["C1"],
        "steps": [{"lane": "bad id", "col": "C1", "n": "1", "label": "a"}],
    }
    with pytest.raises(ReportError, match=r"lanes\.0\.id"):
        parse_report(make_report(blocks=[block]))


def test_swimlane_column_id_must_be_a_safe_slug() -> None:
    block = {
        "type": "swimlane",
        "lanes": ["A"],
        "columns": [{"id": "bad id", "name": "X"}],
        "steps": [{"lane": "A", "col": "bad id", "n": "1", "label": "a"}],
    }
    with pytest.raises(ReportError, match=r"columns\.0\.id"):
        parse_report(make_report(blocks=[block]))


def test_swimlane_lane_ids_must_be_unique() -> None:
    block = {
        "type": "swimlane",
        "lanes": [{"id": "x", "name": "First"}, {"id": "x", "name": "Second"}],
        "columns": ["C1"],
        "steps": [{"lane": "x", "col": "C1", "n": "1", "label": "a"}],
    }
    with pytest.raises(ReportError, match=r"swimlane lanes must be unique"):
        parse_report(make_report(blocks=[block]))


def test_swimlane_column_key_collides_across_string_and_object_forms() -> None:
    """A bare-string column's implicit key (its name) collides with another column's explicit id."""
    block = {
        "type": "swimlane",
        "lanes": ["A"],
        "columns": ["S1", {"id": "S1", "name": "Other"}],  # both resolve to key "S1"
        "steps": [{"lane": "A", "col": "S1", "n": "1", "label": "a"}],
    }
    with pytest.raises(ReportError, match=r"swimlane columns must be unique"):
        parse_report(make_report(blocks=[block]))


def test_swimlane_step_col_references_the_key_not_the_display_name() -> None:
    """With an explicit id, a step must reference the id — the display name is not the key."""
    block = {
        "type": "swimlane",
        "lanes": ["A"],
        "columns": [{"id": "s1", "name": "Sprint 1"}],
        "steps": [{"lane": "A", "col": "Sprint 1", "n": "1", "label": "a"}],  # uses the name, not the id
    }
    with pytest.raises(ReportError, match=r"swimlane step col 'Sprint 1' is not one of the declared columns"):
        parse_report(make_report(blocks=[block]))


def test_swimlane_lanes_must_be_unique() -> None:
    block = _swimlane(lanes=["A", "A"])
    with pytest.raises(ReportError, match=r"swimlane lanes must be unique"):
        parse_report(make_report(blocks=[block]))


def test_swimlane_columns_must_be_unique() -> None:
    block = _swimlane(columns=["C1", "C1"])
    with pytest.raises(ReportError, match=r"swimlane columns must be unique"):
        parse_report(make_report(blocks=[block]))


@pytest.mark.parametrize("field", ["lane", "col", "n", "label"])
def test_swimlane_step_field_may_not_be_blank(field: str) -> None:
    step = {"lane": "A", "col": "C1", "n": "1", "label": "x", field: "  "}
    block = _swimlane(lanes=["A"], columns=["C1"], steps=[step])
    with pytest.raises(ReportError, match=rf"swimlane step {field} must not be blank"):
        parse_report(make_report(blocks=[block]))


def test_swimlane_allows_at_most_eight_lanes() -> None:
    block = _swimlane(
        lanes=[f"L{i}" for i in range(9)],
        columns=["C1"],
        steps=[{"lane": "L0", "col": "C1", "n": "1", "label": "x"}],
    )
    with pytest.raises(ReportError, match=r"blocks\.0\.swimlane\.lanes.*at most 8"):
        parse_report(make_report(blocks=[block]))


def test_swimlane_lane_with_no_steps_is_rejected() -> None:
    block = _swimlane(
        lanes=["A", "B"], columns=["C1"], steps=[{"lane": "A", "col": "C1", "n": "1", "label": "x"}]
    )
    with pytest.raises(ReportError, match=r"swimlane lane 'B' has no steps"):
        parse_report(make_report(blocks=[block]))


def test_swimlane_column_with_no_steps_is_rejected() -> None:
    block = _swimlane(
        lanes=["A"], columns=["C1", "C2"], steps=[{"lane": "A", "col": "C1", "n": "1", "label": "x"}]
    )
    with pytest.raises(ReportError, match=r"swimlane column 'C2' has no steps"):
        parse_report(make_report(blocks=[block]))


def test_swimlane_group_names_must_be_unique() -> None:
    block = _swimlane(
        groups=[
            {"name": "G", "color": "blue", "columns": ["C1"]},
            {"name": "G", "color": "amber", "columns": ["C2"]},
        ]
    )
    with pytest.raises(ReportError, match=r"swimlane group names must be unique"):
        parse_report(make_report(blocks=[block]))


def test_swimlane_group_column_must_be_declared() -> None:
    block = _swimlane(
        lanes=["A"],
        columns=["C1"],
        groups=[{"name": "G", "color": "blue", "columns": ["Ghost"]}],
        steps=[{"lane": "A", "col": "C1", "n": "1", "label": "x"}],
    )
    with pytest.raises(ReportError, match=r"swimlane group 'G' references undeclared column\(s\): Ghost"):
        parse_report(make_report(blocks=[block]))


def test_swimlane_group_columns_must_be_contiguous() -> None:
    block = _swimlane(
        lanes=["A"],
        columns=["C1", "C2", "C3"],
        groups=[{"name": "G", "color": "blue", "columns": ["C1", "C3"]}],
        steps=[{"lane": "A", "col": "C1", "n": "1", "label": "x"}],
    )
    with pytest.raises(ReportError, match=r"swimlane group 'G' columns must be contiguous in column order"):
        parse_report(make_report(blocks=[block]))


def test_swimlane_step_group_must_be_declared() -> None:
    block = _swimlane(
        lanes=["A"],
        columns=["C1"],
        groups=[{"name": "G", "color": "blue", "columns": ["C1"]}],
        steps=[{"lane": "A", "col": "C1", "group": "Nope", "n": "1", "label": "x"}],
    )
    with pytest.raises(ReportError, match=r"swimlane step group 'Nope' is not a declared group"):
        parse_report(make_report(blocks=[block]))


def test_swimlane_step_group_must_cover_its_column() -> None:
    block = _swimlane(
        lanes=["A"],
        columns=["C1", "C2"],
        groups=[{"name": "G", "color": "blue", "columns": ["C1"]}],
        steps=[
            {"lane": "A", "col": "C1", "group": "G", "n": "1", "label": "x"},
            {"lane": "A", "col": "C2", "group": "G", "n": "2", "label": "y"},
        ],
    )
    with pytest.raises(ReportError, match=r"swimlane step group 'G' does not cover column 'C2'"):
        parse_report(make_report(blocks=[block]))


def test_swimlane_step_in_a_split_column_must_name_its_group() -> None:
    block = _swimlane(
        lanes=["A"],
        columns=["C1"],
        groups=[
            {"name": "G1", "color": "blue", "columns": ["C1"]},
            {"name": "G2", "color": "amber", "columns": ["C1"]},
        ],
        steps=[{"lane": "A", "col": "C1", "n": "1", "label": "x"}],
    )
    with pytest.raises(
        ReportError,
        match=r"swimlane step in column 'C1' must name a group — that column is split across 2 groups",
    ):
        parse_report(make_report(blocks=[block]))


def test_swimlane_group_with_no_steps_is_rejected() -> None:
    block = _swimlane(
        lanes=["A"],
        columns=["C1"],
        groups=[
            {"name": "G1", "color": "blue", "columns": ["C1"]},
            {"name": "G2", "color": "amber", "columns": ["C1"]},
        ],
        steps=[{"lane": "A", "col": "C1", "group": "G1", "n": "1", "label": "x"}],
    )
    with pytest.raises(ReportError, match=r"swimlane group 'G2' has no steps"):
        parse_report(make_report(blocks=[block]))


def test_swimlane_interleaving_groups_are_rejected() -> None:
    block = _swimlane(
        lanes=["A"],
        columns=["C1", "C2", "C3"],
        groups=[
            {"name": "Wide", "color": "blue", "columns": ["C1", "C2", "C3"]},
            {"name": "Mid", "color": "amber", "columns": ["C2"]},
        ],
        steps=[
            {"lane": "A", "col": "C1", "group": "Wide", "n": "1", "label": "x"},
            {"lane": "A", "col": "C2", "group": "Mid", "n": "2", "label": "y"},
            {"lane": "A", "col": "C3", "group": "Wide", "n": "3", "label": "z"},
        ],
    )
    with pytest.raises(ReportError, match=r"swimlane group 'Wide' cannot be laid out contiguously"):
        parse_report(make_report(blocks=[block]))


def test_swimlane_without_groups_has_one_subcolumn_per_column() -> None:
    block = _swimlane_block(make_report(blocks=[_swimlane()]))

    assert block.groups == []
    assert block.subcolumns() == [("C1", None), ("C2", None)]


def test_swimlane_orders_a_split_columns_subcolumns_by_span_then_declaration() -> None:
    block = _swimlane_block(
        make_report(
            blocks=[
                _swimlane(
                    lanes=["R"],
                    columns=["S1", "S2", "S3"],
                    groups=[
                        {"name": "MVP", "color": "blue", "columns": ["S1", "S2"]},
                        {"name": "Beta", "color": "amber", "columns": ["S2"]},
                        {"name": "GA", "color": "violet", "columns": ["S2", "S3"]},
                    ],
                    steps=[
                        {"lane": "R", "col": "S1", "n": "1", "label": "a"},
                        {"lane": "R", "col": "S2", "group": "Beta", "n": "2", "label": "b"},
                        {"lane": "R", "col": "S3", "n": "3", "label": "c"},
                    ],
                )
            ]
        )
    )

    assert block.subcolumns() == [
        ("S1", "MVP"),
        ("S2", "MVP"),
        ("S2", "Beta"),
        ("S2", "GA"),
        ("S3", "GA"),
    ]


def test_swimlane_leaves_an_ungrouped_column_among_grouped_columns_untouched() -> None:
    block = _swimlane_block(
        make_report(
            blocks=[
                _swimlane(
                    lanes=["R"],
                    columns=["Early", "Mid", "Late"],
                    groups=[{"name": "Push", "color": "blue", "columns": ["Early", "Mid"]}],
                    steps=[
                        {"lane": "R", "col": "Early", "n": "1", "label": "a"},
                        {"lane": "R", "col": "Mid", "n": "2", "label": "b"},
                        {"lane": "R", "col": "Late", "n": "3", "label": "c"},
                    ],
                )
            ]
        )
    )

    assert block.subcolumns() == [("Early", "Push"), ("Mid", "Push"), ("Late", None)]


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
