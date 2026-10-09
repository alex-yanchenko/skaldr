from collections.abc import Callable
from typing import Any

import pytest

from skaldr.errors import ReportError
from skaldr.export.runs import export_visible_text
from skaldr.export.tree import Paragraph, Quote
from skaldr.models import Link, parse_report
from skaldr.render import render_html
from skaldr.richtext import Link as LinkRun
from skaldr.richtext import Plain, Styled
from tests.factories import lowered, make_report, markdown_of, notion_of

RUNBOOK = "https://example.com/runbook"


def link_block(**overrides: Any) -> dict[str, Any]:
    return {"type": "link", "url": RUNBOOK, **overrides}


def html_of(block: dict[str, Any]) -> str:
    return render_html(parse_report(make_report(blocks=[block])))


def test_a_link_defaults_to_a_card_without_title_or_caption() -> None:
    report = parse_report(make_report(blocks=[link_block()]))

    assert report.blocks[0] == Link(type="link", url=RUNBOOK, display="card", title=None, caption=None)


@pytest.mark.parametrize(
    "url", [RUNBOOK, "http://example.com/a%20b?x=1#top", "https://example.com:8443"], ids=str
)
def test_a_valid_url_is_kept_exactly_as_the_author_wrote_it(url: str) -> None:
    report = parse_report(make_report(blocks=[link_block(url=url)]))

    assert report.model_dump(mode="json")["blocks"][0]["url"] == url


@pytest.mark.parametrize(
    "url", ["ftp://example.com/a", "mailto:ops@example.com", "javascript:alert(1)", "/a"], ids=str
)
def test_a_url_that_is_not_http_or_https_is_refused(url: str) -> None:
    with pytest.raises(ReportError) as raised:
        parse_report(make_report(blocks=[link_block(url=url)]))

    assert str(raised.value) == (
        "invalid content data: blocks.0.link: Value error, 'url' must be an http:// or https:// link"
    )


@pytest.mark.parametrize(
    ("url", "reason"),
    [
        pytest.param("https://", "empty host", id="no-host"),
        pytest.param("https://exa mple.com", "it holds whitespace", id="space-in-host"),
        pytest.param("https://x.io:99999", "invalid port number", id="port-out-of-range"),
    ],
)
def test_a_malformed_url_is_refused(url: str, reason: str) -> None:
    with pytest.raises(ReportError) as raised:
        parse_report(make_report(blocks=[link_block(url=url)]))

    assert str(raised.value) == (
        f"invalid content data: blocks.0.link: Value error, 'url' {url!r} is not a valid URL ({reason})"
    )


def test_an_unknown_display_is_refused_with_the_three_choices() -> None:
    with pytest.raises(ReportError) as raised:
        parse_report(make_report(blocks=[link_block(display="popup")]))

    assert str(raised.value) == (
        "invalid content data: blocks.0.link.display: Input should be 'inline', 'card' or 'embed'"
    )


def test_an_inline_link_takes_no_caption() -> None:
    with pytest.raises(ReportError) as raised:
        parse_report(make_report(blocks=[link_block(display="inline", caption="rev. 7")]))

    assert str(raised.value) == (
        "invalid content data: blocks.0.link: Value error, a link shown inline takes no caption; "
        "use display: card or display: embed"
    )


def test_a_link_is_refused_without_a_url() -> None:
    with pytest.raises(ReportError) as raised:
        parse_report(make_report(blocks=[{"type": "link"}]))

    assert str(raised.value) == "invalid content data: blocks.0.link.url: Field required"


def test_a_link_nests_inside_a_section() -> None:
    section = {"type": "section", "title": "Docs", "blocks": [link_block()]}

    report = parse_report(make_report(blocks=[section]))

    assert report.model_dump(mode="json")["blocks"][0]["blocks"] == [
        {"type": "link", "span": None, "url": RUNBOOK, "display": "card", "title": None, "caption": None}
    ]


def test_an_inline_link_is_a_paragraph_holding_one_anchor() -> None:
    html = html_of(link_block(display="inline", title="Counting runbook"))

    assert f'<p class="text"><a href="{RUNBOOK}">Counting runbook</a></p>' in html


def test_an_untitled_inline_link_shows_the_url_without_its_scheme() -> None:
    html = html_of(link_block(display="inline"))

    assert f'<p class="text"><a href="{RUNBOOK}">example.com/runbook</a></p>' in html


def test_a_card_shows_the_title_the_domain_and_the_caption() -> None:
    html = html_of(link_block(title="Counting runbook", caption="rev. 7"))

    assert (
        f'<a class="link-card" href="{RUNBOOK}"><span class="lc-title">Counting runbook</span>'
        '<span class="lc-domain">example.com</span><span class="lc-caption">rev. 7</span></a>'
    ) in html


def test_an_untitled_card_leads_with_the_url_and_repeats_no_domain() -> None:
    html = html_of(link_block())

    assert (
        f'<a class="link-card" href="{RUNBOOK}"><span class="lc-title">example.com/runbook</span></a>'
    ) in html


def test_an_embed_renders_as_a_card_that_says_the_page_cannot_load_it() -> None:
    html = html_of(link_block(display="embed", title="Live board"))

    assert (
        f'<a class="link-card embed" href="{RUNBOOK}"><span class="lc-title">Live board</span>'
        '<span class="lc-domain">example.com</span>'
        '<span class="lc-note">This page cannot load embedded content; the card opens the link.</span></a>'
    ) in html
    assert "<iframe" not in html


def test_a_card_title_and_caption_are_escaped() -> None:
    html = html_of(link_block(title="<b>x</b>", caption="a & b"))

    assert '<span class="lc-title">&lt;b&gt;x&lt;/b&gt;</span>' in html
    assert '<span class="lc-caption">a &amp; b</span>' in html


def test_a_link_adds_no_remote_load_to_the_page() -> None:
    html = html_of(link_block(display="embed"))

    assert "img-src data:;" in html
    assert "default-src 'none'" in html


def test_an_inline_link_lowers_to_a_paragraph_with_a_link_run() -> None:
    assert lowered([link_block(display="inline", title="Runbook")]) == (
        Paragraph((LinkRun((Plain("Runbook"),), RUNBOOK),)),
    )


@pytest.mark.parametrize("display", ["card", "embed"])
def test_a_card_and_an_embed_lower_to_the_same_quote(display: str) -> None:
    block = link_block(display=display, title="Runbook", caption="rev. 7")

    assert lowered([block]) == (
        Quote(
            (((Styled("bold", (LinkRun((Plain("Runbook"),), RUNBOOK),)),)),),
            (Plain("example.com · rev. 7"),),
        ),
    )


def test_an_untitled_card_lowers_to_a_quote_led_by_the_bare_url() -> None:
    assert lowered([link_block()]) == (
        Quote((((Styled("bold", (LinkRun((Plain("example.com/runbook"),), RUNBOOK),)),)),), ()),
    )


def test_the_export_text_of_a_card_names_the_title_and_the_domain() -> None:
    (quote,) = lowered([link_block(title="Runbook")])
    assert isinstance(quote, Quote)

    assert [export_visible_text(line) for line in quote.lines] == ["Runbook"]
    assert export_visible_text(quote.cite) == "example.com"


def test_github_markdown_writes_an_inline_link() -> None:
    assert markdown_of([link_block(display="inline", title="Runbook")]) == f"[Runbook]({RUNBOOK})\n"


def test_github_markdown_writes_a_card_as_a_quote() -> None:
    assert markdown_of([link_block(title="Runbook", caption="rev. 7")]) == (
        f"> **[Runbook]({RUNBOOK})**\n>\n> *example.com · rev. 7*\n"
    )


def test_github_markdown_writes_an_embed_as_the_same_quote_and_no_iframe() -> None:
    assert markdown_of([link_block(display="embed", title="Runbook")]) == (
        f"> **[Runbook]({RUNBOOK})**\n>\n> *example.com*\n"
    )


def test_notion_markdown_writes_an_inline_link() -> None:
    assert notion_of([link_block(display="inline", title="Runbook")]) == f"[Runbook]({RUNBOOK})\n"


def test_notion_markdown_writes_a_card_as_a_quote() -> None:
    assert notion_of([link_block(title="Runbook", caption="rev. 7")]) == (
        f"> **[Runbook]({RUNBOOK})**<br>*example.com · rev. 7*\n"
    )


@pytest.mark.parametrize("url", ["HTTPS://example.com/a", " https://example.com/a"], ids=repr)
def test_a_url_with_an_uppercase_scheme_or_a_leading_space_is_refused(url: str) -> None:
    with pytest.raises(ReportError) as raised:
        parse_report(make_report(blocks=[link_block(url=url)]))

    assert str(raised.value) == (
        "invalid content data: blocks.0.link: Value error, 'url' must be an http:// or https:// link"
    )


@pytest.mark.parametrize(
    "url",
    ["https://user:pw@example.com/a", "https://google.com@evil.com", "https://user@example.com"],
    ids=str,
)
def test_a_url_holding_a_username_or_password_is_refused(url: str) -> None:
    with pytest.raises(ReportError) as raised:
        parse_report(make_report(blocks=[link_block(url=url)]))

    assert str(raised.value) == (
        f"invalid content data: blocks.0.link: Value error, 'url' {url!r} is not a valid URL "
        "(it holds a username or password)"
    )


GITHUB_ESCAPES = [
    pytest.param("a]b", "a\\]b", id="bracket"),
    pytest.param("a*b*", "a\\*b\\*", id="asterisk"),
    pytest.param("a_b_", "a\\_b\\_", id="underscore"),
    pytest.param("a<b", "a\\<b", id="angle"),
    pytest.param("a|b", "a|b", id="pipe"),
]
NOTION_ESCAPES = [*GITHUB_ESCAPES[:4], pytest.param("a|b", "a\\|b", id="pipe")]


@pytest.mark.parametrize(("text", "github"), GITHUB_ESCAPES)
def test_github_markdown_escapes_a_title_and_caption(text: str, github: str) -> None:
    assert markdown_of([link_block(title=text, caption=text)]) == (
        f"> **[{github}]({RUNBOOK})**\n>\n> *example.com · {github}*\n"
    )


@pytest.mark.parametrize(("text", "notion"), NOTION_ESCAPES)
def test_notion_markdown_escapes_a_title_and_caption(text: str, notion: str) -> None:
    assert notion_of([link_block(title=text, caption=text)]) == (
        f"> **[{notion}]({RUNBOOK})**<br>*example.com · {notion}*\n"
    )


@pytest.mark.parametrize("writer", [markdown_of, notion_of], ids=["github", "notion"])
def test_a_url_holding_parentheses_is_percent_encoded_so_the_link_stays_whole(
    writer: Callable[[list[dict[str, Any]]], str],
) -> None:
    written = writer([link_block(url="https://example.com/a(b)c)d", title="T")])

    assert "[T](https://example.com/a%28b%29c%29d)" in written


def test_notion_markdown_writes_an_embed_without_an_embed_tag() -> None:
    written = notion_of([link_block(display="embed", title="Runbook")])

    assert written == f"> **[Runbook]({RUNBOOK})**<br>*example.com*\n"
    assert "<embed" not in written
