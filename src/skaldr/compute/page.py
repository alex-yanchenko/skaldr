import re
import string
import unicodedata
from collections import Counter
from collections.abc import Iterator, Mapping, Sequence
from functools import cache
from typing import Any, Final, Literal, NamedTuple, TypedDict, cast, get_args, get_type_hints
from urllib.parse import quote, urlsplit

import roman
from pydantic import BaseModel
from typing_extensions import assert_never

from skaldr.errors import ReportError
from skaldr.models import (
    AnyBlock,
    Badge,
    BadgeColorLiteral,
    Card,
    DeltaDirection,
    FieldPath,
    Heading,
    Link,
    ListNumbering,
    Matrix,
    MatrixCell,
    Part,
    Report,
    RichTextMarker,
    Row,
    Section,
    SectionFields,
    StatusState,
    Table,
    col_sum,
    fact_label,
    iter_matrices,
    iter_reference_items,
    iter_referenced_badge_keys,
    iter_tables,
    walk_blocks,
)
from skaldr.prose_blocks import rendered_strings
from skaldr.richtext import PartAnchor, RichContext, parse_rich

_SLUG_CATEGORIES = frozenset("LNM")
_SLUG_SEPARATORS = re.compile(r"-+")

SOURCE_BLOCK_ID = "skaldr-source"
SETTINGS_MENU_ID = "sc-menu"
CONTENTS_PANEL_ID = "skaldr-contents"


def _kept_in_a_slug(character: str) -> bool:
    return unicodedata.category(character)[0] in _SLUG_CATEGORIES


def _slugify(text: str) -> str:
    lowered = unicodedata.normalize("NFC", text).lower()
    marked = "".join(character if _kept_in_a_slug(character) else "-" for character in lowered)
    return _SLUG_SEPARATORS.sub("-", marked).strip("-") or "section"


def _page_ids(report: Report) -> set[str]:
    reference_ids = (
        anchor
        for item in iter_reference_items(report.blocks)
        for anchor in (f"ref-{item.key}", f"fnref-{item.key}")
    )
    return {SOURCE_BLOCK_ID, SETTINGS_MENU_ID, CONTENTS_PANEL_ID, *reference_ids}


Anchored = Heading | Section | Part


def _iter_anchored(blocks: Sequence[AnyBlock]) -> Iterator[Anchored]:
    """Headings (any level, nested), sections and parts, in document order: the blocks that carry an
    anchor id and can appear in the TOC. A section or part yields itself, then its inner headings."""
    for block in walk_blocks(blocks):
        if isinstance(block, (Heading, Section, Part)):
            yield block


def _explicit_anchor(block: Anchored) -> str | None:
    return None if isinstance(block, Part) else block.id


def reference_numbers(report: Report) -> dict[str, int]:
    """`reference key -> 1-based number`, in document order across every `references` block, so an
    inline `[^key]` marker and its entry in the list carry the same number from one source. Keys are
    globally unique (a Report validator enforces it), so each contributes exactly one number."""
    numbers: dict[str, int] = {}
    for item in iter_reference_items(report.blocks):
        numbers[item.key] = len(numbers) + 1
    return numbers


def anchor_slugs(report: Report) -> dict[int, str]:
    """`id(block) -> slug` for every heading and section, in document order. One source for the
    heading/section `id` attribute, the TOC, and same-page `#link` targets so they can't drift. An
    author-set `id` is used verbatim (and reserved so a text-derived slug yields to it with a `-N`
    suffix); a text-derived slug de-dups the same way. Duplicate author ids fail validation."""
    anchored = list(_iter_anchored(report.blocks))
    explicit = [anchor for anchor in map(_explicit_anchor, anchored) if anchor is not None]
    page_ids = _page_ids(report)
    reserved = next((anchor for anchor in explicit if anchor in page_ids), None)
    if reserved is not None:
        raise ReportError(
            f"anchor id '{reserved}' is one the page itself uses (the source block, the settings menu, the "
            "contents panel, or a reference and its citation); give the heading or section another id"
        )

    slugs: dict[int, str] = {}
    taken: set[str] = set(explicit) | page_ids
    for block in anchored:
        explicit_anchor = _explicit_anchor(block)
        if explicit_anchor is not None:
            slugs[id(block)] = explicit_anchor
            continue
        base = _slugify(block.text if isinstance(block, Heading) else block.title)
        slug, suffix = base, 1
        while slug in taken:
            suffix += 1
            slug = f"{base}-{suffix}"
        taken.add(slug)
        slugs[id(block)] = slug
    return slugs


def part_anchors(report: Report, slugs: dict[int, str]) -> dict[str, PartAnchor]:
    return {
        block.doc_id: PartAnchor(
            slugs[id(block)],
            frozenset(
                inner.id
                for inner in walk_blocks(block.blocks)
                if isinstance(inner, Section) and inner.id is not None
            ),
        )
        for block in report.blocks
        if isinstance(block, Part) and block.doc_id is not None
    }


def toc_entries(report: Report, slugs: dict[int, str]) -> list[tuple[str, str]]:
    """(slug, text) for top-level level-2 headings, sections and parts, in document order: the TOC
    targets. A section or part is a top-level region, so it earns a TOC entry and its own anchor."""
    if not report.meta.toc:
        return []
    entries: list[tuple[str, str]] = []
    for block in report.blocks:
        if isinstance(block, Heading) and block.level == 2:
            entries.append((slugs[id(block)], block.text))
        elif isinstance(block, Section | Part):
            entries.append((slugs[id(block)], block.title))
    return entries


def first_table_index(report: Report) -> int | None:
    """Index of the first top-level table block (the legend renders just before it)."""
    for index, block in enumerate(report.blocks):
        if isinstance(block, Table):
            return index
    return None


def badge_legend_slot(report: Report) -> int:
    table_index = first_table_index(report)
    return 0 if table_index is None else table_index


BADGE_LEGEND_SUBJECT: Final = "badges used on this page"


def used_badges(report: Report) -> list[tuple[str, Badge]]:
    """Declared badges that are actually referenced AND carry a legend, in declaration order (drives the
    legend). A badge with `legend: false` opts out — its chips still render, but it never lists."""
    referenced = set(iter_referenced_badge_keys(report.blocks))
    return [
        (key, badge)
        for key, badge in report.badges.items()
        if key in referenced and badge.legend is not False
    ]


DELTA_GLYPHS: Final[Mapping[DeltaDirection, str]] = {"up": "▲", "down": "▼", "flat": "→"}


class StatusGlyph(NamedTuple):
    page: str
    export: str


STATUS_GLYPHS: Final[Mapping[StatusState, StatusGlyph]] = {
    "done": StatusGlyph("✓", "✅"),
    "current": StatusGlyph("◐", "🔵"),
    "pending": StatusGlyph("○", "⚪"),
    "failed": StatusGlyph("✗", "❌"),
    "blocked": StatusGlyph("⏸", "⏸️"),
}


def favicon_href(icon: str) -> str:
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
        f'<text y=".9em" font-size="90">{icon}</text></svg>'
    )
    return "data:image/svg+xml," + quote(svg)


class LinkCard(NamedTuple):
    url: str
    title: str
    domain: str | None
    caption: str | None


def link_card(block: Link) -> LinkCard:
    if block.title is not None:
        return LinkCard(block.url, block.title, urlsplit(block.url).hostname, block.caption)
    return LinkCard(block.url, block.url.split("://", 1)[1], None, block.caption)


class Provenance(NamedTuple):
    source: str | None
    facts: tuple[str, ...]


def provenance_footer(report: Report) -> Provenance | None:
    """Composed footer: meta source/date/updated + each reconciled table's 'Reconciles: …' line."""
    facts = [report.meta.date] if report.meta.date else []
    if report.meta.updated:
        facts.append(f"updated {report.meta.updated}")
    facts.extend(reconcile_line(table) for table in iter_tables(report.blocks) if table.reconcile is not None)
    source = report.meta.source if report.meta.source and report.meta.source.strip() else None
    return Provenance(source, tuple(facts)) if source or facts else None


def _parsed_strings(text: str, marker: RichTextMarker, path: FieldPath) -> list[str]:
    if not marker.split_into_paragraphs:
        return [text]
    try:
        return rendered_strings(text)
    except ReportError as error:
        raise ReportError(f"{'.'.join(path)}: {error}") from error


def _rich_text_marker(hint: object) -> RichTextMarker | None:
    for argument in get_args(hint):
        found = argument if isinstance(argument, RichTextMarker) else _rich_text_marker(argument)
        if found is not None:
            return found
    return None


@cache
def _rich_field_markers(model: type[BaseModel]) -> Mapping[str, RichTextMarker | None]:
    hints = get_type_hints(model, include_extras=True)
    return {name: _rich_text_marker(hints[name]) for name in model.model_fields}


def _rich_texts(
    value: object, path: FieldPath, marker: RichTextMarker | None
) -> Iterator[tuple[FieldPath, str]]:
    if isinstance(value, str):
        if marker is not None:
            yield from ((path, piece) for piece in _parsed_strings(value, marker, path))
    elif isinstance(value, Table):
        for cell_path, text, cell_marker in value.rich_cells():
            cell_field = (*path, *cell_path)
            yield from ((cell_field, piece) for piece in _parsed_strings(text, cell_marker, cell_field))
        yield from _rich_model_texts(value, path)
    elif isinstance(value, BaseModel):
        yield from _rich_model_texts(value, path)
    elif isinstance(value, list):
        for index, item in enumerate(cast("list[object]", value)):
            yield from _rich_texts(item, (*path, str(index)), marker)


def _rich_model_texts(model: BaseModel, path: FieldPath) -> Iterator[tuple[FieldPath, str]]:
    for name, marker in _rich_field_markers(type(model)).items():
        yield from _rich_texts(getattr(model, name), (*path, name), marker)


def rich_text_strings(report: Report) -> Iterator[tuple[FieldPath, str]]:
    return _rich_model_texts(report, ())


def validate_rich_text_fields(report: Report, context: RichContext) -> None:
    for path, text in rich_text_strings(report):
        try:
            parse_rich(text, context)
        except ReportError as error:
            raise ReportError(f"{'.'.join(path)}: {error}") from error


def url_host(url: str) -> str:
    return urlsplit(url).netloc


FactValueKind = Literal["chip", "person", "date", "text", "link"]


class FactValue(NamedTuple):
    kind: FactValueKind
    text: str
    tone: BadgeColorLiteral | None = None
    anchor: str | None = None


class SectionFact(NamedTuple):
    label: str
    values: tuple[FactValue, ...]


def section_titles_by_id(report: Report) -> dict[str, str]:
    return {
        block.id: block.title
        for _, block in report.located_blocks
        if isinstance(block, Section) and block.id is not None
    }


def plain_number(value: str | int | float) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _extra_fact_value(value: str | int | float) -> FactValue:
    return FactValue("chip", plain_number(value), "slate")


def section_facts(fields: SectionFields, titles: Mapping[str, str]) -> tuple[SectionFact, ...]:
    facts: list[SectionFact] = []
    if fields.status is not None:
        facts.append(SectionFact("Status", (FactValue("chip", fields.status, "blue"),)))
    if fields.priority is not None:
        facts.append(SectionFact("Priority", (FactValue("chip", fields.priority, "amber"),)))
    if fields.assignee is not None:
        facts.append(SectionFact("Assignee", (FactValue("person", fields.assignee),)))
    if fields.due is not None:
        facts.append(SectionFact("Due", (FactValue("date", fields.due.isoformat()),)))
    if fields.labels is not None:
        facts.append(
            SectionFact("Labels", tuple(FactValue("chip", label, "slate") for label in fields.labels))
        )
    if fields.estimate is not None:
        facts.append(SectionFact("Estimate", (FactValue("text", plain_number(fields.estimate)),)))
    for link_type, targets in fields.links.items():
        facts.append(
            SectionFact(
                fact_label(link_type),
                tuple(FactValue("link", titles[target], anchor=target) for target in targets),
            )
        )
    for name, value in fields.extras.items():
        values = value if isinstance(value, list) else [value]
        facts.append(SectionFact(name, tuple(_extra_fact_value(item) for item in values)))
    return tuple(facts)


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


LATIN_ALPHABET_SIZE: Final = len(string.ascii_lowercase)
CSS_LOWER_ROMAN_RANGE: Final = range(1, 4000)


def _letters_label(index: int) -> str:
    label = ""
    while index:
        index, place = divmod(index - 1, LATIN_ALPHABET_SIZE)
        label = string.ascii_lowercase[place] + label
    return label


def list_label(index: int, numbering: ListNumbering) -> str:
    match numbering:
        case "letters":
            return _letters_label(index)
        case "roman" if index in CSS_LOWER_ROMAN_RANGE:
            return roman.toRoman(index).lower()
        case "roman" | "decimal":
            return str(index)
        case _:
            assert_never(numbering)


def pct(value: float, of: float) -> str:
    ratio = value / of * 100
    if 0 < ratio < 0.1:
        return "<0.1%"
    return f"{ratio:.1f}%"


class RollupBucket(TypedDict):
    key: str  # a badge key, resolved to its chip label/tone at render time
    count: int


def _rollup_counts(rows: Sequence[Row], by: str) -> Counter[str]:
    """Count rows by a badge column's value, in first-appearance order (a blank cell counts toward no
    badge). The one tally rule shared by a table's own `rollup` strip and its `of_tables` contribution,
    so the two views of the same table can never drift apart."""
    counts: Counter[str] = Counter()
    for row in rows:
        key = row.first_badge(by)
        if key:
            counts[key] += 1
    return counts


def table_rollup(table: Table) -> list[RollupBucket] | None:
    """Count the table's rows by its rollup badge column, in first-appearance order — a summary
    derived from the rows, so it cannot drift from them. None when no rollup is declared. A row left
    blank in that column contributes to no bucket; the table validator guarantees at least one is set."""
    if table.rollup is None:
        return None
    counts = _rollup_counts(table.body_rows, table.rollup.by)
    return [{"key": key, "count": count} for key, count in counts.items()]


class DerivedTally(TypedDict):
    counts: dict[str, int]  # badge key -> how many of the source's units are in that state
    total: int  # the percentage denominator (a matrix's cells, or a table's rows)


def matrix_tallies(report: Report) -> dict[str, DerivedTally]:
    """`matrix id -> {counts: {badge: n}, total: rows*columns}` for every id'd matrix — the derived
    source a `cards` item reads via `of_matrix`. The denominator is the full grid (blank cells count as
    uncovered), so a derived card's percentage is the share of the whole matrix in that state. A matrix
    with no id contributes nothing (only referenceable matrices are tallied)."""
    tallies: dict[str, DerivedTally] = {}
    for matrix in iter_matrices(report.blocks):
        if matrix.id is None:
            continue
        counts: Counter[str] = Counter(cell.badge for cell in matrix.cells if cell.badge is not None)
        tallies[matrix.id] = {"counts": dict(counts), "total": len(matrix.rows) * len(matrix.columns)}
    return tallies


def table_tallies(report: Report) -> dict[str, DerivedTally]:
    """`table id -> {counts: {badge: n}, total: row count}` for every id'd table that declares a `rollup`
    — the derived source a `cards` item reads via `of_tables`. Rows are counted by the table's own
    `rollup.by` column (a blank cell counts toward no badge); the denominator is every row, so an
    `of_tables` card's percentage is the badge's share across the referenced tables. A table with no id
    or no rollup contributes nothing (the validator requires both on any referenced table)."""
    tallies: dict[str, DerivedTally] = {}
    for table in iter_tables(report.blocks):
        if table.id is None or table.rollup is None:
            continue
        rows = table.body_rows
        tallies[table.id] = {"counts": dict(_rollup_counts(rows, table.rollup.by)), "total": len(rows)}
    return tallies


class DerivedCardTally(NamedTuple):
    counted: int
    total: int


def derived_card_tally(
    card: Card,
    matrix_tallies: Mapping[str, DerivedTally],
    table_tallies: Mapping[str, DerivedTally],
) -> DerivedCardTally:
    badge = card.counted_badge
    if card.of_matrix:
        tally = matrix_tallies[card.of_matrix]
        return DerivedCardTally(tally["counts"].get(badge, 0), tally["total"])
    tallies = [table_tallies[table_id] for table_id in card.of_tables or []]
    return DerivedCardTally(
        sum(tally["counts"].get(badge, 0) for tally in tallies), sum(tally["total"] for tally in tallies)
    )


def matrix_grid(block: Matrix) -> list[list[MatrixCell | None]]:
    """The matrix as a row-major grid: `grid[r][c]` is the cell for row `rows[r]`, column `columns[c]`,
    or None for a blank (unfilled) cell. The block validator guarantees at most one cell per (row, col),
    so the lookup is unambiguous; the template only loops and never searches."""
    lookup = {(cell.row, cell.col): cell for cell in block.cells}
    return [[lookup.get((row, col)) for col in block.columns] for row in block.rows]


class MatrixCellDisplay(NamedTuple):
    tone: BadgeColorLiteral | None
    text: str
    state: str | None


def matrix_cell_display(cell: MatrixCell, badges: Mapping[str, Badge]) -> MatrixCellDisplay:
    if cell.badge:
        badge = badges[cell.badge]
        state = badge.label.strip()
        if cell.label and not state:
            return MatrixCellDisplay(badge.tone, cell.label, None)
        if cell.label and state.casefold() != cell.label.strip().casefold():
            return MatrixCellDisplay(badge.tone, cell.label, state)
        return MatrixCellDisplay(badge.tone, badge.label, None)
    return MatrixCellDisplay(cell.tone, cell.label or "", None)


def reconcile_line(table: Table) -> str:
    if table.reconcile is None:
        return ""
    total = col_sum(table.body_rows, table.reconcile.column)
    handled = table.reconcile.handled
    if handled is not None:
        return (
            f"Reconciles: {fmt(total)} + {fmt(handled.value)} {handled.label.lower()} "
            f"= {fmt(table.reconcile.total)}."
        )
    return f"Reconciles: {fmt(total)} = {fmt(table.reconcile.total)}."
