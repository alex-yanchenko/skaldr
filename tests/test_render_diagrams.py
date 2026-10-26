from typing import get_args

import pytest

from skaldr import compute
from skaldr.models import StatusState, parse_report
from skaldr.render import render_html
from tests.factories import make_cell, make_grid, make_report


def test_flow_arrow_leading_connectors_never_dangle() -> None:
    """The connector sits inside the seg, BEFORE the node, so it wraps with its node and never trails
    at a line end. The first seg carries no connector; every later seg opens with one."""
    block = {"type": "flow", "steps": [{"label": "A"}, {"label": "B"}, {"label": "C"}]}

    html = render_html(parse_report(make_report(blocks=[block])))

    assert '<div class="flow arrow">' in html
    assert '<span class="seg"><span class="node">' in html  # first seg: no connector
    assert html.count('<span class="seg"><span class="conn"></span><span class="node">') == 2  # B, C
    assert html.count('class="conn"') == 2  # exactly len(steps) - 1
    assert '<div class="loop">' not in html  # no loop marker unless loop: true


def test_flow_arrow_numbers_and_tones_each_node() -> None:
    block = {"type": "flow", "steps": [{"label": "A", "tone": "info"}, {"label": "B", "tone": "success"}]}

    html = render_html(parse_report(make_report(blocks=[block])))

    # tone and number bound to the SAME node, so a decoupling bug can't pass vacuously
    assert '<span class="node info"><span class="n">1</span>' in html
    assert '<span class="node success"><span class="n">2</span>' in html


def test_flow_arrow_note_renders_as_a_sub_line() -> None:
    block = {"type": "flow", "steps": [{"label": "A", "note": "detail"}, {"label": "B"}]}

    html = render_html(parse_report(make_report(blocks=[block])))

    assert '<span class="sub">detail</span>' in html


@pytest.mark.parametrize("style", ["arrow", "steps"])
def test_flow_numbered_false_omits_the_number_bubbles(style: str) -> None:
    block = {"type": "flow", "style": style, "numbered": False, "steps": [{"label": "A"}, {"label": "B"}]}

    html = render_html(parse_report(make_report(blocks=[block])))

    assert '<span class="n">' not in html


def test_flow_steps_style_renders_caption_cards_with_a_leading_blank_spacer() -> None:
    block = {
        "type": "flow",
        "style": "steps",
        "steps": [{"label": "A", "note": "first note"}, {"label": "B"}],
    }

    html = render_html(parse_report(make_report(blocks=[block])))

    assert '<div class="flow steps">' in html
    assert html.count('class="link blank"') == 1  # ONLY the first card gets the hidden spacer
    assert '<span class="link"></span>' in html  # the second step has a real (non-blank) link
    assert '<div class="cap">first note</div>' in html


def test_flow_steps_style_tones_and_numbers_each_card() -> None:
    """The steps branch has its own tone/number template guards, distinct from the arrow branch."""
    block = {"type": "flow", "style": "steps", "steps": [{"label": "A", "tone": "warning"}, {"label": "B"}]}

    html = render_html(parse_report(make_report(blocks=[block])))

    assert '<div class="card warning"><span class="n">1</span>' in html  # tone + number, bound to the card
    assert '<span class="n">2</span>' in html


def test_flow_loop_marker_names_the_first_node() -> None:
    block = {"type": "flow", "loop": True, "steps": [{"label": "Flag"}, {"label": "Close"}]}

    html = render_html(parse_report(make_report(blocks=[block])))

    assert '<div class="loop"><span class="cyc">↺</span> back to Flag</div>' in html


def test_flow_steps_style_renders_points_as_rich_text_bullets_under_the_card() -> None:
    block = {
        "type": "flow",
        "style": "steps",
        "steps": [
            {"label": "Reason", "note": "the caption", "points": ["Weighs **overlap**", "Scores hits"]},
            {"label": "Deliver"},
        ],
    }

    html = render_html(parse_report(make_report(blocks=[block])))

    # bullets render after the caption, in order, with inline rich text applied
    assert '<div class="cap">the caption</div><ul class="pts">' in html
    assert '<ul class="pts"><li>Weighs <strong>overlap</strong></li><li>Scores hits</li></ul>' in html


def test_flow_steps_card_orders_caption_then_points_then_badges() -> None:
    """Locks the render order inside a card: note → points → badges (a swap would be silent otherwise)."""
    badges = {"OK": {"label": "OK", "tone": "green", "legend": "fine"}}
    block = {
        "type": "flow",
        "style": "steps",
        "steps": [
            {"label": "A", "note": "cap", "points": ["p1"], "badges": ["OK"]},
            {"label": "B"},
        ],
    }

    html = render_html(parse_report(make_report(badges=badges, blocks=[block])))

    assert (
        '<div class="cap">cap</div><ul class="pts"><li>p1</li></ul>'
        '<span class="chips"><span class="chip green">OK</span></span>' in html
    )


def test_flow_arrow_style_still_renders_points_inside_the_node() -> None:
    """Points aren't a steps-only feature — an arrow node carries them too (compact), never dropped."""
    block = {"type": "flow", "steps": [{"label": "A", "points": ["one", "two"]}, {"label": "B"}]}

    html = render_html(parse_report(make_report(blocks=[block])))

    assert '<span class="lab">A</span><ul class="pts"><li>one</li><li>two</li></ul>' in html


def test_flow_step_without_points_emits_no_pts_list() -> None:
    block = {"type": "flow", "steps": [{"label": "A"}, {"label": "B"}]}

    html = render_html(parse_report(make_report(blocks=[block])))

    assert 'class="pts"' not in html


def test_fan_node_carries_points() -> None:
    """Fan hub/spokes are FlowStep too, so points render there rather than silently vanishing."""
    block = {
        "type": "fan",
        "direction": "in",
        "hub": {"label": "Hub", "points": ["synthesised"]},
        "spokes": [{"label": "S1"}, {"label": "S2"}],
    }

    html = render_html(parse_report(make_report(blocks=[block])))

    assert '<span class="lab">Hub</span><ul class="pts"><li>synthesised</li></ul>' in html


def test_fan_in_puts_spokes_before_the_hub_with_a_converging_arrow() -> None:
    block = {
        "type": "fan",
        "direction": "in",
        "hub": {"label": "Record", "tone": "accent"},
        "spokes": [{"label": "A", "tone": "info"}, {"label": "B", "note": "nightly"}],
    }

    html = render_html(parse_report(make_report(blocks=[block])))

    assert '<div class="fan in">' in html
    # spokes well, then the arrow, then the hub — DOM order is the flow direction
    assert (
        '<div class="spokes"><div class="fnode info"><span class="lab">A</span></div>'
        '<div class="fnode"><span class="lab">B</span><span class="sub">nightly</span></div></div>'
        '<div class="merge"><span class="arw">→</span></div>'
        '<div class="hub"><div class="fnode accent"><span class="lab">Record</span></div></div>' in html
    )


def test_fan_out_puts_the_hub_first_then_the_full_spokes_well() -> None:
    block = {
        "type": "fan",
        "direction": "out",
        "hub": {"label": "Request"},
        "spokes": [{"label": "svc-a"}, {"label": "svc-b"}],
    }

    html = render_html(parse_report(make_report(blocks=[block])))

    assert '<div class="fan out">' in html
    assert (
        '<div class="hub"><div class="fnode"><span class="lab">Request</span></div></div>'
        '<div class="merge"><span class="arw">→</span></div>'
        '<div class="spokes"><div class="fnode"><span class="lab">svc-a</span></div>'
        '<div class="fnode"><span class="lab">svc-b</span></div></div>' in html
    )


def test_fan_badges_on_hub_and_a_spoke_both_render_and_feed_the_legend() -> None:
    badges = {"OK": {"label": "OK", "tone": "green", "legend": "fine"}}
    block = {
        "type": "fan",
        "hub": {"label": "H", "badges": ["OK"]},
        "spokes": [{"label": "A", "badges": ["OK"]}, {"label": "B"}],
    }

    html = render_html(parse_report(make_report(badges=badges, blocks=[block])))

    # one chip on the hub, one on spoke A — the spoke-badge iteration is exercised, not just the hub
    assert html.count('<span class="chips"><span class="chip green">OK</span></span>') == 2
    assert "Legend: badges used on this page" in html


def test_fan_inside_a_grid_cell_renders() -> None:
    block = {"type": "fan", "hub": {"label": "H"}, "spokes": [{"label": "A"}, {"label": "B"}]}
    grid = make_grid([make_cell(6, [block])])

    html = render_html(parse_report(make_report(blocks=[grid])))

    assert '<div class="cell span-6">' in html
    assert '<div class="fan in">' in html
    assert '<div class="spokes"><div class="fnode"><span class="lab">A</span></div>' in html
    assert '<div class="hub"><div class="fnode"><span class="lab">H</span></div></div>' in html


def test_walkthrough_renders_numbered_toned_steps_beside_their_detail() -> None:
    block = {
        "type": "walkthrough",
        "steps": [
            {
                "label": "First",
                "sub": "lead-in",
                "tone": "info",
                "detail": [{"type": "text", "body": "do a"}],
            },
            {"label": "Second", "detail": [{"type": "text", "body": "do b"}]},
        ],
    }

    html = render_html(parse_report(make_report(blocks=[block])))

    # default step_span 2 → title column 2fr, detail 4fr, set inline
    assert '<div class="walk" style="grid-template-columns:minmax(120px,2fr) 4fr">' in html
    # step 1: tone class on the step, derived number 1, wrapping label, sub-label
    assert (
        '<div class="wstep info"><span class="wnum">1</span><span class="wlabel">First'
        '<span class="wsub">lead-in</span></span></div>'
        '<div class="wdetail"><p class="text">do a</p></div>' in html
    )
    # step 2: no tone class, number 2, no sub
    assert (
        '<div class="wstep"><span class="wnum">2</span><span class="wlabel">Second</span></div>'
        '<div class="wdetail"><p class="text">do b</p></div>' in html
    )


def test_walkthrough_numeral_is_tone_independent_and_tone_drives_the_step_accent() -> None:
    """A numeral is the same legible muted grey on every step regardless of tone, so an untoned step
    can't drop beside toned ones; the tone instead drives an inline-start accent on the step. The
    accent lives on `.wstep` (which carries the tone class), never on the numeral."""
    block = {
        "type": "walkthrough",
        "steps": [
            {"label": "toned", "tone": "info", "detail": [{"type": "text", "body": "a"}]},
            {"label": "plain", "detail": [{"type": "text", "body": "b"}]},
        ],
    }

    html = render_html(parse_report(make_report(blocks=[block])))

    # the tone class rides the step (which owns the accent), not the numeral — untoned gets no class
    assert '<div class="wstep info"><span class="wnum">1</span>' in html
    assert '<div class="wstep"><span class="wnum">2</span>' in html
    # the numeral is a flat legible muted, never a tone var, so tone can't recolour or fade it
    assert ".walk .wnum{" in html
    assert "color:var(--muted)}" in html
    assert "color:var(--wt" not in html
    # the rail is always present (defaults to a quiet --rule); tone only changes its colour, so an
    # untoned step keeps its rail and a mixed-tone walkthrough never has some steps railless.
    assert "border-inline-start:3px solid var(--wt,var(--rule))" in html
    assert "var(--wt,transparent)" not in html


def test_a_status_list_reads_its_glyphs_from_the_shared_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    states = get_args(StatusState)
    rows = {state: compute.StatusGlyph(f"page-{state}", f"export-{state}") for state in states}
    monkeypatch.setattr(compute, "STATUS_GLYPHS", rows)
    block = {"type": "status_list", "items": [{"state": "blocked", "text": "Vendor"}]}

    html = render_html(parse_report(make_report(blocks=[block])))

    assert (
        '<ul class="status-list"><li class="blocked"><span class="glyph">page-blocked</span>'
        "<span>Vendor</span></li></ul>"
    ) in html


def test_walkthrough_step_detail_can_hold_a_two_column_grid() -> None:
    block = {
        "type": "walkthrough",
        "steps": [
            {
                "label": "Deploy",
                "detail": [
                    {
                        "type": "grid",
                        "cells": [
                            {"span": 3, "blocks": [{"type": "text", "body": "Action"}]},
                            {"span": 3, "blocks": [{"type": "code", "content": "deploy.sh"}]},
                        ],
                    }
                ],
            }
        ],
    }

    html = render_html(parse_report(make_report(blocks=[block])))

    assert '<div class="wdetail"><div class="grid">' in html
    assert "<pre>deploy.sh</pre>" in html


def test_walkthrough_step_span_sets_the_column_widths() -> None:
    block = {
        "type": "walkthrough",
        "step_span": 3,
        "steps": [{"label": "S", "detail": [{"type": "text", "body": "x"}]}],
    }

    html = render_html(parse_report(make_report(blocks=[block])))

    assert '<div class="walk" style="grid-template-columns:minmax(120px,3fr) 3fr">' in html


def test_walkthrough_detail_renders_the_full_nested_block_list() -> None:
    block = {
        "type": "walkthrough",
        "steps": [
            {
                "label": "S",
                "detail": [
                    {"type": "list", "items": ["one", "two"]},
                    {"type": "code", "label": "k", "content": "x = 1"},
                ],
            }
        ],
    }

    html = render_html(parse_report(make_report(blocks=[block])))

    # the detail column hosts real rendered blocks, not rich text
    assert '<ul class="list"><li>one</li><li>two</li></ul>' in html
    assert '<div class="code"><div class="code-label">k</div><pre>x = 1</pre></div>' in html


def test_walkthrough_heading_in_a_step_detail_gets_a_slug_id() -> None:
    block = {
        "type": "walkthrough",
        "steps": [{"label": "S", "detail": [{"type": "heading", "level": 3, "text": "Nested step note"}]}],
    }

    html = render_html(parse_report(make_report(blocks=[block])))

    # anchor_slugs recurses into step details, so the nested heading gets an anchorable id
    assert '<h3 id="nested-step-note">Nested step note</h3>' in html


def test_container_badges_render_chips_on_card_timeline_and_flow() -> None:
    badges = {"OK": {"label": "OK", "tone": "green", "legend": "fine"}}
    blocks = [
        {"type": "cards", "items": [{"label": "A", "value": 1, "badges": ["OK"]}]},
        {"type": "timeline", "items": [{"title": "T", "badges": ["OK"]}]},
        {"type": "flow", "steps": [{"label": "A", "badges": ["OK"]}, {"label": "B"}]},
    ]

    html = render_html(parse_report(make_report(badges=badges, blocks=blocks)))

    # a chip renders inside each of the three containers
    assert html.count('<span class="chips"><span class="chip green">OK</span></span>') == 3
    # and a container badge now feeds the auto-legend — the "dead badge" wart, inverted
    assert "Legend: badges used on this page" in html


def test_timeline_dot_uses_the_rule_token_not_a_hardcoded_color() -> None:
    html = render_html(parse_report(make_report()))

    assert "background:var(--rule); box-shadow:0 0 0 3px var(--page)}" in html


@pytest.mark.parametrize(
    ("state", "glyph"),
    [("done", "✓"), ("current", "◐"), ("pending", "○"), ("failed", "✗"), ("blocked", "⏸")],
)
def test_status_list_glyph_for_every_state(state: str, glyph: str) -> None:
    block = {"type": "status_list", "items": [{"state": state, "text": "x"}]}

    html = render_html(parse_report(make_report(blocks=[block])))

    assert f'<li class="{state}"><span class="glyph">{glyph}</span><span>x</span></li>' in html


def test_status_list_current_glyph_is_info_toned() -> None:
    """The in-progress state mirrors the timeline's `current` marker — an info-toned ◐."""
    block = {"type": "status_list", "items": [{"state": "current", "text": "x"}]}

    html = render_html(parse_report(make_report(blocks=[block])))

    assert "& .current .glyph{color:var(--info-fg)}" in html


def test_timeline_item_without_state_or_time_renders() -> None:
    block = {"type": "timeline", "items": [{"title": "just a title"}]}
    report = parse_report(make_report(blocks=[block]))

    html = render_html(report)

    assert '<div class="ti">just a title</div>' in html
    assert '<div class="time">' not in html
