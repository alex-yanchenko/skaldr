import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

import yaml

from skaldr.export_targets import ExportTarget
from tests.conftest import REPO_ROOT

EXAMPLE: Final = REPO_ROOT / "data" / "example.yaml"
GOLDEN_FOLDER: Final = REPO_ROOT / "tests" / "golden"
COLOURED_SPAN: Final = "[behind schedule]{tone=danger}"
HIGHLIGHTED_SPAN: Final = "[due Friday]{bg=warning}"
COLOURED_AND_HIGHLIGHTED_SPAN: Final = "[vendor lots]{tone=accent bg=sky}"
UNDERLINED_TEXT: Final = "++check digit++"
DOCUMENT_LINK: Final = "[the cold room plan](doc:cold-room-plan#recount)"
ROMAN_LIST_FROM_4: Final = "    start: 4\n    numbering: roman\n"
CALLOUT_IN_A_STEP: Final = (
    '          - type: callout\n            tone: warning\n            body: "A residual gap'
)
TEXT_IN_A_STEP: Final = '          - type: text\n            body: "A residual gap'
EXAMPLE_EDITS_FOR: Final[Mapping[ExportTarget, tuple[tuple[str, str], ...]]] = {
    "markdown": (
        (COLOURED_SPAN, "behind schedule"),
        (COLOURED_AND_HIGHLIGHTED_SPAN, "[vendor lots]{bg=sky}"),
    ),
    "notion": (
        (COLOURED_AND_HIGHLIGHTED_SPAN, "[vendor lots]{tone=accent}"),
        (DOCUMENT_LINK, "the cold room plan"),
    ),
    "adf": (
        (ROMAN_LIST_FROM_4, "    start: 4\n"),
        (CALLOUT_IN_A_STEP, TEXT_IN_A_STEP),
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


def example_text_for(target: ExportTarget) -> str:
    text = EXAMPLE.read_text(encoding="utf-8")
    for written, accepted in EXAMPLE_EDITS_FOR[target]:
        if written not in text:
            raise ValueError(f"data/example.yaml no longer holds {written!r}; update EXAMPLE_EDITS_FOR")
        text = text.replace(written, accepted)
    return text


def example_for(target: ExportTarget) -> dict[str, Any]:
    return yaml.safe_load(example_text_for(target))


def golden_of(target: ExportTarget) -> Path:
    return GOLDEN_FOLDER / f"example.{target}"


def golden_or_scratch_folder(target: ExportTarget, scratch: Path) -> Path:
    rewrites_the_golden = os.environ.get(f"SKALDR_WRITE_{target.upper()}_GOLDEN")
    return golden_of(target) if rewrites_the_golden else scratch
