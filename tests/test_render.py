import base64
import hashlib
import re

import pytest

from skaldr.errors import ReportError
from skaldr.models import Report, load_report, package_path, parse_report
from skaldr.render import (
    extract_source,
    find_placeholders,
    render_embed,
    render_html,
    render_richtext,
)
from tests.conftest import REPO_ROOT
from tests.factories import make_cell, make_grid, make_reconciled_table, make_report, make_table

GOLDEN = REPO_ROOT / "tests" / "golden" / "example.html"

# The three color-scheme rules that drive every light-dark() token. They must render unlayered (see
# test_host_override_essentials_sit_outside_any_layer); asserted by literal so a reformat fails loudly.
COLOR_SCHEME_RULES = (
    ":root{color-scheme:light dark}",
    ':root[data-theme="dark"]{color-scheme:dark}',
    ':root[data-theme="light"]{color-scheme:light}',
)
# Rules that MUST stay unlayered so an embedding host's own unlayered reset can't override them: the
# color-scheme rules, box-sizing (every component assumes border-box), and body's colour/background
# (else skaldr's dark panels keep the host's dark text → invisible). Asserted by literal.
UNLAYERED_ESSENTIALS = (
    *COLOR_SCHEME_RULES,
    "*,*::before,*::after{box-sizing:border-box}",
    "body{font-family:var(--sans); color:var(--ink); background:var(--page)",
    # print forces white --paper; unlayered so it beats the base body rule above (a layered one wouldn't)
    "@media print{body{background:var(--paper)}}",
)


def test_example_render_matches_golden() -> None:
    """Pins the full page. On an intended change, regenerate with:
    uv run skaldr data/example.yaml -o tests/golden/example.html
    and review the HTML diff in the PR."""
    report = load_report(REPO_ROOT / "data" / "example.yaml")

    assert render_html(report) == GOLDEN.read_text(encoding="utf-8")


def test_sales_example_renders_and_reconciles() -> None:
    """Guards the sales-flavoured example shipped for non-dev onboarding — it must stay valid."""
    report = load_report(REPO_ROOT / "examples" / "sales-pipeline.yaml")

    html = render_html(report)

    assert html.startswith("<!doctype html>")
    assert "Q3 Pipeline Review — West Region" in html
    assert "Reconciles: 120 = 120." in html


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
    assert "Legend — badges used on this page" in html


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
    assert "border-inline-start:3px solid var(--wt,transparent)" in html


def test_callout_body_splits_blank_line_paragraphs() -> None:
    block = {"type": "callout", "tone": "info", "body": "First para.\n\nSecond para."}

    html = render_html(parse_report(make_report(blocks=[block])))

    assert '<p class="prose-p">First para.</p><p class="prose-p">Second para.</p>' in html


def test_single_paragraph_callout_stays_inline_without_a_paragraph_wrapper() -> None:
    block = {"type": "callout", "tone": "info", "body": "Just one line."}

    html = render_html(parse_report(make_report(blocks=[block])))

    assert "<div>Just one line.</div>" in html
    assert '<p class="prose-p">' not in html  # no paragraph wrapper emitted for a single paragraph


def test_quote_body_splits_blank_line_paragraphs() -> None:
    block = {"type": "quote", "body": "Line one.\n\nLine two.", "cite": "src"}

    html = render_html(parse_report(make_report(blocks=[block])))

    assert '<p class="prose-p">Line one.</p><p class="prose-p">Line two.</p>' in html


def test_check_list_renders_tickable_boxes_honoring_the_checked_flag() -> None:
    block = {"type": "list", "style": "check", "items": ["todo", {"text": "done", "checked": True}]}

    html = render_html(parse_report(make_report(blocks=[block])))

    assert '<ul class="list check">' in html
    assert '<li><label class="chk"><input type="checkbox"><span>todo</span></label></li>' in html
    assert '<li><label class="chk"><input type="checkbox" checked><span>done</span></label></li>' in html


def test_check_list_nests_checkboxes_at_every_level() -> None:
    block = {"type": "list", "style": "check", "items": [{"text": "parent", "items": ["child"]}]}

    html = render_html(parse_report(make_report(blocks=[block])))

    assert '<span>parent</span></label><ul class="list check"><li><label class="chk">' in html


def test_bullet_list_has_no_checkboxes() -> None:
    block = {"type": "list", "items": ["a"]}

    html = render_html(parse_report(make_report(blocks=[block])))

    assert '<ul class="list"><li>a</li></ul>' in html
    assert 'type="checkbox"' not in html  # only a check-style list emits inputs


def test_def_list_renders_terms_and_rich_multi_paragraph_bodies() -> None:
    block = {
        "type": "def_list",
        "items": [{"term": "Action", "body": "Click **Deploy**."}, {"term": "Say", "body": "One.\n\nTwo."}],
    }

    html = render_html(parse_report(make_report(blocks=[block])))

    assert '<dl class="deflist"><dt>Action</dt><dd>Click <strong>Deploy</strong>.</dd>' in html
    assert '<dt>Say</dt><dd><p class="prose-p">One.</p><p class="prose-p">Two.</p></dd></dl>' in html


def test_note_renders_optional_title_and_body() -> None:
    titled = {"type": "note", "title": "Read aloud", "body": "Speak softly."}
    plain = {"type": "note", "body": "Just an aside."}

    html = render_html(parse_report(make_report(blocks=[titled, plain])))

    assert (
        '<div class="note-block"><div class="note-block-title">Read aloud</div>'
        "<div>Speak softly.</div></div>" in html
    )
    assert '<div class="note-block"><div>Just an aside.</div></div>' in html


def test_panel_renders_a_titled_card_holding_its_blocks() -> None:
    block = {"type": "panel", "title": "Slide 1", "blocks": [{"type": "text", "body": "Point."}]}

    html = render_html(parse_report(make_report(blocks=[block])))

    assert (
        '<div class="panel-card"><div class="panel-card-hd">Slide 1</div><div class="panel-card-body">'
        in html
    )
    assert '<p class="text">Point.</p></div></div>' in html


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


def test_anchor_link_resolves_to_a_heading_inside_a_panel() -> None:
    # proves the anchor walker recurses into a panel; without it the #link would fail as dangling
    blocks = [
        {"type": "panel", "title": "Deck", "blocks": [{"type": "heading", "text": "Inside", "id": "inside"}]},
        {"type": "text", "body": "Jump [in](#inside)."},
    ]

    html = render_html(parse_report(make_report(blocks=blocks)))

    assert '<a href="#inside">in</a>' in html


def test_badge_referenced_only_inside_a_panel_still_feeds_the_legend() -> None:
    # proves the badge walker recurses into a panel; without it this would be an undeclared-reference error
    report = parse_report(
        make_report(
            badges={"P": {"label": "prod", "tone": "blue", "legend": "the prod tag"}},
            blocks=[
                {"type": "panel", "title": "Deck", "blocks": [{"type": "badge_row", "items": [{"key": "P"}]}]}
            ],
        )
    )

    html = render_html(report)

    assert "the prod tag" in html  # legend picked up the panel-nested reference


def test_footnote_reference_inside_a_panel_is_numbered_and_backlinked() -> None:
    # proves iter_reference_items recurses into a panel (footnote numbering + the references list)
    blocks = [
        {
            "type": "panel",
            "title": "Deck",
            "blocks": [
                {"type": "text", "body": "Per the spec[^spec]."},
                {"type": "references", "items": [{"key": "spec", "text": "The spec doc."}]},
            ],
        }
    ]

    html = render_html(parse_report(make_report(blocks=blocks)))

    assert 'href="#ref-spec">[1]</a>' in html  # numbered citation
    assert 'id="ref-spec"' in html  # and the list entry it links to


def test_table_inside_a_panel_still_gets_the_badge_legend_before_it() -> None:
    # proves _iter_tables recurses into a panel (legend placement keys off the first table)
    report = parse_report(
        make_report(
            badges={"P": {"label": "prod", "tone": "blue", "legend": "the prod tag"}},
            blocks=[
                {
                    "type": "panel",
                    "title": "Deck",
                    "blocks": [
                        {
                            "type": "table",
                            "columns": [
                                {"key": "name", "label": "Name", "kind": "text"},
                                {"key": "tag", "label": "", "kind": "badge"},
                            ],
                            "rows": [{"name": "svc", "tag": "P"}],
                        }
                    ],
                }
            ],
        )
    )

    html = render_html(report)

    assert "the prod tag" in html  # legend rendered (placement walks into the panel for the table)
    assert "Legend — badges used on this page" in html


def test_note_body_splits_blank_line_paragraphs() -> None:
    block = {"type": "note", "body": "First aside.\n\nSecond aside."}

    html = render_html(parse_report(make_report(blocks=[block])))

    assert '<p class="prose-p">First aside.</p><p class="prose-p">Second aside.</p>' in html


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


def test_list_renders_nested_sub_items_as_an_indented_child_list() -> None:
    block = {
        "type": "list",
        "items": ["flat", {"text": "parent", "items": ["child a", {"text": "child b", "items": ["deep"]}]}],
    }

    html = render_html(parse_report(make_report(blocks=[block])))

    assert (
        '<ul class="list"><li>flat</li><li>parent'
        '<ul class="list"><li>child a</li><li>child b'
        '<ul class="list"><li>deep</li></ul></li></ul></li></ul>' in html
    )


def test_list_item_object_without_children_emits_no_nested_list() -> None:
    block = {"type": "list", "items": [{"text": "leaf"}]}

    html = render_html(parse_report(make_report(blocks=[block])))

    assert '<ul class="list"><li>leaf</li></ul>' in html  # no empty child <ul></ul>


def test_numbered_list_nests_ordered_children_in_the_parent_style() -> None:
    block = {"type": "list", "style": "number", "items": [{"text": "step", "items": ["sub"]}]}

    html = render_html(parse_report(make_report(blocks=[block])))

    assert '<ol class="list"><li>step<ol class="list"><li>sub</li></ol></li></ol>' in html


def test_list_item_rich_text_is_formatted_at_every_level() -> None:
    block = {"type": "list", "items": [{"text": "**bold** parent", "items": ["*em* child"]}]}

    html = render_html(parse_report(make_report(blocks=[block])))

    assert "<strong>bold</strong> parent" in html
    assert "<em>em</em> child" in html


def test_walkthrough_heading_in_a_step_detail_gets_a_slug_id() -> None:
    block = {
        "type": "walkthrough",
        "steps": [{"label": "S", "detail": [{"type": "heading", "level": 3, "text": "Nested step note"}]}],
    }

    html = render_html(parse_report(make_report(blocks=[block])))

    # anchor_slugs recurses into step details, so the nested heading gets an anchorable id
    assert '<h3 id="nested-step-note">Nested step note</h3>' in html


def test_section_gets_an_anchor_id_and_appears_in_the_toc() -> None:
    report = parse_report(
        make_report(
            meta={"title": "T", "toc": True},
            blocks=[
                {"type": "heading", "text": "Overview"},
                {"type": "section", "title": "Appendix", "blocks": [{"type": "text", "body": "x"}]},
            ],
        )
    )

    html = render_html(report)

    # the section is a TOC target: it carries a matching anchor id and a nav link points at it
    assert '<details class="section" id="appendix"' in html
    assert '<a href="#appendix">Appendix</a>' in html
    assert '<a href="#overview">Overview</a>' in html  # heading still linked, in order


def test_section_and_its_inner_heading_both_get_anchor_ids() -> None:
    block = {
        "type": "section",
        "title": "Appendix",
        "collapsed": False,
        "blocks": [{"type": "heading", "level": 3, "text": "Notes"}],
    }

    html = render_html(parse_report(make_report(blocks=[block])))

    assert '<details class="section" id="appendix"' in html
    assert '<h3 id="notes">Notes</h3>' in html  # nested heading still gets its own anchor


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
    assert "Legend — badges used on this page" in html


def test_container_badges_render_on_a_steps_style_flow_node() -> None:
    """The steps branch renders badge chips through a different template arm than the arrow branch."""
    badges = {"OK": {"label": "OK", "tone": "green", "legend": "fine"}}
    block = {"type": "flow", "style": "steps", "steps": [{"label": "A", "badges": ["OK"]}, {"label": "B"}]}

    html = render_html(parse_report(make_report(badges=badges, blocks=[block])))

    assert '<div class="flow steps">' in html
    assert html.count('<span class="chips"><span class="chip green">OK</span></span>') == 1


def test_expand_forces_collapsed_sections_open_for_pdf() -> None:
    section = {"type": "section", "title": "S", "collapsed": True, "blocks": [{"type": "text", "body": "hi"}]}
    report = parse_report(make_report(blocks=[section]))

    # a collapsed section stays closed in the default render, but --pdf renders it open
    assert '<details class="section" id="s"><summary>S</summary>' in render_html(report)
    assert '<details class="section" id="s" open><summary>S</summary>' in render_html(report, expand=True)


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
        '<td class="c"><span></span></td></tr>'
    ) in html
    assert (
        '<tr><th>Picking</th><td class="c blue"><span>R</span></td><td class="c"><span>n/a</span></td></tr>'
    ) in html


def test_matrix_cell_label_overrides_the_badge_label() -> None:
    block = {
        "type": "matrix",
        "rows": ["r"],
        "columns": ["c"],
        "cells": [{"row": "r", "col": "c", "badge": "HAVE", "label": "✓"}],
    }
    report = parse_report(
        make_report(blocks=[block], badges={"HAVE": {"label": "Have", "tone": "green", "legend": "covered"}})
    )

    html = render_html(report)

    assert '<td class="c green"><span>✓</span></td>' in html  # label wins over the badge's own "Have"


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


def test_swimlane_columns_are_fluid_so_a_few_columns_fill_the_width() -> None:
    """Data columns are a minmax(150px, 1fr) track: they share the width evenly with a 150px floor, so
    a few columns fill the page instead of huddling at a fixed 150px."""
    html = render_html(
        parse_report(
            make_report(
                blocks=[
                    {
                        "type": "swimlane",
                        "lanes": ["A"],
                        "columns": ["C1"],
                        "steps": [{"lane": "A", "col": "C1", "n": "1", "label": "x"}],
                    }
                ]
            )
        )
    )

    assert "--swim-col:minmax(150px, 1fr)" in html


def test_swimlane_plain_renders_gutter_labels_and_stacked_tickets() -> None:
    """A groupless swimlane: header + lane rows only (no poke zones), gutter labels, and two steps in
    the same lane/column stacked in one cell with their free-string `n` verbatim. No group caps."""
    block = {
        "type": "swimlane",
        "lanes": ["Eng"],
        "columns": ["S1"],
        "steps": [
            {"lane": "Eng", "col": "S1", "n": "3a", "label": "A"},
            {"lane": "Eng", "col": "S1", "n": "3b", "label": "B"},
        ],
    }

    html = render_html(parse_report(make_report(blocks=[block])))

    assert "grid-template-columns:max-content repeat(1, var(--swim-col))" in html
    assert "grid-template-rows:auto auto" in html  # header + one lane, no poke zones
    assert 'class="swim-gut"' in html and ">Eng</div>" in html
    assert 'class="swim-hlabel"' in html and ">S1</div>" in html
    # both tickets stacked in a single cell, in order
    assert (
        '<div class="swim-tkt"><span class="swim-n">3a</span>'
        '<span class="swim-body"><span class="swim-l">A</span></span></div>'
        '<div class="swim-tkt"><span class="swim-n">3b</span>'
        '<span class="swim-body"><span class="swim-l">B</span></span></div>' in html
    )
    assert 'class="swim-cap' not in html  # no groups → no caps
    assert 'class="swim-vdash"' not in html  # no group splits → no dashed lines


def test_swimlane_grouped_renders_coloured_caps_tints_and_dashed_splits() -> None:
    """MVP spans S1-S2, Beta and GA split S2, GA continues to S3. Caps carry the group's palette class
    and label, cells and header cells carry the group tint, S2's internal splits render as dashes, and
    the split sprint's label is written exactly once."""
    block = {
        "type": "swimlane",
        "lanes": ["R"],
        "columns": ["S1", "S2", "S3"],
        "groups": [
            {"name": "MVP", "color": "blue", "columns": ["S1", "S2"]},
            {"name": "Beta", "color": "amber", "columns": ["S2"]},
            {"name": "GA", "color": "violet", "columns": ["S2", "S3"]},
        ],
        "steps": [
            {"lane": "R", "col": "S1", "n": "1", "label": "a"},
            {"lane": "R", "col": "S2", "group": "Beta", "n": "2", "label": "b"},
            {"lane": "R", "col": "S3", "n": "3", "label": "c"},
        ],
    }

    html = render_html(parse_report(make_report(blocks=[block])))

    assert "grid-template-rows:var(--swim-poke) auto auto var(--swim-pokeb)" in html
    # top caps carry the palette colour class + a dot + the group label; the outermost caps also carry
    # a grey outer edge (MVP leftmost → left, GA rightmost → right) that rounds with the accent corner
    assert 'class="swim-cap blue left"' in html and '<span class="swim-dot"></span>MVP</div>' in html
    assert 'class="swim-cap amber"' in html and '<span class="swim-dot"></span>Beta</div>' in html
    assert 'class="swim-cap violet right"' in html and '<span class="swim-dot"></span>GA</div>' in html
    assert 'class="swim-capb blue left"' in html  # matching bottom cap, same edge
    # the rounded outer frame is drawn on top of the tints
    # GA owns the rightmost column, so the frame squares its right corners to meet GA's right border
    assert 'class="swim-frame sq-right"' in html
    # cells and header cells carry the group tint class
    assert 'class="swim-cell blue"' in html and 'class="swim-cell amber"' in html
    assert 'class="swim-hcell blue"' in html
    # the two S2-internal group splits render as dashed overlays
    assert html.count('class="swim-vdash"') == 2
    # the split sprint's label is written exactly once, spanning its sub-columns
    assert html.count(">S2</div>") == 1
    # the Beta step landed in its resolved sub-column
    assert '<span class="swim-n">2</span><span class="swim-body"><span class="swim-l">b</span></span>' in html


def test_swimlane_adjacent_caps_render_a_poke_solid_but_an_ungrouped_boundary_does_not() -> None:
    """Two groups each owning a whole column render a full-height `poke` solid at the boundary between
    them; a boundary where one side is ungrouped renders a plain (non-poke) solid instead."""
    two_caps = {
        "type": "swimlane",
        "lanes": ["R"],
        "columns": ["S1", "S2"],
        "groups": [
            {"name": "A", "color": "blue", "columns": ["S1"]},
            {"name": "B", "color": "amber", "columns": ["S2"]},
        ],
        "steps": [
            {"lane": "R", "col": "S1", "n": "1", "label": "a"},
            {"lane": "R", "col": "S2", "n": "2", "label": "b"},
        ],
    }
    grouped_then_ungrouped = {
        "type": "swimlane",
        "lanes": ["R"],
        "columns": ["S1", "S2"],
        "groups": [{"name": "A", "color": "blue", "columns": ["S1"]}],
        "steps": [
            {"lane": "R", "col": "S1", "n": "1", "label": "a"},
            {"lane": "R", "col": "S2", "n": "2", "label": "b"},
        ],
    }

    two_caps_html = render_html(parse_report(make_report(blocks=[two_caps])))
    ungrouped_html = render_html(parse_report(make_report(blocks=[grouped_then_ungrouped])))

    assert 'class="swim-vsolid poke"' in two_caps_html
    assert "poke" not in ungrouped_html.split('class="swim-vsolid', 1)[1].split(">", 1)[0]
    assert 'class="swim-vsolid poke"' not in ungrouped_html


def test_swimlane_group_spanning_all_columns_renders_both_edge_classes() -> None:
    """A group covering every column is leftmost AND rightmost, so its cap carries both edge classes."""
    block = {
        "type": "swimlane",
        "lanes": ["R"],
        "columns": ["C1", "C2"],
        "groups": [{"name": "All", "color": "green", "columns": ["C1", "C2"]}],
        "steps": [
            {"lane": "R", "col": "C1", "n": "1", "label": "a"},
            {"lane": "R", "col": "C2", "n": "2", "label": "b"},
        ],
    }

    html = render_html(parse_report(make_report(blocks=[block])))

    assert 'class="swim-cap green left right"' in html
    assert 'class="swim-capb green left right"' in html


def test_swimlane_values_render_a_footer_row_and_lane_and_group_totals() -> None:
    """`value` on steps renders a footer totals row (label + per-column sums), a lane total beside the
    gutter label, and a group total on the cap."""
    block = {
        "type": "swimlane",
        "lanes": ["Brent"],
        "columns": ["S1", "S2"],
        "groups": [{"name": "MVP", "color": "blue", "columns": ["S1", "S2"]}],
        "steps": [
            {"lane": "Brent", "col": "S1", "n": "1", "label": "a", "value": 3},
            {"lane": "Brent", "col": "S2", "n": "2", "label": "b", "value": 5},
        ],
    }

    html = render_html(parse_report(make_report(blocks=[block])))

    # footer row: the "Total" gutter label and each column's sum, each as a swim-tot pill in a cell
    assert '<div class="swim-gut swim-foot-lbl"' in html
    assert html.count('class="swim-foot"') == 2
    assert '<span class="swim-tot">3</span>' in html and '<span class="swim-tot">5</span>' in html
    # lane total (3+5) beside the gutter label AND the MVP cap's group total → two more totals of 8
    assert html.count('<span class="swim-tot">8</span>') == 2


def test_swimlane_without_values_renders_no_footer_or_totals() -> None:
    """No `value` anywhere → no footer row and no inline totals."""
    block = {
        "type": "swimlane",
        "lanes": ["Brent"],
        "columns": ["S1"],
        "groups": [{"name": "MVP", "color": "blue", "columns": ["S1"]}],
        "steps": [{"lane": "Brent", "col": "S1", "n": "1", "label": "a"}],
    }

    html = render_html(parse_report(make_report(blocks=[block])))

    # the .swim-foot/.swim-tot CSS rules are always inlined; assert no rendered ELEMENT carries them
    assert 'class="swim-foot"' not in html
    assert 'class="swim-gut swim-foot-lbl"' not in html
    assert 'class="swim-tot"' not in html


def test_swimlane_step_value_renders_on_the_ticket() -> None:
    """A step's own `value` renders as a trailing compartment on its ticket; a step without one omits it."""
    block = {
        "type": "swimlane",
        "lanes": ["R"],
        "columns": ["C1", "C2"],
        "steps": [
            {"lane": "R", "col": "C1", "n": "1", "label": "sized", "value": 5},
            {"lane": "R", "col": "C2", "n": "2", "label": "unsized"},
        ],
    }

    html = render_html(parse_report(make_report(blocks=[block])))

    # the sized ticket carries its value compartment; exactly one ticket has one
    assert (
        '<span class="swim-body"><span class="swim-l">sized</span></span><span class="swim-tkt-v">5</span>'
        in html
    )
    assert '<span class="swim-l">unsized</span></span></div>' in html
    assert html.count('class="swim-tkt-v"') == 1


def test_swimlane_step_url_links_the_number_and_state_styles_the_ticket() -> None:
    """A step `url` renders the number as a link; `state` adds its emphasis class (`low`/`blocked`);
    the two compose on one step. A `normal` step keeps a <span> number and no state class."""
    block = {
        "type": "swimlane",
        "lanes": ["R"],
        "columns": ["C1", "C2", "C3"],
        "steps": [
            {"lane": "R", "col": "C1", "n": "1", "label": "linked", "url": "https://example.com/PROJ-1"},
            {"lane": "R", "col": "C2", "n": "2", "label": "low-pri", "state": "low"},
            {
                "lane": "R",
                "col": "C3",
                "n": "3",
                "label": "both",
                "url": "https://example.com/PROJ-3",
                "state": "blocked",
            },
        ],
    }

    html = render_html(parse_report(make_report(blocks=[block])))

    assert '<a class="swim-n" href="https://example.com/PROJ-1">1</a>' in html
    assert '<span class="swim-n">2</span>' in html  # no url → plain span, not a link
    assert '<div class="swim-tkt low">' in html  # low-priority step carries the `low` class
    # url + blocked compose: a blocked ticket whose number is a link
    assert '<div class="swim-tkt blocked"><a class="swim-n" href="https://example.com/PROJ-3">3</a>' in html
    # the normal (state-less) step gets no emphasis class
    assert '<div class="swim-tkt">' in html


def test_swimlane_column_sub_renders_and_ids_decouple_reference_from_display() -> None:
    """A column `sub` renders as a caption under the header; with ids, steps reference the id while the
    header shows the display name and the gutter shows the lane's display name."""
    block = {
        "type": "swimlane",
        "lanes": [{"id": "eng", "name": "Engineering"}],
        "columns": [{"id": "s1", "name": "Sprint 1", "sub": "→ MVP demo"}],
        "steps": [{"lane": "eng", "col": "s1", "n": "1", "label": "Build"}],
    }

    html = render_html(parse_report(make_report(blocks=[block])))

    assert '<span class="swim-hsub">→ MVP demo</span>' in html  # caption under the header
    assert ">Sprint 1<span" in html  # header shows the display name, not the id "s1"
    assert ">Engineering</div>" in html  # gutter shows the lane's display name, not "eng"


def test_swimlane_depends_on_renders_a_needs_marker_of_the_dependency_numbers() -> None:
    """`depends_on` renders a marker of the referenced steps' numbers, comma-joined; a step with none
    gets no marker. The "needs " prefix is CSS, so the element text is just the numbers."""
    block = {
        "type": "swimlane",
        "lanes": ["R"],
        "columns": ["C1", "C2", "C3"],
        "steps": [
            {"lane": "R", "col": "C1", "n": "1", "label": "a", "id": "first"},
            {"lane": "R", "col": "C2", "n": "2", "label": "b", "id": "second", "depends_on": ["first"]},
            {"lane": "R", "col": "C3", "n": "3", "label": "c", "depends_on": ["first", "second"]},
        ],
    }

    html = render_html(parse_report(make_report(blocks=[block])))

    assert '<span class="swim-dep">1</span>' in html  # step 2 needs step 1
    assert '<span class="swim-dep">1, 2</span>' in html  # step 3 needs steps 1 and 2
    assert html.count('class="swim-dep"') == 2  # step 1 has no dependency → no marker


@pytest.mark.parametrize(
    "url", ["https://example.com/PROJ-1", "http://example.com/PROJ-1", "mailto:pm@example.com"]
)
def test_swimlane_step_url_accepts_each_safe_scheme(url: str) -> None:
    """All three allowed schemes render the number as a link out to the given url."""
    block = {
        "type": "swimlane",
        "lanes": ["R"],
        "columns": ["C1"],
        "steps": [{"lane": "R", "col": "C1", "n": "1", "label": "a", "url": url}],
    }

    html = render_html(parse_report(make_report(blocks=[block])))

    assert f'<a class="swim-n" href="{url}">1</a>' in html


def test_swimlane_split_column_footer_is_bare_but_normal_footer_is_banded() -> None:
    """A column split across groups renders a bare (bandless) totals row; an unsplit one keeps the band."""
    split = {
        "type": "swimlane",
        "lanes": ["R"],
        "columns": ["S1", "S2"],
        "groups": [
            {"name": "A", "color": "blue", "columns": ["S1", "S2"]},
            {"name": "B", "color": "amber", "columns": ["S2"]},
        ],
        "steps": [
            {"lane": "R", "col": "S1", "n": "1", "label": "a", "value": 2},
            {"lane": "R", "col": "S2", "group": "A", "n": "2", "label": "b", "value": 3},
            {"lane": "R", "col": "S2", "group": "B", "n": "3", "label": "c", "value": 4},
        ],
    }
    unsplit = {
        "type": "swimlane",
        "lanes": ["R"],
        "columns": ["S1", "S2"],
        "groups": [{"name": "A", "color": "blue", "columns": ["S1", "S2"]}],
        "steps": [
            {"lane": "R", "col": "S1", "n": "1", "label": "a", "value": 2},
            {"lane": "R", "col": "S2", "n": "2", "label": "b", "value": 3},
        ],
    }

    split_html = render_html(parse_report(make_report(blocks=[split])))
    unsplit_html = render_html(parse_report(make_report(blocks=[unsplit])))

    assert 'class="swim-foot bare"' in split_html
    assert 'class="swim-gut swim-foot-lbl bare"' in split_html
    assert 'class="swim-foot bare"' not in unsplit_html
    assert 'class="swim-foot"' in unsplit_html


def test_references_render_bidirectional_links_and_leave_unknown_keys_literal() -> None:
    blocks = [
        {"type": "text", "body": "Method [^sop]; thresholds [^audit]; typo [^missing]."},
        {
            "type": "references",
            "items": [
                {"key": "sop", "text": "*Counting SOP*, rev. 7."},
                {"key": "audit", "text": "Q2 Audit.", "url": "https://example.com/a"},
            ],
        },
    ]
    html = render_html(parse_report(make_report(blocks=blocks)))

    # inline marker → numbered superscript linking down to the source
    assert '<sup class="fn"><a id="fnref-sop" href="#ref-sop">[1]</a></sup>' in html
    assert '<sup class="fn"><a id="fnref-audit" href="#ref-audit">[2]</a></sup>' in html
    # an undeclared key is left as literal text (escaped), never a dangling link
    assert "typo [^missing]." in html
    assert 'href="#ref-missing"' not in html
    # the cited source's whole <li>: number backlinks to the marker; rich text renders; no url → no rlink
    assert (
        '<li id="ref-sop"><a class="rnum" href="#fnref-sop">1</a>'
        '<span class="rtext"><em>Counting SOP</em>, rev. 7.</span></li>' in html
    )
    # the source with a url gets the trailing external-link glyph
    assert '<span class="rtext">Q2 Audit. <a class="rlink" href="https://example.com/a">↗</a></span>' in html


def test_a_reference_cited_twice_reuses_its_number_and_emits_one_anchor_id() -> None:
    blocks = [
        {"type": "text", "body": "First [^sop] and again [^sop]."},
        {"type": "references", "items": [{"key": "sop", "text": "SOP."}]},
    ]
    html = render_html(parse_report(make_report(blocks=blocks)))

    # both citations show number 1; only the first carries the fnref anchor id (ids stay unique)
    assert '<sup class="fn"><a id="fnref-sop" href="#ref-sop">[1]</a></sup>' in html
    assert '<sup class="fn"><a href="#ref-sop">[1]</a></sup>' in html
    assert html.count('id="fnref-sop"') == 1


def test_an_uncited_declared_reference_renders_a_plain_number_not_a_dead_backlink() -> None:
    blocks = [
        {"type": "text", "body": "Cited [^sop]."},
        {
            "type": "references",
            "items": [{"key": "sop", "text": "SOP."}, {"key": "extra", "text": "Never cited."}],
        },
    ]
    html = render_html(parse_report(make_report(blocks=blocks)))

    assert '<li id="ref-sop"><a class="rnum" href="#fnref-sop">1</a>' in html
    # the uncited source has no fnref anchor to link back to, so its number is a plain span
    assert '<li id="ref-extra"><span class="rnum">2</span>' in html
    assert 'href="#fnref-extra"' not in html


def test_a_citation_with_no_references_block_stays_literal() -> None:
    html = render_html(parse_report(make_report(blocks=[{"type": "text", "body": "See [^ghost]."}])))

    assert "See [^ghost]." in html
    assert '<sup class="fn">' not in html


def test_render_richtext_leaves_a_footnote_marker_literal_without_ref_numbers() -> None:
    assert str(render_richtext("see [^x]")) == "see [^x]"


def test_row_tone_renders_on_the_tr() -> None:
    table = make_table(
        columns=[{"key": "a", "label": "A", "kind": "text"}],
        rows=[{"a": "keep"}, {"a": "drop", "tone": "muted"}, {"a": "bad", "tone": "danger"}],
    )

    html = render_html(parse_report(make_report(blocks=[table])))

    assert '<tr class="row muted">' in html
    assert '<tr class="row danger">' in html
    assert '<tr class="row">' in html  # the untoned row is unchanged


def test_indicator_column_renders_a_toned_dot_and_blanks_opt_out() -> None:
    table = make_table(
        columns=[
            {"key": "a", "label": "A", "kind": "text"},
            {"key": "r", "label": "Risk", "kind": "indicator"},
        ],
        rows=[{"a": "bad", "r": "danger"}, {"a": "none", "r": ""}],
    )

    html = render_html(parse_report(make_report(blocks=[table])))

    assert '<span class="dot danger" title="danger"></span>' in html
    assert html.count('class="dot') == 1  # the blank cell opts out — no dot
    assert '<th class="ind">Risk</th>' in html


def test_tone_accepts_palette_aliases_and_teal_sky_are_first_class() -> None:
    """A tone field takes either vocabulary: a palette name normalises to its semantic twin
    (green→success), and teal/sky are first-class tones with their own colour (no lossy mapping)."""
    block = {
        "type": "cards",
        "items": [
            {"label": "a", "value": 1, "tone": "green"},  # palette alias → success
            {"label": "b", "value": 2, "tone": "teal"},  # first-class
        ],
    }
    html = render_html(parse_report(make_report(blocks=[block])))

    assert '<div class="card success">' in html  # green normalised to its semantic twin
    assert '<div class="card teal">' in html  # teal kept as itself
    assert "&.teal{--t:var(--teal-fg)}" in html  # the teal tone is wired in the CSS, not mapped away


def test_badge_colour_accepts_a_semantic_alias() -> None:
    """A badge takes a semantic tone name too — success renders the same chip as green."""
    block = {"type": "badge_row", "items": [{"label": "OK", "tone": "success"}]}

    html = render_html(parse_report(make_report(blocks=[block])))

    assert '<span class="chip green">OK</span>' in html  # success normalised to the palette name


def test_table_placement_cell_badge_renders_its_own_labelled_column() -> None:
    """A placement:cell badge column gets a header + a chip cell (single or list), a title-placement
    badge still chips under the title, and both keys feed the legend."""
    table = {
        "type": "table",
        "columns": [
            {"key": "name", "label": "View", "kind": "text"},
            {"key": "status", "label": "", "kind": "badge"},  # default title-placement
            {"key": "access", "label": "Access", "kind": "badge", "placement": "cell"},  # mid-declared
            {"key": "note", "label": "Notes", "kind": "rich"},
        ],
        "rows": [
            {"name": "One", "status": "LIVE", "access": "WRITE", "note": "a"},
            {"name": "Two", "status": "LIVE", "access": ["WRITE", "READ"], "note": "b"},
        ],
    }
    badges = {
        "LIVE": {"label": "Live", "tone": "green", "legend": "In production."},
        "WRITE": {"label": "Write", "tone": "blue", "legend": "Read-write."},
        "READ": {"label": "Read", "tone": "amber", "legend": "Read-only."},
    }

    html = render_html(parse_report(make_report(badges=badges, blocks=[table])))

    # the cell-badge column keeps its DECLARED position (between View and Notes), not shoved to the end
    assert "<thead><tr><th>View</th><th>Access</th><th>Notes</th></tr></thead>" in html
    assert "<th></th>" not in html  # the title-placement badge column contributes no header cell
    # the in-cell chip(s): row Two lists two, in one bc cell
    assert '<td class="bc"><span class="chip blue">Write</span></td>' in html
    assert (
        '<td class="bc"><span class="chip blue">Write</span><span class="chip amber">Read</span></td>' in html
    )
    # the title-placement status chip still rides under the title (not in its own column)
    assert '<td class="title">One' in html
    assert '<div><span class="chip green">Live</span></div>' in html
    # a cell-only badge key (READ, never used in a title column) feeds the legend — assert the legend
    # MEANING text, which appears only in the legend row (not on a chip)
    assert '<span class="meaning">Read-only.</span>' in html


def _cell_table(detail: str) -> dict[str, object]:
    return make_table(
        columns=[
            {"key": "name", "label": "Name", "kind": "text"},
            {"key": "detail", "label": "Detail", "kind": "rich"},
        ],
        rows=[{"name": "x", "detail": detail}],
    )


def test_rich_cell_blank_line_renders_stacked_paragraphs() -> None:
    html = render_html(parse_report(make_report(blocks=[_cell_table("First para.\n\nSecond para.")])))

    assert '<td><p class="cell-p">First para.</p><p class="cell-p">Second para.</p></td>' in html


def test_rich_cell_single_paragraph_renders_inline_without_a_wrapper() -> None:
    html = render_html(parse_report(make_report(blocks=[_cell_table("Just one line.")])))

    assert "<td>Just one line.</td>" in html
    assert '<p class="cell-p">' not in html  # no wrapper for a one-paragraph cell (CSS still defines it)


def test_rich_cell_single_newline_is_not_a_paragraph_break() -> None:
    html = render_html(parse_report(make_report(blocks=[_cell_table("Line one.\nLine two.")])))

    # one inline run (the newline collapses to a space at render); no paragraph wrapper
    assert "<td>Line one.\nLine two.</td>" in html
    assert '<p class="cell-p">' not in html


def test_rich_cell_paragraph_breaks_work_in_the_title_cell_alongside_a_badge() -> None:
    # the title cell is the other rich_cell call site; a multi-paragraph title stacks and the
    # title-placement badge still chips under it.
    table = make_table(
        columns=[
            {"key": "name", "label": "Name", "kind": "rich"},  # first rich column becomes the title
            {"key": "tag", "label": "", "kind": "badge"},
        ],
        rows=[{"name": "Intro para.\n\nSecond para.", "tag": "LIVE"}],
    )
    report = parse_report(
        make_report(blocks=[table], badges={"LIVE": {"label": "Live", "tone": "green", "legend": "up"}})
    )

    html = render_html(report)

    assert '<td class="title"><p class="cell-p">Intro para.</p><p class="cell-p">Second para.</p>' in html
    assert '<div><span class="chip green">Live</span></div>' in html  # badge still chips under the title


def test_row_and_indicator_tones_accept_palette_aliases() -> None:
    """The manually-validated tones (table row emphasis, indicator dot) alias too: red→danger,
    green→success — and the normalised name drives the rendered class."""
    table = make_table(
        columns=[{"key": "a", "label": "A", "kind": "text"}, {"key": "r", "label": "R", "kind": "indicator"}],
        rows=[{"a": "x", "r": "green", "tone": "red"}],
    )

    html = render_html(parse_report(make_report(blocks=[table])))

    assert '<tr class="row danger">' in html  # row tone red → danger
    assert '<span class="dot success" title="success"></span>' in html  # indicator green → success


def test_grid_cell_tone_renders_an_emphasis_panel() -> None:
    grid = make_grid([{"span": 6, "tone": "accent", "blocks": [{"type": "text", "body": "x"}]}])

    html = render_html(parse_report(make_report(blocks=[grid])))

    assert '<div class="cell span-6 panel accent">' in html


def test_hero_meta_wraps_the_title_in_a_hero_band() -> None:
    html = render_html(parse_report(make_report(meta={"title": "T", "subtitle": ["s"], "hero": True})))

    assert '<header class="hero"><h1>T</h1><p class="subtitle">s</p></header>' in html


def test_no_hero_by_default_renders_a_bare_title() -> None:
    html = render_html(parse_report(make_report()))

    assert '<header class="hero">' not in html
    assert "<h1>Test Report</h1>" in html


def test_embed_drops_the_skeleton_but_keeps_the_controls() -> None:
    html = render_embed(parse_report(make_report(blocks=[{"type": "text", "body": "hi"}])))

    # the document skeleton is dropped — the Artifact host supplies <html>/<head>/<body>
    assert "<!doctype" not in html.lower()
    assert "<html" not in html
    assert "<body" not in html
    # but the fragment stays fully functional: a leading <title> (names the artifact), inline
    # styles, the rendered content, AND the same corner controls + scripts as the full page
    # (inline JS runs inside an Artifact, so theme/width switching and the print handler work).
    assert html.startswith("<title>")
    assert "<title>Test Report</title>" in html
    assert "<style>" in html
    assert '<div class="wrap">' in html
    assert '<p class="text">hi</p>' in html
    assert '<div class="sc" data-open="false">' in html  # corner controls present
    assert 'addEventListener("beforeprint"' in html  # print handler present


def test_embed_and_page_share_content_and_controls() -> None:
    report = parse_report(
        make_report(blocks=[{"type": "heading", "text": "H"}, {"type": "text", "body": "b"}])
    )

    embed = render_embed(report)
    page = render_html(report)

    # the content region (wrap → corner controls) is byte-identical in both — only the outer
    # skeleton differs, since page and embed include the same _content and _controls partials
    marker, sc = '<div class="wrap">', '<div class="sc"'
    assert embed[embed.index(marker) : embed.index(sc)] == page[page.index(marker) : page.index(sc)]


def test_print_css_keeps_the_pdf_readable() -> None:
    html = render_html(parse_report(make_report()))

    # backgrounds/colours must print, or headers go white-on-white and chips/dots/tints vanish
    assert "print-color-adjust:exact" in html
    # a table row must not split across a page break, and the header must repeat on each page
    assert "table.rep tr{break-inside:avoid}" in html
    assert "table.rep thead{display:table-header-group}" in html
    # a group subheader stays with its first data row (never stranded at a page foot)
    assert "table.rep tr.group{break-after:avoid}" in html
    # the table's outer box/shadow is dropped on paper so a mid-table break isn't a half-drawn row
    assert ".table-wrap{border:none; border-radius:0; box-shadow:none}" in html
    # the break-inside list holds these blocks whole but NOT .code — a long code block may fragment
    assert ".card,.callout,figure.fig,blockquote.quote,.tl li,.status-list li,.list li," in html
    assert ".code," not in html
    # code keeps its normal box (no print-only restyle); a single diff line still never splits, and
    # the split stays seamless (default box-decoration-break, never clone)
    assert ".code .diff .ln{break-inside:avoid}" in html
    assert "box-decoration-break:clone" not in html
    # cards/callouts/list+status items stay whole across page breaks
    assert ".flow .seg,.flow .step,.walk .wstep,.kv,.range .rbar,.badge-groups{break-inside:avoid}" in html
    # a header is never stranded from the content it introduces (break in the gap after it forbidden)
    assert "h1,h2,h3,h4,summary{break-after:avoid; break-inside:avoid}" in html
    # a long section may still break — it is NOT force-kept whole
    assert "details.section,.kv{break-inside:avoid}" not in html
    # flows stack vertically (never wrap a lone node) when printing or on a narrow screen
    assert "@media print, (max-width: 640px){" in html
    assert ".flow .track{flex-direction:column; flex-wrap:nowrap}" in html
    assert ".fan{flex-direction:column; align-items:center}" in html
    assert ".fan .merge{transform:rotate(90deg)}" in html
    assert ".walk{grid-template-columns:1fr !important}" in html
    # collapsed walkthrough steps stack flush: the step's inline-start accent offset is zeroed so the
    # title row lines up with its detail beneath it (mirrors the .wdetail block-start reset)
    assert ".walk .wstep{border-inline-start:0; padding-inline-start:0}" in html
    # code wraps instead of clipping at the page edge (no scrollbar on paper)
    assert ".code pre,.code .diff .ln{white-space:pre-wrap" in html
    # print scales down for document density (the print-density knob)
    assert "zoom:0.75}" in html
    # collapsed sections are expanded for print (beforeprint opens them, afterprint restores),
    # with a CSS fallback for script-less hosts
    assert 'addEventListener("beforeprint"' in html
    assert 'addEventListener("afterprint"' in html
    assert "details::details-content{content-visibility:visible" in html


def test_wrap_carries_no_authorable_width_class() -> None:
    """Width is reader-only: the wrap never gets a width-* class from the author, so the reader's
    data-width override is the sole driver. The base cap lives on .wrap itself."""
    html = render_html(parse_report(make_report()))

    assert '<div class="wrap">' in html
    assert "wrap width-" not in html


def test_every_page_credits_and_links_the_project() -> None:
    html = render_html(parse_report(make_report()))

    assert "<!-- Generated by skaldr" in html
    assert "Install & docs: https://github.com/alex-yanchenko/skaldr -->" in html
    assert (
        '<div class="credit">Generated with <a href="https://github.com/alex-yanchenko/skaldr">skaldr</a></div>'
        in html
    )


def test_default_width_cap_lives_on_the_wrap_and_no_author_classes_remain() -> None:
    """The default 1600px cap is baked onto .wrap itself (not an author-set width-default class), and
    the old author-driven .wrap.width-* rules are gone — only the reader's data-width overrides cap."""
    html = render_html(parse_report(make_report()))

    assert ".wrap{margin-inline:auto; padding:40px 48px 80px; max-width:1600px}" in html
    assert ".wrap.width-" not in html


def test_palette_is_theme_aware_via_light_dark() -> None:
    html = render_html(parse_report(make_report()))

    assert COLOR_SCHEME_RULES[0] in html
    assert "--ink:light-dark(#1e293b,#e8ecf3);" in html
    assert "--page:light-dark(#f5f7fa,#0e1116);" in html


def test_explicit_theme_overrides_win_over_the_os_default() -> None:
    html = render_html(parse_report(make_report()))

    assert COLOR_SCHEME_RULES[1] in html
    assert COLOR_SCHEME_RULES[2] in html


def test_host_override_essentials_sit_outside_any_layer() -> None:
    """color-scheme, box-sizing, and body colour/background must each appear exactly once and before
    the first @layer block — otherwise they are layered and an embedding host's own unlayered reset
    would override them (stranding the theme, breaking box-sizing, or leaving dark panels with the
    host's dark text → invisible)."""
    html = render_html(parse_report(make_report()))
    first_layer_offset = html.index("@layer reset {")

    for rule in UNLAYERED_ESSENTIALS:
        assert html.count(rule) == 1
        assert html.index(rule) < first_layer_offset


def test_every_referenced_css_var_is_defined() -> None:
    """A `var(--x)` with no fallback whose token is never assigned resolves to guaranteed-invalid and
    kills its WHOLE declaration at computed-value time — e.g. one bad token in a `gap` shorthand zeroes
    both axes, silently. So every no-fallback token reference must be assigned somewhere in the sheet
    (`:root` globals or a component-local `--c:` alike). This caught `.deflist`'s `var(--s5)` — `--s5`
    was never in the scale (`--s1/2/3/4/6/8`), so the term/body gap collapsed to 0."""
    css = package_path("styles.css").read_text(encoding="utf-8")
    defined = set(re.findall(r"(--[\w-]+)\s*:", css))
    referenced_no_fallback = set(re.findall(r"var\(\s*(--[\w-]+)\s*\)", css))

    assert referenced_no_fallback <= defined, (
        f"CSS references undefined tokens (no fallback): {sorted(referenced_no_fallback - defined)}"
    )


_SAMPLE_SOURCE = 'version: 1\nmeta: {title: T}\nblocks:\n  - {type: text, body: "bin > 12 & <x> --flag"}\n'


def test_full_page_embeds_the_source_before_the_stylesheet() -> None:
    report = parse_report(make_report())

    html = render_html(report, source=_SAMPLE_SOURCE)

    assert '<script type="application/yaml" id="skaldr-source">' in html
    # placed before the CSS so a fetch/read reaches the source ahead of the stylesheet
    assert html.index("skaldr-source") < html.index("<style>")


def test_embed_fragment_also_embeds_the_source() -> None:
    # the artifact case: a shared --embed fragment must carry its own recoverable source
    html = render_embed(parse_report(make_report()), source=_SAMPLE_SOURCE)

    assert extract_source(html) == _SAMPLE_SOURCE


def test_embedded_source_round_trips_through_extract_source_with_specials() -> None:
    html = render_html(parse_report(make_report()), source=_SAMPLE_SOURCE)

    # plain-text embed survives HTML-special chars (`<`, `&`, `--`) with no escaping/decoding
    assert extract_source(html) == _SAMPLE_SOURCE


def test_render_without_source_embeds_no_block() -> None:
    html = render_html(parse_report(make_report()))

    assert "skaldr-source" not in html
    assert extract_source(html) is None


def test_extract_source_returns_none_for_a_page_without_a_block() -> None:
    assert extract_source("<html><body>no skaldr here</body></html>") is None


@pytest.mark.parametrize(
    ("token", "light", "dark"),
    [
        ("--neutral-fg", "#475569", "#cbd5e1"),
        ("--info-bg", "#eff6ff", "#15243c"),
        ("--success-fg", "#15803d", "#86efac"),
        ("--warning-bg", "#fef3c7", "#2c2410"),
        ("--danger-fg", "#b91c1c", "#fca5a5"),
        ("--accent-bg", "#f3e8ff", "#241a38"),
        ("--teal-fg", "#0f766e", "#5eead4"),
        ("--sky-bg", "#e0f2fe", "#0c2740"),
    ],
)
def test_tone_tokens_carry_both_light_and_dark_values(token: str, light: str, dark: str) -> None:
    html = render_html(parse_report(make_report()))

    assert f"{token}:light-dark({light},{dark});" in html


def test_timeline_dot_uses_the_rule_token_not_a_hardcoded_color() -> None:
    html = render_html(parse_report(make_report()))

    assert "background:var(--rule); box-shadow:0 0 0 3px var(--page)}" in html


def test_display_controls_render_with_all_theme_and_width_options() -> None:
    html = render_html(parse_report(make_report()))

    assert '<div class="sc" data-open="false">' in html
    assert 'aria-controls="sc-menu"' in html
    for val, label in [("auto", "Auto"), ("light", "Light"), ("dark", "Dark")]:
        assert (
            f'<button type="button" aria-pressed="false" data-set="theme" data-val="{val}">{label}</button>'
            in html
        )
    for val, label in [("default", "Default"), ("wide", "Wide"), ("full", "Full")]:
        assert (
            f'<button type="button" aria-pressed="false" data-set="width" data-val="{val}">{label}</button>'
            in html
        )


def test_only_theme_is_restored_before_paint_in_the_head() -> None:
    html = render_html(parse_report(make_report()))
    head = html.split("</head>", 1)[0]

    assert "localStorage" in head
    assert 'setAttribute("data-theme"' in head
    # Width is transient per-view: never persisted, so a reader override resets to the default cap on
    # reload. (An absent "skaldr-width" key proves it's neither stored on click nor restored in the head.)
    assert "skaldr-width" not in html


def test_width_switch_overrides_are_defined_in_the_stylesheet() -> None:
    """Only wide/full get data-width override rules; selecting "default" needs none — it falls back
    to the base .wrap cap, so there is no duplicate 1600px rule to drift."""
    html = render_html(parse_report(make_report()))

    assert ':root[data-width="wide"] .wrap{max-width:1920px}' in html
    assert ':root[data-width="full"] .wrap{max-width:none}' in html
    assert ':root[data-width="default"]' not in html


def test_output_carries_a_locked_down_csp_pinning_the_inline_script_hashes() -> None:
    html = render_html(parse_report(make_report()))
    csp = re.search(r'content="(default-src [^"]+)"', html)
    assert csp is not None
    policy = csp.group(1)
    script_src = policy.split("script-src ", 1)[1].split(";", 1)[0]

    assert policy.startswith("default-src 'none';")
    assert "img-src data:;" in policy
    assert "base-uri 'none'" in policy and "form-action 'none'" in policy
    # script-src pins exact hashes, never 'unsafe-inline' — an injected inline script can't run.
    assert "'unsafe-inline'" not in script_src
    # Recompute each inline script's hash from the rendered output so a script edit that isn't
    # reflected in the CSP fails here (the browser would otherwise silently refuse the script).
    for body in re.findall(r"<script>(.*?)</script>", html, re.DOTALL):
        digest = base64.b64encode(hashlib.sha256(body.encode()).digest()).decode()
        assert f"'sha256-{digest}'" in script_src
    # The policy must precede the inline scripts so it governs them.
    assert html.index("Content-Security-Policy") < html.index("<script>")


def test_richtext_applies_the_inline_subset() -> None:
    html = str(render_richtext("**b** *i* `c` ~~s~~ [t](https://x.com)"))

    assert html == '<strong>b</strong> <em>i</em> <code>c</code> <del>s</del> <a href="https://x.com">t</a>'


def test_richtext_escapes_raw_html() -> None:
    assert str(render_richtext("<script>x & y")) == "&lt;script&gt;x &amp; y"


def test_richtext_renders_a_placeholder_as_a_chip_and_collects_it() -> None:
    seen: set[str] = set()
    html = str(render_richtext("Open {{deployed_url}} now", placeholders=seen))

    assert html == 'Open <span class="placeholder">deployed_url</span> now'
    assert seen == {"deployed_url"}


def test_richtext_placeholder_survives_bold_and_italic_neighbours() -> None:
    html = str(render_richtext("**go** to {{url}} *now*"))

    assert html == '<strong>go</strong> to <span class="placeholder">url</span> <em>now</em>'


@pytest.mark.parametrize("token", ["{{url}}", "{{ url }}", "{{  url  }}"])
def test_richtext_placeholder_tolerates_internal_whitespace(token: str) -> None:
    seen: set[str] = set()
    html = str(render_richtext(token, placeholders=seen))

    assert html == '<span class="placeholder">url</span>'
    assert seen == {"url"}


@pytest.mark.parametrize("name", ["next-round", "a_b-2", "deployed_url"])
def test_richtext_placeholder_accepts_letters_digits_underscore_and_hyphen(name: str) -> None:
    seen: set[str] = set()
    html = str(render_richtext(f"retry {{{{{name}}}}} now", placeholders=seen))

    assert html == f'retry <span class="placeholder">{name}</span> now'
    assert seen == {name}


@pytest.mark.parametrize("token", ["{{a.b}}", "{{two words}}", "{{ }}", "{{}}"])
def test_richtext_malformed_placeholder_fails_the_build(token: str) -> None:
    # `{{…}}` is reserved for placeholders — a token whose name isn't letters/digits/_/- is a typo'd
    # blank and hard-fails, rather than silently shipping as prose past the --strict gate.
    with pytest.raises(ReportError, match=r"invalid placeholder '"):
        render_richtext(f"a {token} b")


@pytest.mark.parametrize("body", ["wrap {{ `code` }} it", "wrap {{[x](https://y.com)}} it"])
def test_richtext_placeholder_wrapping_other_markup_fails_without_leaking_the_stash(body: str) -> None:
    # a `{{…}}` around an already-stashed inline element must not leak the internal NUL sentinel into
    # the error — it reports the cause (a placeholder is a bare name) instead.
    with pytest.raises(ReportError, match=r"can't contain a link, `code` span, or") as exc:
        render_richtext(body)

    assert "\x00" not in str(exc.value)


def test_richtext_double_brace_with_an_inner_brace_stays_literal() -> None:
    # the capture is brace-bounded (keeps the scan linear), so a nested-brace token isn't a placeholder
    # at all — it stays literal rather than erroring. A deliberate trade for linear-time matching.
    html = str(render_richtext("a {{b{c}} d"))

    assert html == "a {{b{c}} d"


def test_richtext_literal_double_brace_survives_inside_a_code_span() -> None:
    # the escape hatch: a `code` span is stashed before placeholder parsing, so a literal {{ is safe
    html = str(render_richtext("use `{{raw}}` verbatim"))

    assert html == "use <code>{{raw}}</code> verbatim"


def test_find_placeholders_reaches_table_cells_def_list_and_panel_nested_text() -> None:
    report = parse_report(
        make_report(
            blocks=[
                {
                    "type": "table",
                    "columns": [{"key": "note", "label": "Note", "kind": "rich"}],
                    "rows": [{"note": "ping {{cell_ph}}"}],
                },
                {"type": "def_list", "items": [{"term": "Owner", "body": "{{def_ph}} owns it"}]},
                {"type": "panel", "title": "P", "blocks": [{"type": "text", "body": "in {{panel_ph}}"}]},
            ]
        )
    )

    assert find_placeholders(report) == ["cell_ph", "def_ph", "panel_ph"]


def test_find_placeholders_collects_sorted_unique_names_across_the_report() -> None:
    report = parse_report(
        make_report(
            blocks=[
                {"type": "text", "body": "See {{ticket}} and {{deployed_url}}."},
                {"type": "callout", "tone": "info", "body": "Ping {{ticket}} again."},
            ]
        )
    )

    assert find_placeholders(report) == ["deployed_url", "ticket"]


def test_report_with_no_placeholders_collects_nothing() -> None:
    report = parse_report(make_report(blocks=[{"type": "text", "body": "All real values here."}]))

    assert find_placeholders(report) == []


def test_author_id_becomes_the_heading_and_section_anchor() -> None:
    blocks = [
        {"type": "heading", "text": "Discrepancies & Fixes", "id": "fixes"},
        {"type": "section", "title": "Raw data", "id": "raw", "blocks": [{"type": "text", "body": "x"}]},
    ]

    html = render_html(parse_report(make_report(blocks=blocks)))

    assert '<h2 id="fixes">Discrepancies &amp; Fixes</h2>' in html
    assert '<details class="section" id="raw"' in html


def test_heading_sub_renders_a_rich_caption_inside_the_heading() -> None:
    block = {"type": "heading", "text": "Overview", "sub": "the **10k** count"}

    html = render_html(parse_report(make_report(blocks=[block])))

    assert '<h2 id="overview">Overview<span class="hsub">the <strong>10k</strong> count</span></h2>' in html


def test_heading_without_sub_renders_no_caption_span() -> None:
    html = render_html(parse_report(make_report(blocks=[{"type": "heading", "text": "Overview"}])))

    assert '<h2 id="overview">Overview</h2>' in html
    assert '<span class="hsub">' not in html  # the class lives in the inlined CSS; the span must not


def test_stylesheet_carries_no_footnote_marker_syntax() -> None:
    """The whole stylesheet is inlined into every rendered page, so a literal `[^…]` footnote marker
    in a CSS comment surfaces in the output and trips a consumer scanning the render for unresolved
    markers. Keep the marker syntax out of the sheet — describe it in words instead."""
    css = package_path("styles.css").read_text(encoding="utf-8")

    assert "[^" not in css


def test_richtext_rejects_disallowed_link_scheme() -> None:
    assert str(render_richtext("[x](javascript:alert)")) == "[x](javascript:alert)"


def test_richtext_renders_a_known_same_page_anchor_link() -> None:
    html = str(render_richtext("see [the overview](#overview)", anchor_ids=frozenset({"overview"})))

    assert html == 'see <a href="#overview">the overview</a>'


def test_richtext_rejects_a_dangling_same_page_anchor() -> None:
    with pytest.raises(ReportError, match=r"unknown anchor '#missing'"):
        render_richtext("[x](#missing)", anchor_ids=frozenset({"overview"}))


def test_richtext_leaves_an_anchor_link_literal_without_an_anchor_set() -> None:
    assert str(render_richtext("[x](#overview)")) == "[x](#overview)"


def test_same_page_anchor_link_resolves_to_a_heading_id_in_a_full_render() -> None:
    blocks = [
        {"type": "heading", "text": "Overview"},
        {"type": "text", "body": "Jump to [the overview](#overview)."},
    ]

    html = render_html(parse_report(make_report(blocks=blocks)))

    assert '<a href="#overview">the overview</a>' in html
    assert 'id="overview"' in html  # the heading it targets


def test_dangling_anchor_link_fails_the_whole_render() -> None:
    blocks = [{"type": "text", "body": "[broken](#nope)"}]

    with pytest.raises(ReportError, match=r"unknown anchor '#nope'"):
        render_html(parse_report(make_report(blocks=blocks)))


def test_richtext_leaves_marks_literal_inside_a_code_span() -> None:
    assert str(render_richtext("`**not bold**`")) == "<code>**not bold**</code>"


def test_richtext_url_with_asterisk_is_not_corrupted() -> None:
    html = str(render_richtext("see [x](https://e.com/a*b*c)"))

    assert '<a href="https://e.com/a*b*c">x</a>' in html
    assert "<em>" not in html


def test_duplicate_headings_get_unique_ids_matching_toc() -> None:
    report = parse_report(
        make_report(
            meta={"title": "T", "toc": True},
            blocks=[{"type": "heading", "text": "Details"}, {"type": "heading", "text": "Details"}],
        )
    )

    html = render_html(report)

    assert 'id="details"' in html
    assert 'id="details-2"' in html
    assert 'href="#details"' in html
    assert 'href="#details-2"' in html


def test_richtext_code_span_inside_link_fully_expands() -> None:
    html = str(render_richtext("the [`compute.py`](https://e.com/x) module"))

    assert html == 'the <a href="https://e.com/x"><code>compute.py</code></a> module'
    assert "\x00" not in html


def test_text_block_splits_paragraphs_in_order() -> None:
    report = parse_report(make_report(blocks=[{"type": "text", "body": "one\n\ntwo"}]))

    html = render_html(report)

    assert html.count('<p class="text">') == 2
    assert '<p class="text">one</p>' in html
    assert html.index("one") < html.index("two")


def test_block_span_wraps_the_block_in_a_width_container() -> None:
    """A `span` wraps the block in `.blk span-N` (the width primitive); the block's own markup is
    unchanged inside it."""
    html = render_html(parse_report(make_report(blocks=[{"type": "list", "span": 4, "items": ["a"]}])))

    assert '<div class="blk span-4"><ul class="list"><li>a</li></ul>\n</div>' in html


def test_block_without_span_is_not_wrapped() -> None:
    """No span → no wrapper, so an unspanned block renders exactly as before (full width)."""
    html = render_html(parse_report(make_report(blocks=[{"type": "text", "body": "hi"}])))

    assert 'class="blk' not in html
    assert '<p class="text">hi</p>' in html


def test_totals_footer_renders_the_sum_in_the_number_cell() -> None:
    table = {
        "type": "table",
        "columns": [
            {"key": "issue", "label": "I", "kind": "text"},
            {"key": "count", "label": "C", "kind": "number"},
        ],
        "rows": [{"issue": "a", "count": 10}, {"issue": "b", "count": 5}],
        "totals": {"column": "count"},
    }
    report = parse_report(make_report(blocks=[table]))

    html = render_html(report)

    assert '<tfoot><tr><td>Total</td><td class="num">15</td></tr></tfoot>' in html


def test_diff_code_marks_added_and_removed_lines() -> None:
    block = {"type": "code", "mode": "diff", "content": "+added\n-removed\n context"}
    report = parse_report(make_report(blocks=[block]))

    html = render_html(report)

    assert '<span class="ln add">added</span>' in html
    assert '<span class="ln del">removed</span>' in html
    assert '<span class="ln ctx"> context</span>' in html


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
            {"label": "Transferable", "span": 3, "tone": "success", "sub": "full **credit**"},
            {"label": "Expired", "span": 1, "tone": "danger"},
        ],
    }

    html = render_html(parse_report(make_report(blocks=[block])))

    assert '<div class="range">' in html
    assert (
        '<div class="rbar">'
        '<div class="rseg success" style="flex:3"><span class="rlab">Transferable</span>'
        '<span class="rsub">full <strong>credit</strong></span></div>'
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
    that lives inside a section (the iter_matrices/iter_cards recursion), and an id-less matrix
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

    assert "Legend — badges used on this page" in html
    assert "urgent" in html  # the grouped ref's legend meaning shows


def test_badge_row_flat_items_still_render_the_ungrouped_row() -> None:
    block = {"type": "badge_row", "label": "Affects:", "items": [{"label": "X", "tone": "amber"}]}

    html = render_html(parse_report(make_report(blocks=[block])))

    assert (
        '<div class="badge-row"><span class="label">Affects:</span>'
        '<span class="chip amber">X</span></div>' in html
    )
    assert 'class="badge-groups"' not in html


def test_richtext_strips_nul_bytes() -> None:
    html = str(render_richtext("a\x00b **c**"))

    assert "\x00" not in html
    assert html == "ab <strong>c</strong>"


def test_pct_clamps_tiny_nonzero_to_marker() -> None:
    from skaldr.compute import pct

    assert pct(3, 10000) == "<0.1%"
    assert pct(0, 10000) == "0.0%"


def test_fmt_rounds_float_noise() -> None:
    from skaldr.compute import fmt

    assert fmt(100.00000000000001) == "100"
    assert fmt(-1240) == "-1,240"


def test_section_collapsed_false_renders_open() -> None:
    block = {"type": "section", "title": "S", "collapsed": False, "blocks": [{"type": "text", "body": "x"}]}
    report = parse_report(make_report(blocks=[block]))

    html = render_html(report)

    assert '<details class="section" id="s" open>' in html


def test_section_updated_renders_a_stamp_in_the_summary() -> None:
    block = {
        "type": "section",
        "title": "S",
        "collapsed": False,
        "updated": "18 Jul 2026",
        "blocks": [{"type": "text", "body": "x"}],
    }
    report = parse_report(make_report(blocks=[block]))

    html = render_html(report)

    assert '<summary>S<span class="upd">updated 18 Jul 2026</span></summary>' in html


def test_section_without_updated_has_no_stamp() -> None:
    block = {"type": "section", "title": "S", "collapsed": False, "blocks": [{"type": "text", "body": "x"}]}
    report = parse_report(make_report(blocks=[block]))

    html = render_html(report)

    assert "<summary>S</summary>" in html
    assert 'class="upd"' not in html


def test_table_rollup_renders_counted_chips_in_first_appearance_order() -> None:
    table = make_table(
        columns=[
            {"key": "item", "label": "Item", "kind": "text"},
            {"key": "status", "label": "", "kind": "badge"},
        ],
        rows=[
            {"item": "a", "status": "DONE"},
            {"item": "b", "status": "DONE"},
            {"item": "c", "status": "PENDING"},
        ],
        rollup={"by": "status", "label": "By status:"},
    )
    report = parse_report(
        make_report(
            blocks=[table],
            badges={
                "DONE": {"label": "Done", "tone": "success", "legend": "finished"},
                "PENDING": {"label": "Pending", "tone": "warning", "legend": "not yet"},
            },
        )
    )

    html = render_html(report)

    # both buckets, in first-appearance order; semantic tones render as their palette twins
    # (success→green, warning→amber)
    assert (
        '<div class="rollup"><span class="rollup-lab">By status:</span>'
        '<span class="rollup-item"><span class="chip green">Done</span>'
        '<span class="rollup-n">2</span></span>'
        '<span class="rollup-item"><span class="chip amber">Pending</span>'
        '<span class="rollup-n">1</span></span>'
        "</div>"
    ) in html


def test_table_rollup_without_a_label_omits_the_label_span() -> None:
    table = make_table(
        columns=[
            {"key": "item", "label": "Item", "kind": "text"},
            {"key": "status", "label": "", "kind": "badge"},
        ],
        rows=[{"item": "a", "status": "DONE"}],
        rollup={"by": "status"},
    )
    report = parse_report(
        make_report(
            blocks=[table],
            badges={"DONE": {"label": "Done", "tone": "success", "legend": "finished"}},
        )
    )

    html = render_html(report)

    assert '<div class="rollup"><span class="rollup-item">' in html  # chips start right after the div
    assert '<span class="rollup-lab">' not in html  # no label span (the CSS rule still defines .rollup-lab)


def test_table_without_rollup_renders_no_strip() -> None:
    table = make_table(columns=[{"key": "item", "label": "I", "kind": "text"}], rows=[{"item": "a"}])
    report = parse_report(make_report(blocks=[table]))

    assert 'class="rollup"' not in render_html(report)


def _tint_report(rows: list[dict[str, object]]) -> Report:
    table = make_table(
        columns=[
            {"key": "item", "label": "Item", "kind": "text"},
            {"key": "status", "label": "", "kind": "badge"},
        ],
        rows=rows,
        tint_by="status",
    )
    return parse_report(
        make_report(
            blocks=[table],
            badges={
                "DONE": {"label": "Done", "tone": "success", "legend": "finished"},
                "PENDING": {"label": "Pending", "tone": "warning", "legend": "not yet"},
            },
        )
    )


def test_table_tint_by_tints_each_row_by_its_badge_tone() -> None:
    html = render_html(
        _tint_report(
            [{"item": "a", "status": "DONE"}, {"item": "b", "status": "PENDING"}, {"item": "c", "status": ""}]
        )
    )

    assert '<tr class="row tint green">' in html  # success → green palette twin
    assert '<tr class="row tint amber">' in html  # warning → amber
    assert '<tr class="row">' in html  # blank badge cell → untinted row


def test_table_tint_by_yields_to_an_explicit_row_tone() -> None:
    html = render_html(_tint_report([{"item": "a", "status": "DONE", "tone": "danger"}]))

    assert '<tr class="row danger">' in html  # explicit row tone wins
    assert '<tr class="row tint' not in html  # a toned row never carries a tint class


def test_table_tint_by_a_cell_badge_list_uses_the_first_key_tone() -> None:
    """tint_by may name a placement: cell badge column whose value is a LIST of keys; the row's tint
    comes from the FIRST key's tone (a single row can't carry two tints)."""
    table = make_table(
        columns=[
            {"key": "item", "label": "Item", "kind": "text"},
            {"key": "tags", "label": "Tags", "kind": "badge", "placement": "cell"},
        ],
        rows=[{"item": "a", "tags": ["DONE", "PENDING"]}],
        tint_by="tags",
    )
    report = parse_report(
        make_report(
            blocks=[table],
            badges={
                "DONE": {"label": "Done", "tone": "success", "legend": "finished"},
                "PENDING": {"label": "Pending", "tone": "warning", "legend": "not yet"},
            },
        )
    )

    html = render_html(report)

    assert '<tr class="row tint green">' in html  # first key DONE → success → green drives the tint


def test_image_max_width_renders_style() -> None:
    src = "data:image/svg+xml,<svg/>"
    block = {"type": "image", "src": src, "alt": "a", "max_width": 400}
    report = parse_report(make_report(blocks=[block]))

    html = render_html(report)

    assert 'style="max-width:400px"' in html


def test_timeline_item_without_state_or_time_renders() -> None:
    block = {"type": "timeline", "items": [{"title": "just a title"}]}
    report = parse_report(make_report(blocks=[block]))

    html = render_html(report)

    assert '<div class="ti">just a title</div>' in html
    assert '<div class="time">' not in html


def test_legend_renders_at_top_when_no_table() -> None:
    report = parse_report(
        make_report(
            badges={"P": {"label": "prod", "tone": "violet", "legend": "l"}},
            blocks=[{"type": "badge_row", "items": [{"key": "P"}]}],
        )
    )

    html = render_html(report)

    assert "Legend — badges used on this page" in html


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


def test_empty_badge_cell_renders_no_chip() -> None:
    table = {
        "type": "table",
        "columns": [
            {"key": "issue", "label": "I", "kind": "text"},
            {"key": "tag", "label": "", "kind": "badge"},
        ],
        "rows": [{"issue": "x", "tag": "  "}],
    }
    report = parse_report(make_report(blocks=[table]))

    html = render_html(report)

    assert '<span class="chip' not in html


def test_grid_renders_cells_with_span_classes() -> None:
    grid = make_grid(
        [
            make_cell(2, [{"type": "text", "body": "left"}]),
            make_cell(4, [{"type": "text", "body": "right"}]),
        ]
    )
    html = render_html(parse_report(make_report(blocks=[grid])))

    assert '<div class="grid">' in html
    assert '<div class="cell span-2">' in html
    assert '<div class="cell span-4">' in html
    assert html.index("left") < html.index("right")


def test_nested_grid_renders() -> None:
    grid = make_grid([make_cell(6, [make_grid([make_cell(3, [{"type": "text", "body": "deep"}])])])])
    html = render_html(parse_report(make_report(blocks=[grid])))

    assert html.count('<div class="grid">') == 2
    assert '<div class="cell span-3">' in html
    assert "deep" in html


def _reconciled() -> dict[str, object]:
    return make_reconciled_table(
        reconcile={"total": 10, "column": "count"},
        groups=[{"name": "g", "rows": [{"issue": "x", "count": 10}]}],
    )


def test_reconciled_table_inside_grid_reaches_the_footer() -> None:
    grid = make_grid([make_cell(6, [_reconciled()])])
    report = parse_report(make_report(meta={"title": "T", "source": "s"}, blocks=[grid]))

    html = render_html(report)

    assert '<div class="footer">' in html
    assert "Reconciles: 10 = 10." in html


def test_reconciled_table_in_nested_grid_reaches_the_footer() -> None:
    inner = make_grid([make_cell(6, [_reconciled()])])
    grid = make_grid([make_cell(6, [inner])])
    report = parse_report(make_report(meta={"title": "T", "source": "s"}, blocks=[grid]))

    assert "Reconciles: 10 = 10." in render_html(report)


def test_heading_inside_grid_gets_an_id() -> None:
    grid = make_grid([make_cell(6, [{"type": "heading", "text": "In Cell"}])])

    assert 'id="in-cell"' in render_html(parse_report(make_report(blocks=[grid])))


def test_heading_in_nested_grid_gets_an_id() -> None:
    inner = make_grid([make_cell(6, [{"type": "heading", "text": "Deep Head"}])])
    grid = make_grid([make_cell(6, [inner])])

    assert 'id="deep-head"' in render_html(parse_report(make_report(blocks=[grid])))


def test_table_column_widths_render_proportional_colgroup() -> None:
    table = make_table(
        [
            {"key": "a", "label": "A", "kind": "text", "width": 2},
            {"key": "b", "label": "B", "kind": "number", "width": 4},
        ],
        rows=[{"a": "x", "b": 10}],
    )
    html = render_html(parse_report(make_report(blocks=[table])))

    assert '<colgroup><col style="width:33.3%"><col style="width:66.7%"></colgroup>' in html


def test_single_width_column_renders_full_width() -> None:
    table = make_table([{"key": "a", "label": "A", "kind": "text", "width": 3}], rows=[{"a": "x"}])
    html = render_html(parse_report(make_report(blocks=[table])))

    assert '<colgroup><col style="width:100.0%"></colgroup>' in html


def test_table_renders_inside_a_panel_wrapper() -> None:
    table = make_table([{"key": "a", "label": "A", "kind": "text"}], rows=[{"a": "x"}])
    html = render_html(parse_report(make_report(blocks=[table])))

    assert '<div class="table-wrap"><table class="rep">' in html
    assert html.count('<div class="table-wrap"><table class="rep">') == 1
    assert html.count("</table></div>") == 1


def test_table_with_totals_footer_stays_inside_the_wrapper() -> None:
    table = {
        "type": "table",
        "columns": [
            {"key": "issue", "label": "I", "kind": "text"},
            {"key": "count", "label": "C", "kind": "number"},
        ],
        "rows": [{"issue": "a", "count": 10}],
        "totals": {"column": "count"},
    }
    html = render_html(parse_report(make_report(blocks=[table])))

    assert '<div class="table-wrap"><table class="rep">' in html
    assert "<tfoot>" in html
    assert "</tfoot></table></div>" in html


def test_grouped_table_with_empty_last_group_stays_inside_the_wrapper() -> None:
    table = make_reconciled_table(
        reconcile={"total": 10, "column": "count"},
        groups=[{"name": "g", "rows": [{"issue": "x", "count": 10}]}, {"name": "empty", "rows": []}],
    )
    html = render_html(parse_report(make_report(meta={"title": "T", "source": "s"}, blocks=[table])))

    assert '<div class="table-wrap"><table class="rep">' in html
    assert '<tr class="empty"><td colspan="2">— none —</td></tr></tbody>' in html
    assert "</table></div>" in html


def test_panel_family_shadow_and_surface_tokens_are_in_the_stylesheet() -> None:
    html = render_html(parse_report(make_report()))

    assert "--surface:light-dark(#ffffff,#171d28);" in html
    assert (
        "--shadow:0 1px 2px light-dark(rgba(20,26,40,0.05),rgba(0,0,0,0.5)), "
        "0 4px 16px light-dark(rgba(20,26,40,0.04),rgba(0,0,0,0.35));" in html
    )
    assert (
        ".table-wrap{margin-block:var(--s3); border:1px solid var(--line); "
        "border-radius:var(--r-md); background:var(--surface); box-shadow:var(--shadow)}" in html
    )


def test_table_without_widths_keeps_default_colgroup() -> None:
    table = make_table(
        [
            {"key": "a", "label": "A", "kind": "text"},
            {"key": "b", "label": "B", "kind": "number"},
        ],
        rows=[{"a": "x", "b": 10}],
    )
    html = render_html(parse_report(make_report(blocks=[table])))

    assert '<colgroup><col><col style="width:10%"></colgroup>' in html


def test_subrows_render_compactly_scoped_over_the_main_cell_padding() -> None:
    table = make_table(
        [{"key": "a", "label": "A", "kind": "text"}],
        rows=[{"a": "x", "subrows": [{"label": "inner", "value": 5}]}],
    )
    html = render_html(parse_report(make_report(blocks=[table])))

    assert '<table class="subtable">' in html
    # Nested under table.rep so it out-specifies `table.rep tbody td` (which would otherwise
    # leak 16px padding + a row border into the nested subtable). Assert the `&` so un-nesting
    # the rule to a bare (weaker-specificity) `.subtable td` would fail this.
    assert "& .subtable td{padding:3px 10px 3px 0; border:0;" in html


def test_chart_bar_renders_bars_gridlines_ticks_and_matching_legend() -> None:
    block = {
        "type": "chart",
        "variant": "bar",
        "title": "Q",
        "categories": ["Q1", "Q2"],
        "series": [
            {"label": "Imported", "tone": "success", "values": [80, 90]},
            {"label": "Failed", "tone": "danger", "values": [10, 5]},
        ],
    }
    html = render_html(parse_report(make_report(blocks=[block])))

    assert '<figure class="chart bar">' in html
    assert '<figcaption class="cap">Q</figcaption>' in html
    assert "<rect" in html
    assert '<line class="c-gl"' in html  # gridlines
    assert '<text class="c-axlbl"' in html  # category labels
    # a bar's fill and its legend swatch both resolve to the series tone
    assert 'fill="var(--success-fg)"' in html
    assert 'fill="var(--danger-fg)"' in html
    assert '<i style="background:var(--success-fg)"></i>Imported' in html
    assert '<i style="background:var(--danger-fg)"></i>Failed' in html


def test_chart_bar_stacked_stacks_segments_cumulatively_on_the_baseline() -> None:
    block = {
        "type": "chart",
        "variant": "bar",
        "stacked": True,
        "categories": ["A"],
        "series": [
            {"label": "Auto", "tone": "info", "values": [60]},
            {"label": "Manual", "tone": "warning", "values": [40]},
        ],
    }
    html = render_html(parse_report(make_report(blocks=[block])))

    assert 'fill="var(--info-fg)"' in html and 'fill="var(--warning-fg)"' in html
    assert 'rx="2"' not in html  # stacked segments abut, without the grouped bars' rounding
    rects = re.findall(r'<rect x="[\d.]+" y="([\d.]+)" width="[\d.]+" height="([\d.]+)"', html)
    assert len(rects) == 2
    (y0, h0), (y1, h1) = ((float(y), float(h)) for y, h in rects)
    # first segment sits on the baseline (176); the second abuts its top — proving the cumulative
    # offset, not both drawn from the baseline (which a broken stack would do).
    assert round(y0 + h0) == 176
    assert round(y1 + h1) == round(y0)


def test_chart_line_single_category_renders_a_point_with_no_curve() -> None:
    block = {
        "type": "chart",
        "variant": "line",
        "categories": ["only"],
        "series": [{"label": "X", "values": [5]}],
    }
    html = render_html(parse_report(make_report(blocks=[block])))

    figure = html.split('<figure class="chart line">')[1].split("</figure>")[0]
    assert " C" not in figure  # a lone point is a move-to only, no cubic-Bézier segment
    assert "<circle" in figure  # still shown, as its end dot


def test_chart_line_single_series_gets_area_fill_smoothed_path_and_end_dot() -> None:
    block = {
        "type": "chart",
        "variant": "line",
        "categories": ["a", "b", "c"],
        "series": [{"label": "X", "values": [1, 2, 3]}],
    }
    html = render_html(parse_report(make_report(blocks=[block])))

    assert '<figure class="chart line">' in html
    assert 'opacity="0.10"' in html  # lone series → soft area fill
    assert '<path d="M' in html and " C" in html  # a cubic-Bézier (smoothed) path, not a polyline
    assert "<circle" in html  # end dot


def test_chart_line_multi_series_has_no_area_fill_and_cycles_unset_tones() -> None:
    block = {
        "type": "chart",
        "variant": "line",
        "categories": ["a", "b"],
        "series": [{"label": "One", "values": [1, 2]}, {"label": "Two", "values": [3, 4]}],
    }
    html = render_html(parse_report(make_report(blocks=[block])))

    assert 'opacity="0.10"' not in html  # >1 series: fills would muddy each other, so none
    # untoned series take the palette cycle IN ORDER: series 0 → info, series 1 → success
    assert 'stroke="var(--info-fg)"' in html
    assert 'stroke="var(--success-fg)"' in html
    assert html.index('stroke="var(--info-fg)"') < html.index('stroke="var(--success-fg)"')


def test_chart_donut_renders_arcs_centre_total_and_derived_shares() -> None:
    block = {
        "type": "chart",
        "variant": "donut",
        "slices": [
            {"label": "A", "tone": "success", "value": 60},
            {"label": "B", "tone": "danger", "value": 40},
        ],
    }
    html = render_html(parse_report(make_report(blocks=[block])))

    assert '<figure class="chart donut">' in html
    assert 'transform="rotate(-90)"' in html  # arc segments
    assert 'class="c-total"' in html and ">100<" in html  # centre total = 60 + 40
    # shares are derived, not authored, and shown in the legend
    assert '<i style="background:var(--success-fg)"></i>A 60%' in html
    assert '<i style="background:var(--danger-fg)"></i>B 40%' in html


def test_chart_escapes_author_category_labels() -> None:
    block = {
        "type": "chart",
        "variant": "bar",
        "categories": ["<x>"],
        "series": [{"label": "S", "values": [1]}],
    }
    html = render_html(parse_report(make_report(blocks=[block])))

    assert "&lt;x&gt;" in html  # the label is escaped inside the SVG <text>, never raw markup
