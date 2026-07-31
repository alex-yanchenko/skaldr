"""Rendering: a validated report -> one self-contained HTML page.

The page carries its own skeleton (`<!doctype>`, `<meta charset>`, viewport), inlines all CSS,
and uses system fonts only — so it renders anywhere with no external resources. Rich-text prose
is a limited markdown subset (bold/italic/code/strike/links); everything else is escaped, so a
content file can never smuggle in raw HTML.
"""

import re
from pathlib import Path
from typing import Any, cast

from jinja2 import Environment, PackageLoader, StrictUndefined
from markupsafe import Markup, escape

from skaldr import compute
from skaldr.charts import chart_legend, chart_svg
from skaldr.errors import ReportError
from skaldr.models import (
    ALLOWED_URL_SCHEMES,
    REFERENCE_KEY_PATTERN,
    Heading,
    Report,
    Section,
    load_report,
    package_text,
)

_CODE_SPAN = re.compile(r"`([^`]+)`")
_FOOTNOTE = re.compile(rf"\[\^({REFERENCE_KEY_PATTERN})\]")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
_BOLD = re.compile(r"\*\*([^*]+)\*\*")
_STRIKE = re.compile(r"~~([^~]+)~~")
_ITALIC = re.compile(r"(?<!\*)\*([^*]+)\*(?!\*)")
_PLACEHOLDER = re.compile(r"\{\{\s*(\w+)\s*\}\}")


def render_richtext(
    text: str,
    ref_numbers: dict[str, int] | None = None,
    cited: set[str] | None = None,
    anchor_ids: frozenset[str] | None = None,
    placeholders: set[str] | None = None,
) -> Markup:
    """Escape, then apply the limited inline markdown subset. Code spans, footnote markers, and
    links are stashed as finished HTML *before* the bold/strike/italic passes run, so a stray `*`
    or `~` inside a code span or a URL can't corrupt them. `[^key]` markers resolve to a superscript
    number linking to the `references` list — but only for keys `ref_numbers` actually declares; an
    unknown key is left as literal text so a typo surfaces instead of vanishing. `cited` records
    which keys have already been rendered so only the first occurrence carries the `fnref-` anchor
    id (keeping ids unique) and the references list knows which keys are actually cited; pass one
    shared set across a whole render. `anchor_ids` is the set of valid same-page `#slug` targets — a
    `[…](#id)` link resolves only if its target is in it (a full render passes it; None leaves such
    links literal). `placeholders`, when passed, collects every `{{name}}` blank's name (the tokens
    always render as a chip regardless)."""
    # NUL is the stash sentinel below; strip any literal NUL from input so it can't collide.
    escaped = str(escape(text)).replace("\x00", "")
    stash: list[str] = []
    seen: set[str] = cited if cited is not None else set()

    def _stash(html: str) -> str:
        stash.append(html)
        return f"\x00{len(stash) - 1}\x00"

    result = _CODE_SPAN.sub(lambda match: _stash(f"<code>{match.group(1)}</code>"), escaped)

    def _footnote(match: re.Match[str]) -> str:
        key = match.group(1)
        if ref_numbers is None or key not in ref_numbers:
            return match.group(0)
        # Only the first citation of a key gets the anchor id, so a source cited twice can't emit a
        # duplicate `fnref-` id; every citation still links forward to the list entry.
        anchor = "" if key in seen else f' id="fnref-{key}"'
        seen.add(key)
        return _stash(f'<sup class="fn"><a{anchor} href="#ref-{key}">[{ref_numbers[key]}]</a></sup>')

    result = _FOOTNOTE.sub(_footnote, result)

    def _link(match: re.Match[str]) -> str:
        label, url = match.group(1), match.group(2)
        if url.startswith("#"):
            # Same-page anchor: the target must be a real heading/section id, so a dangling `#link`
            # fails the build instead of shipping a jump-to-nowhere. `url` is already HTML-escaped, and
            # every valid slug is `[a-z0-9-]`. Only a full render supplies the anchor set; without one
            # (a bare render_richtext call) there is nothing to resolve against, so leave it literal.
            if anchor_ids is None:
                return match.group(0)
            if url[1:] not in anchor_ids:
                raise ReportError(
                    f"rich text links to unknown anchor '{url}' — no heading or section has that id"
                )
            return _stash(f'<a href="{url}">{label}</a>')
        if url.startswith(ALLOWED_URL_SCHEMES):
            return _stash(f'<a href="{url}">{label}</a>')
        return match.group(0)

    result = _LINK.sub(_link, result)

    def _placeholder(match: re.Match[str]) -> str:
        # A `{{name}}` fill-me-later blank: always renders as a visible chip so it can't be shipped
        # unnoticed; `placeholders`, when passed, collects the names for the --check --strict gate.
        name = match.group(1)
        if placeholders is not None:
            placeholders.add(name)
        return _stash(f'<span class="placeholder">{name}</span>')

    result = _PLACEHOLDER.sub(_placeholder, result)
    result = _BOLD.sub(r"<strong>\1</strong>", result)
    result = _STRIKE.sub(r"<del>\1</del>", result)
    result = _ITALIC.sub(r"<em>\1</em>", result)
    # A stashed link can contain a stashed code span (`[`code`](url)`), so a single pass would
    # leave the inner placeholder unexpanded — resolve repeatedly until no markers remain.
    while "\x00" in result:
        result = re.sub(r"\x00(\d+)\x00", lambda match: stash[int(match.group(1))], result)
    return Markup(result)


def _environment() -> Environment:
    env = Environment(
        loader=PackageLoader("skaldr", "components"),
        undefined=StrictUndefined,
        autoescape=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    filters = cast("dict[str, Any]", env.filters)
    filters["fmt"] = compute.fmt
    filters["richtext"] = render_richtext
    globals_ = cast("dict[str, Any]", env.globals)
    globals_.update(
        pct=compute.pct,
        col_sum=compute.col_sum,
        reconcile_line=compute.reconcile_line,
        table_rollup=compute.table_rollup,
        matrix_grid=compute.matrix_grid,
        swimlane_layout=compute.swimlane_layout,
        chart_svg=chart_svg,
        chart_legend=chart_legend,
    )
    return env


def _render(
    report: Report,
    template: str,
    *,
    expand: bool = False,
    placeholders: set[str] | None = None,
    source: str | None = None,
) -> str:
    env = _environment()
    slugs = compute.anchor_slugs(report)

    def anchor_id(block: Heading | Section) -> str:
        return slugs[id(block)]

    ref_numbers = compute.reference_numbers(report)
    anchor_ids = frozenset(slugs.values())
    # Templates render top-to-bottom, so this set fills with each `[^key]` as prose renders; the
    # trailing references list reads it to give a cited key a backlink and skip one never cited.
    cited_references: set[str] = set()

    def richtext(text: str) -> Markup:
        return render_richtext(text, ref_numbers, cited_references, anchor_ids, placeholders)

    filters = cast("dict[str, Any]", env.filters)
    filters["richtext"] = richtext

    globals_ = cast("dict[str, Any]", env.globals)
    globals_["badges"] = report.badges
    globals_["anchor_id"] = anchor_id
    globals_["expand_details"] = expand
    globals_["reference_numbers"] = ref_numbers
    globals_["cited_references"] = cited_references
    globals_["matrix_tallies"] = compute.matrix_tallies(report)
    return env.get_template(template).render(
        meta=report.meta,
        blocks=report.blocks,
        styles=package_text("styles.css"),
        toc=compute.toc_entries(report, slugs),
        used_badges=compute.used_badges(report),
        footer=compute.provenance_footer(report),
        first_table_index=compute.first_table_index(report),
        source_block=source_block(source) if source else None,
    )


# A page embeds its own YAML source as PLAIN TEXT between these scissors, inside an inert
# `<script type="application/yaml" id="skaldr-source">` placed BEFORE the inlined CSS — so a fetch or a
# top-of-file read reaches it before the stylesheet, and a narrow fetch ("return only the skaldr-source
# block") gets directly-usable YAML with no decode step. `extract_source` / `skaldr --extract-source`
# read it back, so an agent recovers the source without parsing the rendered HTML. A `<script>` is a
# raw-text element: only the literal `</script>` ends it, so YAML's `<`, `&`, `--`, quotes are all safe.
_SOURCE_BEGIN = "--8<-- skaldr source (yaml) --8<--"
_SOURCE_END = "--8<-- end skaldr source --8<--"
_SOURCE_RE = re.compile(re.escape(_SOURCE_BEGIN) + r"\n(.*?)\n" + re.escape(_SOURCE_END), re.DOTALL)


def source_block(source: str) -> Markup:
    """The inert, self-documenting block carrying the page's own YAML `source` as plain text. Its header
    names the recovery command, so a reader who finds it (or a fetch that returns only it) gets usable
    YAML and knows where it came from — no decode, no HTML parsing."""
    return Markup(
        '<script type="application/yaml" id="skaldr-source">\n'
        "# skaldr embeds this page's editable YAML source below, so an agent can recover it WITHOUT\n"
        "# reading the rendered HTML/CSS. Recover it with `skaldr --extract-source <file-or-url>`, or\n"
        "# read only the lines between the scissor markers. This block does not affect rendering.\n"
        f"{_SOURCE_BEGIN}\n{source}\n{_SOURCE_END}\n"
        "</script>"
    )


def extract_source(html: str) -> str | None:
    """Recover the plain-text YAML source embedded by `source_block`, or None if the page carries none
    (an older render, or one written with --no-source). The inverse of what `source_block` writes."""
    match = _SOURCE_RE.search(html)
    return match.group(1) if match else None


def render_html(report: Report, *, expand: bool = False, source: str | None = None) -> str:
    """A complete, self-contained HTML document — the default output. `expand` forces every
    collapsible `<details>` open; used for PDF output, where headless print can't run the
    beforeprint script that expands sections on screen. `source`, when given, is embedded as plain
    text (see `source_block`) so the page carries its own recoverable YAML."""
    return _render(report, "page.html.j2", expand=expand, source=source)


def find_placeholders(report: Report) -> list[str]:
    """Names of every `{{placeholder}}` fill-me-later blank in the report, sorted and de-duplicated.
    Renders once into a throwaway to reuse the rich-text traversal; the --check --strict gate uses it
    to refuse a doc that still has blanks."""
    seen: set[str] = set()
    _render(report, "page.html.j2", placeholders=seen)
    return sorted(seen)


def render_embed(report: Report, *, source: str | None = None) -> str:
    """A fragment for embedding in a claude.ai Artifact: an inline `<style>` + the content markup +
    the corner controls, without the `<!doctype>`/`<html>`/`<head>`/`<body>` skeleton or the CSP
    meta. It carries the same theme-boot and controls scripts as the full page (Artifacts allow
    inline JS), so it self-manages theme/width and stays `light-dark()` + `[data-theme]` aware.
    `source`, when given, is embedded so a shared Artifact carries its own recoverable YAML — the
    common case, since Artifacts are shared as URLs an agent then has to read back."""
    return _render(report, "embed.html.j2", source=source)


def render_report(report: Report, out_path: Path, *, embed: bool = False, source: str | None = None) -> None:
    """Write an already-loaded report to `out_path` (no re-read of the source file). `source`, when
    given, is embedded — in the full page AND in an `--embed` fragment — so the artifact carries its own
    recoverable YAML. Pass source=None (or render with --no-source) to suppress it."""
    html = render_embed(report, source=source) if embed else render_html(report, source=source)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")


def render_file(data_path: Path, out_path: Path, *, embed: bool = False) -> Report:
    report = load_report(data_path)
    source = data_path.read_text(encoding="utf-8")
    render_report(report, out_path, embed=embed, source=source)
    return report
