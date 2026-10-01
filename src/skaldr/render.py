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
    Heading,
    Report,
    RequestLike,
    Section,
    iter_requests,
    load_report,
    package_text,
    unresolvable_request_variables,
)
from skaldr.richtext import Chip, Citation, RichContext, StyleName, parse_rich, write_runs

HTML_STYLE_TAG: dict[StyleName, str] = {"bold": "strong", "italic": "em", "strike": "del"}


class _HtmlRuns:
    def __init__(self, cited: set[str], placeholders: set[str] | None) -> None:
        self.cited = cited
        self.placeholders = placeholders

    def text(self, text: str) -> str:
        return str(escape(text))

    def code(self, text: str) -> str:
        return f"<code>{escape(text)}</code>"

    def link(self, label: str, url: str) -> str:
        return f'<a href="{escape(url)}">{label}</a>'

    def anchor_link(self, label: str, anchor: str) -> str:
        return f'<a href="#{escape(anchor)}">{label}</a>'

    def citation(self, run: Citation) -> str:
        anchor = "" if run.key in self.cited else f' id="fnref-{run.key}"'
        self.cited.add(run.key)
        return f'<sup class="fn"><a{anchor} href="#ref-{run.key}">[{run.number}]</a></sup>'

    def placeholder(self, name: str) -> str:
        if self.placeholders is not None:
            self.placeholders.add(name)
        return f'<span class="placeholder">{name}</span>'

    def chip(self, run: Chip) -> str:
        return f'<span class="chip {run.tone}">{escape(run.label)}</span>'

    def line_break(self) -> str:
        return "<br>"

    def styled(self, style: StyleName, inner: str) -> str:
        tag = HTML_STYLE_TAG[style]
        return f"<{tag}>{inner}</{tag}>"


def render_richtext(
    text: str,
    ref_numbers: dict[str, int] | None = None,
    cited: set[str] | None = None,
    anchor_ids: frozenset[str] | None = None,
    placeholders: set[str] | None = None,
) -> Markup:
    """Rich text as HTML: `parse_rich` reads the inline subset and every other character is escaped.
    `cited` records which reference keys have rendered, so only the first citation of a key carries
    the `fnref-` anchor id and the references list knows which keys are cited; pass one shared set
    across a whole render. `placeholders`, when passed, collects every `{{name}}` blank's name."""
    runs = parse_rich(str(text), RichContext(reference_numbers=ref_numbers, anchor_ids=anchor_ids))
    return Markup(write_runs(runs, _HtmlRuns(cited if cited is not None else set(), placeholders)))


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
        variable_parts=compute.variable_parts,
        request_wire=compute.request_wire,
        command_for=compute.command_for,
        produced_names=compute.produced_names,
        status_line=compute.status_line,
        status_tone=compute.status_tone,
        case_tone=compute.case_tone,
        recorded_body=compute.recorded_body,
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
    live: int | None = None,
) -> str:
    env = _environment()
    slugs = compute.anchor_slugs(report)

    def anchor_id(block: Heading | Section) -> str:
        return slugs[id(block)]

    groups = compute.request_groups(report)

    def case_group(core: RequestLike) -> str:
        return groups[id(core)]

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
    globals_["case_group"] = case_group
    globals_["expand_details"] = expand
    globals_["reference_numbers"] = ref_numbers
    globals_["cited_references"] = cited_references
    globals_["matrix_tallies"] = compute.matrix_tallies(report)
    globals_["table_tallies"] = compute.table_tallies(report)
    return env.get_template(template).render(
        meta=report.meta,
        blocks=report.blocks,
        styles=package_text("styles.css") + "\n" + compute.case_strip_rules(report, groups),
        toc=compute.toc_entries(report, slugs),
        used_badges=compute.used_badges(report),
        footer=compute.provenance_footer(report),
        first_table_index=compute.first_table_index(report),
        has_requests=any(iter_requests(report.blocks)),
        source_block=source_block(source) if source else None,
        live=live,
    )


# A page embeds its own YAML source as PLAIN TEXT between these scissors, inside an inert
# `<script type="application/yaml" id="skaldr-source">` placed BEFORE the inlined CSS — so a fetch or a
# top-of-file read reaches it before the stylesheet, and a narrow fetch ("return only the skaldr-source
# block") gets directly-usable YAML with no decode step. `extract_source` / `skaldr --extract-source`
# read it back, so an agent recovers the source without parsing the rendered HTML. A `<script>` is a
# raw-text element: only the literal `</script>` ends it, so YAML's `<`, `&`, `--`, quotes are all safe.
_SOURCE_BEGIN = "--8<-- skaldr source (yaml) --8<--"
_SOURCE_BEGIN_ESCAPED = "--8<-- skaldr source (yaml, backslash-escaped) --8<--"
_SOURCE_END = "--8<-- end skaldr source --8<--"
_SOURCE_RE = re.compile(
    "("
    + re.escape(_SOURCE_BEGIN_ESCAPED)
    + "|"
    + re.escape(_SOURCE_BEGIN)
    + r")\n(.*?)\n"
    + re.escape(_SOURCE_END),
    re.DOTALL,
)
_SCRIPT_CLOSE = re.compile(r"<(\\*)(/script)", re.IGNORECASE)


def hide_script_close(source: str) -> str:
    """`source` with every `</script` made unable to terminate the raw-text element carrying it, by
    inserting a backslash. Every way an HTML tokenizer can leave raw text gates on the character after
    `<` being `/`, so one backslash there closes all of them. Backslashes already in front of the slash
    are doubled first, taking a run of n to 2n+1, which is what lets `show_script_close` recover the
    original exactly. A source holding no `</script` comes back unchanged."""
    return _SCRIPT_CLOSE.sub(lambda m: "<" + "\\" * (2 * len(m.group(1)) + 1) + m.group(2), source)


def show_script_close(source: str) -> str:
    """The inverse of `hide_script_close`: a run of 2n+1 backslashes goes back to n. Apply it only to a
    block whose marker is `_SOURCE_BEGIN_ESCAPED`, because an even-length run is one `hide_script_close`
    never wrote, and quietly halving it would invent a source nobody authored."""

    def restore(match: re.Match[str]) -> str:
        run = len(match.group(1))
        if run % 2 == 0:
            raise ReportError(
                f"embedded source is not in the escaped form its marker promises: {match.group(0)!r}"
            )
        return "<" + "\\" * ((run - 1) // 2) + match.group(2)

    return _SCRIPT_CLOSE.sub(restore, source)


def source_block(source: str) -> Markup:
    """The inert, self-documenting block carrying the page's own YAML `source` as plain text. Its header
    names the recovery command, so a reader who finds it (or a fetch that returns only it) gets usable
    YAML and knows where it came from — no decode, no HTML parsing. The one exception is a source that
    itself contains `</script`, which would end the block early: that one is backslash-escaped and says
    so in its own begin marker, so a reader slicing the text raw can see that it needs undoing."""
    hidden = hide_script_close(source)
    begin = _SOURCE_BEGIN if hidden == source else _SOURCE_BEGIN_ESCAPED
    return Markup(
        '<script type="application/yaml" id="skaldr-source">\n'
        "# skaldr embeds this page's editable YAML source below, so an agent can recover it WITHOUT\n"
        "# reading the rendered HTML/CSS. Recover it with `skaldr --extract-source <file-or-url>`, or\n"
        "# read only the lines between the scissor markers. This block does not affect rendering.\n"
        f"{begin}\n{hidden}\n{_SOURCE_END}\n"
        "</script>"
    )


def extract_source(html: str) -> str | None:
    """Recover the plain-text YAML source embedded by `source_block`, or None if the page carries none
    (an older render, or one written with --no-source). The inverse of what `source_block` writes: a
    block marked escaped is unescaped, and every other block — including one written before escaping
    existed — is returned exactly as it sits on the page."""
    match = _SOURCE_RE.search(html)
    if match is None:
        return None
    return show_script_close(match.group(2)) if match.group(1) == _SOURCE_BEGIN_ESCAPED else match.group(2)


def render_html(
    report: Report, *, expand: bool = False, source: str | None = None, live: int | None = None
) -> str:
    """A complete, self-contained HTML document — the default output. `expand` forces every
    collapsible `<details>` open; used for PDF output, where headless print can't run the
    beforeprint script that expands sections on screen. `source`, when given, is embedded as plain
    text (see `source_block`) so the page carries its own recoverable YAML. `live`, when given,
    adds the self-refreshing reloader (see `_live_reload.html.j2`); the integer is a polling
    interval in milliseconds, and 0 means refresh on focus alone."""
    return _render(report, "page.html.j2", expand=expand, source=source, live=live)


def find_placeholders(report: Report) -> list[str]:
    """Names of every unfilled blank in the report, sorted and de-duplicated, from two sources: a
    `{{placeholder}}` in rich text, and a `{{name}}` a `request` interpolates but cannot fill from its
    own declarations. A request variable the author did declare is a runtime blank its reader fills, so
    it is deliberately absent. Renders once into a throwaway to reuse the rich-text traversal; the
    --check --strict gate uses this to refuse a doc that still has blanks."""
    seen: set[str] = set()
    _render(report, "page.html.j2", placeholders=seen)
    return sorted(seen | unresolvable_request_variables(report.blocks))


def render_embed(report: Report, *, source: str | None = None) -> str:
    """A fragment for embedding in a claude.ai Artifact: an inline `<style>` + the content markup +
    the corner controls, without the `<!doctype>`/`<html>`/`<head>`/`<body>` skeleton or the CSP
    meta. It carries the same theme-boot and controls scripts as the full page (Artifacts allow
    inline JS), so it self-manages theme/width and stays `light-dark()` + `[data-theme]` aware.
    `source`, when given, is embedded so a shared Artifact carries its own recoverable YAML — the
    common case, since Artifacts are shared as URLs an agent then has to read back."""
    return _render(report, "embed.html.j2", source=source)


def render_report(
    report: Report,
    out_path: Path,
    *,
    embed: bool = False,
    source: str | None = None,
    live: int | None = None,
) -> None:
    """Write an already-loaded report to `out_path` (no re-read of the source file). `source`, when
    given, is embedded — in the full page AND in an `--embed` fragment — so the artifact carries its own
    recoverable YAML. Pass source=None (or render with --no-source) to suppress it. `live` is ignored
    for an `--embed` fragment: those get published as Artifacts, and a shared page that reloads itself
    on someone else's screen is never what the author meant."""
    html = render_embed(report, source=source) if embed else render_html(report, source=source, live=live)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")


def render_file(data_path: Path, out_path: Path, *, embed: bool = False) -> Report:
    report = load_report(data_path)
    source = data_path.read_text(encoding="utf-8")
    render_report(report, out_path, embed=embed, source=source)
    return report
