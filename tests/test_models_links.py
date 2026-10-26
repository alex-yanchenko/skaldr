from typing import Any, get_args

import pytest

from skaldr.errors import ReportError
from skaldr.models import Image, Media, MediaKind, is_data_uri, parse_report
from tests.factories import make_report


def _refusal(block: dict[str, Any]) -> str:
    with pytest.raises(ReportError) as raised:
        parse_report(make_report(blocks=[block]))
    return str(raised.value)


@pytest.mark.parametrize("src", ["https://example.com/aisle.png", "http://example.com/aisle.png"])
def test_an_image_may_name_a_web_url(src: str) -> None:
    block = parse_report(make_report(blocks=[{"type": "image", "src": src, "alt": "Aisle 12"}])).blocks[0]

    assert block == Image(type="image", src=src, alt="Aisle 12")


@pytest.mark.parametrize(
    "src", ["ftp://example.com/x.png", "file:///etc/passwd", "javascript:alert(1)", "x.png"]
)
def test_an_image_src_that_is_neither_a_data_uri_nor_a_web_url_is_refused(src: str) -> None:
    assert _refusal({"type": "image", "src": src, "alt": "x"}) == (
        "invalid content data: blocks.0.image: "
        "Value error, 'src' must be a data: URI or an http:// or https:// URL"
    )


@pytest.mark.parametrize(
    ("src", "a_data_uri"),
    [
        pytest.param("data:image/png;base64,AA==", True, id="data-uri"),
        pytest.param("https://example.com/data:x.png", False, id="https-holding-data-colon"),
        pytest.param("http://example.com/aisle.png", False, id="http"),
        pytest.param("DATA:image/png;base64,AA==", False, id="upper-case-scheme"),
    ],
)
def test_is_data_uri_reads_only_the_scheme_at_the_start(src: str, a_data_uri: bool) -> None:
    assert is_data_uri(src) is a_data_uri


@pytest.mark.parametrize(
    "alt",
    [
        pytest.param({}, id="missing"),
        pytest.param({"alt": ""}, id="empty"),
        pytest.param({"alt": "  \t"}, id="whitespace"),
    ],
)
def test_an_image_without_visible_alt_text_is_refused(alt: dict[str, str]) -> None:
    assert _refusal({"type": "image", "src": "https://example.com/x.png", **alt}) == (
        "invalid content data: blocks.0.image: Value error, 'alt' must hold visible text"
    )


@pytest.mark.parametrize("kind", get_args(MediaKind))
def test_a_media_block_names_a_kind_and_a_web_url(kind: MediaKind) -> None:
    src = "https://example.com/count-sheet"
    block = {"type": "media", "kind": kind, "src": src, "caption": "Signed count sheet"}

    assert parse_report(make_report(blocks=[block])).blocks[0] == Media(
        type="media", kind=kind, src=src, caption="Signed count sheet"
    )


@pytest.mark.parametrize("src", ["data:application/pdf;base64,AA==", "ftp://example.com/a.pdf", "a.pdf"])
def test_a_media_src_must_be_an_http_or_https_url(src: str) -> None:
    assert _refusal({"type": "media", "kind": "pdf", "src": src}) == (
        "invalid content data: blocks.0.media: Value error, 'src' must be an http:// or https:// link"
    )


def test_a_media_kind_must_be_one_the_block_knows() -> None:
    assert _refusal({"type": "media", "kind": "embed", "src": "https://example.com/x"}) == (
        "invalid content data: blocks.0.media.kind: Input should be 'video', 'audio', 'file' or 'pdf'"
    )


@pytest.mark.parametrize("kind", ["image", "media"])
@pytest.mark.parametrize("src", ["https://clerk:s3cret@example.com/x.png", "https://clerk@example.com/x.png"])
def test_a_url_carrying_a_username_or_password_is_refused(kind: str, src: str) -> None:
    extra = {"alt": "x"} if kind == "image" else {"kind": "video"}

    assert _refusal({"type": kind, "src": src, **extra}) == (
        f"invalid content data: blocks.0.{kind}: "
        f"Value error, 'src' {src!r} is not a valid URL (it holds a username or password)"
    )


def test_references_rejects_duplicate_keys_within_a_block() -> None:
    block = {
        "type": "references",
        "items": [
            {"key": "a", "text": "First"},
            {"key": "b", "text": "Second"},
            {"key": "a", "text": "Clash"},
        ],
    }
    with pytest.raises(ReportError) as raised:
        parse_report(make_report(blocks=[block]))

    assert str(raised.value) == (
        "invalid content data: Value error, reference key(s) used more than once: ['a'], at "
        "blocks.0.references.items.0.key, blocks.0.references.items.2.key; reference keys must be unique"
    )


def test_references_rejects_a_key_reused_across_separate_blocks() -> None:
    first = {"type": "references", "items": [{"key": "a", "text": "First"}]}
    second = {"type": "references", "items": [{"key": "a", "text": "Clash"}]}
    with pytest.raises(ReportError, match=r"reference key\(s\) used more than once: \['a'\]"):
        parse_report(make_report(blocks=[first, second]))


def test_references_rejects_key_with_disallowed_characters() -> None:
    block = {"type": "references", "items": [{"key": "has space", "text": "x"}]}
    with pytest.raises(ReportError, match=r"blocks\.0\.references\.items\.0\.key"):
        parse_report(make_report(blocks=[block]))


def test_references_rejects_url_with_a_disallowed_scheme() -> None:
    block = {"type": "references", "items": [{"key": "a", "text": "x", "url": "javascript:alert(1)"}]}
    with pytest.raises(ReportError, match=r"'url' must be an http://, https://, or mailto: link"):
        parse_report(make_report(blocks=[block]))


@pytest.mark.parametrize(
    ("url", "reason"),
    [
        pytest.param("https://", "empty host", id="no-host"),
        pytest.param("http://#frag", "empty host", id="fragment-only"),
        pytest.param("https://exa mple.com", "it holds whitespace", id="space-in-host"),
        pytest.param("https://exa<mple.com", "invalid international domain name", id="bad-host"),
        pytest.param("https://[::1", "invalid IPv6 address", id="broken-ipv6"),
        pytest.param("https://x.io:99999", "invalid port number", id="port-out-of-range"),
        pytest.param("https://x.io/a b", "it holds whitespace", id="space-in-path"),
        pytest.param("https://x.io/a\tb", "it holds whitespace", id="tab-in-path"),
        pytest.param("https://x.io/\n\n# h", "it holds whitespace", id="newline"),
        pytest.param("https://clerk:s3cret@x.io", "it holds a username or password", id="user-and-password"),
        pytest.param("mailto:", "it names no address", id="bare-mailto"),
        pytest.param("mailto:?subject=hi", "it names no address", id="mailto-with-only-a-query"),
    ],
)
def test_references_rejects_a_malformed_url(url: str, reason: str) -> None:
    block = {"type": "references", "items": [{"key": "a", "text": "x", "url": url}]}

    with pytest.raises(ReportError) as raised:
        parse_report(make_report(blocks=[block]))

    assert str(raised.value) == (
        "invalid content data: blocks.0.references.items.0: "
        f"Value error, 'url' {url!r} is not a valid URL ({reason})"
    )


@pytest.mark.parametrize(
    "url",
    ["https://x.io", "mailto:ops@example.com", "mailto:ops@example.com?subject=hi", "http://x.io/a%20b"],
)
def test_a_valid_url_is_kept_exactly_as_the_author_wrote_it(url: str) -> None:
    block = {"type": "references", "items": [{"key": "a", "text": "x", "url": url}]}

    report = parse_report(make_report(blocks=[block]))

    assert report.model_dump(mode="json")["blocks"][0]["items"][0]["url"] == url


def test_references_requires_at_least_one_item() -> None:
    with pytest.raises(ReportError, match=r"blocks\.0\.references\.items.*at least 1"):
        parse_report(make_report(blocks=[{"type": "references", "items": []}]))
