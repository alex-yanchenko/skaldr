import re
from collections.abc import Callable, Sequence
from typing import Literal

from skaldr.export.runs import Gauge, Mark, MarkScheme
from skaldr.export.tree import CodeBlock, ListKind, ListNode, Node, ToneName
from skaldr.richtext import Citation, StyleName

MarkerFamily = Literal["dash", "ordinal"]
MARKER_FAMILY: dict[ListKind, MarkerFamily] = {"bullet": "dash", "check": "dash", "number": "ordinal"}

STYLE_MARKER: dict[StyleName, str] = {"bold": "**", "italic": "*", "strike": "~~"}
CALLOUT_ICON: dict[ToneName, str] = {
    "info": "💡",
    "success": "✅",
    "warning": "⚠️",
    "danger": "🛑",
    "accent": "📌",
    "neutral": "📝",
    "muted": "📝",
    "teal": "💡",
    "sky": "💡",
}
MARK_GLYPH: dict[MarkScheme, dict[str, str]] = {
    "status": {"done": "✅", "current": "🔵", "pending": "⚪", "failed": "❌", "blocked": "⛔"},
    "timeline": {"done": "✅", "current": "🔵", "pending": "⚪"},
    "swimlane": {"done": "✅", "current": "🔵", "todo": "⚪", "blocked": "⛔", "deferred": "⏸️"},
    "indicator": {
        "success": "🟢",
        "warning": "🟡",
        "danger": "🔴",
        "info": "🔵",
        "neutral": "⚪",
        "accent": "🟣",
        "teal": "🟢",
        "sky": "🔵",
    },
    "check": {"yes": "✓", "no": "✗"},
}
GAUGE_CELLS = 10
BLOCK_START_MARKER = re.compile(r"^(#{1,6}|[-+]+|=+|>)(?=\s|$)")
ORDERED_START_MARKER = re.compile(r"^(\d{1,9})([.)])(?=\s|$)")
BACKTICK_RUN = re.compile(r"`+")
URL_UNSAFE = {" ": "%20", "(": "%28", ")": "%29", "<": "%3C", ">": "%3E", "\\": "\\\\"}


def _wrap_marker(marker: str, inner: str) -> str:
    core = inner.strip()
    if not core:
        return inner
    lead = inner[: len(inner) - len(inner.lstrip())]
    trail = inner[len(inner.rstrip()) :]
    return f"{lead}{marker}{core}{marker}{trail}"


def styled(style: StyleName, inner: str) -> str:
    return _wrap_marker(STYLE_MARKER[style], inner)


def bold_once(text: str) -> str:
    if text.startswith(STYLE_MARKER["bold"]):
        return text
    return styled("bold", text)


def _longest_backtick_run(text: str) -> int:
    return max((len(run) for run in BACKTICK_RUN.findall(text)), default=0)


def code_span(text: str) -> str:
    ticks = "`" * (_longest_backtick_run(text) + 1)
    padding = " " if text.startswith("`") or text.endswith("`") else ""
    return f"{ticks}{padding}{text}{padding}{ticks}"


def code_block_lines(block: CodeBlock) -> list[str]:
    fence = "`" * max(3, _longest_backtick_run(block.content) + 1)
    return [f"{fence}{block.language}", *block.content.split("\n"), fence]


def escape_block_start(text: str) -> str:
    text = BLOCK_START_MARKER.sub(lambda match: "\\" + match.group(1), text)
    return ORDERED_START_MARKER.sub(lambda match: match.group(1) + "\\" + match.group(2), text)


def bang_cannot_open_an_image(escaped_text: str) -> str:
    return escaped_text[:-1] + "\\!" if escaped_text.endswith("!") else escaped_text


def encode_url(url: str) -> str:
    return "".join(URL_UNSAFE.get(character, character) for character in url)


def gauge_bar(value: float, maximum: float) -> str:
    filled = max(0, min(GAUGE_CELLS, round(value / maximum * GAUGE_CELLS))) if maximum else 0
    return "█" * filled + "░" * (GAUGE_CELLS - filled)


def list_marker_family(node: Node) -> MarkerFamily | None:
    return MARKER_FAMILY[node.kind] if isinstance(node, ListNode) else None


def indent_lines(lines: Sequence[str], prefix: str) -> list[str]:
    return [prefix + line if line else line for line in lines]


class MarkupRuns:
    def __init__(self, escape: Callable[[str], str]) -> None:
        self.escape = escape

    def text(self, text: str, /) -> str:
        return bang_cannot_open_an_image(self.escape(text))

    def link(self, label: str, url: str, /) -> str:
        return f"[{label}]({encode_url(url)})"

    def citation(self, run: Citation, /) -> str:
        label = self.escape(f"[{run.number}]")
        return f"[{label}]({encode_url(run.url)})" if run.url else label

    def line_break(self) -> str:
        return "<br>"

    def styled(self, style: StyleName, inner: str, /) -> str:
        return styled(style, inner)

    def mark(self, run: Mark, /) -> str:
        return MARK_GLYPH[run.scheme][run.state]

    def gauge(self, run: Gauge, /) -> str:
        return gauge_bar(run.value, run.maximum)
