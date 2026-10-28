import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Final, assert_never
from urllib.parse import urlsplit

from skaldr.errors import ConnectorError, ExportInvariantError
from skaldr.export.adf.colors import BACKGROUND_COLOR, BADGE_LOZENGE, TEXT_COLOR
from skaldr.export.adf.nodes import (
    AdfBackgroundColor,
    AdfBackgroundColorAttrs,
    AdfCode,
    AdfDate,
    AdfDateAttrs,
    AdfEm,
    AdfHardBreak,
    AdfInline,
    AdfInlineCard,
    AdfInlineCardAttrs,
    AdfLink,
    AdfLinkAttrs,
    AdfMark,
    AdfMention,
    AdfMentionAttrs,
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
from skaldr.export.swaps import require_the_swap
from skaldr.export.tree import ToneName
from skaldr.models import ALLOWED_URL_SCHEMES, Person, StatusState, SwimlaneStepState, ToneLiteral
from skaldr.richtext import Citation, ScriptPosition, StyleName
from skaldr.typed_links import issue_url

AdfInlineNodes = tuple[AdfInline, ...]

PROJECT_KEY: Final = re.compile(r"[A-Z][A-Z0-9_]+")
MARK_RANK: Final[Mapping[str, int]] = {
    "link": 0,
    "strong": 1,
    "em": 2,
    "underline": 3,
    "strike": 4,
    "subsup": 5,
    "textColor": 6,
    "backgroundColor": 7,
    "code": 8,
}
PLACEHOLDER_TONE: Final[ToneName] = "warning"
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

    def __post_init__(self) -> None:
        site = urlsplit(self.site_url)
        refused = (
            not self.site_url.startswith("https://")
            or not site.hostname
            or "@" in site.netloc
            or site.query
            or site.fragment
        )
        if refused:
            raise ConnectorError(
                "issue links need a lowercase https:// site URL with a host and no user info, query or "
                f"fragment, got '{self.site_url}'"
            )
        for key in sorted(self.project_keys):
            if not PROJECT_KEY.fullmatch(key):
                raise ConnectorError(
                    f"'{key}' is not a Jira project key: capital letters, digits and underscores, "
                    "starting with a letter, at least two characters"
                )

    def url_of(self, key: str) -> str:
        return issue_url(self.site_url, key)


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


def background_color_mark(tone: ToneName) -> AdfMark:
    attrs = AdfBackgroundColorAttrs(color=BACKGROUND_COLOR[tone])
    return AdfBackgroundColor(type="backgroundColor", attrs=attrs)


def _script_mark(position: ScriptPosition) -> AdfMark:
    kind = AdfSubsupAttrs(type="sub" if position == "subscript" else "sup")
    return AdfSubsup(type="subsup", attrs=kind)


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


def with_mark(nodes: AdfInlineNodes, mark: AdfMark) -> AdfInlineNodes:
    return tuple(_marked(node, mark) for node in nodes)


def _retexted(node: AdfText, text: str) -> AdfText:
    retexted = AdfText(type="text", text=text)
    if "marks" in node:
        retexted["marks"] = node["marks"]
    return retexted


def _merged(nodes: Sequence[AdfInline]) -> AdfInlineNodes:
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


def _date_node(day: date) -> AdfDate:
    midnight_utc = datetime(day.year, day.month, day.day, tzinfo=UTC)
    return AdfDate(type="date", attrs=AdfDateAttrs(timestamp=str(int(midnight_utc.timestamp()) * 1000)))


def _shows_nothing(nodes: AdfInlineNodes) -> bool:
    return all(node["type"] == "text" and not node["text"].strip() for node in nodes)


def _text_of(nodes: AdfInlineNodes) -> str:
    return "".join(node["text"] for node in nodes if node["type"] == "text")


def _status(text: str, color: LozengeColor) -> AdfInlineNodes:
    if not text:
        return ()
    return (AdfStatus(type="status", attrs=AdfStatusAttrs(text=text, color=color)),)


def _lozenge(mark: Mark) -> AdfInlineNodes | None:
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

    def write(self, runs: ExportRich) -> AdfInlineNodes:
        return write_export_runs(runs, self)

    def concat(self, parts: Sequence[AdfInlineNodes], /) -> AdfInlineNodes:
        return _merged([node for part in parts for node in part])

    def text(self, text: str, /) -> AdfInlineNodes:
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

    def code(self, text: str, /) -> AdfInlineNodes:
        if not text:
            return ()
        return (AdfText(type="text", text=text, marks=[AdfCode(type="code")]),)

    def link(self, label: AdfInlineNodes, url: str, /) -> AdfInlineNodes:
        if not url.startswith(ALLOWED_URL_SCHEMES):
            return label
        mark = AdfLink(type="link", attrs=AdfLinkAttrs(href=url))
        return with_mark(tuple(map(_as_text_in_a_link, label)), mark)

    def anchor_link(self, _label: AdfInlineNodes, _anchor: str, /) -> AdfInlineNodes:
        raise ExportInvariantError(
            "a Jira description cannot link to its own headings; the export check should have refused it"
        )

    def section_link(self, label: AdfInlineNodes, _anchor: str, /) -> AdfInlineNodes:
        return label

    def date_mention(self, label: AdfInlineNodes, start: date, end: date | None, /) -> AdfInlineNodes:
        dates = (
            (_date_node(start),) if end is None else (_date_node(start), _plain_text(" to "), _date_node(end))
        )
        if _shows_nothing(label):
            return dates
        return (*label, _plain_text(" "), *dates)

    def person_mention(self, label: AdfInlineNodes, _key: str, person: Person, /) -> AdfInlineNodes:
        if person.jira is None:
            return label
        attrs = AdfMentionAttrs(id=person.jira, text="@" + _text_of(label))
        return (AdfMention(type="mention", attrs=attrs),)

    def issue_link(self, label: AdfInlineNodes, _key: str, url: str | None, /) -> AdfInlineNodes:
        if url is None:
            return label
        return (AdfInlineCard(type="inlineCard", attrs=AdfInlineCardAttrs(url=url)),)

    def document_link(self, _label: AdfInlineNodes, _doc_id: str, _section: str | None, /) -> AdfInlineNodes:
        raise ExportInvariantError(
            "a Jira description cannot link to another skaldr document; "
            "the export check should have refused it"
        )

    def citation(self, run: Citation, /) -> AdfInlineNodes:
        label = (_plain_text(f"[{run.number}]"),)
        linked = self.link(label, run.url) if run.url else label
        return with_mark(linked, _script_mark("superscript"))

    def placeholder(self, name: str, /) -> AdfInlineNodes:
        return with_mark((_plain_text("{{" + name + "}}"),), background_color_mark(PLACEHOLDER_TONE))

    def styled(self, style: StyleName, inner: AdfInlineNodes, /) -> AdfInlineNodes:
        return with_mark(inner, _style_mark(style))

    def script(self, position: ScriptPosition, text: str, /) -> AdfInlineNodes:
        if not text:
            return ()
        return with_mark((_plain_text(text),), _script_mark(position))

    def tinted(
        self, tone: ToneLiteral | None, background: ToneLiteral | None, inner: AdfInlineNodes, /
    ) -> AdfInlineNodes:
        coloured = inner if tone is None else with_mark(inner, text_color_mark(tone))
        return coloured if background is None else with_mark(coloured, background_color_mark(background))

    def toned_label(self, tone: ToneLiteral, inner: AdfInlineNodes, /) -> AdfInlineNodes:
        return with_mark(inner, text_color_mark(tone))

    def math(self, expression: str, /) -> AdfInlineNodes:
        require_the_swap("inline math", "adf")
        return self.code(expression)

    def chip(self, run: Chip, /) -> AdfInlineNodes:
        return _status(run.label, BADGE_LOZENGE[run.tone])

    def line_break(self) -> AdfInlineNodes:
        return (AdfHardBreak(type="hardBreak"),)

    def mark(self, run: Mark, /) -> AdfInlineNodes:
        lozenge = _lozenge(run)
        return lozenge if lozenge is not None else (_plain_text(mark_glyph(run)),)

    def gauge(self, run: Gauge, /) -> AdfInlineNodes:
        return (_plain_text(gauge_bar(run.value, run.maximum)),)
