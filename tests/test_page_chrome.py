from pathlib import Path
from typing import Any

import pytest

from skaldr.errors import ReportError
from skaldr.export.lower import lower_report
from skaldr.export.markdown import render_markdown_document
from skaldr.export.notion import render_notion
from skaldr.export.tree import BlockRegion, LoweredDocument, Paragraph
from skaldr.models import Meta, load_report, parse_report
from skaldr.render import render_embed, render_html
from skaldr.richtext import Plain
from tests.factories import make_report, write_index_document

COVER = "https://example.com/cover.png"
BEAKER_FAVICON = (
    '<link rel="icon" href="data:image/svg+xml,%3Csvg%20xmlns%3D%22http%3A//www.w3.org/2000/svg%22'
    "%20viewBox%3D%220%200%20100%20100%22%3E%3Ctext%20y%3D%22.9em%22%20font-size%3D%2290%22%3E"
    '%F0%9F%A7%AA%3C/text%3E%3C/svg%3E">'
)


def report_with(**meta: Any) -> dict[str, Any]:
    return make_report(meta={"title": "Q3 count", **meta})


def test_the_page_header_has_no_icon_or_cover_by_default() -> None:
    meta = parse_report(make_report()).meta

    assert (meta.icon, meta.cover) == (None, None)


def test_the_icon_and_the_cover_are_kept_as_written() -> None:
    meta = parse_report(report_with(icon="\U0001f9ea", cover=COVER)).meta

    assert meta == Meta(title="Q3 count", icon="\U0001f9ea", cover=COVER)


def test_an_icon_that_is_not_one_emoji_is_refused() -> None:
    with pytest.raises(ReportError) as raised:
        parse_report(report_with(icon="lab"))

    assert str(raised.value) == (
        "invalid content data: meta.icon: Value error, icon must be a single emoji (got 'lab')"
    )


@pytest.mark.parametrize("cover", ["ftp://example.com/a.png", "/cover.png", "data:image/png;base64,AA=="])
def test_a_cover_that_is_not_http_or_https_is_refused(cover: str) -> None:
    with pytest.raises(ReportError) as raised:
        parse_report(report_with(cover=cover))

    assert str(raised.value) == (
        "invalid content data: meta: Value error, 'cover' must be an http:// or https:// link"
    )


@pytest.mark.parametrize("cover", ["HTTPS://example.com/a.png", " https://example.com/a.png"], ids=repr)
def test_a_cover_with_an_uppercase_scheme_or_a_leading_space_is_refused(cover: str) -> None:
    with pytest.raises(ReportError) as raised:
        parse_report(report_with(cover=cover))

    assert str(raised.value) == (
        "invalid content data: meta: Value error, 'cover' must be an http:// or https:// link"
    )


@pytest.mark.parametrize(
    "cover", ["https://user:pw@example.com/a.png", "https://google.com@evil.com"], ids=str
)
def test_a_cover_holding_a_username_or_password_is_refused(cover: str) -> None:
    with pytest.raises(ReportError) as raised:
        parse_report(report_with(cover=cover))

    assert str(raised.value) == (
        f"invalid content data: meta: Value error, 'cover' {cover!r} is not a valid URL "
        "(it holds a username or password)"
    )


def test_an_ampersand_in_the_cover_is_escaped_in_the_href() -> None:
    html = render_html(parse_report(report_with(cover="https://example.com/c.png?w=1&h=2")))

    assert '<p class="cover"><a href="https://example.com/c.png?w=1&amp;h=2">Cover image</a></p>' in html


def test_an_index_document_carries_its_icon_and_cover_into_the_lowered_document(tmp_path: Path) -> None:
    index = write_index_document(
        tmp_path,
        {"one.yaml": make_report(meta={"title": "Part one"})},
        meta={"title": "Combined", "icon": "\U0001f9ea", "cover": COVER},
    )

    document = lower_report(load_report(index))

    assert (document.title, document.icon, document.cover) == ("Combined", "\U0001f9ea", COVER)


def test_a_malformed_cover_is_refused() -> None:
    with pytest.raises(ReportError) as raised:
        parse_report(report_with(cover="https://"))

    assert str(raised.value) == (
        "invalid content data: meta: Value error, 'cover' 'https://' is not a valid URL (empty host)"
    )


def test_the_icon_sits_beside_the_title() -> None:
    html = render_html(parse_report(report_with(icon="\U0001f9ea")))

    assert '<h1><span class="title-icon" aria-hidden="true">\U0001f9ea</span>Q3 count</h1>' in html


def test_the_icon_sits_beside_the_title_in_the_hero_band() -> None:
    html = render_html(parse_report(report_with(icon="\U0001f9ea", hero=True)))

    assert (
        '<header class="hero"><h1><span class="title-icon" aria-hidden="true">\U0001f9ea</span>'
        "Q3 count</h1></header>"
    ) in html


def test_the_icon_is_the_favicon_as_an_inline_svg() -> None:
    html = render_html(parse_report(report_with(icon="\U0001f9ea")))

    assert BEAKER_FAVICON in html


def test_a_page_without_an_icon_has_no_favicon_link_and_a_plain_title() -> None:
    html = render_html(parse_report(report_with()))

    assert '<link rel="icon"' not in html
    assert "<h1>Q3 count</h1>" in html


def test_the_cover_is_a_link_because_the_page_allows_no_remote_images() -> None:
    html = render_html(parse_report(report_with(cover=COVER)))

    assert f'<p class="cover"><a href="{COVER}">Cover image</a></p>' in html
    assert f'src="{COVER}"' not in html
    assert "img-src data:;" in html


def test_an_embedded_fragment_shows_the_icon_and_the_cover_link_without_a_favicon() -> None:
    fragment = render_embed(parse_report(report_with(icon="\U0001f9ea", cover=COVER)))

    assert '<span class="title-icon" aria-hidden="true">\U0001f9ea</span>Q3 count' in fragment
    assert f'<a href="{COVER}">Cover image</a>' in fragment
    assert '<link rel="icon"' not in fragment


def test_the_lowered_document_carries_the_icon_and_the_cover() -> None:
    document = lower_report(parse_report(report_with(icon="\U0001f9ea", cover=COVER)))

    assert document == LoweredDocument(
        "Q3 count",
        (BlockRegion(0, (Paragraph((Plain("Hello."),)),)),),
        icon="\U0001f9ea",
        cover=COVER,
    )


def test_github_markdown_leads_the_title_with_the_icon_and_links_the_cover_under_it() -> None:
    document = lower_report(parse_report(report_with(icon="\U0001f9ea", cover=COVER)))

    assert render_markdown_document(document) == (
        f"# \U0001f9ea Q3 count\n\n[Cover image]({COVER})\n\nHello.\n"
    )


def test_github_markdown_keeps_the_plain_title_without_an_icon_or_a_cover() -> None:
    document = lower_report(parse_report(report_with()))

    assert render_markdown_document(document) == "# Q3 count\n\nHello.\n"


def test_github_markdown_puts_the_cover_between_the_title_and_the_body() -> None:
    document = lower_report(parse_report(make_report(meta={"title": "Q3 count", "cover": COVER})))

    assert render_markdown_document(document) == f"# Q3 count\n\n[Cover image]({COVER})\n\nHello.\n"


def test_notion_markdown_carries_neither_because_they_are_page_properties() -> None:
    plain_body = render_notion(lower_report(parse_report(report_with())).body)
    decorated = render_notion(lower_report(parse_report(report_with(icon="\U0001f9ea", cover=COVER))).body)

    assert decorated == plain_body == "Hello.\n"


def test_the_json_dump_names_the_icon_and_the_cover() -> None:
    dumped = parse_report(report_with(icon="\U0001f9ea", cover=COVER)).model_dump(mode="json")["meta"]

    assert (dumped["icon"], dumped["cover"]) == ("\U0001f9ea", COVER)
