import base64
import hashlib
import re

import pytest

from skaldr.errors import ReportError
from skaldr.models import load_report, parse_report
from skaldr.render import render_embed, render_html, render_richtext
from tests.conftest import REPO_ROOT
from tests.factories import make_cell, make_grid, make_reconciled_table, make_report, make_table

GOLDEN = REPO_ROOT / "tests" / "golden" / "example.html"


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
    assert '<details class="section"><summary>S</summary>' in render_html(report)
    assert '<details class="section" open><summary>S</summary>' in render_html(report, expand=True)


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
    assert '<span class="chk yes">✓</span>' in html  # bare true
    assert "<td>free</td>" in html  # bare string cell renders unwrapped, no span
    assert '<span class="ct danger">paid</span>' in html  # {value, tone} cell
    assert '<span class="ct">n/a</span>' in html  # {value} with NO tone → default-muted, no tone class
    # the highlighted column is column B specifically (content-anchored, not just a count)
    assert '<td class="hl"><span class="chk no">✗</span></td>' in html
    assert '<td class="hl"><span class="ct danger">paid</span></td>' in html
    assert html.count('<td class="hl">') == 3  # every cell of column B (three rows)


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
    assert '<div class="wrap width-default">' in html
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
    marker, sc = '<div class="wrap width-default">', '<div class="sc"'
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
    assert ".flow .seg,.flow .step,.kv{break-inside:avoid}" in html
    # a header is never stranded from the content it introduces (break in the gap after it forbidden)
    assert "h1,h2,h3,h4,summary{break-after:avoid; break-inside:avoid}" in html
    # a long section may still break — it is NOT force-kept whole
    assert "details.section,.kv{break-inside:avoid}" not in html
    # flows stack vertically (never wrap a lone node) when printing or on a narrow screen
    assert "@media print, (max-width: 640px){" in html
    assert ".flow .track{flex-direction:column; flex-wrap:nowrap}" in html
    assert ".fan{flex-direction:column; align-items:center}" in html
    assert ".fan .merge{transform:rotate(90deg)}" in html
    # code wraps instead of clipping at the page edge (no scrollbar on paper)
    assert ".code pre,.code .diff .ln{white-space:pre-wrap" in html
    # print scales down for document density (the print-density knob)
    assert "zoom:0.75}" in html
    # collapsed sections are expanded for print (beforeprint opens them, afterprint restores),
    # with a CSS fallback for script-less hosts
    assert 'addEventListener("beforeprint"' in html
    assert 'addEventListener("afterprint"' in html
    assert "details::details-content{content-visibility:visible" in html


def test_width_defaults_to_default() -> None:
    html = render_html(parse_report(make_report()))

    assert '<div class="wrap width-default">' in html


def test_every_page_credits_and_links_the_project() -> None:
    html = render_html(parse_report(make_report()))

    assert "<!-- Generated by skaldr" in html
    assert "Install & docs: https://github.com/alex-yanchenko/skaldr -->" in html
    assert (
        '<div class="credit">Generated with <a href="https://github.com/alex-yanchenko/skaldr">skaldr</a></div>'
        in html
    )


@pytest.mark.parametrize("mode", ["default", "wide", "full"])
def test_width_mode_sets_the_wrap_class(mode: str) -> None:
    report = parse_report(make_report(meta={"title": "T", "width": mode}))

    assert f'<div class="wrap width-{mode}">' in render_html(report)


def test_width_caps_are_defined_in_the_stylesheet() -> None:
    html = render_html(parse_report(make_report(meta={"title": "T", "width": "wide"})))

    assert ".wrap.width-default{max-width:1600px}" in html
    assert ".wrap.width-wide{max-width:1920px}" in html
    assert ".wrap.width-full{max-width:none}" in html


def test_palette_is_theme_aware_via_light_dark() -> None:
    html = render_html(parse_report(make_report()))

    assert "color-scheme:light dark;" in html
    assert "--ink:light-dark(#1e293b,#e8ecf3);" in html
    assert "--page:light-dark(#f5f7fa,#0e1116);" in html


def test_explicit_theme_overrides_win_over_the_os_default() -> None:
    html = render_html(parse_report(make_report()))

    assert ':root[data-theme="dark"]{color-scheme:dark}' in html
    assert ':root[data-theme="light"]{color-scheme:light}' in html


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
    # Width is transient per-view: never persisted, so a new page keeps the author's meta.width.
    # (An absent "skaldr-width" key proves it's neither stored on click nor restored in the head.)
    assert "skaldr-width" not in html


def test_width_switch_overrides_are_defined_in_the_stylesheet() -> None:
    html = render_html(parse_report(make_report()))

    assert ':root[data-width="default"] .wrap{max-width:1600px}' in html
    assert ':root[data-width="wide"] .wrap{max-width:1920px}' in html
    assert ':root[data-width="full"] .wrap{max-width:none}' in html


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


def test_unknown_width_mode_is_rejected() -> None:
    with pytest.raises(ReportError, match=r"width"):
        parse_report(make_report(meta={"title": "T", "width": "huge"}))


def test_richtext_applies_the_inline_subset() -> None:
    html = str(render_richtext("**b** *i* `c` ~~s~~ [t](https://x.com)"))

    assert html == '<strong>b</strong> <em>i</em> <code>c</code> <del>s</del> <a href="https://x.com">t</a>'


def test_richtext_escapes_raw_html() -> None:
    assert str(render_richtext("<script>x & y")) == "&lt;script&gt;x &amp; y"


def test_richtext_rejects_disallowed_link_scheme() -> None:
    assert str(render_richtext("[x](javascript:alert)")) == "[x](javascript:alert)"


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


def test_status_list_maps_state_to_glyph() -> None:
    block = {"type": "status_list", "items": [{"state": "failed", "text": "broke"}]}
    report = parse_report(make_report(blocks=[block]))

    html = render_html(report)

    assert '<li class="failed"><span class="glyph">✗</span><span>broke</span></li>' in html


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


def test_card_string_value_and_tone_render() -> None:
    block = {"type": "cards", "items": [{"label": "Status", "value": "HEALTHY", "tone": "accent"}]}
    report = parse_report(make_report(blocks=[block]))

    html = render_html(report)

    assert '<div class="card accent">' in html
    assert '<div class="n str">HEALTHY</div>' in html


def test_badge_row_reference_renders_declared_chip() -> None:
    report = parse_report(
        make_report(
            badges={"PROD": {"label": "prod", "tone": "violet", "legend": "l"}},
            blocks=[{"type": "badge_row", "items": [{"key": "PROD"}]}],
        )
    )

    html = render_html(report)

    assert '<span class="chip violet">prod</span>' in html


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

    assert '<details class="section" open>' in html


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
