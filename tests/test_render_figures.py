import pytest

from skaldr.models import Report, parse_report
from skaldr.render import render_html
from tests.factories import (
    EDGE_BADGES,
    HAVE_BADGE,
    MATRIX_OF_EDGE_BADGE_LABELS,
    MATRIX_OF_EVERY_CELL_SHAPE,
    make_report,
    make_table,
)


def test_a_declared_badge_no_block_uses_renders_no_legend_with_or_without_a_table() -> None:
    badges = {"P": {"label": "prod", "tone": "blue", "legend": "the prod tag"}}
    text = {"type": "text", "body": "Intro."}
    table = make_table([{"key": "a", "label": "A", "kind": "text"}], rows=[{"a": "x"}])

    pages = [
        render_html(parse_report(make_report(badges=badges, blocks=blocks)))
        for blocks in ([text], [text, table])
    ]

    assert ["Legend: badges used on this page" in page for page in pages] == [False, False]


def test_the_legend_renders_once_before_the_first_block_when_badges_are_used_and_no_table_exists() -> None:
    badges = {"P": {"label": "prod", "tone": "blue", "legend": "the prod tag"}}
    blocks = [{"type": "text", "body": "Intro."}, {"type": "badge_row", "items": [{"key": "P"}]}]

    html = render_html(parse_report(make_report(badges=badges, blocks=blocks)))

    assert (
        html.count("Legend: badges used on this page"),
        html.index("Legend: badges used on this page") < html.index("Intro."),
    ) == (1, True)


def test_container_badges_render_on_a_steps_style_flow_node() -> None:
    """The steps branch renders badge chips through a different template arm than the arrow branch."""
    badges = {"OK": {"label": "OK", "tone": "green", "legend": "fine"}}
    block = {"type": "flow", "style": "steps", "steps": [{"label": "A", "badges": ["OK"]}, {"label": "B"}]}

    html = render_html(parse_report(make_report(badges=badges, blocks=[block])))

    assert '<div class="flow steps">' in html
    assert html.count('<span class="chips"><span class="chip green">OK</span></span>') == 1


@pytest.mark.parametrize(
    ("delta", "expected"),
    [
        ({"label": "12%", "direction": "up", "tone": "success"}, '<span class="delta success">▲ 12%</span>'),
        ({"label": "8%", "direction": "down", "tone": "danger"}, '<span class="delta danger">▼ 8%</span>'),
        ({"label": "0", "direction": "flat", "tone": "info"}, '<span class="delta info">→ 0</span>'),
        (
            {"label": "n/a"},
            '<span class="delta neutral">n/a</span>',
        ),  # no direction → no glyph; no tone → neutral
    ],
    ids=["up", "down", "flat", "bare"],
)
def test_card_delta_renders_each_glyph_and_the_chosen_tone(delta: dict[str, str], expected: str) -> None:
    block = {"type": "cards", "items": [{"label": "X", "value": 1, "delta": delta}]}

    html = render_html(parse_report(make_report(blocks=[block])))

    assert expected in html


def test_card_delta_tone_is_independent_of_the_card_tone() -> None:
    # a danger-toned card can carry a green delta: escalations dropping is good, so down = success
    block = {
        "type": "cards",
        "items": [
            {
                "label": "Escalations",
                "value": 90,
                "tone": "danger",
                "delta": {"label": "-12", "direction": "down", "tone": "success"},
            }
        ],
    }
    html = render_html(parse_report(make_report(blocks=[block])))

    assert '<div class="card danger">' in html  # the card's own tone
    assert '<span class="delta success">▼ -12</span>' in html  # the delta's independent tone


def test_comparison_renders_options_features_checks_toned_cells_and_highlight() -> None:
    block = {
        "type": "comparison",
        "options": ["A", "B"],
        "highlight": 1,
        "rows": [
            {"feature": "Fast", "values": [True, False]},
            {"feature": "Cost", "values": ["free", {"value": "paid", "tone": "danger"}]},
            {"feature": "Support", "values": [{"value": "n/a"}, "24/7"]},  # untoned cell + bare string
        ],
    }
    html = render_html(parse_report(make_report(blocks=[block])))

    assert '<table class="cmp">' in html
    assert '<th class="hl">B</th>' in html  # the highlighted option header (index 1)
    assert '<td class="feat">Fast</td>' in html
    assert '<span class="chk good">✓</span>' in html  # bare true
    assert "<td>free</td>" in html  # bare string cell renders unwrapped, no span
    assert '<span class="ct danger">paid</span>' in html  # {value, tone} cell
    assert '<span class="ct">n/a</span>' in html  # {value} with NO tone → default-muted, no tone class
    # the highlighted column is column B specifically (content-anchored, not just a count)
    assert '<td class="hl"><span class="chk bad">✗</span></td>' in html
    assert '<td class="hl"><span class="ct danger">paid</span></td>' in html
    assert html.count('<td class="hl">') == 3  # every cell of column B (three rows)


def test_comparison_highlight_reads_as_a_panel_not_just_a_tint() -> None:
    """The highlighted column gets accent side-borders + a header cap so it reads as a deliberate
    panel in light theme (the bare --accent-bg tint was a washed smudge). Scoped to .cmp — the shared
    --accent-bg token is untouched; the border colour routes through a token like every other colour."""
    block = {
        "type": "comparison",
        "options": ["A", "B"],
        "highlight": 1,
        "rows": [{"feature": "Fast", "values": [False, True]}],
    }
    html = render_html(parse_report(make_report(blocks=[block])))

    assert '<th class="hl">B</th>' in html  # the feature actually renders a highlighted column
    assert "--accent-line:color-mix(in srgb, var(--accent-fg) 30%, transparent);" in html  # tokenised
    assert "box-shadow:inset 0 3px 0 var(--accent-fg)" in html  # header cap on th.hl
    assert "& .hl{border-inline:1px solid var(--accent-line)}" in html  # column side-borders


def test_comparison_negative_polarity_flips_the_check_colour_not_the_glyph() -> None:
    """A 'negative' column marks a present-is-bad attribute: a true ✓ reads BAD (red) and a false ✗
    reads GOOD (green). The glyph still tracks present/absent — only the colour flips."""
    block = {
        "type": "comparison",
        "options": ["Ours", "Theirs"],
        "polarity": ["positive", "negative"],
        "rows": [
            {"feature": "Leaks disk layout", "values": [True, False]},
            {"feature": "Reconciles exactly", "values": [False, True]},
            {"feature": "Effort", "values": ["low", {"value": "high", "tone": "danger"}]},
        ],
    }
    html = render_html(parse_report(make_report(blocks=[block])))

    # positive column: present → ✓ green (good), absent → ✗ red (bad) — the normal reading
    assert '<td><span class="chk good">✓</span></td>' in html
    assert '<td><span class="chk bad">✗</span></td>' in html
    # negative column: absent → ✗ but green (good), present → ✓ but red (bad) — presence is the flaw
    assert '<td><span class="chk good">✗</span></td>' in html
    assert '<td><span class="chk bad">✓</span></td>' in html
    # polarity flips only ✓/✗ bool cells; a toned cell in the negative column renders untouched
    assert '<td><span class="ct danger">high</span></td>' in html


def test_matrix_fills_cells_by_state_and_leaves_blanks_empty() -> None:
    block = {
        "type": "matrix",
        "rows": ["Receiving", "Picking"],
        "columns": ["Docs", "Tests"],
        "cells": [
            {"row": "Receiving", "col": "Docs", "badge": "HAVE"},  # badge → tone fill + its label
            {"row": "Picking", "col": "Docs", "tone": "blue", "label": "R"},  # one-off fill + text
            {"row": "Picking", "col": "Tests", "label": "n/a"},  # label only → no fill
            # Receiving/Tests omitted → a blank cell
        ],
    }
    report = parse_report(
        make_report(blocks=[block], badges={"HAVE": {"label": "Have", "tone": "green", "legend": "covered"}})
    )

    html = render_html(report)

    assert "<thead><tr><th></th><th>Docs</th><th>Tests</th></tr></thead>" in html
    assert (
        '<tr><th>Receiving</th><td class="c green"><span>Have</span></td>'
        '<td class="c blank"><span></span></td></tr>'
    ) in html
    assert (
        '<tr><th>Picking</th><td class="c blue"><span>R</span></td><td class="c"><span>n/a</span></td></tr>'
    ) in html


def test_only_a_missing_matrix_cell_is_marked_blank() -> None:
    block = {
        "type": "matrix",
        "rows": ["r"],
        "columns": ["missing", "label only", "toned"],
        "cells": [
            {"row": "r", "col": "label only", "label": "n/a"},
            {"row": "r", "col": "toned", "tone": "green"},
        ],
    }

    html = render_html(parse_report(make_report(blocks=[block])))

    assert (
        '<tr><th>r</th><td class="c blank"><span></span></td><td class="c"><span>n/a</span></td>'
        '<td class="c green"><span></span></td></tr>'
    ) in html


def test_a_matrix_cell_with_a_badge_and_a_label_shows_the_badge_chip_then_the_label() -> None:
    html = render_html(parse_report(make_report(blocks=[MATRIX_OF_EVERY_CELL_SHAPE], badges=HAVE_BADGE)))

    assert (
        "<tr><th>Receiving</th>"
        '<td class="c green"><span>Have</span></td>'
        '<td class="c green"><span><span class="chip">Have</span> runbook v2</span></td>'
        '<td class="c red"><span>none yet</span></td>'
        '<td class="c"><span>n/a</span></td></tr>'
    ) in html


def test_a_matrix_cell_whose_badge_adds_no_name_shows_its_text_without_a_chip() -> None:
    html = render_html(parse_report(make_report(blocks=[MATRIX_OF_EDGE_BADGE_LABELS], badges=EDGE_BADGES)))

    assert (
        "<tr><th>Receiving</th>"
        '<td class="c red"><span>lbl</span></td>'
        '<td class="c amber"><span>lbl</span></td>'
        '<td class="c green"><span>Have</span></td>'
        '<td class="c blue"><span><span class="chip">A|B *x*</span> a_b [c] &lt;d&gt; | e</span></td></tr>'
    ) in html


def test_matrix_tone_only_cell_fills_without_text() -> None:
    """A cell with a one-off `tone` and no `label` is a pure colour swatch — the fill, an empty span."""
    block = {
        "type": "matrix",
        "rows": ["r"],
        "columns": ["c"],
        "cells": [{"row": "r", "col": "c", "tone": "green"}],
    }

    html = render_html(parse_report(make_report(blocks=[block])))

    assert '<td class="c green"><span></span></td>' in html


def test_matrix_badge_reference_appears_in_the_legend() -> None:
    """A badge used only by a matrix (no table on the page) still lists in the derived legend, which
    renders at the top when the page has no table."""
    block = {
        "type": "matrix",
        "rows": ["r"],
        "columns": ["c"],
        "cells": [{"row": "r", "col": "c", "badge": "HAVE"}],
    }
    report = parse_report(
        make_report(blocks=[block], badges={"HAVE": {"label": "Have", "tone": "green", "legend": "covered"}})
    )

    html = render_html(report)

    assert '<span class="chip green">Have</span><span class="meaning">covered</span>' in html


def test_meter_renders_derived_percentage_and_tone() -> None:
    block = {"type": "meter", "items": [{"label": "Load", "value": 85, "max": 100, "tone": "warning"}]}
    report = parse_report(make_report(blocks=[block]))

    html = render_html(report)

    assert '<div class="fill warning" style="width:85.0%">' in html
    assert '<span class="m-val">85.0%</span>' in html


def test_meter_renders_multiple_items_each_with_its_own_tone() -> None:
    block = {
        "type": "meter",
        "items": [
            {"label": "Extract", "value": 100, "max": 100, "tone": "info"},
            {"label": "Load", "value": 85, "max": 100, "tone": "warning"},
        ],
    }
    report = parse_report(make_report(blocks=[block]))

    html = render_html(report)

    assert (
        '<div class="meter">'
        '<span class="m-label">Extract</span><div class="track">'
        '<div class="fill info" style="width:100.0%"></div></div><span class="m-val">100.0%</span>'
        '<span class="m-label">Load</span><div class="track">'
        '<div class="fill warning" style="width:85.0%"></div></div><span class="m-val">85.0%</span>'
        "</div>" in html
    )


def test_meter_item_without_tone_falls_back_to_neutral() -> None:
    block = {"type": "meter", "items": [{"label": "X", "value": 1, "max": 2}]}
    report = parse_report(make_report(blocks=[block]))

    html = render_html(report)

    assert '<div class="fill neutral" style="width:50.0%">' in html


def test_range_segments_carry_their_span_as_flex_with_soft_tint() -> None:
    """Segments distribute the bar by `flex:<span>` (exact proportional fill, no rounding); tone is a
    class, sub is a rich line."""
    block = {
        "type": "range",
        "segments": [
            {"label": "Supported", "span": 3, "tone": "success", "sub": "security **fixes**"},
            {"label": "Expired", "span": 1, "tone": "danger"},
        ],
    }

    html = render_html(parse_report(make_report(blocks=[block])))

    assert '<div class="range">' in html
    assert (
        '<div class="rbar">'
        '<div class="rseg success" style="flex:3"><span class="rlab">Supported</span>'
        '<span class="rsub">security <strong>fixes</strong></span></div>'
        '<div class="rseg danger" style="flex:1"><span class="rlab">Expired</span></div>'
        "</div>" in html
    )
    assert 'class="raxis"' not in html  # no axis given → no axis row


def test_range_three_segments_each_emit_their_own_span() -> None:
    """Covers 3+ segments and distinct span values through the real render path."""
    block = {
        "type": "range",
        "segments": [
            {"label": "A", "span": 2},
            {"label": "B", "span": 1},
            {"label": "C", "span": 1},
        ],
    }

    html = render_html(parse_report(make_report(blocks=[block])))

    assert (
        '<div class="rseg neutral" style="flex:2"><span class="rlab">A</span></div>'
        '<div class="rseg neutral" style="flex:1"><span class="rlab">B</span></div>'
        '<div class="rseg neutral" style="flex:1"><span class="rlab">C</span></div>' in html
    )


def test_range_axis_renders_both_end_cap_labels() -> None:
    block = {
        "type": "range",
        "axis": {"min": "2015", "max": "2025"},
        "segments": [{"label": "A", "span": 1}, {"label": "B", "span": 1}],
    }

    html = render_html(parse_report(make_report(blocks=[block])))

    assert '<div class="raxis"><span class="rmin">2015</span><span class="rmax">2025</span></div>' in html


@pytest.mark.parametrize(
    ("axis", "expected"),
    [
        ({"min": "2015"}, '<span class="rmin">2015</span><span class="rmax"></span>'),
        ({"max": "now"}, '<span class="rmin"></span><span class="rmax">now</span>'),
    ],
)
def test_range_axis_with_one_end_omitted_renders_an_empty_cap(axis: dict[str, str], expected: str) -> None:
    """Either end may be omitted; the present label keeps its side and the omitted end is an empty span."""
    block = {"type": "range", "axis": axis, "segments": [{"label": "A", "span": 1}]}

    html = render_html(parse_report(make_report(blocks=[block])))

    assert f'<div class="raxis">{expected}</div>' in html


def test_range_segment_without_tone_falls_back_to_neutral() -> None:
    block = {"type": "range", "segments": [{"label": "X", "span": 1}]}

    html = render_html(parse_report(make_report(blocks=[block])))

    assert '<div class="rseg neutral" style="flex:1"><span class="rlab">X</span></div>' in html


def test_card_string_value_and_tone_render() -> None:
    block = {"type": "cards", "items": [{"label": "Status", "value": "HEALTHY", "tone": "accent"}]}
    report = parse_report(make_report(blocks=[block]))

    html = render_html(report)

    assert '<div class="card accent">' in html
    assert '<div class="n str">HEALTHY</div>' in html


def _matrix_with_cards(card_items: list[dict[str, object]]) -> Report:
    """A page with derived summary cards above a matrix they count (the matrix has 3 HAVE, 1 GAP cells
    across a 2x2 grid → 4 total)."""
    cards = {"type": "cards", "items": card_items}
    matrix = {
        "type": "matrix",
        "id": "cov",
        "rows": ["A", "B"],
        "columns": ["X", "Y"],
        "cells": [
            {"row": "A", "col": "X", "badge": "HAVE"},
            {"row": "A", "col": "Y", "badge": "HAVE"},
            {"row": "B", "col": "X", "badge": "HAVE"},
            {"row": "B", "col": "Y", "badge": "GAP"},
        ],
    }
    return parse_report(
        make_report(
            blocks=[cards, matrix],
            badges={
                "HAVE": {"label": "Have", "tone": "green", "legend": "covered"},
                "GAP": {"label": "Gap", "tone": "red", "legend": "missing"},
                # declared but never placed in the matrix — a derived card counting it must show 0
                "PENDING": {"label": "Pending", "tone": "blue", "legend": "not started"},
            },
        )
    )


def test_derived_card_counts_a_matrix_state_with_chip_on_top() -> None:
    html = render_html(_matrix_with_cards([{"badge": "HAVE", "of_matrix": "cov"}]))

    # border + chip both take the badge's palette colour; value 3 of 4 = 75.0%, label from the badge
    assert (
        '<div class="card green"><span class="chip green cbadge">Have</span>'
        '<div class="n">3<span class="pct">75.0%</span></div></div>'
    ) in html


def test_derived_card_counts_zero_when_the_state_is_absent_from_the_matrix() -> None:
    html = render_html(_matrix_with_cards([{"badge": "PENDING", "of_matrix": "cov"}]))

    # PENDING is declared but appears in no cell → count 0 of 4 = 0.0%
    assert (
        '<div class="card blue"><span class="chip blue cbadge">Pending</span>'
        '<div class="n">0<span class="pct">0.0%</span></div></div>'
    ) in html


def test_derived_card_label_override_and_note_render() -> None:
    html = render_html(
        _matrix_with_cards([{"badge": "GAP", "of_matrix": "cov", "label": "Blocked", "note": "escalate"}])
    )

    # GAP appears once (1 of 4 = 25.0%); the label overrides the badge label; the note renders
    assert (
        '<div class="card red"><span class="chip red cbadge">Blocked</span>'
        '<div class="n">1<span class="pct">25.0%</span></div><div class="note">escalate</div></div>'
    ) in html


def test_derived_card_resolves_a_matrix_nested_in_a_section() -> None:
    """`of_matrix` resolves across the whole block tree — a top-level summary card can count a matrix
    that lives inside a section (the iter_matrices recursion), and an id-less matrix
    elsewhere on the page does not interfere with the count."""
    decoy = {  # id-less, all HAVE — would inflate the count if wrongly tallied
        "type": "matrix",
        "rows": ["A"],
        "columns": ["X", "Y"],
        "cells": [{"row": "A", "col": "X", "badge": "HAVE"}, {"row": "A", "col": "Y", "badge": "HAVE"}],
    }
    section = {
        "type": "section",
        "title": "Detail",
        "blocks": [
            {
                "type": "matrix",
                "id": "cov",
                "rows": ["A", "B"],
                "columns": ["X", "Y"],
                "cells": [
                    {"row": "A", "col": "X", "badge": "HAVE"},
                    {"row": "B", "col": "Y", "badge": "GAP"},
                ],
            }
        ],
    }
    cards = {"type": "cards", "items": [{"badge": "HAVE", "of_matrix": "cov"}]}
    report = parse_report(
        make_report(
            blocks=[cards, decoy, section],
            badges={
                "HAVE": {"label": "Have", "tone": "green", "legend": "x"},
                "GAP": {"label": "Gap", "tone": "red", "legend": "y"},
            },
        )
    )

    html = render_html(report)

    # counts only the id'd "cov" matrix (1 HAVE of 4), NOT the id-less decoy's 2 HAVE
    assert (
        '<span class="chip green cbadge">Have</span><div class="n">1<span class="pct">25.0%</span></div>'
        in html
    )


def _tables_with_summary_cards(card_items: list[dict[str, object]]) -> Report:
    """A page with derived summary cards over two rollup tables — tier1 (2 HAVE, 1 GAP) and tier2
    (1 HAVE, 1 GAP) → 3 HAVE, 2 GAP across 5 rows total."""
    cards = {"type": "cards", "items": card_items}

    def _table(tid: str, rows: list[dict[str, str]]) -> dict[str, object]:
        return {
            "type": "table",
            "id": tid,
            "columns": [
                {"key": "item", "label": "Item", "kind": "text"},
                {"key": "st", "label": "", "kind": "badge"},
            ],
            "rollup": {"by": "st"},
            "rows": rows,
        }

    return parse_report(
        make_report(
            blocks=[
                cards,
                _table(
                    "tier1",
                    [{"item": "a", "st": "HAVE"}, {"item": "b", "st": "HAVE"}, {"item": "c", "st": "GAP"}],
                ),
                _table("tier2", [{"item": "d", "st": "HAVE"}, {"item": "e", "st": "GAP"}]),
            ],
            badges={
                "HAVE": {"label": "Have", "tone": "green", "legend": "covered"},
                "GAP": {"label": "Gap", "tone": "red", "legend": "missing"},
            },
        )
    )


def test_of_tables_card_sums_a_badge_across_the_named_tables() -> None:
    html = render_html(_tables_with_summary_cards([{"badge": "HAVE", "of_tables": ["tier1", "tier2"]}]))

    # 3 HAVE rows (2 in tier1 + 1 in tier2) over 5 rows total = 60.0%; chip/label/border from the badge
    assert (
        '<div class="card green"><span class="chip green cbadge">Have</span>'
        '<div class="n">3<span class="pct">60.0%</span></div></div>'
    ) in html


def test_of_tables_card_counting_one_table_matches_that_tables_rollup() -> None:
    # a single-table of_tables is the same count as the table's own rollup (1 GAP of 3 rows = 33.3%)
    html = render_html(_tables_with_summary_cards([{"badge": "GAP", "of_tables": ["tier1"]}]))

    assert (
        '<div class="card red"><span class="chip red cbadge">Gap</span>'
        '<div class="n">1<span class="pct">33.3%</span></div></div>'
    ) in html


def _table_block(tid: str | None, rows: list[dict[str, str]], *, rollup: bool = True) -> dict[str, object]:
    block: dict[str, object] = {
        "type": "table",
        "columns": [
            {"key": "item", "label": "Item", "kind": "text"},
            {"key": "st", "label": "", "kind": "badge"},
        ],
        "rows": rows,
    }
    if tid is not None:
        block["id"] = tid
    if rollup:
        block["rollup"] = {"by": "st"}
    return block


def test_of_tables_card_counts_zero_when_the_badge_is_absent_everywhere() -> None:
    report = parse_report(
        make_report(
            blocks=[
                {"type": "cards", "items": [{"badge": "PENDING", "of_tables": ["tier1"]}]},
                _table_block("tier1", [{"item": "a", "st": "HAVE"}, {"item": "b", "st": "GAP"}]),
            ],
            badges={
                "HAVE": {"label": "Have", "tone": "green", "legend": "x"},
                "GAP": {"label": "Gap", "tone": "red", "legend": "y"},
                "PENDING": {"label": "Pending", "tone": "blue", "legend": "z"},  # declared, in no row
            },
        )
    )

    html = render_html(report)

    assert (
        '<div class="card blue"><span class="chip blue cbadge">Pending</span>'
        '<div class="n">0<span class="pct">0.0%</span></div></div>'
    ) in html


def test_of_tables_resolves_nested_tables_counts_blanks_in_the_denominator_and_ignores_decoys() -> None:
    """The referenced tables live inside a section (iter_tables recurses); a blank-status row counts
    toward the denominator but no badge; and neither an id-less table nor an id'd table with no rollup
    (both unreferenced decoys) contributes to the count."""
    section = {
        "type": "section",
        "title": "Tiers",
        "blocks": [
            # tier1: 2 HAVE + 1 blank status → HAVE 2 of 3 rows
            _table_block(
                "tier1", [{"item": "a", "st": "HAVE"}, {"item": "b", "st": "HAVE"}, {"item": "c", "st": ""}]
            ),
            _table_block("tier2", [{"item": "d", "st": "HAVE"}, {"item": "e", "st": "GAP"}]),  # HAVE 1 of 2
        ],
    }
    report = parse_report(
        make_report(
            blocks=[
                {"type": "cards", "items": [{"badge": "HAVE", "of_tables": ["tier1", "tier2"]}]},
                section,
                _table_block(None, [{"item": "x", "st": "HAVE"}]),  # id-less decoy → skipped
                _table_block(
                    "norollup", [{"item": "y", "st": "HAVE"}], rollup=False
                ),  # rollup-less decoy → skipped
            ],
            badges={
                "HAVE": {"label": "Have", "tone": "green", "legend": "x"},
                "GAP": {"label": "Gap", "tone": "red", "legend": "y"},
            },
        )
    )

    html = render_html(report)

    # HAVE = 3 (2 in tier1 + 1 in tier2) over 5 rows (tier1's blank row is in the denominator) = 60.0%;
    # the two decoys would push the count higher if wrongly tallied
    assert (
        '<div class="card green"><span class="chip green cbadge">Have</span>'
        '<div class="n">3<span class="pct">60.0%</span></div></div>'
    ) in html


def test_badge_row_reference_renders_declared_chip() -> None:
    report = parse_report(
        make_report(
            badges={"PROD": {"label": "prod", "tone": "violet", "legend": "l"}},
            blocks=[{"type": "badge_row", "items": [{"key": "PROD"}]}],
        )
    )

    html = render_html(report)

    assert '<span class="chip violet">prod</span>' in html


def test_badge_row_groups_render_as_a_labelled_gutter_dl() -> None:
    block = {
        "type": "badge_row",
        "groups": [
            {"label": "Severity", "items": [{"label": "High", "tone": "red"}]},
            {"label": "Area", "items": [{"label": "API", "tone": "blue"}]},
        ],
    }

    html = render_html(parse_report(make_report(blocks=[block])))

    assert (
        '<dl class="badge-groups">'
        '<dt>Severity</dt><dd><span class="chip red">High</span></dd>'
        '<dt>Area</dt><dd><span class="chip blue">API</span></dd>'
        "</dl>" in html
    )
    assert 'class="badge-row"' not in html  # grouped mode does not also emit the flat row


def test_badge_row_group_renders_multiple_chips_in_order() -> None:
    """A group with more than one chip renders them all, in order, inside its dd."""
    block = {
        "type": "badge_row",
        "groups": [
            {"label": "Mix", "items": [{"label": "A", "tone": "blue"}, {"label": "B", "tone": "red"}]}
        ],
    }

    html = render_html(parse_report(make_report(blocks=[block])))

    assert '<dt>Mix</dt><dd><span class="chip blue">A</span><span class="chip red">B</span></dd>' in html


def test_badge_row_grouped_reference_feeds_the_auto_legend() -> None:
    """A ref inside a group must reach the same walker as a flat ref, so its legend meaning renders."""
    report = parse_report(
        make_report(
            badges={"HIGH": {"label": "high", "tone": "red", "legend": "urgent"}},
            blocks=[{"type": "badge_row", "groups": [{"label": "Sev", "items": [{"key": "HIGH"}]}]}],
        )
    )

    html = render_html(report)

    assert "Legend: badges used on this page" in html
    assert "urgent" in html  # the grouped ref's legend meaning shows


def test_badge_row_flat_items_still_render_the_ungrouped_row() -> None:
    block = {"type": "badge_row", "label": "Affects:", "items": [{"label": "X", "tone": "amber"}]}

    html = render_html(parse_report(make_report(blocks=[block])))

    assert (
        '<div class="badge-row"><span class="label">Affects:</span>'
        '<span class="chip amber">X</span></div>' in html
    )
    assert 'class="badge-groups"' not in html


def test_pct_clamps_tiny_nonzero_to_marker() -> None:
    from skaldr.compute import pct

    assert pct(3, 10000) == "<0.1%"
    assert pct(0, 10000) == "0.0%"


def test_fmt_rounds_float_noise() -> None:
    from skaldr.compute import fmt

    assert fmt(100.00000000000001) == "100"
    assert fmt(-1240) == "-1,240"


def test_legend_renders_at_top_when_no_table() -> None:
    report = parse_report(
        make_report(
            badges={"P": {"label": "prod", "tone": "violet", "legend": "l"}},
            blocks=[{"type": "badge_row", "items": [{"key": "P"}]}],
        )
    )

    html = render_html(report)

    assert "Legend: badges used on this page" in html


def test_badge_with_legend_false_chips_but_stays_out_of_the_legend() -> None:
    report = parse_report(
        make_report(
            badges={
                "KEEP": {"label": "keep", "tone": "blue", "legend": "explained"},
                "ONEOFF": {"label": "oneoff", "tone": "amber", "legend": False},
            },
            blocks=[{"type": "badge_row", "items": [{"key": "KEEP"}, {"key": "ONEOFF"}]}],
        )
    )

    html = render_html(report)

    assert '<span class="chip amber">oneoff</span>' in html  # the one-off chip still renders
    assert "explained" in html  # the legend still lists the badge that has one
    assert html.count('class="legend-row"') == 1  # exactly one legend entry — ONEOFF is excluded
