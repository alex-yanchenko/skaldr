import re
from collections.abc import Callable
from html import escape
from types import SimpleNamespace

import pytest

from skaldr.errors import ReportError
from skaldr.models import load_report, package_path, parse_report
from skaldr.render import (
    RecordedRender,
    RenderOptions,
    extract_source,
    hide_script_close,
    html_environment,
    recorded_render,
    render_embed,
    render_html,
    render_richtext,
    show_script_close,
)
from skaldr.version import skaldr_version
from tests.conftest import REPO_ROOT
from tests.factories import make_report
from tests.factories.render_factory import inline_scripts, script_hash

GOLDEN = REPO_ROOT / "tests" / "golden" / "example.html"


# The three color-scheme rules that drive every light-dark() token. They must render unlayered (see
# test_host_override_essentials_sit_outside_any_layer); asserted by literal so a reformat fails loudly.
COLOR_SCHEME_RULES = (
    ":root{color-scheme:light dark}",
    ':root[data-theme="dark"]{color-scheme:dark}',
    ':root[data-theme="light"]{color-scheme:light}',
)


# Rules that MUST stay unlayered so an embedding host's own unlayered reset can't override them: the
# color-scheme rules, box-sizing (every component assumes border-box), and body's colour/background
# (else skaldr's dark panels keep the host's dark text → invisible). Asserted by literal.
UNLAYERED_ESSENTIALS = (
    *COLOR_SCHEME_RULES,
    "*,*::before,*::after{box-sizing:border-box}",
    "body{font-family:var(--sans); color:var(--ink); background:var(--page)",
    # print forces white --paper; unlayered so it beats the base body rule above (a layered one wouldn't)
    "@media print{body{background:var(--paper)}}",
)


def test_example_render_matches_golden() -> None:
    """Pins the full page. On an intended change, regenerate with:
    uv run skaldr data/example.yaml -o tests/golden/example.html --no-source
    and review the HTML diff in the PR. The flag matters: this compares against a render that was
    given no source, so a golden carrying the embedded source block fails on 390 phantom lines."""
    report = load_report(REPO_ROOT / "data" / "example.yaml")

    assert render_html(report) == _stamped_with_the_installed_version(GOLDEN.read_text(encoding="utf-8"))


def _stamped_with_the_installed_version(page: str) -> str:
    return re.sub(r"(&#34;version&#34;:&#34;)[^&]*(&#34;)", rf"\g<1>{skaldr_version()}\g<2>", page, count=1)


def test_a_page_records_the_options_and_the_skaldr_version_it_was_rendered_with() -> None:
    page = render_html(parse_report(make_report()), source="version: 1\n", live=500)

    assert recorded_render(page) == RecordedRender(
        RenderOptions(embed=False, live=500, source=True, version=skaldr_version()), 500
    )


def test_the_first_render_stamp_on_a_page_is_the_one_read() -> None:
    real = RenderOptions(embed=True, live=None, source=False, version="9.9.9")
    forged = RenderOptions(embed=False, live=999, source=True, version="9.9.9")
    page = (
        f'<meta name="skaldr-render" content="{escape(real.model_dump_json())}">'
        f'<p><meta name="skaldr-render" content="{escape(forged.model_dump_json())}"></p>'
    )

    assert recorded_render(page) == RecordedRender(real, None)


def test_sales_example_renders_and_reconciles() -> None:
    """Guards the sales-flavoured example shipped for non-dev onboarding — it must stay valid."""
    report = load_report(REPO_ROOT / "examples" / "sales-pipeline.yaml")

    html = render_html(report)

    assert html.startswith("<!doctype html>")
    assert "Q3 Pipeline Review: West Region" in html
    assert "Reconciles: 120 = 120." in html


def test_hero_meta_wraps_the_title_in_a_hero_band() -> None:
    html = render_html(parse_report(make_report(meta={"title": "T", "subtitle": ["s"], "hero": True})))

    assert '<header class="hero"><h1>T</h1><p class="subtitle">s</p></header>' in html


def test_no_hero_by_default_renders_a_bare_title() -> None:
    html = render_html(parse_report(make_report()))

    assert '<header class="hero">' not in html
    assert "<h1>Test Report</h1>" in html


def test_embed_drops_the_skeleton_but_keeps_the_controls() -> None:
    html = render_embed(parse_report(make_report(blocks=[{"type": "text", "body": "hi"}])))

    # the document skeleton is dropped — the Artifact host supplies <html>/<head>/<body>
    assert "<!doctype" not in html.lower()
    assert "<html" not in html
    assert "<body" not in html
    # but the fragment stays fully functional: a leading <title> (names the artifact), inline
    # styles, the rendered content, AND the same corner controls + scripts as the full page
    # (inline JS runs inside an Artifact, so theme/width switching and the print handler work).
    assert html.startswith("<title>")
    assert "<title>Test Report</title>" in html
    assert "<style>" in html
    assert '<div class="wrap">' in html
    assert '<p class="text">hi</p>' in html
    assert '<div class="sc" data-open="false">' in html  # corner controls present
    assert 'addEventListener("beforeprint"' in html  # print handler present


def test_embed_and_page_share_content_and_controls() -> None:
    report = parse_report(
        make_report(blocks=[{"type": "heading", "text": "H"}, {"type": "text", "body": "b"}])
    )

    embed = render_embed(report)
    page = render_html(report)

    # the content region (wrap → corner controls) is byte-identical in both — only the outer
    # skeleton differs, since page and embed include the same _content and _controls partials
    marker, sc = '<div class="wrap">', '<div class="sc"'
    assert embed[embed.index(marker) : embed.index(sc)] == page[page.index(marker) : page.index(sc)]


def test_print_css_keeps_the_pdf_readable() -> None:
    html = render_html(parse_report(make_report()))

    # backgrounds/colours must print, or headers go white-on-white and chips/dots/tints vanish
    assert "print-color-adjust:exact" in html
    # a table row must not split across a page break, and the header must repeat on each page
    assert "table.rep tr{break-inside:avoid}" in html
    assert "table.rep thead{display:table-header-group}" in html
    # a group subheader stays with its first data row (never stranded at a page foot)
    assert "table.rep tr.group{break-after:avoid}" in html
    # the table's outer box/shadow is dropped on paper so a mid-table break isn't a half-drawn row
    assert ".table-wrap{border:none; border-radius:0; box-shadow:none}" in html
    # the break-inside list holds these blocks whole but NOT .code — a long code block may fragment
    assert ".card,.callout,figure.fig,blockquote.quote,.tl li,.status-list li,.list li," in html
    assert ".code," not in html
    # code keeps its normal box (no print-only restyle); a single diff line still never splits, and
    # the split stays seamless (default box-decoration-break, never clone)
    assert ".code .diff .ln{break-inside:avoid}" in html
    assert "box-decoration-break:clone" not in html
    # cards/callouts/list+status items stay whole across page breaks
    assert ".flow .seg,.flow .step,.walk .wstep,.kv,.range .rbar,.badge-groups{break-inside:avoid}" in html
    # a header is never stranded from the content it introduces (break in the gap after it forbidden)
    assert "h1,h2,h3,h4,summary{break-after:avoid; break-inside:avoid}" in html
    # a long section may still break — it is NOT force-kept whole
    assert "details.section,.kv{break-inside:avoid}" not in html
    # flows stack vertically (never wrap a lone node) when printing or on a narrow screen
    assert "@media print, (max-width: 640px){" in html
    assert ".flow .track{flex-direction:column; flex-wrap:nowrap}" in html
    assert ".fan{flex-direction:column; align-items:center}" in html
    assert ".fan .merge{transform:rotate(90deg)}" in html
    assert ".walk{grid-template-columns:1fr !important}" in html
    # collapsed walkthrough steps stack flush: the step's inline-start accent offset is zeroed so the
    # title row lines up with its detail beneath it (mirrors the .wdetail block-start reset)
    assert ".walk .wstep{border-inline-start:0; padding-inline-start:0}" in html
    # code wraps instead of clipping at the page edge (no scrollbar on paper)
    assert ".code pre,.code .diff .ln{white-space:pre-wrap" in html
    # print scales down for document density (the print-density knob)
    assert "zoom:0.75}" in html
    # collapsed sections are expanded for print (beforeprint opens them, afterprint restores),
    # with a CSS fallback for script-less hosts
    assert 'addEventListener("beforeprint"' in html
    assert 'addEventListener("afterprint"' in html
    assert "details::details-content{content-visibility:visible" in html


def test_wrap_carries_no_authorable_width_class() -> None:
    """Width is reader-only: the wrap never gets a width-* class from the author, so the reader's
    data-width override is the sole driver. The base cap lives on .wrap itself."""
    html = render_html(parse_report(make_report()))

    assert '<div class="wrap">' in html
    assert "wrap width-" not in html


def test_every_page_credits_and_links_the_project() -> None:
    html = render_html(parse_report(make_report()))

    assert "<!-- Generated by skaldr" in html
    assert "Install & docs: https://github.com/alex-yanchenko/skaldr -->" in html
    assert (
        '<div class="credit">Generated with <a href="https://github.com/alex-yanchenko/skaldr">skaldr</a></div>'
        in html
    )


def test_default_width_cap_lives_on_the_wrap_and_no_author_classes_remain() -> None:
    """The default 1600px cap is baked onto .wrap itself (not an author-set width-default class), and
    the old author-driven .wrap.width-* rules are gone — only the reader's data-width overrides cap."""
    html = render_html(parse_report(make_report()))

    assert ".wrap{margin-inline:auto; padding:40px 48px 80px; max-width:1600px}" in html
    assert ".wrap.width-" not in html


def test_palette_is_theme_aware_via_light_dark() -> None:
    html = render_html(parse_report(make_report()))

    assert COLOR_SCHEME_RULES[0] in html
    assert "--ink:light-dark(#1e293b,#e8ecf3);" in html
    assert "--page:light-dark(#f5f7fa,#0e1116);" in html


def test_explicit_theme_overrides_win_over_the_os_default() -> None:
    html = render_html(parse_report(make_report()))

    assert COLOR_SCHEME_RULES[1] in html
    assert COLOR_SCHEME_RULES[2] in html


def test_host_override_essentials_sit_outside_any_layer() -> None:
    """color-scheme, box-sizing, and body colour/background must each appear exactly once and before
    the first @layer block — otherwise they are layered and an embedding host's own unlayered reset
    would override them (stranding the theme, breaking box-sizing, or leaving dark panels with the
    host's dark text → invisible)."""
    html = render_html(parse_report(make_report()))
    first_layer_offset = html.index("@layer reset {")

    for rule in UNLAYERED_ESSENTIALS:
        assert html.count(rule) == 1
        assert html.index(rule) < first_layer_offset


def test_every_referenced_css_var_is_defined() -> None:
    """A `var(--x)` with no fallback whose token is never assigned resolves to guaranteed-invalid and
    kills its WHOLE declaration at computed-value time — e.g. one bad token in a `gap` shorthand zeroes
    both axes, silently. So every no-fallback token reference must be assigned somewhere in the sheet
    (`:root` globals or a component-local `--c:` alike). This caught `.deflist`'s `var(--s5)` — `--s5`
    was never in the scale (`--s1/2/3/4/6/8`), so the term/body gap collapsed to 0."""
    css = package_path("styles.css").read_text(encoding="utf-8")
    defined = set(re.findall(r"(--[\w-]+)\s*:", css))
    referenced_no_fallback = set(re.findall(r"var\(\s*(--[\w-]+)\s*\)", css))

    assert referenced_no_fallback <= defined, (
        f"CSS references undefined tokens (no fallback): {sorted(referenced_no_fallback - defined)}"
    )


_SAMPLE_SOURCE = 'version: 1\nmeta: {title: T}\nblocks:\n  - {type: text, body: "bin > 12 & <x> --flag"}\n'


def test_full_page_embeds_the_source_before_the_stylesheet() -> None:
    report = parse_report(make_report())

    html = render_html(report, source=_SAMPLE_SOURCE)

    assert '<script type="application/yaml" id="skaldr-source">' in html
    # placed before the CSS so a fetch/read reaches the source ahead of the stylesheet
    assert html.index("skaldr-source") < html.index("<style>")


def test_embed_fragment_also_embeds_the_source() -> None:
    # the artifact case: a shared --embed fragment must carry its own recoverable source
    html = render_embed(parse_report(make_report()), source=_SAMPLE_SOURCE)

    assert extract_source(html) == _SAMPLE_SOURCE


def test_embedded_source_round_trips_through_extract_source_with_specials() -> None:
    html = render_html(parse_report(make_report()), source=_SAMPLE_SOURCE)

    # plain-text embed survives HTML-special chars (`<`, `&`, `--`) with no escaping/decoding
    assert extract_source(html) == _SAMPLE_SOURCE


def _source_carrying(payload: str) -> str:
    return f'version: 1\nmeta: {{title: T}}\nblocks:\n  - {{type: code, content: "{payload}"}}\n'


def _embedded_text(html: str) -> str:
    start = html.index('id="skaldr-source">')
    return html[start : html.index("--8<-- end skaldr source --8<--", start)]


@pytest.mark.parametrize("render", [render_html, render_embed], ids=["page", "embed"])
def test_a_closing_script_tag_in_the_source_cannot_end_the_source_block(
    render: Callable[..., str],
) -> None:
    hostile = _source_carrying("</script><img onerror=alert(1)>")

    html = render(parse_report(make_report()), source=hostile)

    assert "</script><img onerror=alert(1)>" not in html
    assert "<\\/script><img onerror=alert(1)>" in _embedded_text(html)
    assert extract_source(html) == hostile


@pytest.mark.parametrize(
    ("plain", "hidden"),
    [
        ("</script>", "<\\/script>"),
        ("</SCRIPT >", "<\\/SCRIPT >"),
        ("<\\/script>", "<\\\\\\/script>"),
        ("</script</script>", "<\\/script<\\/script>"),
        ("nothing to hide", "nothing to hide"),
        ("", ""),
    ],
    ids=["bare", "upper-with-space", "already-escaped", "adjacent", "no-match", "empty"],
)
def test_hiding_a_script_close_is_exactly_reversible(plain: str, hidden: str) -> None:
    assert hide_script_close(plain) == hidden
    assert show_script_close(hidden) == plain


def test_hiding_leaves_no_sequence_that_can_end_a_raw_text_element() -> None:
    for payload in ("</script>", "</SCRIPT/", "</script\t", "</script</script></script>", "<\\/script>"):
        assert "</script" not in hide_script_close(payload).lower()


@pytest.mark.parametrize(
    "payload",
    ["</script>", "</SCRIPT >", "a <\\/script> b", "</script</script></script>", "plain text"],
    ids=["bare", "upper-with-space", "already-escaped", "adjacent", "no-match"],
)
def test_an_embedded_source_round_trips_whether_or_not_it_needed_escaping(payload: str) -> None:
    source = _source_carrying(payload)

    html = render_html(parse_report(make_report()), source=source)

    assert "</script" not in _embedded_text(html).lower()
    assert extract_source(html) == source


def test_a_source_needing_no_escaping_keeps_the_plain_marker() -> None:
    source = _source_carrying("nothing dangerous here")

    html = render_html(parse_report(make_report()), source=source)

    assert "backslash-escaped" not in html


def test_a_page_written_before_escaping_existed_is_read_back_untouched() -> None:
    legacy = (
        '<script type="application/yaml" id="skaldr-source">\n'
        "--8<-- skaldr source (yaml) --8<--\n"
        "body: a <\\/script> written by hand\n"
        "--8<-- end skaldr source --8<--\n"
    )

    assert extract_source(legacy) == "body: a <\\/script> written by hand"


def test_unescaping_a_block_that_was_never_escaped_raises() -> None:
    with pytest.raises(ReportError, match="not in the escaped form"):
        show_script_close("a <\\\\/script> b")


def test_render_without_source_embeds_no_block() -> None:
    html = render_html(parse_report(make_report()))

    assert "skaldr-source" not in html
    assert extract_source(html) is None


def test_extract_source_returns_none_for_a_page_without_a_block() -> None:
    assert extract_source("<html><body>no skaldr here</body></html>") is None


@pytest.mark.parametrize(
    ("token", "light", "dark"),
    [
        ("--neutral-fg", "#475569", "#cbd5e1"),
        ("--info-bg", "#eff6ff", "#15243c"),
        ("--success-fg", "#15803d", "#86efac"),
        ("--warning-bg", "#fef3c7", "#2c2410"),
        ("--danger-fg", "#b91c1c", "#fca5a5"),
        ("--accent-bg", "#f3e8ff", "#241a38"),
        ("--teal-fg", "#0f766e", "#5eead4"),
        ("--sky-bg", "#e0f2fe", "#0c2740"),
    ],
)
def test_tone_tokens_carry_both_light_and_dark_values(token: str, light: str, dark: str) -> None:
    html = render_html(parse_report(make_report()))

    assert f"{token}:light-dark({light},{dark});" in html


def test_display_controls_render_with_all_theme_and_width_options() -> None:
    html = render_html(parse_report(make_report()))

    assert '<div class="sc" data-open="false">' in html
    assert 'aria-controls="sc-menu"' in html
    for val, label in [("auto", "Auto"), ("light", "Light"), ("dark", "Dark")]:
        assert (
            f'<button type="button" aria-pressed="false" data-set="theme" data-val="{val}">{label}</button>'
            in html
        )
    for val, label in [("default", "Default"), ("wide", "Wide"), ("full", "Full")]:
        assert (
            f'<button type="button" aria-pressed="false" data-set="width" data-val="{val}">{label}</button>'
            in html
        )


def test_theme_and_width_are_restored_before_paint_in_the_head() -> None:
    html = render_html(parse_report(make_report()))
    head = html.split("</head>", 1)[0]

    assert "function restore(" in head


def test_width_switch_overrides_are_defined_in_the_stylesheet() -> None:
    """Only wide/full get data-width override rules; selecting "default" needs none — it falls back
    to the base .wrap cap, so there is no duplicate 1600px rule to drift."""
    html = render_html(parse_report(make_report()))

    assert ':root[data-width="wide"] .wrap{max-width:1920px}' in html
    assert ':root[data-width="full"] .wrap{max-width:none}' in html
    assert ':root[data-width="default"]' not in html


def test_output_carries_a_locked_down_csp_pinning_the_inline_script_hashes() -> None:
    html = render_html(parse_report(make_report()))
    csp = re.search(r'content="(default-src [^"]+)"', html)
    assert csp is not None
    policy = csp.group(1)
    script_src = policy.split("script-src ", 1)[1].split(";", 1)[0]

    assert policy.startswith("default-src 'none';")
    assert "img-src data:;" in policy
    assert "base-uri 'none'" in policy and "form-action 'none'" in policy
    # script-src pins exact hashes, never 'unsafe-inline' — an injected inline script can't run.
    assert "'unsafe-inline'" not in script_src
    # Recompute each inline script's hash from the rendered output so a script edit that isn't
    # reflected in the CSP fails here (the browser would otherwise silently refuse the script).
    scripts = inline_scripts(html)
    assert len(scripts) == 2
    assert [body[:40] for body in scripts if f"'sha256-{script_hash(body)}'" not in script_src] == []
    # The policy must precede the inline scripts so it governs them.
    assert html.index("Content-Security-Policy") < html.index("<script>")


def test_a_block_type_the_html_dispatch_does_not_handle_fails_instead_of_rendering_nothing() -> None:
    environment = html_environment()
    environment.filters["richtext"] = render_richtext
    page = environment.from_string('{% from "macros.html.j2" import render_block %}{{ render_block(block) }}')

    with pytest.raises(ReportError) as raised:
        page.render(block=SimpleNamespace(type="a_block_type_the_template_misses", span=None))

    assert str(raised.value) == "no HTML template renders the block type 'a_block_type_the_template_misses'"


@pytest.mark.parametrize(
    ("meta", "footer"),
    [
        pytest.param(
            {"source": "commit `abc123` in **main**", "date": "5 Oct"},
            '<div class="footer">commit <code>abc123</code> in <strong>main</strong> · 5 Oct</div>',
            id="the-source-is-rich-text",
        ),
        pytest.param(
            {"date": "a `b` <i>"},
            '<div class="footer">a `b` &lt;i&gt;</div>',
            id="the-other-facts-stay-escaped-plain-text",
        ),
    ],
)
def test_the_footer_reads_its_source_as_rich_text(meta: dict[str, str], footer: str) -> None:
    html = render_html(parse_report(make_report(meta={"title": "T", **meta})))

    assert footer in html


def test_a_rich_text_mistake_in_the_source_names_the_field() -> None:
    report = parse_report(make_report(meta={"title": "T", "source": "[x]{tone=nope}"}))

    with pytest.raises(ReportError, match=r"^meta\.source: unknown tone 'nope'"):
        render_html(report)
