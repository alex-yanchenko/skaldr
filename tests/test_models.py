from typing import Any, get_args

import pytest

from skaldr.errors import ReportError
from skaldr.models import (
    TONE_BADGE_COLOR,
    BadgeColorLiteral,
    Cards,
    Meta,
    Meter,
    MeterItem,
    Report,
    Text,
    ToneLiteral,
    badge_color_of,
    parse_report,
)
from tests.factories import make_reconciled_table, make_report, make_table
from tests.factories.models_factory import in_a_tab


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


_TABLE_WITH_ID = make_table([{"key": "a", "label": "A"}], rows=[{"a": "x"}], id="dup")


@pytest.mark.parametrize(
    ("blocks", "message"),
    [
        pytest.param(
            [_TABLE_WITH_ID, in_a_tab(_TABLE_WITH_ID)],
            "table id(s) used more than once: ['dup'], at blocks.0.table.id, "
            "blocks.1.tabs.tabs.0.blocks.0.table.id; table ids must be unique",
            id="table-id",
        ),
        pytest.param(
            [
                {"type": "references", "items": [{"key": "a", "text": "A"}]},
                in_a_tab({"type": "references", "items": [{"key": "a", "text": "B"}]}),
            ],
            "reference key(s) used more than once: ['a'], at blocks.0.references.items.0.key, "
            "blocks.1.tabs.tabs.0.blocks.0.references.items.0.key; reference keys must be unique",
            id="reference-key",
        ),
        pytest.param(
            [
                {"type": "heading", "text": "A", "id": "dup"},
                in_a_tab({"type": "heading", "text": "B", "id": "dup"}),
            ],
            "heading/section id(s) used more than once: ['dup'], at blocks.0.heading.id, "
            "blocks.1.tabs.tabs.0.blocks.0.heading.id; heading and section ids must be unique",
            id="heading-id-in-a-tab",
        ),
        pytest.param(
            [
                {"type": "heading", "text": "A", "id": "dup"},
                {"type": "section", "title": "B", "id": "dup", "blocks": [{"type": "text", "body": "x"}]},
            ],
            "heading/section id(s) used more than once: ['dup'], at blocks.0.heading.id, "
            "blocks.1.section.id; heading and section ids must be unique",
            id="heading-and-section-id",
        ),
    ],
)
def test_a_repeated_id_is_refused_naming_every_place_it_is_used(
    blocks: list[dict[str, Any]], message: str
) -> None:
    with pytest.raises(ReportError) as excinfo:
        parse_report(make_report(blocks=blocks))

    assert str(excinfo.value) == f"invalid content data: Value error, {message}"


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


@pytest.mark.parametrize(
    ("tone", "color"),
    [
        pytest.param("success", "green", id="semantic-tone-takes-its-palette-twin"),
        pytest.param("neutral", "slate", id="neutral-is-slate"),
        pytest.param("teal", "teal", id="palette-only-tone-keeps-its-name"),
    ],
)
def test_the_badge_color_of_a_tone(tone: ToneLiteral, color: BadgeColorLiteral) -> None:
    assert badge_color_of(tone) == color


def test_the_tone_to_badge_color_table_pairs_every_tone_with_a_distinct_color() -> None:
    assert (set(TONE_BADGE_COLOR), sorted(TONE_BADGE_COLOR.values())) == (
        set(get_args(ToneLiteral)),
        sorted(get_args(BadgeColorLiteral)),
    )


def _comparison(**overrides: Any) -> dict[str, Any]:
    return {
        "type": "comparison",
        "options": ["a", "b"],
        "rows": [{"feature": "f", "values": [True, False]}],
        **overrides,
    }


@pytest.mark.parametrize(
    ("block", "message"),
    [
        pytest.param(
            _comparison(highlight=True),
            "blocks.0.comparison.highlight: Value error, must be a number, not a boolean",
            id="highlight-true",
        ),
        pytest.param(
            _comparison(highlight="1"),
            "blocks.0.comparison.highlight: Input should be a valid integer",
            id="highlight-numeric-string",
        ),
        pytest.param(
            {"type": "meter", "items": [{"label": "m", "value": "5", "max": 10}]},
            "blocks.0.meter.items.0.value.int: Input should be a valid integer; "
            "blocks.0.meter.items.0.value.float: Input should be a valid number",
            id="meter-value-numeric-string",
        ),
        pytest.param(
            {"type": "list", "style": "number", "start": "4", "items": ["a"]},
            "blocks.0.list.start: Input should be a valid integer",
            id="list-start-numeric-string",
        ),
        pytest.param(
            {"type": "text", "body": "x", "span": 2.0},
            "blocks.0.text.span: Input should be a valid integer",
            id="span-a-float",
        ),
        pytest.param(
            {"type": "section", "title": "S", "collapsed": "no", "blocks": [{"type": "text", "body": "x"}]},
            "blocks.0.section.collapsed: Input should be a valid boolean",
            id="collapsed-yes-no-string",
        ),
        pytest.param(
            {"type": "list", "style": "check", "items": [{"text": "a", "checked": 1}]},
            "blocks.0.list.items.0.ListItem.checked: Input should be a valid boolean",
            id="checked-an-integer",
        ),
        pytest.param(
            make_reconciled_table(
                reconcile={"total": "100", "column": "count", "handled": {"label": "Clean", "value": 90}}
            ),
            "blocks.0.table.reconcile.total: Input should be a valid integer",
            id="reconcile-total-numeric-string",
        ),
    ],
)
def test_a_value_of_the_wrong_yaml_type_is_refused_rather_than_coerced(
    block: dict[str, Any], message: str
) -> None:
    with pytest.raises(ReportError) as raised:
        parse_report(make_report(blocks=[block]))

    assert str(raised.value) == f"invalid content data: {message}"


def test_yaml_numbers_fill_number_fields_without_changing_type() -> None:
    block = {"type": "meter", "items": [{"label": "m", "value": 5, "max": 10.5}]}

    assert parse_report(make_report(blocks=[block])).blocks[0] == Meter(
        type="meter", items=[MeterItem(label="m", value=5, max=10.5)]
    )


BEYOND_FLOAT_RANGE = 10**400


NUMBER_OUT_OF_RANGE = "must be between -1e+300 and 1e+300"


def _bar_chart(*values: float) -> dict[str, Any]:
    return {
        "type": "chart",
        "variant": "bar",
        "categories": ["a"],
        "series": [{"label": f"s{index}", "values": [value]} for index, value in enumerate(values)],
    }


@pytest.mark.parametrize(
    ("block", "location"),
    [
        pytest.param(
            make_reconciled_table(
                groups=[{"name": "g", "rows": [{"issue": "x", "count": BEYOND_FLOAT_RANGE}]}]
            ),
            f"blocks.0.table: Value error, groups.0.rows.0.count: {NUMBER_OUT_OF_RANGE}",
            id="table-number-cell-beyond-float-range",
        ),
        pytest.param(
            make_reconciled_table(
                reconcile={"total": 10, "column": "count"},
                groups=[
                    {
                        "name": "g",
                        "rows": [
                            {
                                "issue": "x",
                                "count": 10,
                                "subrows": [{"label": "a", "value": BEYOND_FLOAT_RANGE}],
                            }
                        ],
                    }
                ],
            ),
            f"blocks.0.table: Value error, groups.0.rows.0.subrows.0.value: {NUMBER_OUT_OF_RANGE}",
            id="subrow-value-beyond-float-range",
        ),
        pytest.param(
            _bar_chart(1e308, 1e308),
            f"blocks.0.chart.series.0.values.0: Value error, {NUMBER_OUT_OF_RANGE}; "
            f"blocks.0.chart.series.1.values.0: Value error, {NUMBER_OUT_OF_RANGE}",
            id="chart-value-near-the-float-limit",
        ),
        pytest.param(
            {"type": "chart", "variant": "donut", "slices": [{"label": "a", "value": 1e301}]},
            f"blocks.0.chart.slices.0.value: Value error, {NUMBER_OUT_OF_RANGE}",
            id="donut-slice-past-the-bound",
        ),
        pytest.param(
            {"type": "cards", "items": [{"label": "x", "value": -BEYOND_FLOAT_RANGE}]},
            f"blocks.0.cards.items.0.value.function-before[_reject_bool_and_non_finite(), "
            f"union[int,float]]: Value error, {NUMBER_OUT_OF_RANGE}; "
            "blocks.0.cards.items.0.value.str: Input should be a valid string",
            id="card-value-below-the-negative-bound",
        ),
    ],
)
def test_a_number_beyond_the_shared_bound_is_refused_with_its_path(
    block: dict[str, Any], location: str
) -> None:
    with pytest.raises(ReportError) as raised:
        parse_report(make_report(blocks=[block]))

    assert str(raised.value) == f"invalid content data: {location}"
