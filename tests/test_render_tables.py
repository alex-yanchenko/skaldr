import re

import pytest

from skaldr.models import Report, parse_report
from skaldr.render import render_html
from tests.factories import (
    make_cell,
    make_grid,
    make_label_table,
    make_reconciled_table,
    make_report,
    make_table,
)
from tests.factories.render_factory import css_declarations


def test_a_labelled_badge_column_without_a_placement_is_its_own_html_column() -> None:
    table = {
        "type": "table",
        "columns": [
            {"key": "name", "label": "View"},
            {"key": "access", "label": "Access", "kind": "badge"},
            {"key": "status", "label": "", "kind": "badge"},
        ],
        "rows": [{"name": "One", "access": "WRITE", "status": "LIVE"}],
    }
    badges = {
        "WRITE": {"label": "Write", "tone": "blue", "legend": "Read-write."},
        "LIVE": {"label": "Live", "tone": "green", "legend": "In production."},
    }

    html = render_html(parse_report(make_report(badges=badges, blocks=[table])))

    assert "<thead><tr><th>View</th><th>Access</th></tr></thead>" in html
    assert '<td class="bc"><span class="chip blue">Write</span></td>' in html
    assert '<div><span class="chip green">Live</span></div>' in html


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


def test_table_column_without_kind_renders_as_a_text_title_column() -> None:
    # {key, label} with no kind is a text column — it becomes the title cell, no boilerplate needed
    table = {
        "type": "table",
        "columns": [{"key": "flag", "label": "Flag"}, {"key": "n", "label": "N", "kind": "number"}],
        "rows": [{"flag": "overflow", "n": 4}],
    }

    html = render_html(parse_report(make_report(blocks=[table])))

    assert '<thead><tr><th>Flag</th><th class="num">N</th></tr></thead>' in html
    assert '<td class="title">overflow' in html


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


_OPS_BADGES = {"OPS": {"label": "Ops", "tone": "blue", "legend": "Operations."}}


_OPS_LEGEND_ROW = (
    '<div class="legend-row"><span class="chip blue">Ops</span><span class="meaning">Operations.</span></div>'
)


def _rendered_one_row_badge_table(value: object, placement: str) -> str:
    table = make_table(
        columns=[
            {"key": "name", "label": "Name", "kind": "text"},
            {"key": "tag", "label": "Tag", "kind": "badge", "placement": placement},
        ],
        rows=[{"name": "Row one", "tag": value}],
    )
    return render_html(parse_report(make_report(badges=_OPS_BADGES, blocks=[table])))


def _tbody(html: str) -> str:
    match = re.search(r"<tbody>.*?</tbody>", html, re.S)
    assert match is not None
    return match.group(0)


@pytest.mark.parametrize(
    ("value", "placement", "expected_tbody"),
    [
        pytest.param(
            " OPS ",
            "cell",
            '<tbody>\n<tr class="row">\n<td class="title">Row one\n</td>\n'
            '<td class="bc"><span class="chip blue">Ops</span></td>\n</tr>\n</tbody>',
            id="cell",
        ),
        pytest.param(
            [" OPS "],
            "cell",
            '<tbody>\n<tr class="row">\n<td class="title">Row one\n</td>\n'
            '<td class="bc"><span class="chip blue">Ops</span></td>\n</tr>\n</tbody>',
            id="cell-list",
        ),
        pytest.param(
            " OPS ",
            "title",
            '<tbody>\n<tr class="row">\n<td class="title">Row one\n'
            '<div><span class="chip blue">Ops</span></div></td>\n</tr>\n</tbody>',
            id="title",
        ),
    ],
)
def test_padded_table_badge_key_validates_and_renders_the_declared_badge(
    value: object, placement: str, expected_tbody: str
) -> None:
    html = _rendered_one_row_badge_table(value, placement)

    assert (_tbody(html), _OPS_LEGEND_ROW in html) == (expected_tbody, True)


@pytest.mark.parametrize(
    ("placement", "expected_tbody"),
    [
        pytest.param(
            "cell",
            '<tbody>\n<tr class="row">\n<td class="title">Row one\n</td>\n'
            '<td class="bc"></td>\n</tr>\n</tbody>',
            id="cell",
        ),
        pytest.param(
            "title",
            '<tbody>\n<tr class="row">\n<td class="title">Row one\n</td>\n</tr>\n</tbody>',
            id="title",
        ),
    ],
)
def test_blank_table_badge_key_renders_no_chip_and_no_legend(placement: str, expected_tbody: str) -> None:
    html = _rendered_one_row_badge_table("  ", placement)

    assert (_tbody(html), _OPS_LEGEND_ROW in html) == (expected_tbody, False)


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


@pytest.mark.parametrize(
    ("detail", "cell"),
    [
        pytest.param(
            "Steps:\n- `a`\n- b",
            '<td><p class="cell-p">Steps:</p><ul class="list"><li><code>a</code></li><li>b</li></ul></td>',
            id="bullets",
        ),
        pytest.param(
            "2. b\n3. c", '<td><ol class="list" start="2"><li>b</li><li>c</li></ol></td>', id="numbers"
        ),
    ],
)
def test_a_rich_cell_holding_list_lines_renders_a_list(detail: str, cell: str) -> None:
    html = render_html(parse_report(make_report(blocks=[_cell_table(detail)])))

    assert cell in html


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


def test_totals_footer_labels_the_first_cell_that_is_not_the_summed_column() -> None:
    table = {
        "type": "table",
        "columns": [
            {"key": "count", "label": "C", "kind": "number"},
            {"key": "issue", "label": "I", "kind": "text"},
            {"key": "note", "label": "N", "kind": "text"},
        ],
        "rows": [{"count": 10, "issue": "a", "note": "x"}, {"count": 5, "issue": "b", "note": "y"}],
        "totals": {"column": "count"},
    }
    report = parse_report(make_report(blocks=[table]))

    footer = re.search(r"<tfoot>.*?</tfoot>", render_html(report))

    assert footer is not None
    assert footer.group(0) == '<tfoot><tr><td class="num">15</td><td>Total</td><td></td></tr></tfoot>'


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


def test_a_padded_badge_key_still_tints_the_row_and_feeds_the_rollup() -> None:
    table = make_table(
        columns=[
            {"key": "item", "label": "Item", "kind": "text"},
            {"key": "status", "label": "", "kind": "badge"},
        ],
        rows=[{"item": "a", "status": " DONE "}, {"item": "b", "status": " DONE "}],
        tint_by="status",
        rollup={"by": "status"},
    )
    badges = {"DONE": {"label": "Done", "tone": "success", "legend": "finished"}}

    html = render_html(parse_report(make_report(blocks=[table], badges=badges)))

    assert (html.count('<tr class="row tint green">'), '<span class="rollup-n">2</span>' in html) == (2, True)


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


@pytest.mark.parametrize(
    ("columns", "colgroup"),
    [
        pytest.param(
            [{"key": "a", "label": "A"}, {"key": "b", "label": "B", "kind": "number", "tone": "success"}],
            '<colgroup><col><col class="tint success" style="width:10%"></colgroup>',
            id="beside-the-default-widths",
        ),
        pytest.param(
            [
                {"key": "a", "label": "A", "width": 2},
                {"key": "b", "label": "B", "kind": "number", "tone": "success", "width": 4},
            ],
            '<colgroup><col style="width:33.3%"><col class="tint success" style="width:66.7%"></colgroup>',
            id="beside-weighted-widths",
        ),
    ],
)
def test_a_toned_column_tints_its_col(columns: list[dict[str, object]], colgroup: str) -> None:
    table = make_table(columns, rows=[{"a": "x", "b": 10}])

    html = render_html(parse_report(make_report(blocks=[table])))

    assert colgroup in html


def test_the_stylesheet_paints_a_col_by_its_tone_class() -> None:
    html = render_html(parse_report(make_report()))

    assert css_declarations(html, "& col.tint.success") == ["--tb:var(--success-bg)"]


def test_a_muted_row_paints_opaque_cells_over_a_column_tint() -> None:
    html = render_html(parse_report(make_report()))

    assert {
        selector: css_declarations(html, selector)
        for selector in (
            "& tbody tr.row.muted",
            "& tbody tr.row.muted td",
            "& tbody tr.row.muted td::after",
        )
    } == {
        "& tbody tr.row.muted": [],
        "& tbody tr.row.muted td": [
            "position:relative;background-color:var(--surface);"
            "border-block-end-color:color-mix(insrgb,var(--line)55%,var(--surface))"
        ],
        "& tbody tr.row.muted td::after": [
            'content:"";position:absolute;inset:0;background:var(--surface);opacity:0.45;pointer-events:none'
        ],
    }


def test_a_row_hover_lays_a_translucent_wash_over_the_cell_so_a_column_tint_shows_through() -> None:
    html = render_html(parse_report(make_report()))

    assert (
        css_declarations(html, "& tbody tr.row:hover td"),
        css_declarations(html, "& tbody tr.row:hover > td"),
    ) == ([], ["background-image:linear-gradient(var(--row-hover),var(--row-hover))"])
    assert (
        "--row-hover:light-dark(color-mix(insrgb,var(--ink)3%,transparent),"
        "color-mix(insrgb,var(--ink)5%,transparent));" in re.sub(r"\s+", "", html)
    )


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
    assert '<tr class="empty"><td colspan="2">none</td></tr></tbody>' in html
    assert "</table></div>" in html


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


@pytest.mark.parametrize(
    ("count", "width"),
    [
        pytest.param(9, "10", id="nine-numbers-keep-the-default"),
        pytest.param(10, "9.1", id="ten-numbers-scale-to-elevenths"),
        pytest.param(12, "7.7", id="twelve-numbers-scale-to-thirteenths"),
    ],
)
def test_number_columns_too_many_for_their_default_width_scale_down_beside_the_label(
    count: int, width: str
) -> None:
    html = render_html(parse_report(make_report(blocks=[make_label_table(["number"] * count)])))

    cols = f'<col style="width:{width}%">' * count
    assert f"<colgroup><col>{cols}</colgroup>" in html


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
