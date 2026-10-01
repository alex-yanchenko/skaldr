from typing import Any

import pytest

from skaldr.errors import ReportError
from skaldr.export.inline import bold, italic, plain
from skaldr.export.lower import lower_report
from skaldr.export.runs import Chip, Gauge, Mark
from skaldr.export.tree import (
    Callout,
    CodeBlock,
    Heading,
    ListEntry,
    ListNode,
    LoweredDocument,
    Node,
    Paragraph,
    Quote,
    TableOfContents,
    TocEntry,
    Toggle,
)
from skaldr.models import parse_report
from skaldr.richtext import Code, Link, Plain, Styled
from tests.factories import API_BADGES, lowered, make_report

API_LEGEND = Toggle(
    (Plain("Legend: badges used on this page"),),
    None,
    (ListNode("bullet", (ListEntry((Chip("api", "blue"), Plain(" the API"))),)),),
)


def test_a_report_lowers_to_its_title_and_body() -> None:
    report = parse_report(make_report(meta={"title": "Count", "subtitle": ["Sub **bold** {{blank}}"]}))

    assert lower_report(report) == LoweredDocument(
        "Count",
        (Paragraph((Plain("Sub **bold** {{blank}}"),), "muted"), Paragraph((Plain("Hello."),))),
    )


def test_a_block_with_no_markdown_form_yet_fails_naming_its_type() -> None:
    with pytest.raises(ReportError, match=r"^a `flow` block has no Markdown export yet$"):
        lowered([{"type": "flow", "steps": [{"label": "a"}, {"label": "b"}]}])


def test_rich_text_keeps_the_spaces_inside_a_code_span() -> None:
    assert lowered([{"type": "text", "body": "run  `a  b`\nnow"}]) == (
        Paragraph((Plain("run "), Code("a  b"), Plain(" now"))),
    )


def test_an_author_heading_id_becomes_the_anchor() -> None:
    assert lowered([{"type": "heading", "text": "Count", "id": "tally"}]) == (
        Heading(2, (Plain("Count"),), "tally"),
    )


def test_a_heading_with_a_line_break_stays_one_heading() -> None:
    assert lowered([{"type": "heading", "text": "First\n## Injected"}]) == (
        Heading(2, (Plain("First ## Injected"),), "first-injected"),
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
        ListNode(
            "bullet",
            (
                ListEntry(
                    (
                        *bold("Clean"),
                        Plain(": "),
                        Plain("9"),
                        Plain(" (90.0%)"),
                        Plain(" "),
                        Mark("delta", "up"),
                        Plain(" +1"),
                        Plain(" "),
                        Chip("api", "blue"),
                    ),
                    children=(Paragraph((Plain("since Monday"),), "muted"),),
                    tone="success",
                ),
            ),
        ),
        API_LEGEND,
    )


def test_a_meter_reading_is_a_gauge_with_its_share_and_tone() -> None:
    meter = {"type": "meter", "items": [{"label": "Zone", "value": 5, "max": 10, "tone": "warning"}]}

    assert lowered([meter]) == (
        ListNode(
            "bullet",
            (
                ListEntry(
                    (*bold("Zone"), Plain(": "), Gauge(5, 10), Plain(" 50.0% (5 of 10)")), tone="warning"
                ),
            ),
        ),
    )


def test_a_range_shows_its_axis_and_each_segment_share() -> None:
    block = {
        "type": "range",
        "axis": {"min": "Jan"},
        "segments": [
            {"label": "Seg", "span": 1, "tone": "danger", "sub": "one"},
            {"label": "Rest", "span": 3},
        ],
    }

    assert lowered([block]) == (
        Paragraph((Plain("From Jan to end"),), "muted"),
        ListNode(
            "bullet",
            (
                ListEntry(
                    (*bold("Seg"), Plain(": "), Plain("1 (25.0%)"), Plain(", "), Plain("one")), tone="danger"
                ),
                ListEntry((*bold("Rest"), Plain(": "), Plain("3 (75.0%)"))),
            ),
        ),
    )


def test_status_and_timeline_entries_lead_with_their_state_mark() -> None:
    blocks = [
        {"type": "status_list", "items": [{"state": "blocked", "text": "Vendor"}]},
        {
            "type": "timeline",
            "items": [{"time": "Mon", "title": "Start", "state": "done"}, {"title": "Later"}],
        },
    ]

    assert lowered(blocks) == (
        ListNode("bullet", (ListEntry((Mark("status", "blocked"), Plain(" "), Plain("Vendor"))),)),
        ListNode(
            "bullet",
            (
                ListEntry((Mark("timeline", "done"), Plain(" "), *bold("Mon"), Plain(": "), Plain("Start"))),
                ListEntry((Plain("Later"),)),
            ),
        ),
    )


def test_definitions_badge_groups_and_references_are_lists() -> None:
    blocks = [
        {"type": "def_list", "items": [{"term": "Fix", "body": "first\n\nsecond"}]},
        {"type": "badge_row", "groups": [{"label": "Owners:", "items": [{"label": "ops", "tone": "teal"}]}]},
        {
            "type": "references",
            "items": [{"key": "a", "text": "SOP", "url": "https://e.com"}, {"key": "b", "text": "Memo"}],
        },
    ]

    assert lowered(blocks) == (
        ListNode(
            "bullet",
            (
                ListEntry(
                    (*bold("Fix"), Plain(": "), Plain("first")), children=(Paragraph((Plain("second"),)),)
                ),
            ),
        ),
        ListNode("bullet", (ListEntry((*bold("Owners"), Plain(": "), Chip("ops", "teal"))),)),
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


def test_an_embedded_image_becomes_its_caption() -> None:
    image = {"type": "image", "src": "data:image/png;base64,AA==", "alt": "chart", "caption": "Fig 1"}

    assert lowered([image]) == (Paragraph(italic((Plain("Image: "), Plain("Fig 1"))), "muted"),)


@pytest.mark.parametrize(
    ("code", "language"),
    [
        pytest.param({"label": "q.sql", "content": "select 1\n"}, "sql", id="suffix"),
        pytest.param({"label": "fix.ts", "content": "+a", "mode": "diff"}, "diff", id="diff"),
        pytest.param({"content": "plain"}, "", id="no-label"),
    ],
)
def test_a_code_block_language_comes_from_its_label_or_mode(code: dict[str, Any], language: str) -> None:
    label: tuple[Node, ...] = (Paragraph((Code(code["label"]),)),) if "label" in code else ()

    assert lowered([{"type": "code", **code}]) == (*label, CodeBlock(code["content"].rstrip("\n"), language))


def test_a_quote_and_a_note_keep_their_text() -> None:
    blocks = [
        {"type": "quote", "body": "said\n\nagain", "cite": "Ops"},
        {"type": "note", "title": "Aside", "body": "x"},
    ]

    assert lowered(blocks) == (
        Quote(((Plain("said"),), (Plain("again"),)), (Plain("Ops"),)),
        Callout("neutral", (Paragraph(bold("Aside")), Paragraph((Plain("x"),)))),
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
