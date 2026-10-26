from typing import Any

import pytest

from skaldr.code_language import code_language
from skaldr.export.inline import bold, plain
from skaldr.export.lower import lower_report
from skaldr.export.lower.context import with_bold_label
from skaldr.export.runs import Chip, ExportRich
from skaldr.export.tree import (
    BlockRegion,
    Callout,
    CodeBlock,
    DisplayMath,
    Divider,
    Heading,
    HeadingLevel,
    ListEntry,
    ListNode,
    LoweredDocument,
    Media,
    Node,
    PagePart,
    Paragraph,
    Quote,
    ReferenceEntry,
    References,
    TableOfContents,
    TocEntry,
    Toggle,
    capped_heading_level,
    heading_of,
)
from skaldr.models import parse_report
from skaldr.richtext import AnchorLink, Code, InlineMath, Link, Plain, Rich, Styled, Tinted
from tests.factories import API_BADGES, lowered, lowered_as_written_today, make_report
from tests.factories.lower_factory import API_LEGEND


def test_a_report_lowers_to_its_title_and_body() -> None:
    report = parse_report(make_report(meta={"title": "Count", "subtitle": ["Sub **bold** {{blank}}"]}))

    assert lower_report(report) == LoweredDocument(
        "Count",
        (
            PagePart("header", (Paragraph((Plain("Sub **bold** {{blank}}"),), "muted"),)),
            BlockRegion(0, (Paragraph((Plain("Hello."),)),)),
        ),
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
        pytest.param("[a\nb]{tone=info}", (Tinted("info", None, (Plain("a b"),)),), id="tinted"),
        pytest.param("  x  ", (Plain("x"),), id="outer-spaces-trimmed"),
        pytest.param("  `x`  ", (Code("x"),), id="outer-spaces-around-code-dropped"),
        pytest.param("`x\ry`", (Code("x y"),), id="code-carriage-return"),
        pytest.param("`x\r\ny`", (Code("x y"),), id="code-crlf"),
        pytest.param("`x\n`", (Code("x "),), id="code-ending-in-a-line-break"),
        pytest.param("`\n`", (Code(" "),), id="code-of-only-a-line-break"),
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


def test_a_level_four_heading_keeps_its_level_and_anchor() -> None:
    assert lowered([{"type": "heading", "level": 4, "text": "Bin detail"}]) == (
        Heading(4, (Plain("Bin detail"),), "bin-detail"),
    )


@pytest.mark.parametrize(
    ("level", "capped"),
    [
        pytest.param(0, 1, id="below-the-range"),
        pytest.param(1, 1, id="top"),
        pytest.param(5, 5, id="below-the-cap"),
        pytest.param(6, 6, id="the-cap"),
        pytest.param(7, 6, id="past-the-cap"),
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
        Paragraph((Plain("SOP v2"), Plain(" · "), Plain("1 Oct")), "muted"),
    )


@pytest.mark.parametrize(
    ("meta", "runs"),
    [
        pytest.param(
            {"source": "commit `abc123` in `app.ts`"},
            (Plain("commit "), Code("abc123"), Plain(" in "), Code("app.ts")),
            id="the-source-is-rich-text",
        ),
        pytest.param(
            {"source": "x", "date": "a `b` + c"},
            (Plain("x"), Plain(" · "), Plain("a `b` + c")),
            id="the-date-and-the-other-facts-stay-plain",
        ),
        pytest.param({"date": "1 Oct"}, (Plain("1 Oct"),), id="no-source"),
        pytest.param({"source": " ", "date": "1 Oct"}, (Plain("1 Oct"),), id="a-blank-source-is-no-source"),
    ],
)
def test_the_provenance_footer_reads_its_source_as_rich_text(meta: dict[str, str], runs: ExportRich) -> None:
    assert lowered([{"type": "text", "body": "x"}], meta={"title": "T", **meta}) == (
        Paragraph((Plain("x"),)),
        Paragraph(runs, "muted"),
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


def test_references_lower_to_a_node_holding_each_number_text_and_source_address() -> None:
    references = {
        "type": "references",
        "items": [{"key": "a", "text": "SOP", "url": "https://e.com"}, {"key": "b", "text": "Memo"}],
    }

    assert lowered([references]) == (
        References(
            (
                ReferenceEntry(1, (Plain("SOP"),), "https://e.com"),
                ReferenceEntry(2, (Plain("Memo"),)),
            )
        ),
    )


def test_references_are_written_today_as_bullets_led_by_their_number_with_a_source_link() -> None:
    references = {
        "type": "references",
        "items": [{"key": "a", "text": "SOP", "url": "https://e.com"}, {"key": "b", "text": "Memo"}],
    }

    assert lowered_as_written_today([references]) == (
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


@pytest.mark.parametrize(
    ("image", "node"),
    [
        pytest.param(
            {"caption": "Overflow bins"},
            Media("image", "https://example.com/aisle.png", plain("Aisle 12"), plain("Overflow bins")),
            id="with-a-caption",
        ),
        pytest.param({}, Media("image", "https://example.com/aisle.png", plain("Aisle 12")), id="alt-only"),
        pytest.param(
            {"src": "data:image/png;base64,AA=="},
            Media("image", "data:image/png;base64,AA==", plain("Aisle 12")),
            id="data-uri-left-for-the-writers-to-refuse",
        ),
    ],
)
def test_an_image_keeps_its_source_alt_and_caption(image: dict[str, Any], node: Media) -> None:
    block = {"type": "image", "src": "https://example.com/aisle.png", "alt": "Aisle 12", **image}

    assert lowered([block]) == (node,)


@pytest.mark.parametrize(
    ("block", "node"),
    [
        pytest.param(
            {"kind": "video", "src": "https://example.com/walk.mp4", "caption": "Dock walk"},
            Media("video", "https://example.com/walk.mp4", (), plain("Dock walk")),
            id="video-with-a-caption",
        ),
        pytest.param(
            {"kind": "pdf", "src": "https://example.com/sheet.pdf"},
            Media("pdf", "https://example.com/sheet.pdf"),
            id="pdf-without-a-caption",
        ),
    ],
)
def test_a_media_block_keeps_its_kind_url_and_caption(block: dict[str, Any], node: Media) -> None:
    assert lowered([{"type": "media", **block}]) == (node,)


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
            {"content": "gh run list", "lang": "shell"}, (CodeBlock("gh run list", "shell"),), id="lang"
        ),
        pytest.param(
            {"label": "q.sql", "content": "x", "lang": "plain text"},
            (Paragraph((Code("q.sql"),)), CodeBlock("x", "plain text")),
            id="lang-wins-over-the-label-suffix",
        ),
        pytest.param(
            {"content": "+a", "mode": "diff", "lang": "python"},
            (CodeBlock("+a", "diff"),),
            id="diff-mode-wins-over-lang",
        ),
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


@pytest.mark.parametrize(
    ("label", "language"),
    [
        pytest.param("Deploy.SH", "bash", id="an-upper-case-suffix"),
        pytest.param("app.Py", "python", id="a-mixed-case-suffix"),
        pytest.param(None, "", id="no-label"),
        pytest.param("Makefile", "", id="no-suffix"),
    ],
)
def test_a_code_language_ignores_the_case_of_the_label_suffix(label: str | None, language: str) -> None:
    assert code_language(label) == language


def test_a_quote_and_a_note_keep_their_text() -> None:
    blocks = [
        {"type": "quote", "body": "said\n\nagain", "cite": "Ops"},
        {"type": "note", "title": "Aside", "body": "x"},
    ]

    assert lowered(blocks) == (
        Quote((Paragraph((Plain("said"),)), Paragraph((Plain("again"),))), (Plain("Ops"),)),
        Callout("neutral", (Paragraph(bold("Aside")), Paragraph((Plain("x"),)))),
    )


@pytest.mark.parametrize(
    ("expression", "lowered_expression"),
    [
        pytest.param("E = mc^2", "E = mc^2", id="one-line"),
        pytest.param("\n  a \\\\\n\n  b\n\n", "  a \\\\\n  b", id="blank-lines-dropped"),
    ],
)
def test_a_math_block_keeps_its_expression_without_blank_lines(
    expression: str, lowered_expression: str
) -> None:
    assert lowered([{"type": "math", "expression": expression}]) == (DisplayMath(lowered_expression),)


@pytest.mark.parametrize(
    ("item", "runs"),
    [
        pytest.param("$`a\nb`$", (InlineMath("a b"),), id="line-break-inside"),
        pytest.param("$`a\r\nb`$", (InlineMath("a b"),), id="crlf-inside"),
    ],
)
def test_inline_math_lowers_onto_one_line(item: str, runs: Rich) -> None:
    assert lowered([{"type": "list", "items": [item]}]) == (ListNode("bullet", (ListEntry(runs),)),)


def test_an_untitled_callout_and_note_are_their_body_alone() -> None:
    blocks = [{"type": "callout", "tone": "warning", "body": "careful"}, {"type": "note", "body": "aside"}]

    assert lowered(blocks) == (
        Callout("warning", (Paragraph((Plain("careful"),)),)),
        Callout("neutral", (Paragraph((Plain("aside"),)),)),
    )


def test_a_callout_and_a_note_carry_their_icon() -> None:
    blocks = [
        {"type": "callout", "tone": "success", "icon": "🚀", "title": "Go", "body": "now"},
        {"type": "note", "icon": "📌", "body": "aside"},
    ]

    assert lowered(blocks) == (
        Callout("success", (Paragraph(bold("Go")), Paragraph((Plain("now"),))), icon="🚀"),
        Callout("neutral", (Paragraph((Plain("aside"),)),), icon="📌"),
    )


def test_a_divider_lowers_to_a_divider_node_between_its_neighbours() -> None:
    blocks = [{"type": "text", "body": "a"}, {"type": "divider"}, {"type": "text", "body": "b"}]

    assert lowered(blocks) == (Paragraph((Plain("a"),)), Divider(), Paragraph((Plain("b"),)))
