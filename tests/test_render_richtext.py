import re
from pathlib import Path
from typing import get_args

import pytest

from skaldr.errors import ReportError
from skaldr.models import ToneLiteral, load_report, package_path, package_text, parse_report
from skaldr.render import find_placeholders, placeholder_locations, render_html, render_richtext
from tests.factories import make_report, make_toggle, write_index_document


def test_a_badge_and_a_citation_inside_a_toggle_feed_the_legend_and_the_numbering() -> None:
    toggle = make_toggle(
        {"type": "badge_row", "items": [{"key": "OPS"}]},
        {"type": "text", "body": "Per the SOP [^sop]."},
        {"type": "references", "items": [{"key": "sop", "text": "Counting SOP"}]},
    )
    badges = {"OPS": {"label": "ops", "tone": "blue", "legend": "Run by ops."}}

    html = render_html(parse_report(make_report(badges=badges, blocks=[toggle])))

    assert '<span class="chip blue">ops</span><span class="meaning">Run by ops.</span>' in html
    assert '<sup class="fn"><a id="fnref-sop" href="#ref-sop">[1]</a></sup>' in html


def test_an_anchor_link_reaches_a_level_four_heading_inside_a_section() -> None:
    section = {
        "type": "section",
        "title": "Appendix",
        "collapsed": False,
        "blocks": [{"type": "heading", "level": 4, "text": "Raw", "id": "raw"}],
    }
    blocks = [section, {"type": "text", "body": "See [the raw counts](#raw)."}]

    html = render_html(parse_report(make_report(blocks=blocks)))

    assert (
        '<div class="section-body"><h4 id="raw">Raw</h4>\n</div></details>\n\n'
        '<p class="text">See <a href="#raw">the raw counts</a>.</p>'
    ) in html


def test_references_render_bidirectional_links_and_leave_unknown_keys_literal() -> None:
    blocks = [
        {"type": "text", "body": "Method [^sop]; thresholds [^audit]; typo [^missing]."},
        {
            "type": "references",
            "items": [
                {"key": "sop", "text": "*Counting SOP*, rev. 7."},
                {"key": "audit", "text": "Q2 Audit.", "url": "https://example.com/a"},
            ],
        },
    ]
    html = render_html(parse_report(make_report(blocks=blocks)))

    # inline marker → numbered superscript linking down to the source
    assert '<sup class="fn"><a id="fnref-sop" href="#ref-sop">[1]</a></sup>' in html
    assert '<sup class="fn"><a id="fnref-audit" href="#ref-audit">[2]</a></sup>' in html
    # an undeclared key is left as literal text (escaped), never a dangling link
    assert "typo [^missing]." in html
    assert 'href="#ref-missing"' not in html
    # the cited source's whole <li>: number backlinks to the marker; rich text renders; no url → no rlink
    assert (
        '<li id="ref-sop"><a class="rnum" href="#fnref-sop">1</a>'
        '<span class="rtext"><em>Counting SOP</em>, rev. 7.</span></li>' in html
    )
    # the source with a url gets the trailing external-link glyph
    assert '<span class="rtext">Q2 Audit. <a class="rlink" href="https://example.com/a">↗</a></span>' in html


def test_a_reference_cited_twice_reuses_its_number_and_emits_one_anchor_id() -> None:
    blocks = [
        {"type": "text", "body": "First [^sop] and again [^sop]."},
        {"type": "references", "items": [{"key": "sop", "text": "SOP."}]},
    ]
    html = render_html(parse_report(make_report(blocks=blocks)))

    # both citations show number 1; only the first carries the fnref anchor id (ids stay unique)
    assert '<sup class="fn"><a id="fnref-sop" href="#ref-sop">[1]</a></sup>' in html
    assert '<sup class="fn"><a href="#ref-sop">[1]</a></sup>' in html
    assert html.count('id="fnref-sop"') == 1


def test_an_uncited_declared_reference_renders_a_plain_number_not_a_dead_backlink() -> None:
    blocks = [
        {"type": "text", "body": "Cited [^sop]."},
        {
            "type": "references",
            "items": [{"key": "sop", "text": "SOP."}, {"key": "extra", "text": "Never cited."}],
        },
    ]
    html = render_html(parse_report(make_report(blocks=blocks)))

    assert '<li id="ref-sop"><a class="rnum" href="#fnref-sop">1</a>' in html
    # the uncited source has no fnref anchor to link back to, so its number is a plain span
    assert '<li id="ref-extra"><span class="rnum">2</span>' in html
    assert 'href="#fnref-extra"' not in html


def test_a_citation_with_no_references_block_stays_literal() -> None:
    html = render_html(parse_report(make_report(blocks=[{"type": "text", "body": "See [^ghost]."}])))

    assert "See [^ghost]." in html
    assert '<sup class="fn">' not in html


def test_render_richtext_leaves_a_footnote_marker_literal_without_ref_numbers() -> None:
    assert str(render_richtext("see [^x]")) == "see [^x]"


def test_richtext_applies_the_inline_subset() -> None:
    html = str(render_richtext("**b** *i* `c` ~~s~~ [t](https://x.com)"))

    assert html == '<strong>b</strong> <em>i</em> <code>c</code> <del>s</del> <a href="https://x.com">t</a>'


def test_richtext_writes_underline_subscript_and_superscript_as_html_elements() -> None:
    html = str(render_richtext("++under *it*++ H~2~O 10^3^ f^'^"))

    assert html == "<u>under <em>it</em></u> H<sub>2</sub>O 10<sup>3</sup> f<sup>&#39;</sup>"


@pytest.mark.parametrize(
    ("text", "html"),
    [
        pytest.param("[late]{tone=danger}", '<span style="color:var(--danger-fg)">late</span>', id="color"),
        pytest.param(
            "[due]{bg=amber}", '<span style="background:var(--warning-bg)">due</span>', id="highlight"
        ),
        pytest.param(
            "[**now** &lt;]{tone=sky bg=neutral}",
            '<span style="color:var(--sky-fg);background:var(--neutral-bg)">'
            "<strong>now</strong> &amp;lt;</span>",
            id="color-and-highlight-around-escaped-marks",
        ),
        pytest.param(
            "[[a]{tone=danger}](https://x.io)",
            '<a href="https://x.io"><span style="color:var(--danger-fg)">a</span></a>',
            id="span-inside-a-link-label",
        ),
    ],
)
def test_richtext_writes_an_attribute_span_with_the_tone_tokens(text: str, html: str) -> None:
    assert str(render_richtext(text)) == html


def test_richtext_writes_inline_math_as_mathml_and_keeps_prose_dollars() -> None:
    html = str(render_richtext("costs $5, so $`x_i < 2`$ holds"))

    assert html == (
        'costs $5, so <math xmlns="http://www.w3.org/1998/Math/MathML" display="inline"><mrow>'
        "<msub><mi>x</mi><mi>i</mi></msub><mo>&lt;</mo><mn>2</mn></mrow></math> holds"
    )


def test_raw_markup_in_inline_math_renders_as_escaped_text() -> None:
    html = str(render_richtext(r"a $`\text{<script>alert(1)</script>}`$ b"))

    assert html == (
        'a <math xmlns="http://www.w3.org/1998/Math/MathML" display="inline"><mrow>'
        "<mtext>&lt;script&gt;alert(1)&lt;/script&gt;</mtext></mrow></math> b"
    )


def test_raw_markup_in_a_math_block_renders_as_escaped_text() -> None:
    block = {"type": "math", "expression": r"\text{<script>alert(1)</script>}"}

    html = render_html(parse_report(make_report(blocks=[block])))

    assert (
        '<div class="math"><math xmlns="http://www.w3.org/1998/Math/MathML" display="block"><mrow>'
        "<mtext>&lt;script&gt;alert(1)&lt;/script&gt;</mtext></mrow></math></div>"
    ) in html


@pytest.mark.parametrize(
    ("expression", "attribute"),
    [
        pytest.param(r"\href{javascript:alert(1)}{x}", "href", id="href"),
        pytest.param(r"\class{loud}{x}", "class", id="class"),
        pytest.param(r"\style{color:red}{x}", "style", id="style"),
    ],
)
def test_inline_math_setting_a_page_level_attribute_fails_the_render(expression: str, attribute: str) -> None:
    with pytest.raises(ReportError) as raised:
        render_richtext(f"$`{expression}`$")

    assert str(raised.value) == (
        f"math expression '{expression}' sets the {attribute} attribute, which is not a MathML attribute "
        r"skaldr renders: leave out \href, \class and \style"
    )


def test_a_math_block_renders_display_mathml() -> None:
    html = render_html(parse_report(make_report(blocks=[{"type": "math", "expression": "\\frac{a}{b}"}])))

    assert (
        '<div class="math"><math xmlns="http://www.w3.org/1998/Math/MathML" display="block"><mrow><mfrac>'
        "<mrow><mi>a</mi></mrow><mrow><mi>b</mi></mrow></mfrac></mrow></math></div>"
    ) in html


@pytest.mark.parametrize(
    "token",
    [
        pytest.param(f"--{tone}-{kind}:light-dark(", id=f"{tone}-{kind}")
        for tone in get_args(ToneLiteral)
        for kind in ("fg", "bg")
    ],
)
def test_every_tone_an_attribute_span_names_has_a_color_and_a_tint_token(token: str) -> None:
    assert token in package_text("styles.css")


def test_a_link_inside_an_attribute_span_fails_the_build_instead_of_publishing_its_syntax() -> None:
    with pytest.raises(ReportError) as raised:
        render_richtext("[see [docs](https://x.io) now]{tone=info}")

    assert str(raised.value) == (
        "the attribute list {tone=info} follows no [text] it can color: the text inside a [text]{…} span "
        "is not empty and holds no link"
    )


def test_richtext_keeps_brackets_and_braces_that_form_no_attribute_span_as_text() -> None:
    html = str(render_richtext("[a]{x} [b] {tone=info} [c](https://e.com){tone=info}"))

    assert html == '[a]{x} [b] {tone=info} <a href="https://e.com">c</a>{tone=info}'


def test_richtext_keeps_marker_characters_that_form_no_mark_as_text() -> None:
    html = str(render_richtext("C++ in ~5 days, cut from ~5 days~ to 2, 2^10 & a ++ b ++ c"))

    assert html == "C++ in ~5 days, cut from ~5 days~ to 2, 2^10 &amp; a ++ b ++ c"


def test_richtext_escapes_raw_html() -> None:
    assert str(render_richtext("<script>x & y")) == "&lt;script&gt;x &amp; y"


def test_richtext_escapes_a_link_target_inside_its_href() -> None:
    html = str(render_richtext('[x](https://e.com/?a=1&b="2") [y](#sec)', anchor_ids=frozenset({"sec"})))

    assert html == '<a href="https://e.com/?a=1&amp;b=&#34;2&#34;">x</a> <a href="#sec">y</a>'


@pytest.mark.parametrize(
    ("text", "html"),
    [
        pytest.param("**a ~~b** c~~", "<strong>a ~~b</strong> c~~", id="bold-crosses-strike"),
        pytest.param("~~a *b~~ c*", "<del>a *b</del> c*", id="strike-crosses-italic"),
        pytest.param(
            "~~a **b ~~ c** d~~",
            "<del>a <strong>b ~~ c</strong> d</del>",
            id="strike-holds-a-bold-with-tildes",
        ),
        pytest.param(
            "*a **b* c**", "<em>a <em><em>b</em> c</em></em>", id="italic-crossing-bold-pairs-as-commonmark"
        ),
    ],
)
def test_richtext_crossed_emphasis_renders_well_nested_tags(text: str, html: str) -> None:
    assert str(render_richtext(text)) == html


@pytest.mark.parametrize(
    ("text", "html"),
    [
        pytest.param(
            "~~cut from **~5 days**~~ to 2",
            "<del>cut from <strong>~5 days</strong></del> to 2",
            id="a-tilde-inside-a-bold-leaves-the-strike-around-it",
        ),
        pytest.param(
            "*see ~~a**b~~ here*",
            "<em>see <del>a**b</del> here</em>",
            id="asterisks-inside-a-strike-leave-the-italic-around-it",
        ),
    ],
)
def test_richtext_a_marker_character_inside_an_inner_emphasis_does_not_block_the_outer_one(
    text: str, html: str
) -> None:
    assert str(render_richtext(text)) == html


@pytest.mark.parametrize(
    ("text", "html"),
    [
        pytest.param("[l](https://a.io/`c`)", '<a href="https://a.io/`c`">l</a>', id="code-span"),
        pytest.param("[l](https://a.io/[^sop])", '<a href="https://a.io/[^sop]">l</a>', id="citation"),
    ],
)
def test_richtext_a_web_link_target_is_read_as_written(text: str, html: str) -> None:
    assert str(render_richtext(text, {"sop": 1})) == html


def test_richtext_rejects_an_anchor_link_whose_target_holds_backticks_as_an_unknown_anchor() -> None:
    with pytest.raises(ReportError) as raised:
        render_richtext("[l](#sec`c`)", anchor_ids=frozenset({"sec"}))

    assert str(raised.value) == (
        "rich text links to unknown anchor '#sec`c`': no heading or section has that id"
    )


def test_richtext_renders_a_placeholder_as_a_chip_and_collects_it() -> None:
    seen: set[str] = set()
    html = str(render_richtext("Open {{deployed_url}} now", placeholders=seen))

    assert html == 'Open <span class="placeholder">deployed_url</span> now'
    assert seen == {"deployed_url"}


def test_richtext_placeholder_survives_bold_and_italic_neighbours() -> None:
    html = str(render_richtext("**go** to {{url}} *now*"))

    assert html == '<strong>go</strong> to <span class="placeholder">url</span> <em>now</em>'


@pytest.mark.parametrize("token", ["{{url}}", "{{ url }}", "{{  url  }}"])
def test_richtext_placeholder_tolerates_internal_whitespace(token: str) -> None:
    seen: set[str] = set()
    html = str(render_richtext(token, placeholders=seen))

    assert html == '<span class="placeholder">url</span>'
    assert seen == {"url"}


@pytest.mark.parametrize("name", ["next-round", "a_b-2", "deployed_url"])
def test_richtext_placeholder_accepts_letters_digits_underscore_and_hyphen(name: str) -> None:
    seen: set[str] = set()
    html = str(render_richtext(f"retry {{{{{name}}}}} now", placeholders=seen))

    assert html == f'retry <span class="placeholder">{name}</span> now'
    assert seen == {name}


@pytest.mark.parametrize("token", ["{{a.b}}", "{{two words}}", "{{ }}", "{{}}"])
def test_richtext_malformed_placeholder_fails_the_build(token: str) -> None:
    # `{{…}}` is reserved for placeholders — a token whose name isn't letters/digits/_/- is a typo'd
    # blank and hard-fails, rather than silently shipping as prose past the --strict gate.
    with pytest.raises(ReportError, match=r"invalid placeholder '"):
        render_richtext(f"a {token} b")


@pytest.mark.parametrize(
    ("body", "token"),
    [("wrap {{ `code` }} it", "{{`code`}}"), ("wrap {{[x](https://y.com)}} it", "{{[x](https://y.com)}}")],
)
def test_richtext_placeholder_wrapping_other_markup_fails_naming_it_as_written(body: str, token: str) -> None:
    with pytest.raises(ReportError) as exc:
        render_richtext(body)

    assert str(exc.value).startswith(f"invalid placeholder '{token}': ")


def test_richtext_double_brace_with_an_inner_brace_stays_literal() -> None:
    # the capture is brace-bounded (keeps the scan linear), so a nested-brace token isn't a placeholder
    # at all — it stays literal rather than erroring. A deliberate trade for linear-time matching.
    html = str(render_richtext("a {{b{c}} d"))

    assert html == "a {{b{c}} d"


def test_richtext_literal_double_brace_survives_inside_a_code_span() -> None:
    # the escape hatch: a `code` span is stashed before placeholder parsing, so a literal {{ is safe
    html = str(render_richtext("use `{{raw}}` verbatim"))

    assert html == "use <code>{{raw}}</code> verbatim"


def test_find_placeholders_reaches_table_cells_def_list_and_panel_nested_text() -> None:
    report = parse_report(
        make_report(
            blocks=[
                {
                    "type": "table",
                    "columns": [{"key": "note", "label": "Note", "kind": "rich"}],
                    "rows": [{"note": "ping {{cell_ph}}"}],
                },
                {"type": "def_list", "items": [{"term": "Owner", "body": "{{def_ph}} owns it"}]},
                {"type": "panel", "title": "P", "blocks": [{"type": "text", "body": "in {{panel_ph}}"}]},
            ]
        )
    )

    assert find_placeholders(report) == ["cell_ph", "def_ph", "panel_ph"]


def test_find_placeholders_collects_sorted_unique_names_across_the_report() -> None:
    report = parse_report(
        make_report(
            blocks=[
                {"type": "text", "body": "See {{ticket}} and {{deployed_url}}."},
                {"type": "callout", "tone": "info", "body": "Ping {{ticket}} again."},
            ]
        )
    )

    assert find_placeholders(report) == ["deployed_url", "ticket"]


def test_placeholder_locations_name_the_block_or_meta_field_that_holds_each_blank() -> None:
    report = parse_report(
        make_report(
            meta={"title": "Plan for {{team}}", "date": "{{when}}"},
            blocks=[
                {"type": "text", "body": "See {{ticket}} and {{ticket}}."},
                {
                    "type": "section",
                    "title": "Rollout of {{ticket}}",
                    "blocks": [
                        {"type": "callout", "tone": "info", "body": "Ping {{owner}}."},
                        {"type": "text", "body": "Literal \\{{ticket}} here and `{{owner}}` in code."},
                    ],
                },
                {"type": "text", "body": "No blanks."},
            ],
        )
    )

    assert placeholder_locations(report) == {
        "owner": ["blocks.1.blocks.0.body"],
        "team": ["meta.title"],
        "ticket": ["blocks.0.body"],
        "when": ["meta.date"],
    }


def test_a_section_title_is_plain_text_so_only_its_body_holds_a_blank() -> None:
    report = parse_report(
        make_report(
            blocks=[
                {
                    "type": "section",
                    "title": "Open {{ticket}}",
                    "blocks": [{"type": "text", "body": "About {{ticket}} and {{owner}}."}],
                }
            ]
        )
    )

    assert placeholder_locations(report) == {
        "owner": ["blocks.0.blocks.0.body"],
        "ticket": ["blocks.0.blocks.0.body"],
    }


def test_backticks_in_two_paragraphs_do_not_hide_a_blank_from_its_location() -> None:
    report = parse_report(
        make_report(blocks=[{"type": "text", "body": "one ` tick\n\nthen {{tail}} and ` more"}])
    )

    assert (find_placeholders(report), placeholder_locations(report)) == (
        ["tail"],
        {"tail": ["blocks.0.body"]},
    )


def test_every_counted_blank_has_a_location_and_nothing_else_does(tmp_path: Path) -> None:
    first = make_report(meta={"title": "A"}, blocks=[{"type": "text", "body": "A {{x}} and `{{code}}`."}])
    second = make_report(
        meta={"title": "B"}, blocks=[{"type": "text", "body": "B {{x}}, {{ y }}, \\{{lit}}."}]
    )
    index = write_index_document(tmp_path, {"a.yaml": first, "b.yaml": second})

    report = load_report(index)

    assert (list(placeholder_locations(report)), find_placeholders(report)) == (["x", "y"], ["x", "y"])
    assert placeholder_locations(report)["x"] == ["blocks.0.blocks.0.body", "blocks.1.blocks.0.body"]


def test_report_with_no_placeholders_collects_nothing() -> None:
    report = parse_report(make_report(blocks=[{"type": "text", "body": "All real values here."}]))

    assert find_placeholders(report) == []


def test_stylesheet_carries_no_footnote_marker_syntax() -> None:
    """The whole stylesheet is inlined into every rendered page, so a literal `[^…]` footnote marker
    in a CSS comment surfaces in the output and trips a consumer scanning the render for unresolved
    markers. Keep the marker syntax out of the sheet — describe it in words instead."""
    css = package_path("styles.css").read_text(encoding="utf-8")

    assert "[^" not in css


def test_richtext_rejects_disallowed_link_scheme() -> None:
    assert str(render_richtext("[x](javascript:alert)")) == "[x](javascript:alert)"


def test_richtext_renders_a_known_same_page_anchor_link() -> None:
    html = str(render_richtext("see [the overview](#overview)", anchor_ids=frozenset({"overview"})))

    assert html == 'see <a href="#overview">the overview</a>'


def test_richtext_rejects_a_dangling_same_page_anchor() -> None:
    with pytest.raises(ReportError, match=r"unknown anchor '#missing'"):
        render_richtext("[x](#missing)", anchor_ids=frozenset({"overview"}))


def test_richtext_leaves_an_anchor_link_literal_without_an_anchor_set() -> None:
    assert str(render_richtext("[x](#overview)")) == "[x](#overview)"


def test_same_page_anchor_link_resolves_to_a_heading_id_in_a_full_render() -> None:
    blocks = [
        {"type": "heading", "text": "Overview"},
        {"type": "text", "body": "Jump to [the overview](#overview)."},
    ]

    html = render_html(parse_report(make_report(blocks=blocks)))

    assert '<a href="#overview">the overview</a>' in html
    assert 'id="overview"' in html  # the heading it targets


def test_an_anchor_link_reaches_a_heading_whose_text_is_not_ascii() -> None:
    blocks = [
        {"type": "heading", "text": "Über uns"},
        {"type": "text", "body": "See [about us](#über-uns)."},
    ]

    html = render_html(parse_report(make_report(blocks=blocks)))

    assert (
        re.findall(r'<h2 id="[^"]*">Über uns</h2>', html),
        re.findall(r'<a href="#[^"]*">about us</a>', html),
    ) == (['<h2 id="über-uns">Über uns</h2>'], ['<a href="#über-uns">about us</a>'])


def test_a_citation_links_to_its_reference_even_when_a_heading_reads_like_its_id() -> None:
    blocks = [
        {"type": "heading", "text": "Ref a"},
        {"type": "text", "body": "Claim.[^a]"},
        {"type": "references", "items": [{"key": "a", "text": "A source."}]},
    ]

    html = render_html(parse_report(make_report(blocks=blocks)))

    assert re.findall(r'id="(ref-a[^"]*)"', html) == ["ref-a-2", "ref-a"]


def test_dangling_anchor_link_fails_the_whole_render() -> None:
    blocks = [{"type": "text", "body": "[broken](#nope)"}]

    with pytest.raises(ReportError, match=r"unknown anchor '#nope'"):
        render_html(parse_report(make_report(blocks=blocks)))


def test_richtext_leaves_marks_literal_inside_a_code_span() -> None:
    assert str(render_richtext("`**not bold**`")) == "<code>**not bold**</code>"


def test_richtext_url_with_asterisk_is_not_corrupted() -> None:
    html = str(render_richtext("see [x](https://e.com/a*b*c)"))

    assert '<a href="https://e.com/a*b*c">x</a>' in html
    assert "<em>" not in html


def test_richtext_code_span_inside_link_fully_expands() -> None:
    html = str(render_richtext("the [`compute.py`](https://e.com/x) module"))

    assert html == 'the <a href="https://e.com/x"><code>compute.py</code></a> module'
    assert "\x00" not in html


def test_richtext_replaces_nul_bytes_with_the_replacement_character() -> None:
    assert str(render_richtext("a\x00b **c**")) == "a\N{REPLACEMENT CHARACTER}b <strong>c</strong>"
