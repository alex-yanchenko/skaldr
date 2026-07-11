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
from skaldr.models import Heading, Report, load_report, package_text

_CODE_SPAN = re.compile(r"`([^`]+)`")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
_BOLD = re.compile(r"\*\*([^*]+)\*\*")
_STRIKE = re.compile(r"~~([^~]+)~~")
_ITALIC = re.compile(r"(?<!\*)\*([^*]+)\*(?!\*)")
_ALLOWED_SCHEMES = ("http://", "https://", "mailto:")


def render_richtext(text: str) -> Markup:
    """Escape, then apply the limited inline markdown subset. Code spans and links are stashed as
    finished HTML *before* the bold/strike/italic passes run, so a stray `*` or `~` inside a code
    span or a URL can't corrupt them."""
    # NUL is the stash sentinel below; strip any literal NUL from input so it can't collide.
    escaped = str(escape(text)).replace("\x00", "")
    stash: list[str] = []

    def _stash(html: str) -> str:
        stash.append(html)
        return f"\x00{len(stash) - 1}\x00"

    result = _CODE_SPAN.sub(lambda match: _stash(f"<code>{match.group(1)}</code>"), escaped)

    def _link(match: re.Match[str]) -> str:
        label, url = match.group(1), match.group(2)
        if url.startswith(_ALLOWED_SCHEMES):
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
    )
    return env


def render_html(report: Report) -> str:
    env = _environment()
    slugs = compute.heading_slugs(report)

    def heading_id(block: Heading) -> str:
        return slugs[id(block)]

    globals_ = cast("dict[str, Any]", env.globals)
    globals_["badges"] = report.badges
    globals_["heading_id"] = heading_id
    return env.get_template("page.html.j2").render(
        meta=report.meta,
        blocks=report.blocks,
        styles=package_text("styles.css"),
        toc=compute.toc_entries(report, slugs),
        used_badges=compute.used_badges(report),
        footer=compute.provenance_footer(report),
        first_table_index=compute.first_table_index(report),
    )


def render_file(data_path: Path, out_path: Path) -> Report:
    report = load_report(data_path)
    html = render_html(report)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    return report
