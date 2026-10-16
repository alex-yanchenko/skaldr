import html
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Final
from urllib.parse import quote

from skaldr.errors import ExportInvariantError
from skaldr.export.markup import STYLE_TAG, URL_SAFE_CHARACTERS, MarkupRuns, wrap_around_core
from skaldr.export.runs import Chip, ExportRich, IndicatorMark, write_export_runs
from skaldr.models import BADGE_COLOR_TONE, ToneLiteral
from skaldr.richtext import SCRIPT_HTML_TAG, Citation, ScriptPosition, StyleName
from skaldr.typed_links import date_target_text

HTML_STYLE_TAG: Final[Mapping[StyleName, str]] = {**STYLE_TAG, "underline": "ins"}


CANNOT_TINT: Final = (
    "GitHub Markdown cannot colour or highlight text; the export check should have refused it"
)


def underlined(inner: str) -> str:
    return wrap_around_core(inner, "<ins>", "</ins>")


def scripted(position: ScriptPosition, escaped_text: str) -> str:
    tag = SCRIPT_HTML_TAG[position]
    return f"<{tag}>{escaped_text}</{tag}>"


def start_attribute(number: int) -> str:
    return f' start="{number}"' if number != 1 else ""


def date_tag(label: str, start: date, end: date | None) -> str:
    if end is None:
        return f'<time datetime="{start.isoformat()}">{label}</time>'
    return f'<span data-range="{date_target_text(start, end)}">{label}</span>'


def _href(url: str) -> str:
    return html.escape(quote(url, safe=URL_SAFE_CHARACTERS), quote=True)


class HtmlRuns(MarkupRuns):
    def __init__(self, heading_slugs: Mapping[str, str]) -> None:
        self.heading_slugs = heading_slugs

    def write(self, runs: ExportRich) -> str:
        return write_export_runs(runs, self)

    def escape(self, text: str, /) -> str:
        return html.escape(text, quote=False)

    def text(self, text: str, /) -> str:
        return self.escape(text)

    def code(self, text: str, /) -> str:
        return f"<code>{self.escape(text)}</code>"

    def placeholder(self, name: str, /) -> str:
        return self.code("{{" + name + "}}")

    def math(self, expression: str, /) -> str:
        return self.code(expression)

    def underline(self, inner: str, /) -> str:
        return underlined(inner)

    def script(self, position: ScriptPosition, text: str, /) -> str:
        return scripted(position, self.escape(text))

    def styled(self, style: StyleName, inner: str, /) -> str:
        tag = HTML_STYLE_TAG[style]
        return wrap_around_core(inner, f"<{tag}>", f"</{tag}>")

    def tinted(self, tone: ToneLiteral | None, _background: ToneLiteral | None, inner: str, /) -> str:
        if tone is not None:
            raise ExportInvariantError(CANNOT_TINT)
        return wrap_around_core(inner, "<mark>", "</mark>")

    def link(self, label: str, url: str, /) -> str:
        return f'<a href="{_href(url)}">{label}</a>'

    def anchor_link(self, label: str, anchor: str, /) -> str:
        slug = self.heading_slugs.get(anchor)
        return f'<a href="#{html.escape(slug, quote=True)}">{label}</a>' if slug else label

    def section_link(self, label: str, anchor: str, /) -> str:
        return self.anchor_link(label, anchor)

    def document_link(self, label: str, doc_id: str, _section: str | None, /) -> str:
        return self.link(label, f"{doc_id}.md")

    def date_mention(self, label: str, start: date, end: date | None, /) -> str:
        return date_tag(label, start, end)

    def citation(self, run: Citation, /) -> str:
        label = f"[{run.number}]"
        return self.link(label, run.url) if run.url else label

    def line_break(self) -> str:
        return "<br>"

    def toned_label(self, tone: ToneLiteral, inner: str, /) -> str:
        return f"{self.mark(IndicatorMark(tone))} {inner}"

    def chip(self, run: Chip, /) -> str:
        dot = self.mark(IndicatorMark(BADGE_COLOR_TONE[run.tone]))
        return f"{dot} <strong>{self.escape(run.label)}</strong>"


def details_lines(summary: str, body: Sequence[str], *, opened: bool) -> list[str]:
    opening = "<details open>" if opened else "<details>"
    head = [opening, f"<summary>{summary}</summary>"]
    return [*head, "", *body, "", "</details>"] if body else [*head, "</details>"]
