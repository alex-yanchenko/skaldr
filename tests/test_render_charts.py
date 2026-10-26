import re

import pytest

from skaldr.charts import DONUT_TOTAL_FONT_PX
from skaldr.models import parse_report
from skaldr.render import render_html
from tests.factories import make_report, markdown_of, notion_of
from tests.factories.render_factory import css_declarations


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


@pytest.mark.parametrize(
    ("largest", "ticks"),
    [
        pytest.param(1500, ["0", "500", "1k", "1.5k", "2k"], id="thousands"),
        pytest.param(1_000_000, ["0", "250k", "500k", "750k", "1M"], id="one-million"),
        pytest.param(2_500_000, ["0", "1.25M", "2.5M", "3.75M", "5M"], id="millions"),
        pytest.param(5_000_000_000, ["0", "1.25B", "2.5B", "3.75B", "5B"], id="billions"),
        pytest.param(0.05, ["0", "0.0125", "0.025", "0.0375", "0.05"], id="fractions"),
    ],
)
def test_chart_axis_ticks_use_k_m_and_b_for_large_values(largest: float, ticks: list[str]) -> None:
    block = {
        "type": "chart",
        "variant": "bar",
        "categories": ["A"],
        "series": [{"label": "S", "values": [largest]}],
    }

    html = render_html(parse_report(make_report(blocks=[block])))

    assert re.findall(r'<text class="c-tick"[^>]*>([^<]*)</text>', html) == ticks


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


@pytest.mark.parametrize(
    ("values", "total"),
    [
        pytest.param([1.25, 1233.31], "1,234.56", id="two-decimals"),
        pytest.param([5.25, 5], "10.25", id="decimal-plus-whole"),
        pytest.param([60, 40], "100", id="whole"),
        pytest.param([0.1, 0.2], "0.3", id="float-noise-rounded-away"),
    ],
)
def test_a_donut_centre_total_reads_the_same_as_the_total_both_exports_write(
    values: list[float], total: str
) -> None:
    donut = {
        "type": "chart",
        "variant": "donut",
        "slices": [{"label": f"S{index}", "value": value} for index, value in enumerate(values)],
    }

    centre = re.search(
        r'<text class="c-total"[^>]*>([^<]*)</text>', render_html(parse_report(make_report(blocks=[donut])))
    )
    markdown_total = re.search(r"^\| \*\*Total\*\* \| \*\*([^*]*)\*\* \|", markdown_of([donut]), re.MULTILINE)
    notion_total = re.search(r"<td>\*\*Total\*\*</td>\s*<td>\*\*([^*]*)\*\*</td>", notion_of([donut]))

    assert tuple(match.group(1) if match else None for match in (centre, markdown_total, notion_total)) == (
        total,
        total,
        total,
    )


CENTRE_TOTAL_ATTRIBUTES = 'class="c-total" text-anchor="middle" dominant-baseline="middle" y="-7"'


CENTRE_TOTAL_FITTED_TO_THE_HOLE = 'textLength="86" lengthAdjust="spacingAndGlyphs"'


@pytest.mark.parametrize(
    ("values", "centre"),
    [
        pytest.param([60, 40], f"<text {CENTRE_TOTAL_ATTRIBUTES}>100</text>", id="short"),
        pytest.param([5.25, 5], f"<text {CENTRE_TOTAL_ATTRIBUTES}>10.25</text>", id="short-decimal"),
        pytest.param([12000, 345], f"<text {CENTRE_TOTAL_ATTRIBUTES}>12,345</text>", id="widest-natural"),
        pytest.param(
            [1.25, 1233.31],
            f"<text {CENTRE_TOTAL_ATTRIBUTES} {CENTRE_TOTAL_FITTED_TO_THE_HOLE}>1,234.56</text>",
            id="narrowest-fitted",
        ),
        pytest.param(
            [123000, 456.78],
            f"<text {CENTRE_TOTAL_ATTRIBUTES} {CENTRE_TOTAL_FITTED_TO_THE_HOLE}>123,456.78</text>",
            id="long",
        ),
        pytest.param(
            [12345678.9],
            f"<text {CENTRE_TOTAL_ATTRIBUTES} {CENTRE_TOTAL_FITTED_TO_THE_HOLE}>12,345,678.9</text>",
            id="longest",
        ),
    ],
)
def test_a_long_donut_centre_total_is_fitted_to_the_hole_and_a_short_one_keeps_its_size(
    values: list[float], centre: str
) -> None:
    donut = {
        "type": "chart",
        "variant": "donut",
        "slices": [{"label": f"S{index}", "value": value} for index, value in enumerate(values)],
    }

    html = render_html(parse_report(make_report(blocks=[donut])))

    assert re.findall(r'<text class="c-total"[^>]*>[^<]*</text>', html) == [centre]


def test_the_donut_centre_total_is_styled_at_the_font_size_its_fit_is_estimated_for() -> None:
    html = render_html(parse_report(make_report()))

    assert css_declarations(html, "& .c-total") == [
        f"fill:var(--ink);font-size:{DONUT_TOTAL_FONT_PX}px;font-weight:700"
    ]


def test_chart_escapes_author_category_labels() -> None:
    block = {
        "type": "chart",
        "variant": "bar",
        "categories": ["<x>"],
        "series": [{"label": "S", "values": [1]}],
    }
    html = render_html(parse_report(make_report(blocks=[block])))

    assert "&lt;x&gt;" in html  # the label is escaped inside the SVG <text>, never raw markup


def _bar_chart_at_the_bound(**overrides: object) -> dict[str, object]:
    return {
        "type": "chart",
        "variant": "bar",
        "categories": ["a"],
        "series": [{"label": "s0", "values": [1e300]}, {"label": "s1", "values": [1e300]}],
        **overrides,
    }


@pytest.mark.parametrize(
    "block",
    [
        pytest.param(_bar_chart_at_the_bound(), id="grouped-bars"),
        pytest.param(_bar_chart_at_the_bound(stacked=True), id="stacked-bars"),
        pytest.param(_bar_chart_at_the_bound(variant="line"), id="lines"),
        pytest.param(
            {
                "type": "chart",
                "variant": "donut",
                "slices": [{"label": "a", "value": 1e300}, {"label": "b", "value": 1e300}],
            },
            id="donut",
        ),
    ],
)
def test_a_chart_of_the_largest_numbers_skaldr_accepts_still_renders(block: dict[str, object]) -> None:
    html = render_html(parse_report(make_report(blocks=[block])))

    assert html.count('role="img"') == 1
