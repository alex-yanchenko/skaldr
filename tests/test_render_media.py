from collections.abc import Callable
from typing import Any

import pytest

from skaldr.models import parse_report
from skaldr.render import render_html
from tests.factories import in_a_grid_cell, in_an_open_section, make_report


def test_image_max_width_renders_style() -> None:
    src = "data:image/svg+xml,<svg/>"
    block = {"type": "image", "src": src, "alt": "a", "max_width": 400}
    report = parse_report(make_report(blocks=[block]))

    html = render_html(report)

    assert 'style="max-width:400px"' in html


def _html_of(block: dict[str, Any]) -> str:
    return render_html(parse_report(make_report(blocks=[block])))


def test_a_web_image_renders_as_a_link_card_with_its_alt_host_and_caption() -> None:
    block = {
        "type": "image",
        "src": "https://cdn.example.com/aisle.png?v=2",
        "alt": "Aisle 12 <overflow>",
        "caption": "Overflow bins",
    }

    assert (
        '<figure class="fig"><div class="frame">'
        '<a class="media-card" href="https://cdn.example.com/aisle.png?v=2" rel="noopener noreferrer">'
        '<span class="media-kind">Image</span>'
        '<span class="media-title">Aisle 12 &lt;overflow&gt;</span>'
        '<span class="media-host">cdn.example.com</span></a></div>'
        "<figcaption>Overflow bins</figcaption></figure>"
    ) in _html_of(block)


def test_a_web_image_with_a_max_width_and_no_caption_keeps_the_width_and_drops_the_caption() -> None:
    block = {"type": "image", "src": "https://example.com/a.png", "alt": "A", "max_width": 300}

    assert (
        '<figure class="fig" style="max-width:300px"><div class="frame">'
        '<a class="media-card" href="https://example.com/a.png" rel="noopener noreferrer">'
        '<span class="media-kind">Image</span><span class="media-title">A</span>'
        '<span class="media-host">example.com</span></a></div></figure>'
    ) in _html_of(block)


def test_a_web_image_never_becomes_an_img_element_the_csp_would_block() -> None:
    block = {"type": "image", "src": "https://example.com/a.png", "alt": "A"}

    assert "<img" not in _html_of(block)


@pytest.mark.parametrize(
    ("kind", "label"), [("video", "Video"), ("audio", "Audio"), ("file", "File"), ("pdf", "PDF")]
)
def test_a_media_block_renders_as_a_link_card_titled_by_its_caption(kind: str, label: str) -> None:
    block = {"type": "media", "kind": kind, "src": "https://files.example.com/walk", "caption": "Dock walk"}

    assert (
        '<figure class="fig"><div class="frame">'
        '<a class="media-card" href="https://files.example.com/walk" rel="noopener noreferrer">'
        f'<span class="media-kind">{label}</span>'
        '<span class="media-title">Dock walk</span>'
        '<span class="media-host">files.example.com</span></a></div></figure>'
    ) in _html_of(block)


@pytest.mark.parametrize(
    "container",
    [
        pytest.param(in_an_open_section, id="section"),
        pytest.param(in_a_grid_cell, id="grid"),
    ],
)
def test_a_web_image_and_a_media_block_render_their_cards_inside_a_section_or_a_grid_cell(
    container: Callable[[list[dict[str, Any]]], dict[str, Any]],
) -> None:
    blocks = [
        {"type": "image", "src": "https://example.com/a.png", "alt": "A"},
        {"type": "media", "kind": "pdf", "src": "https://example.com/s.pdf", "caption": "Sheet"},
    ]

    html = _html_of(container(blocks))

    assert (html.count('<figure class="fig"><div class="frame"><a class="media-card"'), "<img" in html) == (
        2,
        False,
    )


def test_a_media_block_without_a_caption_is_titled_by_its_url() -> None:
    block = {"type": "media", "kind": "pdf", "src": "https://files.example.com/sheet.pdf"}

    assert (
        '<span class="media-kind">PDF</span>'
        '<span class="media-title">https://files.example.com/sheet.pdf</span>'
        '<span class="media-host">files.example.com</span>'
    ) in _html_of(block)


def test_the_page_policy_still_allows_only_data_images() -> None:
    block = {"type": "media", "kind": "video", "src": "https://example.com/walk.mp4"}

    assert "default-src 'none'; img-src data:;" in _html_of(block)
