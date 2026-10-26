from skaldr.models import parse_report
from skaldr.render import render_html
from tests.factories import make_cell, make_grid, make_report, make_toggle


def test_panel_renders_a_titled_card_holding_its_blocks() -> None:
    block = {"type": "panel", "title": "Slide 1", "blocks": [{"type": "text", "body": "Point."}]}

    html = render_html(parse_report(make_report(blocks=[block])))

    assert (
        '<div class="panel-card"><div class="panel-card-hd">Slide 1</div><div class="panel-card-body">'
        in html
    )
    assert '<p class="text">Point.</p></div></div>' in html


def test_a_toggle_is_a_collapsed_details_with_no_anchor() -> None:
    html = render_html(parse_report(make_report(blocks=[make_toggle(title="Raw counts")])))

    assert (
        '<details class="toggle"><summary>Raw counts</summary>'
        '<div class="section-body"><p class="text">x</p></div></details>'
    ) in html


def test_a_toggle_set_not_collapsed_starts_open() -> None:
    html = render_html(parse_report(make_report(blocks=[make_toggle(title="Raw counts", collapsed=False)])))

    assert '<details class="toggle" open><summary>Raw counts</summary>' in html


def test_a_pdf_render_opens_every_toggle() -> None:
    html = render_html(parse_report(make_report(blocks=[make_toggle(title="Raw counts")])), expand=True)

    assert '<details class="toggle" open><summary>Raw counts</summary>' in html


def test_a_toggle_is_not_a_toc_entry_but_a_heading_inside_it_is_a_link_target() -> None:
    toggle = make_toggle(
        {"type": "heading", "level": 3, "text": "Inside", "id": "inside"}, title="Raw counts"
    )
    blocks = [
        {"type": "heading", "text": "Overview"},
        toggle,
        {"type": "text", "body": "Jump [in](#inside)."},
    ]

    html = render_html(parse_report(make_report(meta={"title": "T", "toc": True}, blocks=blocks)))

    assert '<nav class="toc"><a href="#overview">Overview</a></nav>' in html
    assert (
        '<details class="toggle"><summary>Raw counts</summary><div class="section-body">'
        '<h3 id="inside">Inside</h3>\n</div></details>\n\n'
        '<p class="text">Jump <a href="#inside">in</a>.</p>'
    ) in html


def test_a_toggle_nests_inside_a_grid_cell_and_another_toggle() -> None:
    outer = make_toggle(make_toggle(title="Inner"), title="Outer")
    grid = make_grid([make_cell(6, [outer])])

    html = render_html(parse_report(make_report(blocks=[grid])))

    assert (
        '<div class="grid"><div class="cell span-6"><details class="toggle"><summary>Outer</summary>'
        '<div class="section-body"><details class="toggle"><summary>Inner</summary>'
        '<div class="section-body"><p class="text">x</p></div></details>\n</div></details>\n</div></div>'
    ) in html


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
    # proves iter_tables recurses into a panel (legend placement keys off the first table)
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
    assert "Legend: badges used on this page" in html


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


def test_a_panel_inside_a_section_renders_as_a_card_in_the_section_body() -> None:
    panel = {"type": "panel", "title": "Card", "blocks": [{"type": "text", "body": "inside"}]}
    report = parse_report(make_report(blocks=[{"type": "section", "title": "Appendix", "blocks": [panel]}]))

    html = render_html(report)

    assert (
        '<details class="section" id="appendix"><summary>Appendix</summary><div class="section-body">'
        '<div class="panel-card"><div class="panel-card-hd">Card</div><div class="panel-card-body">'
        '<p class="text">inside</p></div></div>\n</div></details>'
    ) in html


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


def test_expand_forces_collapsed_sections_open_for_pdf() -> None:
    section = {"type": "section", "title": "S", "collapsed": True, "blocks": [{"type": "text", "body": "hi"}]}
    report = parse_report(make_report(blocks=[section]))

    # a collapsed section stays closed in the default render, but --pdf renders it open
    assert '<details class="section" id="s"><summary>S</summary>' in render_html(report)
    assert '<details class="section" id="s" open><summary>S</summary>' in render_html(report, expand=True)


def test_grid_cell_tone_renders_an_emphasis_panel() -> None:
    grid = make_grid([{"span": 6, "tone": "accent", "blocks": [{"type": "text", "body": "x"}]}])

    html = render_html(parse_report(make_report(blocks=[grid])))

    assert '<div class="cell span-6 panel accent">' in html


def test_author_id_becomes_the_heading_and_section_anchor() -> None:
    blocks = [
        {"type": "heading", "text": "Discrepancies & Fixes", "id": "fixes"},
        {"type": "section", "title": "Raw data", "id": "raw", "blocks": [{"type": "text", "body": "x"}]},
    ]

    html = render_html(parse_report(make_report(blocks=blocks)))

    assert '<h2 id="fixes">Discrepancies &amp; Fixes</h2>' in html
    assert '<details class="section" id="raw"' in html


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


def test_heading_inside_grid_gets_an_id() -> None:
    grid = make_grid([make_cell(6, [{"type": "heading", "text": "In Cell"}])])

    assert 'id="in-cell"' in render_html(parse_report(make_report(blocks=[grid])))


def test_heading_in_nested_grid_gets_an_id() -> None:
    inner = make_grid([make_cell(6, [{"type": "heading", "text": "Deep Head"}])])
    grid = make_grid([make_cell(6, [inner])])

    assert 'id="deep-head"' in render_html(parse_report(make_report(blocks=[grid])))


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
