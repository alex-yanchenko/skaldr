import re

import pytest

from skaldr.errors import ReportError
from skaldr.models import parse_report
from skaldr.render import render_html
from tests.factories import make_report
from tests.factories.render_factory import css_declarations


def test_callout_body_splits_blank_line_paragraphs() -> None:
    block = {"type": "callout", "tone": "info", "body": "First para.\n\nSecond para."}

    html = render_html(parse_report(make_report(blocks=[block])))

    assert '<p class="prose-p">First para.</p><p class="prose-p">Second para.</p>' in html


def test_single_paragraph_callout_stays_inline_without_a_paragraph_wrapper() -> None:
    block = {"type": "callout", "tone": "info", "body": "Just one line."}

    html = render_html(parse_report(make_report(blocks=[block])))

    assert "<div>Just one line.</div>" in html
    assert '<p class="prose-p">' not in html  # no paragraph wrapper emitted for a single paragraph


def test_a_run_of_blank_lines_in_a_text_body_writes_no_empty_paragraph() -> None:
    block = {"type": "text", "body": "a\n\n\n\nb\n\n"}

    html = render_html(parse_report(make_report(blocks=[block])))

    assert re.findall(r'<p class="text">.*?</p>', html) == ['<p class="text">a</p>', '<p class="text">b</p>']


def test_quote_body_splits_blank_line_paragraphs() -> None:
    block = {"type": "quote", "body": "Line one.\n\nLine two.", "cite": "src"}

    html = render_html(parse_report(make_report(blocks=[block])))

    assert '<p class="prose-p">Line one.</p><p class="prose-p">Line two.</p>' in html


def test_check_list_renders_tickable_boxes_honoring_the_checked_flag() -> None:
    block = {"type": "list", "style": "check", "items": ["todo", {"text": "done", "checked": True}]}

    html = render_html(parse_report(make_report(blocks=[block])))

    assert '<ul class="list check">' in html
    assert '<li><label class="chk"><input type="checkbox"><span>todo</span></label></li>' in html
    assert '<li><label class="chk"><input type="checkbox" checked><span>done</span></label></li>' in html


def test_check_list_nests_checkboxes_at_every_level() -> None:
    block = {"type": "list", "style": "check", "items": [{"text": "parent", "items": ["child"]}]}

    html = render_html(parse_report(make_report(blocks=[block])))

    assert '<span>parent</span></label><ul class="list check"><li><label class="chk">' in html


def test_bullet_list_has_no_checkboxes() -> None:
    block = {"type": "list", "items": ["a"]}

    html = render_html(parse_report(make_report(blocks=[block])))

    assert '<ul class="list"><li>a</li></ul>' in html
    assert 'type="checkbox"' not in html  # only a check-style list emits inputs


@pytest.mark.parametrize(
    ("options", "opening"),
    [
        pytest.param({}, '<ol class="list">', id="default"),
        pytest.param({"start": 3}, '<ol class="list" start="3">', id="start"),
        pytest.param({"numbering": "decimal"}, '<ol class="list">', id="decimal-is-the-default"),
        pytest.param({"numbering": "letters"}, '<ol class="list" type="a">', id="letters"),
        pytest.param({"numbering": "roman", "start": 4}, '<ol class="list" start="4" type="i">', id="roman"),
    ],
)
def test_a_numbered_list_opens_at_its_start_in_its_numbering(
    options: dict[str, object], opening: str
) -> None:
    block = {"type": "list", "style": "number", "items": ["a"], **options}

    html = render_html(parse_report(make_report(blocks=[block])))

    assert f"{opening}<li>a</li></ol>" in html


def test_a_nested_numbered_list_keeps_the_numbering_and_counts_from_one() -> None:
    block = {
        "type": "list",
        "style": "number",
        "start": 3,
        "numbering": "letters",
        "items": [{"text": "a", "items": ["b"]}],
    }

    html = render_html(parse_report(make_report(blocks=[block])))

    assert (
        '<ol class="list" start="3" type="a"><li>a<ol class="list" type="a"><li>b</li></ol></li></ol>' in html
    )


def test_a_decision_list_leads_each_item_with_a_decided_or_open_glyph() -> None:
    block = {
        "type": "list",
        "style": "decision",
        "items": ["which region", {"text": "use the queue", "decided": True, "items": ["retry later"]}],
    }

    html = render_html(parse_report(make_report(blocks=[block])))

    assert (
        '<ul class="list decision">'
        '<li><span class="dec open"><span class="glyph">?</span><span>which region</span></span></li>'
        '<li><span class="dec decided"><span class="glyph">✓</span><span>use the queue</span></span>'
        '<ul class="list decision"><li><span class="dec open"><span class="glyph">?</span>'
        "<span>retry later</span></span></li></ul></li></ul>"
    ) in html
    assert css_declarations(html, ".list.decision .dec.decided .glyph") == ["color:var(--success-fg)"]


def test_def_list_renders_terms_and_rich_multi_paragraph_bodies() -> None:
    block = {
        "type": "def_list",
        "items": [{"term": "Action", "body": "Click **Deploy**."}, {"term": "Say", "body": "One.\n\nTwo."}],
    }

    html = render_html(parse_report(make_report(blocks=[block])))

    assert '<dl class="deflist"><dt>Action</dt><dd>Click <strong>Deploy</strong>.</dd>' in html
    assert '<dt>Say</dt><dd><p class="prose-p">One.</p><p class="prose-p">Two.</p></dd></dl>' in html


def test_a_callout_and_a_note_with_an_icon_lead_with_it_beside_their_title_and_body() -> None:
    callout = {"type": "callout", "tone": "info", "icon": "🚀", "title": "Launch", "body": "Go."}
    note = {"type": "note", "icon": "📌", "body": "Aside."}

    html = render_html(parse_report(make_report(blocks=[callout, note])))

    assert (
        '<div class="callout info iconed"><span class="block-icon" aria-hidden="true">🚀</span>'
        '<div class="iconed-body"><div class="title">Launch</div><div>Go.</div></div></div>'
    ) in html
    assert (
        '<div class="note-block iconed"><span class="block-icon" aria-hidden="true">📌</span>'
        '<div class="iconed-body"><div>Aside.</div></div></div>'
    ) in html
    assert css_declarations(html, "& > .block-icon") == ["flex:none;font-size:1.15em;line-height:1.4"]
    assert css_declarations(html, "& > .iconed-body") == ["flex:1;min-width:0"]


def test_a_callout_without_an_icon_keeps_its_plain_markup() -> None:
    block = {"type": "callout", "tone": "warning", "title": "Careful", "body": "b"}

    html = render_html(parse_report(make_report(blocks=[block])))

    assert '<div class="callout warning"><div class="title">Careful</div><div>b</div></div>' in html


def test_note_renders_optional_title_and_body() -> None:
    titled = {"type": "note", "title": "Read aloud", "body": "Speak softly."}
    plain = {"type": "note", "body": "Just an aside."}

    html = render_html(parse_report(make_report(blocks=[titled, plain])))

    assert (
        '<div class="note-block"><div class="note-block-title">Read aloud</div>'
        "<div>Speak softly.</div></div>" in html
    )
    assert '<div class="note-block"><div>Just an aside.</div></div>' in html


def test_a_divider_is_a_rule_between_the_blocks_around_it() -> None:
    blocks = [{"type": "text", "body": "Above."}, {"type": "divider"}, {"type": "text", "body": "Below."}]

    html = render_html(parse_report(make_report(blocks=blocks)))

    assert '<p class="text">Above.</p>\n<hr class="divider">\n\n<p class="text">Below.</p>' in html


def test_a_divider_inside_a_panel_sits_in_the_panel_body() -> None:
    panel = {
        "type": "panel",
        "title": "Deck",
        "blocks": [{"type": "text", "body": "One."}, {"type": "divider"}],
    }

    html = render_html(parse_report(make_report(blocks=[panel])))

    assert '<div class="panel-card-body"><p class="text">One.</p><hr class="divider">\n</div></div>' in html


def test_note_body_splits_blank_line_paragraphs() -> None:
    block = {"type": "note", "body": "First aside.\n\nSecond aside."}

    html = render_html(parse_report(make_report(blocks=[block])))

    assert '<p class="prose-p">First aside.</p><p class="prose-p">Second aside.</p>' in html


def test_list_renders_nested_sub_items_as_an_indented_child_list() -> None:
    block = {
        "type": "list",
        "items": ["flat", {"text": "parent", "items": ["child a", {"text": "child b", "items": ["deep"]}]}],
    }

    html = render_html(parse_report(make_report(blocks=[block])))

    assert (
        '<ul class="list"><li>flat</li><li>parent'
        '<ul class="list"><li>child a</li><li>child b'
        '<ul class="list"><li>deep</li></ul></li></ul></li></ul>' in html
    )


def test_list_item_object_without_children_emits_no_nested_list() -> None:
    block = {"type": "list", "items": [{"text": "leaf"}]}

    html = render_html(parse_report(make_report(blocks=[block])))

    assert '<ul class="list"><li>leaf</li></ul>' in html  # no empty child <ul></ul>


def test_numbered_list_nests_ordered_children_in_the_parent_style() -> None:
    block = {"type": "list", "style": "number", "items": [{"text": "step", "items": ["sub"]}]}

    html = render_html(parse_report(make_report(blocks=[block])))

    assert '<ol class="list"><li>step<ol class="list"><li>sub</li></ol></li></ol>' in html


def test_list_item_rich_text_is_formatted_at_every_level() -> None:
    block = {"type": "list", "items": [{"text": "**bold** parent", "items": ["*em* child"]}]}

    html = render_html(parse_report(make_report(blocks=[block])))

    assert "<strong>bold</strong> parent" in html
    assert "<em>em</em> child" in html


def test_a_level_four_heading_is_an_h4_with_its_anchor_and_sub() -> None:
    heading = {"type": "heading", "level": 4, "text": "Bin detail", "sub": "by **aisle**"}

    html = render_html(parse_report(make_report(blocks=[heading])))

    assert '<h4 id="bin-detail">Bin detail<span class="hsub">by <strong>aisle</strong></span></h4>' in html


@pytest.mark.parametrize(
    ("block", "body_html"),
    [
        pytest.param(
            {"type": "callout", "tone": "warning", "body": "- first\n- second"},
            '<div><ul class="list"><li>first</li><li>second</li></ul></div>',
            id="callout-whose-body-is-a-list",
        ),
        pytest.param(
            {"type": "note", "body": "Two checks:\n1. lint\n2. test"},
            '<div><p class="prose-p">Two checks:</p><ol class="list"><li>lint</li><li>test</li></ol></div>',
            id="note-with-an-intro-and-a-numbered-list",
        ),
        pytest.param(
            {"type": "quote", "body": "3. three\n4. four"},
            '<div><ol class="list" start="3"><li>three</li><li>four</li></ol></div>',
            id="numbered-list-keeps-its-first-number",
        ),
        pytest.param(
            {"type": "text", "body": "Intro\n- a\n- b"},
            '<p class="text">Intro</p><ul class="list"><li>a</li><li>b</li></ul>',
            id="text-body",
        ),
        pytest.param(
            {"type": "def_list", "items": [{"term": "Why", "body": "- one\n- two"}]},
            '<dd><ul class="list"><li>one</li><li>two</li></ul></dd>',
            id="definition-body",
        ),
        pytest.param(
            {"type": "def_list", "items": [{"term": "Why", "body": "Intro.\n- one\n- two"}]},
            '<dd><p class="prose-p">Intro.</p><ul class="list"><li>one</li><li>two</li></ul></dd>',
            id="definition-body-with-a-paragraph-before-its-list",
        ),
        pytest.param(
            {"type": "text", "muted": True, "body": "Intro\n- a\n- b"},
            '<p class="text muted">Intro</p><ul class="list muted"><li>a</li><li>b</li></ul>',
            id="muted-text-body",
        ),
        pytest.param(
            {"type": "text", "body": "0. zero\n1. one"},
            '<ol class="list" start="0"><li>zero</li><li>one</li></ol>',
            id="a-numbered-list-from-zero",
        ),
        pytest.param(
            {"type": "callout", "tone": "info", "body": "- a\n- b\n  - x\n  - y"},
            '<div><ul class="list"><li>a</li><li>b<ul class="list"><li>x</li><li>y</li></ul></li></ul></div>',
            id="a-nested-list",
        ),
    ],
)
def test_list_lines_in_a_prose_body_render_as_a_list(block: dict[str, object], body_html: str) -> None:
    html = render_html(parse_report(make_report(blocks=[block])))

    assert body_html in html


def test_a_single_marked_line_in_a_prose_body_stays_text() -> None:
    block = {"type": "callout", "tone": "info", "body": "- not a list on its own"}

    html = render_html(parse_report(make_report(blocks=[block])))

    assert "<div>- not a list on its own</div>" in html


def test_a_list_nested_too_deep_names_the_field() -> None:
    body = "\n".join("  " * level + f"- n{level}" for level in range(21)) + "\n- tail"
    block = {"type": "callout", "tone": "info", "body": body}

    with pytest.raises(ReportError, match=r"^blocks\.0\.body: a list nests more than 20 levels deep"):
        render_html(parse_report(make_report(blocks=[block])))


def test_a_rich_text_mistake_inside_a_prose_list_item_names_the_field() -> None:
    block = {"type": "callout", "tone": "info", "body": "- ok\n- [bad]{tone=nope}"}

    with pytest.raises(ReportError, match=r"^blocks\.0\.body: unknown tone 'nope'"):
        render_html(parse_report(make_report(blocks=[block])))


def test_heading_sub_renders_a_rich_caption_inside_the_heading() -> None:
    block = {"type": "heading", "text": "Overview", "sub": "the **10k** count"}

    html = render_html(parse_report(make_report(blocks=[block])))

    assert '<h2 id="overview">Overview<span class="hsub">the <strong>10k</strong> count</span></h2>' in html


def test_heading_without_sub_renders_no_caption_span() -> None:
    html = render_html(parse_report(make_report(blocks=[{"type": "heading", "text": "Overview"}])))

    assert '<h2 id="overview">Overview</h2>' in html
    assert '<span class="hsub">' not in html  # the class lives in the inlined CSS; the span must not


def test_text_block_splits_paragraphs_in_order() -> None:
    report = parse_report(make_report(blocks=[{"type": "text", "body": "one\n\ntwo"}]))

    html = render_html(report)

    assert html.count('<p class="text">') == 2
    assert '<p class="text">one</p>' in html
    assert html.index("one") < html.index("two")


def test_block_span_wraps_the_block_in_a_width_container() -> None:
    """A `span` wraps the block in `.blk span-N` (the width primitive); the block's own markup is
    unchanged inside it."""
    html = render_html(parse_report(make_report(blocks=[{"type": "list", "span": 4, "items": ["a"]}])))

    assert '<div class="blk span-4"><ul class="list"><li>a</li></ul>\n</div>' in html


def test_block_without_span_is_not_wrapped() -> None:
    """No span → no wrapper, so an unspanned block renders exactly as before (full width)."""
    html = render_html(parse_report(make_report(blocks=[{"type": "text", "body": "hi"}])))

    assert 'class="blk' not in html
    assert '<p class="text">hi</p>' in html


def test_diff_code_marks_added_and_removed_lines() -> None:
    block = {"type": "code", "mode": "diff", "content": "+added\n-removed\n context"}
    report = parse_report(make_report(blocks=[block]))

    html = render_html(report)

    assert '<span class="ln add">added</span>' in html
    assert '<span class="ln del">removed</span>' in html
    assert '<span class="ln ctx"> context</span>' in html
