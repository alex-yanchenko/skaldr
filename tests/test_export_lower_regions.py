from dataclasses import replace
from typing import Any

import pytest

from skaldr.errors import RegionNotFoundError
from skaldr.export.inline import plain
from skaldr.export.lower import (
    assemble_page,
    lower_region,
    lower_regions,
    lower_report,
    lowering_for,
    region_for_section,
)
from skaldr.export.markdown import render_markdown_document
from skaldr.export.notion import render_notion
from skaldr.export.runs import Chip
from skaldr.export.tree import (
    BlockRegion,
    Heading,
    ListEntry,
    ListNode,
    LoweredDocument,
    PagePart,
    Paragraph,
    TableCell,
    TableNode,
    TableOfContents,
    TableRow,
    TocEntry,
    Toggle,
)
from skaldr.models import Report, parse_report
from skaldr.richtext import Plain
from tests.factories import API_BADGES, make_report, make_section, make_table

INTRO = BlockRegion(0, (Paragraph(plain("Intro.")),))
SET_UP = BlockRegion(
    1,
    (Heading(2, plain("Set up"), "st1"), ListNode("bullet", (ListEntry(plain("Inside one.")),))),
    section_id="st1",
    anchor="st1",
)
FIRST_WEEK = BlockRegion(
    2,
    (Toggle(plain("First week"), 2, (Paragraph(plain("Inside two.")),), "first-week"),),
    anchor="first-week",
)
WRAP_UP = BlockRegion(3, (Heading(2, plain("Wrap up"), "wrap-up"),), anchor="wrap-up")
CLOSING = BlockRegion(4, (ListNode("bullet", (ListEntry(plain("Closing.")),)),))
HEADER = PagePart(
    "header",
    (
        Paragraph(plain("Spring edition"), "muted"),
        TableOfContents(
            (
                TocEntry("st1", plain("Set up")),
                TocEntry("first-week", plain("First week")),
                TocEntry("wrap-up", plain("Wrap up")),
            )
        ),
    ),
)
FOOTER = PagePart("footer", (Paragraph(plain("2026-03-01"), "muted"),))
NOTION_PAGE = (
    'Spring edition {color="gray"}\n'
    "<table_of_contents/>\n"
    "Intro.\n"
    "## Set up\n"
    "- Inside one.\n"
    '## First week {toggle="true"}\n'
    "\tInside two.\n"
    "## Wrap up\n"
    "- Closing.\n"
    '2026-03-01 {color="gray"}\n'
)
MARKDOWN_PAGE = (
    "# Field guide\n\n"
    "Spring edition\n\n"
    "- [Set up](#set-up)\n- [First week](#first-week)\n- [Wrap up](#wrap-up)\n\n"
    "Intro.\n\n"
    "## Set up\n\n"
    "- Inside one.\n\n"
    "## First week\n\n"
    "Inside two.\n\n"
    "## Wrap up\n\n"
    "- Closing.\n\n"
    "2026-03-01\n"
)
LEGEND = PagePart(
    "legend",
    (
        Toggle(
            plain("Legend: badges used on this page"),
            None,
            (ListNode("bullet", (ListEntry((Chip("api", "blue"), Plain(" "), Plain("the API"))),)),),
        ),
    ),
)
BADGE_ROW = BlockRegion(0, (Paragraph((Chip("api", "blue"),)),))
PLAIN_SECTION = BlockRegion(
    1, (Toggle(plain("st1"), 2, (Paragraph(plain("x")),), "st1"),), section_id="st1", anchor="st1"
)
TABLE = BlockRegion(2, (TableNode((TableCell(plain("A")),), (TableRow((TableCell(plain("x")),)),)),))


def _field_guide() -> Report:
    return parse_report(
        make_report(
            meta={"title": "Field guide", "subtitle": ["Spring edition"], "toc": True, "date": "2026-03-01"},
            blocks=[
                {"type": "text", "body": "Intro."},
                make_section(
                    "st1",
                    title="Set up",
                    collapsed=False,
                    blocks=[{"type": "list", "items": ["Inside one."]}],
                ),
                {
                    "type": "section",
                    "title": "First week",
                    "blocks": [{"type": "text", "body": "Inside two."}],
                },
                {"type": "heading", "text": "Wrap up"},
                {"type": "list", "items": ["Closing."]},
            ],
        )
    )


def _badged(blocks: list[dict[str, Any]]) -> Report:
    return parse_report(make_report(badges=API_BADGES, blocks=blocks))


def test_each_top_level_block_lowers_to_a_region_naming_its_section() -> None:
    assert lower_regions(lowering_for(_field_guide())) == (INTRO, SET_UP, FIRST_WEEK, WRAP_UP, CLOSING)


def test_one_top_level_section_lowers_on_its_own() -> None:
    lowering = lowering_for(_field_guide())

    assert (lower_region(lowering, 1), lower_region(lowering, 2)) == (SET_UP, FIRST_WEEK)


@pytest.mark.parametrize("source_index", [5, -1], ids=["past-the-end", "negative"])
def test_a_region_index_outside_the_top_level_blocks_is_refused(source_index: int) -> None:
    with pytest.raises(RegionNotFoundError) as refusal:
        lower_region(lowering_for(_field_guide()), source_index)

    assert str(refusal.value) == f"the report has no top-level block {source_index}; its blocks are 0 to 4"


def test_a_section_id_finds_its_region() -> None:
    regions = (INTRO, SET_UP, FIRST_WEEK, WRAP_UP, CLOSING)

    assert region_for_section(regions, "st1") == SET_UP


def test_a_section_id_with_no_region_is_refused() -> None:
    with pytest.raises(RegionNotFoundError) as refusal:
        region_for_section((INTRO, SET_UP), "st2")

    assert str(refusal.value) == "no top-level section has the id 'st2'"


def test_only_a_top_level_section_id_is_a_section_id() -> None:
    report = parse_report(
        make_report(
            blocks=[
                {"type": "heading", "text": "Costs", "id": "costs"},
                make_table([{"key": "a", "label": "A"}], rows=[{"a": "x"}], id="spend"),
            ]
        )
    )

    assert lower_regions(lowering_for(report)) == (
        BlockRegion(0, (Heading(2, plain("Costs"), "costs"),), anchor="costs"),
        replace(TABLE, source_index=1),
    )


def test_assembling_keeps_an_empty_region_and_drops_an_empty_page_part() -> None:
    lowering = lowering_for(parse_report(make_report()))

    assert assemble_page([BlockRegion(0, ())], lowering) == LoweredDocument(
        "Test Report", (BlockRegion(0, ()),)
    )


def test_the_page_puts_the_header_before_the_regions_and_the_footer_after() -> None:
    assert lower_report(_field_guide()) == LoweredDocument(
        "Field guide", (HEADER, INTRO, SET_UP, FIRST_WEEK, WRAP_UP, CLOSING, FOOTER)
    )


def test_joining_the_regions_writes_the_whole_page_for_both_writers() -> None:
    lowering = lowering_for(_field_guide())
    document = assemble_page(lower_regions(lowering), lowering)

    assert (render_notion(document.body), render_markdown_document(document)) == (NOTION_PAGE, MARKDOWN_PAGE)


def test_a_page_with_no_subtitle_contents_legend_or_footer_holds_only_its_regions() -> None:
    assert lower_report(parse_report(make_report())) == LoweredDocument(
        "Test Report", (BlockRegion(0, (Paragraph(plain("Hello.")),)),)
    )


@pytest.mark.parametrize(
    ("selected", "regions"),
    [
        pytest.param((0, 1, 2), (BADGE_ROW, PLAIN_SECTION, LEGEND, TABLE), id="right-before-the-first-table"),
        pytest.param((1, 2), (PLAIN_SECTION, LEGEND, TABLE), id="a-selection-that-holds-the-table"),
        pytest.param((0, 1), (BADGE_ROW, PLAIN_SECTION, LEGEND), id="a-selection-that-ends-before-it"),
    ],
)
def test_the_badge_legend_goes_before_the_first_top_level_table(
    selected: tuple[int, ...], regions: tuple[BlockRegion | PagePart, ...]
) -> None:
    lowering = lowering_for(
        _badged(
            [
                {"type": "badge_row", "items": [{"key": "API"}]},
                make_section("st1"),
                make_table([{"key": "a", "label": "A"}], rows=[{"a": "x"}]),
            ]
        )
    )

    page = assemble_page([lower_region(lowering, index) for index in selected], lowering)

    assert page == LoweredDocument("Test Report", regions)


def test_the_badge_legend_leads_a_page_with_no_top_level_table() -> None:
    page = lower_report(_badged([make_section("st1"), {"type": "badge_row", "items": [{"key": "API"}]}]))

    assert page == LoweredDocument(
        "Test Report",
        (LEGEND, replace(PLAIN_SECTION, source_index=0), replace(BADGE_ROW, source_index=1)),
    )
