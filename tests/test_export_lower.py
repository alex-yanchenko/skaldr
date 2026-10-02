from typing import Any

import pytest

from skaldr.errors import ReportError
from skaldr.export.inline import bold, italic, plain
from skaldr.export.lower import lower_report
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
from skaldr.models import parse_report
from skaldr.richtext import AnchorLink, Code, Link, Plain, Rich, Styled
from tests.factories import lowered, make_cell, make_flow, make_grid, make_report


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
        pytest.param({"type": "def_list", "items": [{"term": "a", "body": "b"}]}, "def_list", id="def-list"),
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
