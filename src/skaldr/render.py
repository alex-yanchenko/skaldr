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


def render_richtext(
    text: str,
    ref_numbers: dict[str, int] | None = None,
    cited: set[str] | None = None,
    anchor_ids: frozenset[str] | None = None,
) -> Markup:
    """Escape, then apply the limited inline markdown subset. Code spans, footnote markers, and
    links are stashed as finished HTML *before* the bold/strike/italic passes run, so a stray `*`
    or `~` inside a code span or a URL can't corrupt them. `[^key]` markers resolve to a superscript
    number linking to the `references` list — but only for keys `ref_numbers` actually declares; an
    unknown key is left as literal text so a typo surfaces instead of vanishing. `cited` records
    which keys have already been rendered so only the first occurrence carries the `fnref-` anchor
    id (keeping ids unique) and the references list knows which keys are actually cited; pass one
    shared set across a whole render."""
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
        swimlane_layout=compute.swimlane_layout,
        chart_svg=chart_svg,
        chart_legend=chart_legend,
    )
    return env


def _render(report: Report, template: str, *, expand: bool = False) -> str:
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
        return render_richtext(text, ref_numbers, cited_references, anchor_ids)

    filters = cast("dict[str, Any]", env.filters)
    filters["richtext"] = richtext

    globals_ = cast("dict[str, Any]", env.globals)
    globals_["badges"] = report.badges
    globals_["anchor_id"] = anchor_id
    globals_["expand_details"] = expand
    globals_["reference_numbers"] = ref_numbers
    globals_["cited_references"] = cited_references
    return env.get_template(template).render(
        meta=report.meta,
        blocks=report.blocks,
        styles=package_text("styles.css"),
        toc=compute.toc_entries(report, slugs),
        used_badges=compute.used_badges(report),
        footer=compute.provenance_footer(report),
        first_table_index=compute.first_table_index(report),
    )


def render_html(report: Report, *, expand: bool = False) -> str:
    """A complete, self-contained HTML document — the default output. `expand` forces every
    collapsible `<details>` open; used for PDF output, where headless print can't run the
    beforeprint script that expands sections on screen."""
    return _render(report, "page.html.j2", expand=expand)


def render_embed(report: Report) -> str:
    """A fragment for embedding in a claude.ai Artifact: an inline `<style>` + the content markup +
    the corner controls, without the `<!doctype>`/`<html>`/`<head>`/`<body>` skeleton or the CSP
    meta. It carries the same theme-boot and controls scripts as the full page (Artifacts allow
    inline JS), so it self-manages theme/width and stays `light-dark()` + `[data-theme]` aware."""
    return _render(report, "embed.html.j2")


def render_report(report: Report, out_path: Path, *, embed: bool = False) -> None:
    """Write an already-loaded report to `out_path` (no re-read of the source file)."""
    html = render_embed(report) if embed else render_html(report)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")


def render_file(data_path: Path, out_path: Path, *, embed: bool = False) -> Report:
    report = load_report(data_path)
    render_report(report, out_path, embed=embed)
    return report
