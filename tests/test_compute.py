from skaldr.compute import (
    first_table_index,
    fmt,
    heading_slugs,
    provenance_footer,
    reconcile_line,
    reference_numbers,
    toc_entries,
    used_badges,
)
from skaldr.models import Table, parse_report
from tests.factories import make_cell, make_grid, make_reconciled_table, make_report


def test_fmt_variants() -> None:
    assert fmt(1500) == "1,500"
    assert fmt(1500.0) == "1,500"
    assert fmt(1500.5) == "1,500.5"
    assert fmt("HEALTHY") == "HEALTHY"
    assert fmt(True) == "True"


def test_heading_slugs_dedup_collisions() -> None:
    report = parse_report(
        make_report(
            meta={"title": "T", "toc": True},
            blocks=[{"type": "heading", "text": "Details"}, {"type": "heading", "text": "Details"}],
        )
    )

    assert sorted(heading_slugs(report).values()) == ["details", "details-2"]


def test_toc_uses_deduped_slugs() -> None:
    report = parse_report(
        make_report(
            meta={"title": "T", "toc": True},
            blocks=[{"type": "heading", "text": "Details"}, {"type": "heading", "text": "Details"}],
        )
    )

    assert toc_entries(report, heading_slugs(report)) == [("details", "Details"), ("details-2", "Details")]


def test_toc_empty_when_toc_disabled() -> None:
    report = parse_report(make_report(blocks=[{"type": "heading", "text": "X"}]))

    assert toc_entries(report, heading_slugs(report)) == []


def test_used_badges_returns_referenced_in_declaration_order() -> None:
    table = make_reconciled_table(
        columns=[
            {"key": "issue", "label": "I", "kind": "text"},
            {"key": "tag", "label": "", "kind": "badge"},
            {"key": "count", "label": "C", "kind": "number"},
        ],
        reconcile={"total": 30, "column": "count"},
        # Rows reference B before A, but declaration order (A, B) must win; C is declared, unused.
        groups=[
            {
                "name": "g",
                "rows": [{"issue": "x", "tag": "B", "count": 10}, {"issue": "y", "tag": "A", "count": 20}],
            }
        ],
    )
    badges = {
        "A": {"label": "A", "tone": "amber", "legend": "la"},
        "B": {"label": "B", "tone": "blue", "legend": "lb"},
        "C": {"label": "C", "tone": "green", "legend": "lc"},
    }

    report = parse_report(make_report(badges=badges, blocks=[table]))

    assert [key for key, _ in used_badges(report)] == ["A", "B"]


def test_reconcile_line_with_and_without_handled() -> None:
    with_handled = parse_report(make_report(blocks=[make_reconciled_table()])).blocks[0]
    without_handled = parse_report(
        make_report(
            blocks=[
                make_reconciled_table(
                    reconcile={"total": 10, "column": "count"},
                    groups=[{"name": "g", "rows": [{"issue": "x", "count": 10}]}],
                )
            ]
        )
    ).blocks[0]

    assert isinstance(with_handled, Table)
    assert isinstance(without_handled, Table)
    assert reconcile_line(with_handled) == "Reconciles: 10 + 90 clean = 100."
    assert reconcile_line(without_handled) == "Reconciles: 10 = 10."


def test_provenance_footer_recurses_into_sections() -> None:
    section = {"type": "section", "title": "Appendix", "blocks": [make_reconciled_table()]}
    report = parse_report(make_report(meta={"title": "T", "source": "src"}, blocks=[section]))

    footer = provenance_footer(report)

    assert footer == "src · Reconciles: 10 + 90 clean = 100."


def test_first_table_index() -> None:
    report = parse_report(make_report(blocks=[{"type": "text", "body": "x"}, make_reconciled_table()]))

    assert first_table_index(report) == 1


def test_reference_numbers_are_in_document_order_across_blocks_and_sections() -> None:
    first = {"type": "references", "items": [{"key": "a", "text": "A"}, {"key": "b", "text": "B"}]}
    nested = {"type": "references", "items": [{"key": "c", "text": "C"}, {"key": "d", "text": "D"}]}
    report = parse_report(
        make_report(blocks=[first, {"type": "section", "title": "More", "blocks": [nested]}])
    )

    assert reference_numbers(report) == {"a": 1, "b": 2, "c": 3, "d": 4}


def test_reference_numbers_reach_a_references_block_nested_in_a_grid_cell() -> None:
    refs = {"type": "references", "items": [{"key": "a", "text": "A"}]}
    grid = make_grid([make_cell(6, [refs])])
    report = parse_report(make_report(blocks=[grid]))

    assert reference_numbers(report) == {"a": 1}
