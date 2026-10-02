from typing import Any, get_args

import pytest

from skaldr.errors import ReportError
from skaldr.export.inline import bold, italic, plain
from skaldr.export.lower import lower_report, place_legend
from skaldr.export.lower.context import with_bold_label
from skaldr.export.markup import status_glyph
from skaldr.export.runs import Chip, ExportRich, Gauge, StatusMark
from skaldr.export.tree import (
    Callout,
    CodeBlock,
    Heading,
    HeadingLevel,
    ListEntry,
    ListNode,
    LoweredDocument,
    Node,
    Paragraph,
    Quote,
    TableOfContents,
    TocEntry,
    Toggle,
    capped_heading_level,
    heading_of,
)
from skaldr.models import StatusState, parse_report
from skaldr.richtext import AnchorLink, Code, Link, Plain, Rich, Styled
from tests.factories import API_BADGES, lowered, make_cell, make_flow, make_grid, make_report

API_LEGEND = Toggle(
    (Plain("Legend: badges used on this page"),),
    None,
    (ListNode("bullet", (ListEntry((Chip("api", "blue"), Plain(" "), Plain("the API"))),)),),
)


def test_a_report_lowers_to_its_title_and_body() -> None:
    report = parse_report(make_report(meta={"title": "Count", "subtitle": ["Sub **bold** {{blank}}"]}))

    assert lower_report(report) == LoweredDocument(
        "Count",
        (Paragraph((Plain("Sub **bold** {{blank}}"),), "muted"), Paragraph((Plain("Hello."),))),
    )


@pytest.mark.parametrize(
    ("block", "block_type"),
    [
        pytest.param({"type": "flow", "steps": [{"label": "a"}, {"label": "b"}]}, "flow", id="flow"),
        pytest.param(
            {"type": "fan", "hub": {"label": "H"}, "spokes": [{"label": "A"}, {"label": "B"}]},
            "fan",
            id="fan",
        ),
        pytest.param(make_grid([make_cell(6)]), "grid", id="grid"),
        pytest.param(make_flow(), "request_flow", id="request-flow"),
    ],
)
def test_a_block_with_no_markdown_form_yet_fails_naming_its_type(
    block: dict[str, Any], block_type: str
) -> None:
    with pytest.raises(ReportError) as raised:
        lowered([block])

    assert str(raised.value) == f"a `{block_type}` block has no Markdown export yet"


def test_a_walkthrough_step_with_no_sub_is_its_bold_label() -> None:
    walkthrough = {
        "type": "walkthrough",
        "steps": [{"label": "Go", "detail": [{"type": "text", "body": "d"}]}],
    }

    assert lowered([walkthrough]) == (
        ListNode("number", (ListEntry(bold("Go"), children=(Paragraph((Plain("d"),)),)),)),
    )


def test_rich_text_keeps_the_spaces_inside_a_code_span() -> None:
    assert lowered([{"type": "text", "body": "run  `a  b`\nnow"}]) == (
        Paragraph((Plain("run "), Code("a  b"), Plain(" now"))),
    )


@pytest.mark.parametrize(
    ("item", "runs"),
    [
        pytest.param("[a\nb](https://e.com)", (Link((Plain("a b"),), "https://e.com"),), id="link-label"),
        pytest.param("[a\nb](#count)", (AnchorLink((Plain("a b"),), "count"),), id="anchor-link-label"),
        pytest.param("**a\nb**", (Styled("bold", (Plain("a b"),)),), id="styled"),
        pytest.param("  x  ", (Plain("x"),), id="outer-spaces-trimmed"),
        pytest.param("  `x`  ", (Code("x"),), id="outer-spaces-around-code-dropped"),
        pytest.param("`x\ry`", (Code("x y"),), id="code-carriage-return"),
        pytest.param("`x\r\ny`", (Code("x y"),), id="code-crlf"),
    ],
)
def test_rich_text_lowers_onto_one_line(item: str, runs: Rich) -> None:
    blocks = [{"type": "heading", "text": "Count"}, {"type": "list", "items": [item]}]

    assert lowered(blocks) == (
        Heading(2, (Plain("Count"),), "count"),
        ListNode("bullet", (ListEntry(runs),)),
    )


@pytest.mark.parametrize(
    ("text", "runs"),
    [
        pytest.param("Appendix\n", (Plain("Appendix"),), id="trailing-newline"),
        pytest.param("  a \n b  ", (Plain("a b"),), id="inner-and-outer-whitespace"),
        pytest.param(" \n ", (), id="only-whitespace"),
    ],
)
def test_plain_text_is_trimmed_and_collapsed_to_one_line(text: str, runs: Rich) -> None:
    assert plain(text) == runs


def test_an_author_heading_id_becomes_the_anchor() -> None:
    assert lowered([{"type": "heading", "text": "Count", "id": "tally"}]) == (
        Heading(2, (Plain("Count"),), "tally"),
    )


def test_a_heading_with_a_line_break_stays_one_heading() -> None:
    assert lowered([{"type": "heading", "text": "First\n## Injected"}]) == (
        Heading(2, (Plain("First ## Injected"),), "first-injected"),
    )


def test_a_heading_sub_is_a_muted_italic_line_under_it() -> None:
    assert lowered([{"type": "heading", "text": "Count", "sub": "by **aisle**"}]) == (
        Heading(2, (Plain("Count"),), "count"),
        Paragraph((Styled("italic", (Plain("by "), Styled("bold", (Plain("aisle"),)))),), "muted"),
    )


def test_an_open_section_is_a_heading_and_nesting_never_goes_past_level_four() -> None:
    section = {
        "type": "section",
        "title": "Open",
        "collapsed": False,
        "blocks": [{"type": "heading", "text": "Deep", "level": 3}],
    }

    assert lowered([section]) == (Heading(2, (Plain("Open"),), "open"), Heading(4, (Plain("Deep"),), "deep"))


@pytest.mark.parametrize(
    ("level", "capped"),
    [
        pytest.param(0, 1, id="below-the-range"),
        pytest.param(1, 1, id="top"),
        pytest.param(4, 4, id="the-cap"),
        pytest.param(7, 4, id="past-the-cap"),
    ],
)
def test_a_heading_level_is_capped_to_what_the_writer_supports(level: int, capped: HeadingLevel) -> None:
    assert capped_heading_level(level) == capped


@pytest.mark.parametrize(
    ("node", "heading"),
    [
        pytest.param(Heading(3, (Plain("H"),), "h"), Heading(3, (Plain("H"),), "h"), id="heading"),
        pytest.param(
            Toggle((Plain("T"),), 2, (Paragraph((Plain("x"),)),), "t"),
            Heading(2, (Plain("T"),), "t"),
            id="heading-toggle",
        ),
        pytest.param(Toggle((Plain("T"),), None, ()), None, id="plain-toggle"),
        pytest.param(Paragraph((Plain("p"),)), None, id="paragraph"),
    ],
)
def test_a_heading_or_a_heading_toggle_reads_as_a_heading(node: Node, heading: Heading | None) -> None:
    assert heading_of(node) == heading


def test_muted_text_and_the_provenance_footer_are_muted_paragraphs() -> None:
    blocks = [{"type": "text", "body": "aside", "muted": True}]

    assert lowered(blocks, meta={"title": "T", "source": "SOP v2", "date": "1 Oct"}) == (
        Paragraph((Plain("aside"),), "muted"),
        Paragraph((Plain("SOP v2 · 1 Oct"),), "muted"),
    )


def test_the_table_of_contents_lists_what_the_html_lists() -> None:
    blocks = [
        {"type": "heading", "text": "Overview"},
        {"type": "heading", "text": "Detail", "level": 3},
        {"type": "section", "title": "Appendix", "blocks": [{"type": "text", "body": "x"}]},
    ]

    assert lowered(blocks, meta={"title": "T", "toc": True}) == (
        TableOfContents(
            (TocEntry("overview", (Plain("Overview"),)), TocEntry("appendix", (Plain("Appendix"),)))
        ),
        Heading(2, (Plain("Overview"),), "overview"),
        Heading(3, (Plain("Detail"),), "detail"),
        Toggle((Plain("Appendix"),), 2, (Paragraph((Plain("x"),)),), "appendix"),
    )


def test_references_are_bullets_led_by_their_number_with_a_source_link() -> None:
    references = {
        "type": "references",
        "items": [{"key": "a", "text": "SOP", "url": "https://e.com"}, {"key": "b", "text": "Memo"}],
    }

    assert lowered([references]) == (
        ListNode(
            "bullet",
            (
                ListEntry(
                    (
                        Plain("[1]"),
                        Plain(" "),
                        Plain("SOP"),
                        Plain(" "),
                        Link((Plain("source"),), "https://e.com"),
                    )
                ),
                ListEntry((Plain("[2]"), Plain(" "), Plain("Memo"))),
            ),
        ),
    )


def test_the_badge_legend_comes_right_after_the_table_of_contents_when_the_page_has_no_table() -> None:
    blocks = [{"type": "heading", "text": "A"}, {"type": "badge_row", "items": [{"key": "API"}]}]

    assert lowered(blocks, meta={"title": "T", "toc": True}, badges=API_BADGES) == (
        TableOfContents((TocEntry("a", (Plain("A"),)),)),
        API_LEGEND,
        Heading(2, (Plain("A"),), "a"),
        Paragraph((Chip("api", "blue"),)),
    )


@pytest.mark.parametrize(
    ("legend_at", "nodes"),
    [
        pytest.param(
            None,
            [API_LEGEND, Paragraph((Plain("a"),)), Paragraph((Plain("b"),)), Paragraph((Plain("table"),))],
            id="no-top-level-table-puts-it-first",
        ),
        pytest.param(
            2,
            [Paragraph((Plain("a"),)), Paragraph((Plain("b"),)), API_LEGEND, Paragraph((Plain("table"),))],
            id="right-before-the-first-top-level-table",
        ),
        pytest.param(
            0,
            [API_LEGEND, Paragraph((Plain("a"),)), Paragraph((Plain("b"),)), Paragraph((Plain("table"),))],
            id="table-first",
        ),
    ],
)
def test_the_badge_legend_goes_where_the_html_puts_it(legend_at: int | None, nodes: list[Node]) -> None:
    blocks = [[Paragraph((Plain("a"),))], [Paragraph((Plain("b"),))], [Paragraph((Plain("table"),))]]

    assert place_legend(blocks, [API_LEGEND], legend_at) == nodes


def test_a_card_shows_its_share_delta_badges_and_note() -> None:
    card = {
        "label": "Clean",
        "value": 9,
        "of": 10,
        "tone": "success",
        "delta": {"label": "+1", "direction": "up"},
        "badges": ["API"],
        "note": "since Monday",
    }

    assert lowered([{"type": "cards", "items": [card]}], badges=API_BADGES) == (
        API_LEGEND,
        ListNode(
            "bullet",
            (
                ListEntry(
                    (
                        *bold("Clean"),
                        Plain(": "),
                        Plain("9"),
                        Plain(" "),
                        Plain("(90.0%)"),
                        Plain(" "),
                        Plain("▲ +1"),
                        Plain(" "),
                        Chip("api", "blue"),
                    ),
                    children=(Paragraph((Plain("since Monday"),), "muted"),),
                    tone="success",
                ),
            ),
        ),
    )


@pytest.mark.parametrize(
    ("card", "text"),
    [
        pytest.param(
            {"label": "Site", "value": "West"}, (*bold("Site"), Plain(": "), Plain("West")), id="text-value"
        ),
        pytest.param(
            {"label": "Lag", "value": 3, "delta": {"label": "flat"}},
            (*bold("Lag"), Plain(": "), Plain("3"), Plain(" "), Plain("flat")),
            id="delta-without-direction",
        ),
        pytest.param(
            {"label": "Cost", "value": 5, "delta": {"label": "-8%", "direction": "down", "tone": "success"}},
            (*bold("Cost"), Plain(": "), Plain("5"), Plain(" "), Chip("▼ -8%", "green")),
            id="toned-delta-is-a-colored-chip",
        ),
        pytest.param({"label": " ", "value": 7}, (Plain("7"),), id="blank-label"),
        pytest.param({"label": "Empty", "value": ""}, bold("Empty"), id="empty-value-is-the-label-alone"),
    ],
)
def test_a_card_shows_only_the_parts_it_has(card: dict[str, Any], text: ExportRich) -> None:
    assert lowered([{"type": "cards", "items": [card]}]) == (ListNode("bullet", (ListEntry(text),)),)


@pytest.mark.parametrize(
    "blocks",
    [
        pytest.param(
            [
                {"type": "cards", "items": [{"badge": "API", "of_matrix": "m"}]},
                {
                    "type": "matrix",
                    "id": "m",
                    "rows": ["r"],
                    "columns": ["c"],
                    "cells": [{"row": "r", "col": "c", "badge": "API"}],
                },
            ],
            id="of-matrix",
        ),
        pytest.param(
            [
                {"type": "cards", "items": [{"badge": "API", "of_tables": ["t"]}]},
                {
                    "type": "table",
                    "id": "t",
                    "columns": [
                        {"key": "item", "label": "Item", "kind": "text"},
                        {"key": "state", "label": "State", "kind": "badge"},
                    ],
                    "rows": [{"item": "a", "state": "API"}],
                    "rollup": {"by": "state"},
                },
            ],
            id="of-tables",
        ),
    ],
)
def test_a_derived_card_fails_until_its_source_blocks_export(blocks: list[dict[str, Any]]) -> None:
    with pytest.raises(ReportError) as raised:
        lowered(blocks, badges=API_BADGES)

    assert str(raised.value) == "a derived `cards` item has no Markdown export yet"


def test_fact_strip_and_key_value_entries_are_labelled_bullets() -> None:
    blocks = [
        {
            "type": "fact_strip",
            "facts": [{"label": "Site:", "value": "West  wing"}, {"label": " ", "value": "x"}],
        },
        {"type": "key_value", "pairs": [{"label": "Owner", "value": "**ops**"}]},
    ]

    assert lowered(blocks) == (
        ListNode(
            "bullet",
            (ListEntry((*bold("Site"), Plain(": "), Plain("West wing"))), ListEntry((Plain("x"),))),
        ),
        ListNode("bullet", (ListEntry((*bold("Owner"), Plain(": "), Styled("bold", (Plain("ops"),)))),)),
    )


def test_a_meter_reading_is_a_gauge_with_its_share_and_tone() -> None:
    meter = {"type": "meter", "items": [{"label": "Zone", "value": 5, "max": 10, "tone": "warning"}]}

    assert lowered([meter]) == (
        ListNode(
            "bullet",
            (
                ListEntry(
                    (*bold("Zone"), Plain(": "), Gauge(5, 10), Plain(" "), Plain("50.0%")),
                    tone="warning",
                ),
            ),
        ),
    )


@pytest.mark.parametrize(
    ("axis", "note"),
    [
        pytest.param({"min": "Jan"}, (Paragraph((Plain("From Jan"),), "muted"),), id="start-only"),
        pytest.param({"max": "Dec"}, (Paragraph((Plain("To Dec"),), "muted"),), id="end-only"),
        pytest.param({"min": "Jan", "max": "Dec"}, (Paragraph((Plain("Jan to Dec"),), "muted"),), id="both"),
        pytest.param(
            {"min": "  ", "max": "Dec"}, (Paragraph((Plain("To Dec"),), "muted"),), id="blank-start"
        ),
        pytest.param(None, (), id="no-axis"),
    ],
)
def test_a_range_shows_the_axis_ends_it_has_and_each_segment_share(
    axis: dict[str, str] | None, note: tuple[Node, ...]
) -> None:
    block = {
        "type": "range",
        "segments": [
            {"label": "Seg", "span": 1, "tone": "danger", "sub": "one"},
            {"label": "Rest", "span": 3},
        ],
        **({"axis": axis} if axis else {}),
    }

    assert lowered([block]) == (
        *note,
        ListNode(
            "bullet",
            (
                ListEntry(
                    (*bold("Seg"), Plain(": "), Plain("25.0%"), Plain(", "), Plain("one")), tone="danger"
                ),
                ListEntry((*bold("Rest"), Plain(": "), Plain("75.0%"))),
            ),
        ),
    )


def test_status_and_timeline_entries_lead_with_their_state_mark() -> None:
    blocks = [
        {"type": "status_list", "items": [{"state": "blocked", "text": "Vendor"}]},
        {
            "type": "timeline",
            "items": [
                {"time": "Mon", "title": "Start", "state": "done", "badges": ["API"], "body": "kick-off"},
                {"title": "Later"},
            ],
        },
    ]

    assert lowered(blocks, badges=API_BADGES) == (
        API_LEGEND,
        ListNode("bullet", (ListEntry((StatusMark("blocked"), Plain(" "), Plain("Vendor"))),)),
        ListNode(
            "bullet",
            (
                ListEntry(
                    (
                        StatusMark("done"),
                        Plain(" "),
                        *bold("Mon"),
                        Plain(": "),
                        Plain("Start"),
                        Plain(" "),
                        Chip("api", "blue"),
                    ),
                    children=(Paragraph((Plain("kick-off"),)),),
                ),
                ListEntry((Plain("Later"),)),
            ),
        ),
    )


def test_a_state_glyph_is_a_coloured_emoji_because_markdown_has_no_css_class_to_colour_it() -> None:
    assert {state: status_glyph(state) for state in get_args(StatusState)} == {
        "done": "✅",
        "current": "🔵",
        "pending": "⚪",
        "failed": "❌",
        "blocked": "⛔",
    }


def test_a_definition_keeps_its_later_paragraphs_and_an_empty_body_is_its_term_alone() -> None:
    block = {
        "type": "def_list",
        "items": [{"term": "Fix", "body": "first\n\nsecond"}, {"term": "Gap", "body": " "}],
    }

    assert lowered([block]) == (
        ListNode(
            "bullet",
            (
                ListEntry(
                    (*bold("Fix"), Plain(": "), Plain("first")), children=(Paragraph((Plain("second"),)),)
                ),
                ListEntry(bold("Gap")),
            ),
        ),
    )


@pytest.mark.parametrize(
    ("label", "text", "runs"),
    [
        pytest.param("Site", plain("West"), (*bold("Site"), Plain(": "), Plain("West")), id="label-and-text"),
        pytest.param(
            "Site:",
            plain("West"),
            (*bold("Site"), Plain(": "), Plain("West")),
            id="its-own-colon-is-not-doubled",
        ),
        pytest.param(":", plain("West"), (Plain("West"),), id="a-lone-colon-is-no-label"),
        pytest.param(None, plain("West"), (Plain("West"),), id="no-label"),
        pytest.param("Gap", (), bold("Gap"), id="no-text-leaves-no-dangling-colon"),
    ],
)
def test_a_label_is_bold_and_joined_to_its_text_by_one_colon(
    label: str | None, text: ExportRich, runs: ExportRich
) -> None:
    assert with_bold_label(label, text) == runs


def test_a_badge_row_is_a_labelled_line_and_its_groups_are_labelled_bullets() -> None:
    blocks = [
        {
            "type": "badge_row",
            "label": "Affects:",
            "items": [{"key": "API"}, {"label": "two\nlines", "tone": "red"}],
        },
        {"type": "badge_row", "groups": [{"label": "Owners:", "items": [{"label": "ops", "tone": "teal"}]}]},
    ]

    assert lowered(blocks, badges=API_BADGES) == (
        API_LEGEND,
        Paragraph((*bold("Affects"), Plain(": "), Chip("api", "blue"), Plain(" "), Chip("two lines", "red"))),
        ListNode("bullet", (ListEntry((*bold("Owners"), Plain(": "), Chip("ops", "teal"))),)),
    )


def test_a_badge_label_or_legend_with_a_line_break_stays_on_one_line() -> None:
    badges = {"API": {"label": "a\npi", "tone": "blue", "legend": "the API,\n- folded\n"}}

    assert lowered([{"type": "badge_row", "items": [{"key": "API"}]}], badges=badges) == (
        Toggle(
            (Plain("Legend: badges used on this page"),),
            None,
            (
                ListNode(
                    "bullet", (ListEntry((Chip("a pi", "blue"), Plain(" "), Plain("the API, - folded"))),)
                ),
            ),
        ),
        Paragraph((Chip("a pi", "blue"),)),
    )


@pytest.mark.parametrize(
    ("image", "caption"),
    [
        pytest.param(
            {"caption": "Fig **1** [^x]"}, "Fig **1** [^x]", id="caption-stays-literal-like-the-html"
        ),
        pytest.param({}, "chart", id="no-caption-falls-back-to-alt"),
    ],
)
def test_an_embedded_image_becomes_its_caption(image: dict[str, Any], caption: str) -> None:
    block = {"type": "image", "src": "data:image/png;base64,AA==", "alt": "chart", **image}

    assert lowered([block]) == (Paragraph((Styled("italic", (Plain(f"Image: {caption}"),)),), "muted"),)


@pytest.mark.parametrize(
    ("code", "nodes"),
    [
        pytest.param(
            {"label": "q.sql", "content": "select 1\n\n"},
            (Paragraph((Code("q.sql"),)), CodeBlock("select 1", "sql")),
            id="suffix",
        ),
        pytest.param(
            {"label": "fix.ts", "content": "+a", "mode": "diff"},
            (Paragraph((Code("fix.ts"),)), CodeBlock("+a", "diff")),
            id="diff",
        ),
        pytest.param(
            {"label": "notes.unknown", "content": "x"},
            (Paragraph((Code("notes.unknown"),)), CodeBlock("x", "")),
            id="unmapped-suffix",
        ),
        pytest.param({"content": "plain"}, (CodeBlock("plain", ""),), id="no-label"),
        pytest.param(
            {"label": "run.sh\n# injected", "content": "x"},
            (Paragraph((Code("run.sh # injected"),)), CodeBlock("x", "")),
            id="label-stays-on-one-line",
        ),
    ],
)
def test_a_code_block_language_comes_from_its_label_or_mode(
    code: dict[str, Any], nodes: tuple[Node, ...]
) -> None:
    assert lowered([{"type": "code", **code}]) == nodes


def test_a_quote_and_a_note_keep_their_text() -> None:
    blocks = [
        {"type": "quote", "body": "said\n\nagain", "cite": "Ops"},
        {"type": "note", "title": "Aside", "body": "x"},
    ]

    assert lowered(blocks) == (
        Quote(((Plain("said"),), (Plain("again"),)), (Plain("Ops"),)),
        Callout("neutral", (Paragraph(bold("Aside")), Paragraph((Plain("x"),)))),
    )


def test_an_untitled_callout_and_note_are_their_body_alone() -> None:
    blocks = [{"type": "callout", "tone": "warning", "body": "careful"}, {"type": "note", "body": "aside"}]

    assert lowered(blocks) == (
        Callout("warning", (Paragraph((Plain("careful"),)),)),
        Callout("neutral", (Paragraph((Plain("aside"),)),)),
    )


def test_a_collapsed_section_is_a_toggle_heading_with_its_updated_line() -> None:
    section = {
        "type": "section",
        "title": "Raw",
        "updated": "1 Jan",
        "blocks": [{"type": "text", "body": "x"}],
    }

    assert lowered([section]) == (
        Toggle(
            (Plain("Raw"),),
            2,
            (Paragraph(italic(plain("updated 1 Jan")), "muted"), Paragraph((Plain("x"),))),
            "raw",
        ),
    )


def test_a_panel_and_a_walkthrough_carry_their_content() -> None:
    blocks = [
        {"type": "panel", "title": "Next", "blocks": [{"type": "text", "body": "p"}]},
        {
            "type": "walkthrough",
            "steps": [
                {"label": "Go", "sub": "first", "tone": "info", "detail": [{"type": "text", "body": "d"}]}
            ],
        },
    ]

    assert lowered(blocks) == (
        Callout("neutral", (Paragraph(bold("Next")), Paragraph((Plain("p"),)))),
        ListNode(
            "number",
            (
                ListEntry(
                    (*bold("Go"), Plain(" "), Styled("italic", (Plain("first"),))),
                    children=(Paragraph((Plain("d"),)),),
                    tone="info",
                ),
            ),
        ),
    )
