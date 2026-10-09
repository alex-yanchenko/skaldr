import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from typing_extensions import assert_never

from skaldr.export.adf.colors import BADGE_LOZENGE, TEXT_COLOR
from skaldr.export.adf.nodes import (
    AdfCode,
    AdfEm,
    AdfHardBreak,
    AdfInline,
    AdfInlineCard,
    AdfInlineCardAttrs,
    AdfLink,
    AdfLinkAttrs,
    AdfMark,
    AdfStatus,
    AdfStatusAttrs,
    AdfStrike,
    AdfStrong,
    AdfSubsup,
    AdfSubsupAttrs,
    AdfText,
    AdfTextColor,
    AdfTextColorAttrs,
    AdfUnderline,
    LozengeColor,
)
from skaldr.export.glyphs import gauge_bar, mark_glyph
from skaldr.export.runs import (
    Chip,
    ExportRich,
    Gauge,
    Mark,
    StatusMark,
    SwimlaneMark,
    mark_name,
    write_export_runs,
)
from skaldr.export.tree import ToneName
from skaldr.models import StatusState, SwimlaneStepState, ToneLiteral
from skaldr.richtext import Citation, ScriptPosition, StyleName

AdfInlines = tuple[AdfInline, ...]

MARK_RANK: Final[Mapping[str, int]] = {
    "link": 0,
    "strong": 1,
    "em": 2,
    "underline": 3,
    "strike": 4,
    "subsup": 5,
    "textColor": 6,
    "code": 7,
}
STATUS_LOZENGE: Final[Mapping[StatusState, LozengeColor]] = {
    "done": "green",
    "current": "blue",
    "pending": "neutral",
    "failed": "red",
    "blocked": "yellow",
}
SWIMLANE_LOZENGE: Final[Mapping[SwimlaneStepState, LozengeColor]] = {
    "done": "green",
    "current": "blue",
    "todo": "neutral",
    "blocked": "yellow",
    "deferred": "purple",
}


@dataclass(frozen=True)
class IssueLinks:
    site_url: str
    project_keys: frozenset[str]

    def url_of(self, key: str) -> str:
        return f"{self.site_url.rstrip('/')}/browse/{key}"


def _issue_key_pattern(links: IssueLinks) -> re.Pattern[str]:
    projects = "|".join(re.escape(project) for project in sorted(links.project_keys, key=len, reverse=True))
    return re.compile(rf"(?<![\w-])(?:{projects})-\d+(?![\w-])")


def _plain_text(text: str) -> AdfText:
    return AdfText(type="text", text=text)


def _style_mark(style: StyleName) -> AdfMark:
    match style:
        case "bold":
            return AdfStrong(type="strong")
        case "italic":
            return AdfEm(type="em")
        case "underline":
            return AdfUnderline(type="underline")
        case "strike":
            return AdfStrike(type="strike")
        case _:
            assert_never(style)


def text_color_mark(tone: ToneName) -> AdfMark:
    return AdfTextColor(type="textColor", attrs=AdfTextColorAttrs(color=TEXT_COLOR[tone]))


def _marked(node: AdfInline, mark: AdfMark) -> AdfInline:
    if node["type"] != "text":
        return node
    marks = node.get("marks", [])
    if any(existing["type"] == mark["type"] for existing in marks):
        return node
    if mark["type"] != "link" and any(existing["type"] == "code" for existing in marks):
        return node
    ordered = sorted([*marks, mark], key=lambda each: MARK_RANK[each["type"]])
    return AdfText(type="text", text=node["text"], marks=ordered)


def with_mark(nodes: AdfInlines, mark: AdfMark) -> AdfInlines:
    return tuple(_marked(node, mark) for node in nodes)


def _retexted(node: AdfText, text: str) -> AdfText:
    retexted = AdfText(type="text", text=text)
    if "marks" in node:
        retexted["marks"] = node["marks"]
    return retexted


def _merged(nodes: Sequence[AdfInline]) -> AdfInlines:
    merged: list[AdfInline] = []
    for node in nodes:
        previous = merged[-1] if merged else None
        if (
            previous is not None
            and previous["type"] == "text"
            and node["type"] == "text"
            and previous.get("marks") == node.get("marks")
        ):
            merged[-1] = _retexted(previous, previous["text"] + node["text"])
        else:
            merged.append(node)
    return tuple(merged)


def _as_text_in_a_link(node: AdfInline) -> AdfInline:
    if node["type"] != "inlineCard":
        return node
    return _plain_text(node["attrs"]["url"].rsplit("/", 1)[-1])


def _status(text: str, color: LozengeColor) -> AdfInlines:
    if not text:
        return ()
    return (AdfStatus(type="status", attrs=AdfStatusAttrs(text=text, color=color)),)


def _lozenge(mark: Mark) -> AdfInlines | None:
    match mark:
        case StatusMark():
            return _status(mark_name(mark), STATUS_LOZENGE[mark.state])
        case SwimlaneMark():
            return _status(mark_name(mark), SWIMLANE_LOZENGE[mark.state])
        case _:
            return None


class AdfRuns:
    def __init__(self, issue_links: IssueLinks | None = None) -> None:
        self.issue_links = issue_links
        self.issue_key = _issue_key_pattern(issue_links) if issue_links and issue_links.project_keys else None

    def write(self, runs: ExportRich) -> AdfInlines:
        return write_export_runs(runs, self)

    def concat(self, parts: Sequence[AdfInlines], /) -> AdfInlines:
        return _merged([node for part in parts for node in part])

    def text(self, text: str, /) -> AdfInlines:
        if not text:
            return ()
        if self.issue_links is None or self.issue_key is None:
            return (_plain_text(text),)
        nodes: list[AdfInline] = []
        written_up_to = 0
        for found in self.issue_key.finditer(text):
            if found.start() > written_up_to:
                nodes.append(_plain_text(text[written_up_to : found.start()]))
            card = AdfInlineCardAttrs(url=self.issue_links.url_of(found.group()))
            nodes.append(AdfInlineCard(type="inlineCard", attrs=card))
            written_up_to = found.end()
        if written_up_to < len(text):
            nodes.append(_plain_text(text[written_up_to:]))
        return tuple(nodes)

    def code(self, text: str, /) -> AdfInlines:
        if not text:
            return ()
        return (AdfText(type="text", text=text, marks=[AdfCode(type="code")]),)

    def link(self, label: AdfInlines, url: str, /) -> AdfInlines:
        mark = AdfLink(type="link", attrs=AdfLinkAttrs(href=url))
        return with_mark(tuple(map(_as_text_in_a_link, label)), mark)

    def anchor_link(self, label: AdfInlines, _anchor: str, /) -> AdfInlines:
        return label

    def citation(self, run: Citation, /) -> AdfInlines:
        label = (_plain_text(f"[{run.number}]"),)
        return self.link(label, run.url) if run.url else label

    def placeholder(self, name: str, /) -> AdfInlines:
        return self.code("{{" + name + "}}")

    def styled(self, style: StyleName, inner: AdfInlines, /) -> AdfInlines:
        return with_mark(inner, _style_mark(style))

    def script(self, position: ScriptPosition, text: str, /) -> AdfInlines:
        if not text:
            return ()
        kind = AdfSubsupAttrs(type="sub" if position == "subscript" else "sup")
        return with_mark((_plain_text(text),), AdfSubsup(type="subsup", attrs=kind))

    def tinted(
        self, tone: ToneLiteral | None, _background: ToneLiteral | None, inner: AdfInlines, /
    ) -> AdfInlines:
        return inner if tone is None else with_mark(inner, text_color_mark(tone))

    def math(self, expression: str, /) -> AdfInlines:
        return self.code(expression)

    def chip(self, run: Chip, /) -> AdfInlines:
        return _status(run.label, BADGE_LOZENGE[run.tone])

    def line_break(self) -> AdfInlines:
        return (AdfHardBreak(type="hardBreak"),)

    def mark(self, run: Mark, /) -> AdfInlines:
        lozenge = _lozenge(run)
        return lozenge if lozenge is not None else (_plain_text(mark_glyph(run)),)

    def gauge(self, run: Gauge, /) -> AdfInlines:
        return (_plain_text(gauge_bar(run.value, run.maximum)),)


def write_adf_runs(runs: ExportRich, issue_links: IssueLinks | None = None) -> AdfInlines:
    return AdfRuns(issue_links).write(runs)
