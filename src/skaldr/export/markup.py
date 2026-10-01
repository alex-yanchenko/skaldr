import re
from collections.abc import Sequence
from typing import Literal

STYLE_MARKER: dict[Literal["bold", "italic", "strike"], str] = {"bold": "**", "italic": "*", "strike": "~~"}
CALLOUT_ICON: dict[str, str] = {
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
TAB_ICON: dict[str, str] = {"success": "✅", "info": "🔵", "warning": "⚠️", "danger": "🛑"}


def wrap_marker(marker: str, inner: str) -> str:
    core = inner.strip()
    if not core:
        return inner
    lead = inner[: len(inner) - len(inner.lstrip())]
    trail = inner[len(inner.rstrip()) :]
    return f"{lead}{marker}{core}{marker}{trail}"


def code_fence(content: str) -> str:
    longest = max((len(run) for run in re.findall(r"`+", content)), default=0)
    return "`" * max(3, longest + 1)


def indent_lines(lines: Sequence[str], prefix: str) -> list[str]:
    return [prefix + line if line else line for line in lines]
