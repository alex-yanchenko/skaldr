import re

import pytest

from skaldr.models import parse_report
from skaldr.render import render_embed, render_html
from tests.factories import make_report

HEADINGS = [
    {"type": "heading", "text": "Method"},
    {"type": "text", "body": "How it was counted."},
    {"type": "heading", "text": "Results & limits"},
]

CONTENTS_BUTTON = (
    '<button class="toc-btn" type="button" aria-label="Contents" aria-expanded="false" '
    'aria-controls="contents-panel" popovertarget="contents-panel">'
)

CONTENTS_PANEL = (
    '<nav class="toc-pop" id="contents-panel" popover="manual" aria-label="Contents">'
    '<div class="toc-pop-hd">On this page</div>'
    '<a href="#method">Method</a>'
    '<a href="#results-limits">Results &amp; limits</a>'
    "</nav>"
)


INLINE_TABLE_OF_CONTENTS = (
    '<nav class="toc"><a href="#method">Method</a><a href="#results-limits">Results &amp; limits</a></nav>'
)


def page_with(*, toc: bool, blocks: list[dict[str, str]]) -> str:
    return render_html(parse_report(make_report(meta={"title": "T", "toc": toc}, blocks=blocks)))


def controls_of(html: str) -> str:
    found = re.search(r'<div class="sc" data-open="false">.*?\n</div>\n<script>', html, flags=re.DOTALL)
    assert found is not None
    return found.group(0)


def test_a_page_with_a_table_of_contents_gets_a_contents_button_before_the_settings_button() -> None:
    controls = controls_of(page_with(toc=True, blocks=HEADINGS))

    assert controls.index(CONTENTS_BUTTON) < controls.index('<button class="sc-btn"')


def test_the_contents_panel_is_a_manual_popover_listing_the_table_of_contents_entries() -> None:
    controls = controls_of(page_with(toc=True, blocks=HEADINGS))

    assert CONTENTS_PANEL in controls.replace("\n", "")


def test_the_inline_table_of_contents_stays() -> None:
    html = page_with(toc=True, blocks=HEADINGS)

    assert INLINE_TABLE_OF_CONTENTS in html


@pytest.mark.parametrize(
    ("toc", "blocks"),
    [
        pytest.param(False, HEADINGS, id="the-document-asks-for-no-table-of-contents"),
        pytest.param(True, [{"type": "text", "body": "No headings."}], id="the-table-of-contents-is-empty"),
    ],
)
def test_a_page_without_a_table_of_contents_has_no_contents_button_or_panel(
    toc: bool, blocks: list[dict[str, str]]
) -> None:
    html = page_with(toc=toc, blocks=blocks)

    assert ("toc-btn" in controls_of(html), "popover=" in html) == (False, False)


def test_an_embedded_page_gets_the_same_contents_button_and_panel() -> None:
    html = render_embed(parse_report(make_report(meta={"title": "T", "toc": True}, blocks=HEADINGS)))

    assert (CONTENTS_BUTTON in html, CONTENTS_PANEL in html.replace("\n", "")) == (True, True)
