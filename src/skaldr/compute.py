"""Derived, never-authored values: TOC, the used-badge legend, the provenance footer, and the
number/percent formatting helpers the templates call, so they can't drift from the data.

`col_sum` is re-exported from `models` (it lives there because `Table._reconcile` validates against
it, and models must not import compute) so templates can reach it through this one module.
"""

import re
from collections.abc import Iterator, Sequence
from typing import Any

from skaldr.models import (
    AnyBlock,
    Badge,
    Grid,
    Heading,
    InnerGrid,
    Report,
    Section,
    Table,
    col_sum,
    iter_reference_items,
    iter_referenced_badge_keys,
)

__all__ = [
    "col_sum",
    "first_table_index",
    "fmt",
    "heading_slugs",
    "pct",
    "provenance_footer",
    "reconcile_line",
    "reference_numbers",
    "toc_entries",
    "used_badges",
]

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


def _slugify(text: str) -> str:
    return _SLUG_STRIP.sub("-", text.lower()).strip("-") or "section"


def _iter_headings(blocks: Sequence[AnyBlock]) -> Iterator[Heading]:
    for block in blocks:
        if isinstance(block, Heading):
            yield block
        elif isinstance(block, Section):
            yield from _iter_headings(block.blocks)
        elif isinstance(block, (Grid, InnerGrid)):
            for cell in block.cells:
                yield from _iter_headings(cell.blocks)


def _iter_tables(blocks: Sequence[AnyBlock]) -> Iterator[Table]:
    for block in blocks:
        if isinstance(block, Table):
            yield block
        elif isinstance(block, Section):
            yield from _iter_tables(block.blocks)
        elif isinstance(block, (Grid, InnerGrid)):
            for cell in block.cells:
                yield from _iter_tables(cell.blocks)


def reference_numbers(report: Report) -> dict[str, int]:
    """`reference key -> 1-based number`, in document order across every `references` block, so an
    inline `[^key]` marker and its entry in the list carry the same number from one source. Keys are
    globally unique (a Report validator enforces it), so each contributes exactly one number."""
    numbers: dict[str, int] = {}
    for item in iter_reference_items(report.blocks):
        numbers[item.key] = len(numbers) + 1
    return numbers


def heading_slugs(report: Report) -> dict[int, str]:
    """`id(heading) -> slug`, de-duplicated with `-2` suffixes across every heading in document
    order. One source for both the heading `id` and the TOC so anchors can't drift."""
    slugs: dict[int, str] = {}
    seen: dict[str, int] = {}
    for heading in _iter_headings(report.blocks):
        base = _slugify(heading.text)
        seen[base] = seen.get(base, 0) + 1
        slugs[id(heading)] = base if seen[base] == 1 else f"{base}-{seen[base]}"
    return slugs


def toc_entries(report: Report, slugs: dict[int, str]) -> list[tuple[str, str]]:
    """(slug, text) for top-level level-2 headings, using the shared de-duplicated slugs."""
    if not report.meta.toc:
        return []
    return [
        (slugs[id(block)], block.text)
        for block in report.blocks
        if isinstance(block, Heading) and block.level == 2
    ]


def first_table_index(report: Report) -> int | None:
    """Index of the first top-level table block (the legend renders just before it)."""
    for index, block in enumerate(report.blocks):
        if isinstance(block, Table):
            return index
    return None


def used_badges(report: Report) -> list[tuple[str, Badge]]:
    """Declared badges that are actually referenced, in declaration order (drives the legend)."""
    referenced = set(iter_referenced_badge_keys(report.blocks))
    return [(key, badge) for key, badge in report.badges.items() if key in referenced]


def provenance_footer(report: Report) -> str | None:
    """Composed footer: meta source/date + each reconciled table's 'Reconciles: …' line."""
    parts = [part for part in (report.meta.source, report.meta.date) if part]
    parts.extend(
        reconcile_line(table) for table in _iter_tables(report.blocks) if table.reconcile is not None
    )
    return " · ".join(parts) if parts else None


def fmt(value: Any) -> str:
    """Thousands separators for ints/whole floats; strings pass through untouched."""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float):
        # Round first so summed float noise (100.00000000000001) reads as a clean count.
        rounded = round(value, 4)
        return f"{rounded:,.0f}" if rounded.is_integer() else f"{rounded:,}"
    return str(value)


def pct(value: float, of: float) -> str:
    ratio = value / of * 100
    if 0 < ratio < 0.1:
        return "<0.1%"
    return f"{ratio:.1f}%"


def reconcile_line(table: Table) -> str:
    if table.reconcile is None:
        return ""
    total = col_sum(table.all_rows(), table.reconcile.column)
    handled = table.reconcile.handled
    if handled is not None:
        return (
            f"Reconciles: {fmt(total)} + {fmt(handled.value)} {handled.label.lower()} "
            f"= {fmt(table.reconcile.total)}."
        )
    return f"Reconciles: {fmt(total)} = {fmt(table.reconcile.total)}."
