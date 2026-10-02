import re
from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from typing import Final
from urllib.parse import quote

from typing_extensions import assert_never

from skaldr.export.runs import Chip, Gauge, Mark
from skaldr.export.tree import CodeBlock, ToneName
from skaldr.models import StatusState
from skaldr.richtext import Citation, StyleName

STYLE_MARKER: Final[Mapping[StyleName, str]] = {"bold": "**", "italic": "*", "strike": "~~"}
CALLOUT_ICON: Final[Mapping[ToneName, str]] = {
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
GAUGE_CELLS: Final = 10
BLOCK_START_MARKER = re.compile(r"^(#{1,6}|[-+]+|=+|>)(?=\s|$)")
ORDERED_START_MARKER = re.compile(r"^(\d{1,9})([.)])(?=\s|$)")
BACKTICK_RUN = re.compile(r"`+")
URL_SAFE_CHARACTERS: Final = "/:?#[]@!$&'*+,;=%~"


def _wrap_marker(marker: str, inner: str) -> str:
    core = inner.strip()
    if not core:
        return inner
    lead = inner[: len(inner) - len(inner.lstrip())]
    trail = inner[len(inner.rstrip()) :]
    return f"{lead}{marker}{core}{marker}{trail}"


def styled(style: StyleName, inner: str) -> str:
    return _wrap_marker(STYLE_MARKER[style], inner)


def _longest_backtick_run(text: str) -> int:
    return max((len(run) for run in BACKTICK_RUN.findall(text)), default=0)


def _commonmark_would_strip_a_space_from_each_end(text: str) -> bool:
    return text.startswith(" ") and text.endswith(" ") and bool(text.strip(" "))


def code_span(text: str) -> str:
    ticks = "`" * (_longest_backtick_run(text) + 1)
    needs_padding = (
        text.startswith("`") or text.endswith("`") or _commonmark_would_strip_a_space_from_each_end(text)
    )
    padding = " " if needs_padding else ""
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
    return quote(url, safe=URL_SAFE_CHARACTERS)


def gauge_bar(value: float, maximum: float) -> str:
    filled = max(0, min(GAUGE_CELLS, round(value / maximum * GAUGE_CELLS)))
    return "█" * filled + "░" * (GAUGE_CELLS - filled)


def status_glyph(state: StatusState) -> str:
    match state:
        case "done":
            return "✅"
        case "current":
            return "🔵"
        case "pending":
            return "⚪"
        case "failed":
            return "❌"
        case "blocked":
            return "⛔"
        case _:
            assert_never(state)


def indent_lines(lines: Sequence[str], prefix: str) -> list[str]:
    return [prefix + line if line else line for line in lines]


class MarkupRuns(ABC):
    @abstractmethod
    def escape(self, text: str, /) -> str: ...

    @abstractmethod
    def code(self, text: str, /) -> str: ...

    @abstractmethod
    def anchor_link(self, label: str, anchor: str, /) -> str: ...

    @abstractmethod
    def placeholder(self, name: str, /) -> str: ...

    @abstractmethod
    def chip(self, run: Chip, /) -> str: ...

    def text(self, text: str, /) -> str:
        return bang_cannot_open_an_image(self.escape(text))

    def link(self, label: str, url: str, /) -> str:
        return f"[{label}]({encode_url(url)})"

    def citation(self, run: Citation, /) -> str:
        label = self.escape(f"[{run.number}]")
        return f"[{label}]({encode_url(run.url)})" if run.url else label

    def styled(self, style: StyleName, inner: str, /) -> str:
        return styled(style, inner)

    def mark(self, run: Mark, /) -> str:
        return status_glyph(run.state)

    def gauge(self, run: Gauge, /) -> str:
        return gauge_bar(run.value, run.maximum)
