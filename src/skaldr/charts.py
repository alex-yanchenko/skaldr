"""Chart geometry → inline SVG. Self-contained: the author supplies data, skaldr computes every
coordinate here (scales, ticks, gridlines, bar rects, smoothed line paths, donut arcs) and emits an
`<svg>` with no script and no external reference. Colours route through the palette tokens; any
author-supplied text (category labels) is escaped before it reaches the markup.

Kept separate from `compute` because it is a self-contained geometry unit with no report-wide state.
"""

import math
from typing import TypedDict, assert_never

from markupsafe import Markup, escape

from skaldr.models import Chart, Tone


class LegendRow(TypedDict):
    label: str
    colour: str
    note: str | None  # a derived share (donut) or None (bar/line)


# Plot box for bar/line (viewBox units). The left gutter holds y-tick labels; the baseline sits
# above a strip for the x-axis category labels.
_W, _H = 460, 210
_AX_L, _AX_R, _TOP, _BASE = 46, 452, 12, 176
_PLOT_W, _PLOT_H = _AX_R - _AX_L, _BASE - _TOP
_XLBL_Y = 195
# Donut box.
_D_CX, _D_CY, _D_R, _D_SW = 105, 100, 62, 26

# When a series/slice gives no tone, colour it from this cycle so multiple series stay distinct
# without the author naming a colour for each (derived-not-authored).
_CYCLE: tuple[Tone, ...] = ("info", "success", "warning", "danger", "accent", "neutral")


def _fill(tone: Tone | None, index: int) -> str:
    return f"var(--{tone or _CYCLE[index % len(_CYCLE)]}-fg)"


def _nice_max(value: float) -> float:
    """Smallest 'round' number (1/2/5 x 10^n) at least as large as `value` — the y-axis top, so
    gridlines land on readable ticks."""
    if value <= 0:
        return 1.0
    magnitude = 10 ** math.floor(math.log10(value))
    for step in (1, 2, 5, 10):
        if value <= step * magnitude:
            return float(step * magnitude)
    return float(10 * magnitude)


def _tick(value: float) -> str:
    """Compact axis-tick text: 1500 → '1.5k', 2000 → '2k', 250 → '250'."""
    if value >= 1000:
        return f"{value / 1000:g}k"
    return f"{value:g}"


def _smooth(points: list[tuple[float, float]]) -> str:
    """A path `d` that curves smoothly through every point (Catmull-Rom → cubic Bézier). A polyline
    would show sharp vertices that `stroke-linejoin` can't soften on a thin line; this reads as one
    flowing line."""
    if len(points) < 2:  # a lone point (single-category line): just a move-to, drawn as its end dot
        return f"M{points[0][0]:.1f},{points[0][1]:.1f}"
    padded = [points[0], *points, points[-1]]
    parts = [f"M{points[0][0]:.1f},{points[0][1]:.1f}"]
    for i in range(1, len(padded) - 2):
        p0, p1, p2, p3 = padded[i - 1], padded[i], padded[i + 1], padded[i + 2]
        c1x, c1y = p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6
        c2x, c2y = p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6
        parts.append(f"C{c1x:.1f},{c1y:.1f} {c2x:.1f},{c2y:.1f} {p2[0]:.1f},{p2[1]:.1f}")
    return " ".join(parts)


def _grid_and_ticks(top: float) -> list[str]:
    out: list[str] = []
    for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
        y = _BASE - frac * _PLOT_H
        out.append(f'<line class="c-gl" x1="{_AX_L}" y1="{y:.1f}" x2="{_AX_R}" y2="{y:.1f}"/>')
        label = _tick(frac * top)
        out.append(f'<text class="c-tick" x="{_AX_L - 6}" y="{y + 3:.1f}" text-anchor="end">{label}</text>')
    return out


def _x_labels(categories: list[str], centers: list[float]) -> list[str]:
    return [
        f'<text class="c-axlbl" x="{cx:.1f}" y="{_XLBL_Y}" text-anchor="middle">{escape(cat)}</text>'
        for cat, cx in zip(categories, centers, strict=True)
    ]


def _bar_svg(chart: Chart) -> str:
    n, m = len(chart.categories), len(chart.series)
    step = _PLOT_W / n
    body: list[str] = []
    if chart.stacked:
        top = _nice_max(max(sum(series.values[i] for series in chart.series) for i in range(n)))
        bar_w = min(step * 0.5, 56)
        for i in range(n):
            x = _AX_L + i * step + (step - bar_w) / 2
            cum = 0.0
            for j, series in enumerate(chart.series):
                h = series.values[i] / top * _PLOT_H
                y = _BASE - cum - h
                body.append(
                    f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" '
                    f'height="{h:.1f}" fill="{_fill(series.tone, j)}"/>'
                )
                cum += h
    else:
        top = _nice_max(max(max(series.values) for series in chart.series))
        pad = step * 0.16
        bar_w = (step - 2 * pad) / m
        for i in range(n):
            gx = _AX_L + i * step + pad
            for j, series in enumerate(chart.series):
                h = series.values[i] / top * _PLOT_H
                x = gx + j * bar_w
                body.append(
                    f'<rect x="{x + bar_w * 0.09:.1f}" y="{_BASE - h:.1f}" width="{bar_w * 0.82:.1f}" '
                    f'height="{h:.1f}" rx="2" fill="{_fill(series.tone, j)}"/>'
                )
    centers = [_AX_L + (i + 0.5) * step for i in range(n)]
    return _svg(_grid_and_ticks(top) + body + _x_labels(chart.categories, centers))


def _line_svg(chart: Chart) -> str:
    n, m = len(chart.categories), len(chart.series)
    top = _nice_max(max(max(series.values) for series in chart.series))
    step = _PLOT_W / n
    xs = [_AX_L + (i + 0.5) * step for i in range(n)]
    body: list[str] = []
    for j, series in enumerate(chart.series):
        pts = [(xs[i], _BASE - series.values[i] / top * _PLOT_H) for i in range(n)]
        path = _smooth(pts)
        colour = _fill(series.tone, j)
        if m == 1:  # a lone series gets a soft area fill; overlapping fills would muddy each other
            close = f"L{xs[-1]:.1f},{_BASE} L{xs[0]:.1f},{_BASE} Z"
            body.append(f'<path d="{path} {close}" fill="{colour}" opacity="0.10"/>')
        body.append(
            f'<path d="{path}" fill="none" stroke="{colour}" stroke-width="2.5" stroke-linecap="round"/>'
        )
        body.append(f'<circle cx="{pts[-1][0]:.1f}" cy="{pts[-1][1]:.1f}" r="3.5" fill="{colour}"/>')
    return _svg(_grid_and_ticks(top) + body + _x_labels(chart.categories, xs))


def _donut_svg(chart: Chart) -> str:
    circ = 2 * math.pi * _D_R
    total = sum(segment.value for segment in chart.slices)
    body = [f'<circle r="{_D_R}" fill="none" stroke="var(--panel)" stroke-width="{_D_SW}"/>']
    offset = 0.0
    for i, segment in enumerate(chart.slices):
        dash = segment.value / total * circ
        body.append(
            f'<circle r="{_D_R}" fill="none" stroke="{_fill(segment.tone, i)}" stroke-width="{_D_SW}" '
            f'stroke-dasharray="{dash:.2f} {circ - dash:.2f}" stroke-dashoffset="{-offset:.2f}" '
            'transform="rotate(-90)"/>'
        )
        offset += dash
    centre = escape(_format_total(total))
    body.append(
        f'<text class="c-total" text-anchor="middle" dominant-baseline="middle" y="-7">{centre}</text>'
    )
    body.append('<text class="c-totlbl" text-anchor="middle" dominant-baseline="middle" y="17">TOTAL</text>')
    inner = "".join(body)
    return (
        f'<svg viewBox="0 0 210 200" role="img" preserveAspectRatio="xMidYMid meet">'
        f'<g transform="translate({_D_CX},{_D_CY})">{inner}</g></svg>'
    )


def _format_total(value: float) -> str:
    """Thousands-separated integer if whole, else one decimal — for the donut centre total."""
    return f"{value:,.0f}" if value == int(value) else f"{value:,.1f}"


def _svg(children: list[str]) -> str:
    # No preserveAspectRatio override: with width:100%/height:auto the viewBox scales uniformly, so
    # circles/text/bars keep their proportions at any container width.
    return f'<svg viewBox="0 0 {_W} {_H}" role="img">{"".join(children)}</svg>'


def chart_svg(chart: Chart) -> Markup:
    """The `<svg>` for a chart block. Safe to emit directly — geometry is computed and any author
    text is escaped in the builders above."""
    if chart.variant == "bar":
        return Markup(_bar_svg(chart))
    if chart.variant == "line":
        return Markup(_line_svg(chart))
    if chart.variant == "donut":
        return Markup(_donut_svg(chart))
    assert_never(chart.variant)


def chart_legend(chart: Chart) -> list[LegendRow]:
    """Legend rows (label + resolved colour + optional share note). Colours come from the SAME
    `_fill` cycle the SVG uses, so a legend swatch always matches its series/slice."""
    if chart.variant == "donut":
        total = sum(segment.value for segment in chart.slices)
        return [
            {
                "label": segment.label,
                "colour": _fill(segment.tone, i),
                "note": f"{segment.value / total * 100:.0f}%",
            }
            for i, segment in enumerate(chart.slices)
        ]
    return [
        {"label": series.label, "colour": _fill(series.tone, i), "note": None}
        for i, series in enumerate(chart.series)
    ]
