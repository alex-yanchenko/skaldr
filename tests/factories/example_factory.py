import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

import yaml

from skaldr.export_targets import EXPORT_TARGETS, ExportTarget

_REPO_ROOT: Final = Path(__file__).resolve().parents[2]
EXAMPLE: Final = _REPO_ROOT / "data" / "example.yaml"
GOLDEN_FOLDER: Final = _REPO_ROOT / "tests" / "golden"
GOLDEN_REWRITE_VARIABLE_FOR: Final[Mapping[ExportTarget, str]] = {
    target: f"SKALDR_WRITE_{target.upper()}_GOLDEN" for target in EXPORT_TARGETS
}
COLOURED_SPAN: Final = "[behind schedule]{tone=danger}"
HIGHLIGHTED_SPAN: Final = "[due Friday]{bg=warning}"
COLOURED_AND_HIGHLIGHTED_SPAN: Final = "[vendor lots]{tone=accent bg=sky}"
UNDERLINED_TEXT: Final = "++check digit++"
DOCUMENT_LINK: Final = "[the cold room plan](doc:cold-room-plan#recount)"
ROMAN_LIST_FROM_4: Final = "    start: 4\n    numbering: roman\n"
EXAMPLE_CALLOUT_IN_A_STEP: Final = (
    '          - type: callout\n            tone: warning\n            body: "A residual gap'
)
EXAMPLE_TEXT_IN_A_STEP: Final = '          - type: text\n            body: "A residual gap'
EXAMPLE_EDITS_FOR: Final[Mapping[ExportTarget, tuple[tuple[str, str], ...]]] = {
    "markdown": (
        (COLOURED_SPAN, "behind schedule"),
        (COLOURED_AND_HIGHLIGHTED_SPAN, "vendor lots"),
    ),
    "notion": (
        (COLOURED_AND_HIGHLIGHTED_SPAN, "[vendor lots]{tone=accent}"),
        (DOCUMENT_LINK, "the cold room plan"),
    ),
    "adf": (
        (HIGHLIGHTED_SPAN, "due Friday"),
        (COLOURED_AND_HIGHLIGHTED_SPAN, "[vendor lots]{tone=accent}"),
        (ROMAN_LIST_FROM_4, "    start: 4\n"),
        (EXAMPLE_CALLOUT_IN_A_STEP, EXAMPLE_TEXT_IN_A_STEP),
        (DOCUMENT_LINK, "the cold room plan"),
    ),
    "slack": (
        (UNDERLINED_TEXT, "check digit"),
        (COLOURED_SPAN, "behind schedule"),
        (HIGHLIGHTED_SPAN, "due Friday"),
        (COLOURED_AND_HIGHLIGHTED_SPAN, "vendor lots"),
        (DOCUMENT_LINK, "the cold room plan"),
        (ROMAN_LIST_FROM_4, ""),
    ),
}
FIRST_REFUSAL_IN_DOCUMENT_ORDER_OF_THE_EXAMPLE: Final[Mapping[ExportTarget, str]] = {
    "markdown": "GitHub cannot draw a range bar, at blocks.4.range; use a meter or a table",
    "notion": "Notion cannot draw a range bar, at blocks.4.range; use a meter or a table",
    "adf": "ADF cannot draw a range bar, at blocks.4.range; use a meter or a table",
    "slack": "a Slack canvas cannot draw a range bar, at blocks.4.range; use a meter or a table",
}


def edited_once(text: str, written: str, accepted: str) -> str:
    occurrences = text.count(written)
    if occurrences != 1:
        raise ValueError(
            f"data/example.yaml holds {written!r} {occurrences} times, not once; update EXAMPLE_EDITS_FOR"
        )
    return text.replace(written, accepted)


def example_text_for(target: ExportTarget) -> str:
    text = EXAMPLE.read_text(encoding="utf-8")
    for written, accepted in EXAMPLE_EDITS_FOR[target]:
        text = edited_once(text, written, accepted)
    return text


def example_for(target: ExportTarget) -> dict[str, Any]:
    return yaml.safe_load(example_text_for(target))


def golden_of(target: ExportTarget) -> Path:
    return GOLDEN_FOLDER / f"example.{target}"


def golden_or_scratch_folder(target: ExportTarget, scratch: Path) -> Path:
    golden_rewrite_requested = bool(os.environ.get(GOLDEN_REWRITE_VARIABLE_FOR[target]))
    return golden_of(target) if golden_rewrite_requested else scratch
