import json
from pathlib import Path
from typing import Any

import pytest

from skaldr.export import EXPORT_MANIFEST, export_notion, render_export
from skaldr.export.budget import character_budget
from skaldr.export.notion import NotionChunks, chunk_notion, render_notion, render_notion_regions
from skaldr.export.runs import Chip, IndicatorMark, StatusMark
from skaldr.export.tree import (
    BlockRegion,
    Card,
    Cards,
    Columns,
    FactStrip,
    GridColumn,
    Heading,
    KeyValueList,
    LabelledValue,
    ListEntry,
    ListNode,
    LoweredDocument,
    Node,
    Paragraph,
    Quote,
    TableCell,
    TableNode,
    TableRow,
)
from skaldr.export_targets import ExportTarget
from skaldr.models import parse_report
from skaldr.richtext import Code, Plain
from tests.factories import make_report, make_section, notion_of

SITE_AND_OWNER = [{"label": "Site", "value": "West"}, {"label": "Owner:", "value": "ops"}]


def _fact_strip(facts: list[dict[str, Any]]) -> dict[str, Any]:
    return {"type": "fact_strip", "facts": facts}


def test_a_fact_strip_is_a_column_per_fact_with_its_label_in_grey_over_its_value() -> None:
    assert notion_of([_fact_strip(SITE_AND_OWNER)]) == (
        "<columns>\n"
        '\t<column ratio="50">\n\t\tSite {color="gray"}\n\t\tWest\n\t</column>\n'
        '\t<column ratio="50">\n\t\tOwner {color="gray"}\n\t\tops\n\t</column>\n'
        "</columns>\n"
    )


def test_a_fact_without_a_label_is_its_value_alone_and_three_facts_share_the_page_to_a_hundred() -> None:
    facts = (
        LabelledValue("Site", (Plain("West"),)),
        LabelledValue(None, (Plain("ops"),)),
        LabelledValue("Due", (Plain("Fri"),)),
    )

    assert render_notion([FactStrip(facts)]) == (
        "<columns>\n"
        '\t<column ratio="34">\n\t\tSite {color="gray"}\n\t\tWest\n\t</column>\n'
        '\t<column ratio="33">\n\t\tops\n\t</column>\n'
        '\t<column ratio="33">\n\t\tDue {color="gray"}\n\t\tFri\n\t</column>\n'
        "</columns>\n"
    )


def test_a_single_fact_is_a_bullet_since_a_column_list_needs_two_columns() -> None:
    assert notion_of([_fact_strip(SITE_AND_OWNER[:1])]) == "- **Site**: West\n"


def test_five_facts_are_two_strips_of_three_and_two_so_no_column_is_narrower_than_a_quarter() -> None:
    facts = [{"label": f"F{number}", "value": str(number)} for number in range(1, 6)]

    assert notion_of([_fact_strip(facts)]) == (
        "<columns>\n"
        '\t<column ratio="34">\n\t\tF1 {color="gray"}\n\t\t1\n\t</column>\n'
        '\t<column ratio="33">\n\t\tF2 {color="gray"}\n\t\t2\n\t</column>\n'
        '\t<column ratio="33">\n\t\tF3 {color="gray"}\n\t\t3\n\t</column>\n'
        "</columns>\n"
        "<columns>\n"
        '\t<column ratio="50">\n\t\tF4 {color="gray"}\n\t\t4\n\t</column>\n'
        '\t<column ratio="50">\n\t\tF5 {color="gray"}\n\t\t5\n\t</column>\n'
        "</columns>\n"
    )


def test_section_fields_are_a_fact_strip_of_columns() -> None:
    section = make_section("st1", collapsed=False, fields={"status": "Open", "estimate": 3})

    assert notion_of([section]) == (
        "## st1\n"
        "<columns>\n"
        '\t<column ratio="50">\n\t\tStatus {color="gray"}\n\t\tOpen\n\t</column>\n'
        '\t<column ratio="50">\n\t\tEstimate {color="gray"}\n\t\t3\n\t</column>\n'
        "</columns>\n"
        "x\n"
    )


def test_a_key_value_list_is_a_two_column_table_with_a_bold_header_column_and_no_header_row() -> None:
    block = {
        "type": "key_value",
        "pairs": [{"label": "Lead", "value": "**Ana**"}, {"label": "Site:", "value": "West"}],
    }

    assert notion_of([block]) == (
        '<table fit-page-width="true" header-column="true">\n'
        "\t<tr>\n\t\t<td>**Lead**</td>\n\t\t<td>**Ana**</td>\n\t</tr>\n"
        "\t<tr>\n\t\t<td>**Site**</td>\n\t\t<td>West</td>\n\t</tr>\n"
        "</table>\n"
    )


def test_a_key_value_table_on_a_full_width_page_is_sized_like_any_other_table() -> None:
    nodes = [KeyValueList((LabelledValue("Lead", (Plain("Ana"),)),))]

    assert render_notion(nodes, "full") == (
        '<table fit-page-width="true" header-column="true">\n'
        '\t<colgroup>\n\t\t<col width="600">\n\t\t<col width="600">\n\t</colgroup>\n'
        "\t<tr>\n\t\t<td>**Lead**</td>\n\t\t<td>Ana</td>\n\t</tr>\n"
        "</table>\n"
    )


def test_a_key_value_value_holding_inline_code_with_a_closing_tag_stays_a_bullet_list() -> None:
    nodes = [KeyValueList((LabelledValue("Tag", (Code("</td>"),)),))]

    assert render_notion(nodes) == "- **Tag**: `</td>`\n"


def test_a_definition_list_is_a_bold_term_over_its_body_blocks() -> None:
    block = {
        "type": "def_list",
        "items": [
            {"term": "Drift", "body": "first\n\nsecond"},
            {"term": "Steps", "body": "- one\n- two"},
            {"term": "Gap", "body": " "},
        ],
    }

    assert notion_of([block]) == ("**Drift**\n\tfirst\n\tsecond\n**Steps**\n\t- one\n\t- two\n**Gap**\n")


def test_cards_are_callouts_in_columns_filled_by_their_tone_with_the_note_as_the_last_grey_line() -> None:
    block = {
        "type": "cards",
        "items": [
            {"label": "Clean", "value": 9, "tone": "success", "note": "since Monday"},
            {"label": "Lag", "value": "3 days"},
        ],
    }

    assert notion_of([block]) == (
        "<columns>\n"
        '\t<column ratio="50">\n'
        '\t\t<callout icon="✅" color="green_bg">\n'
        "\t\t\t**Clean**\n\t\t\t9\n"
        '\t\t\tsince Monday {color="gray"}\n'
        "\t\t</callout>\n"
        "\t</column>\n"
        '\t<column ratio="50">\n'
        '\t\t<callout icon="📝" color="gray_bg">\n'
        "\t\t\t**Lag**\n\t\t\t3 days\n"
        "\t\t</callout>\n"
        "\t</column>\n"
        "</columns>\n"
    )


def test_a_card_with_a_badge_leads_with_the_badge_and_keeps_its_colour() -> None:
    nodes = [
        Cards(
            (
                Card("API rows", (Plain("1 (50.0%)"),), note="live", badge="blue"),
                Card("Other", (Plain("2"),)),
            )
        )
    ]

    assert render_notion(nodes) == (
        "<columns>\n"
        '\t<column ratio="50">\n'
        '\t\t<callout icon="📝" color="gray_bg">\n'
        '\t\t\t<span color="blue">**API rows**</span>\n\t\t\t1 (50.0%)\n'
        '\t\t\tlive {color="gray"}\n'
        "\t\t</callout>\n"
        "\t</column>\n"
        '\t<column ratio="50">\n'
        '\t\t<callout icon="📝" color="gray_bg">\n'
        "\t\t\t**Other**\n\t\t\t2\n"
        "\t\t</callout>\n"
        "\t</column>\n"
        "</columns>\n"
    )


def test_a_single_card_is_one_callout_with_no_columns() -> None:
    block = {"type": "cards", "items": [{"label": "Lag", "value": "3 days", "tone": "danger"}]}

    assert notion_of([block]) == ('<callout icon="🛑" color="red_bg">\n\t**Lag**\n\t3 days\n</callout>\n')


def test_cards_and_facts_inside_a_grid_column_are_not_a_nested_column_list() -> None:
    cards = Cards((Card("A", (Plain("1"),)), Card("B", (Plain("2"),))))
    facts = FactStrip((LabelledValue("Site", (Plain("West"),)), LabelledValue("Due", (Plain("Fri"),))))
    grid = Columns((GridColumn(50, (cards,)), GridColumn(50, (facts,))))

    assert render_notion([grid]) == (
        "<columns>\n"
        '\t<column ratio="50">\n'
        '\t\t<callout icon="📝" color="gray_bg">\n\t\t\t**A**\n\t\t\t1\n\t\t</callout>\n'
        '\t\t<callout icon="📝" color="gray_bg">\n\t\t\t**B**\n\t\t\t2\n\t\t</callout>\n'
        "\t</column>\n"
        '\t<column ratio="50">\n'
        "\t\t- **Site**: West\n\t\t- **Due**: Fri\n"
        "\t</column>\n"
        "</columns>\n"
    )


def _strip_and_a_folded_key_value() -> tuple[Node, ...]:
    return (
        FactStrip((LabelledValue("Site", (Plain("West"),)), LabelledValue("Due", (Plain("Fri"),)))),
        KeyValueList((LabelledValue("Tag", (Code("</td>"),)),)),
    )


STRIP_AND_FOLDED_KEY_VALUE_PAGE = (
    "<columns>\n"
    '\t<column ratio="50">\n\t\tSite {color="gray"}\n\t\tWest\n\t</column>\n'
    '\t<column ratio="50">\n\t\tDue {color="gray"}\n\t\tFri\n\t</column>\n'
    "</columns>\n"
    "- **Tag**: `</td>`\n"
)


def test_each_region_of_a_page_holds_the_native_nodes_written_for_it() -> None:
    regions = (
        BlockRegion(0, (Paragraph((Plain("first"),)),)),
        BlockRegion(1, _strip_and_a_folded_key_value()),
        BlockRegion(2, (Paragraph((Plain("last"),)),)),
    )

    assert render_notion_regions(LoweredDocument("Plan", regions)) == (
        "first\n",
        STRIP_AND_FOLDED_KEY_VALUE_PAGE,
        "last\n",
    )


def test_a_chunk_boundary_falls_between_the_blocks_of_a_native_strip_section_and_the_next() -> None:
    nodes = (
        Heading(2, (Plain("A"),)),
        *_strip_and_a_folded_key_value(),
        Heading(2, (Plain("B"),)),
        Paragraph((Plain("z"),)),
    )
    first_section = "## A\n" + STRIP_AND_FOLDED_KEY_VALUE_PAGE

    assert chunk_notion(nodes, character_budget(len(first_section))) == NotionChunks(
        (first_section, "## B\nz\n"), ()
    )


def test_a_status_glyph_is_the_page_glyph_in_the_state_colour() -> None:
    block = {
        "type": "status_list",
        "items": [
            {"state": "done", "text": "Ship"},
            {"state": "current", "text": "Test"},
            {"state": "pending", "text": "Plan"},
            {"state": "failed", "text": "Fix"},
            {"state": "blocked", "text": "Vendor"},
        ],
    }

    assert notion_of([block]) == (
        '- <span color="green">✓</span> Ship\n'
        '- <span color="blue">◐</span> Test\n'
        '- <span color="gray">○</span> Plan\n'
        '- <span color="red">✗</span> Fix\n'
        '- <span color="yellow">⏸</span> Vendor\n'
    )


def test_a_status_glyph_on_a_filled_cell_is_the_bare_glyph() -> None:
    table = TableNode(
        (TableCell((Plain("A"),)),),
        (TableRow((TableCell((StatusMark("done"),), "info"),)),),
    )

    assert render_notion([table]) == (
        '<table fit-page-width="true" header-row="true">\n'
        "\t<tr>\n\t\t<td>**A**</td>\n\t</tr>\n"
        '\t<tr>\n\t\t<td color="blue_bg">✓</td>\n\t</tr>\n'
        "</table>\n"
    )


def test_a_quote_holding_a_list_has_the_list_as_its_children() -> None:
    block = {"type": "quote", "body": "Said:\n\n- one\n- two", "cite": "Ana"}

    assert notion_of([block]) == "> Said:\n\t- one\n\t- two\n\t*Ana*\n"


def test_a_quote_of_paragraphs_stays_one_line() -> None:
    block = {"type": "quote", "body": "One.\n\nTwo.", "cite": "Ana"}

    assert notion_of([block]) == "> One.<br>Two.<br>*Ana*\n"


def test_a_quote_that_opens_with_a_list_is_an_empty_quote_over_the_list() -> None:
    nodes = [Quote((ListNode("bullet", (ListEntry((Plain("one"),)),)),))]

    assert render_notion(nodes) == ">\n\t- one\n"


def _table_with_row(row: TableRow) -> TableNode:
    return TableNode(
        (TableCell((Plain("Name"),)), TableCell((Plain("Status"),))),
        (row,),
    )


def _rendered_row(row: TableRow) -> str:
    return render_notion([_table_with_row(row)]).split("\t</tr>\n", 1)[1].rsplit("</table>", 1)[0]


def test_a_muted_row_strikes_its_title_and_has_no_fill() -> None:
    row = TableRow((TableCell((Plain("old"),)), TableCell((Plain("x"),))), "muted")

    assert _rendered_row(row) == "\t<tr>\n\t\t<td>~~old~~</td>\n\t\t<td>x</td>\n\t</tr>\n"


def test_a_danger_row_is_filled_end_to_end_and_its_badge_takes_the_normal_colour() -> None:
    row = TableRow((TableCell((Plain("bad"),)), TableCell((Chip("x", "red"),))), "danger")

    assert _rendered_row(row) == ('\t<tr color="red_bg">\n\t\t<td>bad</td>\n\t\t<td>**x**</td>\n\t</tr>\n')


def test_a_row_tone_other_than_muted_or_danger_still_fills_one_cell() -> None:
    row = TableRow((TableCell((Plain("ok"),)), TableCell((Chip("x", "green"),))), "success")

    assert _rendered_row(row) == ('\t<tr>\n\t\t<td>ok</td>\n\t\t<td color="green_bg">**x**</td>\n\t</tr>\n')


def test_a_tinted_row_is_filled_end_to_end() -> None:
    row = TableRow((TableCell((Plain("a"),)), TableCell((Chip("x", "blue"),))), tint="info")

    assert _rendered_row(row) == ('\t<tr color="blue_bg">\n\t\t<td>a</td>\n\t\t<td>**x**</td>\n\t</tr>\n')


def test_a_row_tone_wins_over_a_tint() -> None:
    row = TableRow((TableCell((Plain("a"),)), TableCell((Plain("b"),))), "muted", tint="info")

    assert _rendered_row(row) == "\t<tr>\n\t\t<td>~~a~~</td>\n\t\t<td>b</td>\n\t</tr>\n"


def test_an_indicator_dot_sits_in_an_unfilled_cell() -> None:
    row = TableRow(
        (TableCell((Plain("a"),)), TableCell((IndicatorMark("danger"),), "danger")),
    )

    assert _rendered_row(row) == "\t<tr>\n\t\t<td>a</td>\n\t\t<td>🔴</td>\n\t</tr>\n"


def test_a_row_tone_skips_an_indicator_cell_for_the_one_cell_fill() -> None:
    row = TableRow(
        (TableCell((IndicatorMark("danger"),), "danger"), TableCell((Plain("b"),))),
        "info",
    )

    assert _rendered_row(row) == '\t<tr>\n\t\t<td>🔴</td>\n\t\t<td color="blue_bg">b</td>\n\t</tr>\n'


def _notion_manifest(directory: Path, **meta: str) -> dict[str, Any]:
    export_notion(parse_report(make_report(meta={"title": "Plan", **meta})), directory)
    return json.loads((directory / EXPORT_MANIFEST).read_text(encoding="utf-8"))


def test_the_notion_manifest_carries_the_icon_and_cover_the_page_sets() -> None:
    report = parse_report(
        make_report(meta={"title": "Plan", "icon": "🧪", "cover": "https://example.com/cover.png"})
    )

    rendered = render_export(report, "notion")

    assert (rendered.title, rendered.icon, rendered.cover) == (
        "Plan",
        "🧪",
        "https://example.com/cover.png",
    )


def test_a_notion_export_writes_the_icon_and_cover_into_the_manifest(tmp_path: Path) -> None:
    manifest = _notion_manifest(tmp_path, icon="🧪", cover="https://example.com/cover.png")

    assert manifest == {
        "title": "Plan",
        "files": ["page.md"],
        "icon": "🧪",
        "cover": "https://example.com/cover.png",
    }


def test_a_notion_export_without_an_icon_or_cover_writes_the_manifest_it_always_wrote(
    tmp_path: Path,
) -> None:
    assert _notion_manifest(tmp_path) == {"title": "Plan", "files": ["page.md"]}


@pytest.mark.parametrize("target", ["markdown", "adf", "slack"])
def test_another_target_leaves_the_icon_and_cover_out_of_its_manifest(target: ExportTarget) -> None:
    report = parse_report(
        make_report(meta={"title": "Plan", "icon": "🧪", "cover": "https://example.com/cover.png"})
    )

    rendered = render_export(report, target)

    assert (rendered.icon, rendered.cover) == (None, None)
