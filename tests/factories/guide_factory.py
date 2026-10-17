import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from markdown_it import MarkdownIt

from skaldr.export.capabilities import CAPABILITIES, Capability, Feature, Rejection
from skaldr.export_targets import ExportTarget
from skaldr.replace_file import replace_file
from tests.conftest import REPO_ROOT

CapabilityTable = Mapping[Feature, Mapping[ExportTarget, Capability]]

GUIDE_FILE: Final = REPO_ROOT / "src" / "skaldr" / "skill" / "GUIDE.md"
GUIDE_REWRITE_VARIABLE: Final = "SKALDR_WRITE_GUIDE"
GUIDE_REWRITE_COMMAND: Final = f"{GUIDE_REWRITE_VARIABLE}=1 uv run pytest tests/test_guide_refusals.py"
REFUSAL_LEAD_INS: Final[Mapping[ExportTarget, str]] = {
    "markdown": "The GitHub-flavored export refuses:",
    "notion": "The Notion export refuses:",
    "adf": "The ADF export refuses:",
    "slack": "The canvas export refuses:",
}
EXPORT_TABLE_COLUMNS: Final[Mapping[str, ExportTarget]] = {
    "GitHub-flavored": "markdown",
    "Notion": "notion",
    "ADF": "adf",
    "Canvas Markdown": "slack",
}
SAYS_REFUSED: Final = re.compile(r"refus|fails? the export", re.IGNORECASE)


class RefusalLeadInError(ValueError):
    pass


class GuideTableRowError(ValueError):
    pass


@dataclass(frozen=True)
class RefusingCell:
    target: ExportTarget
    row: str
    text: str


def _bold_names(features: Sequence[Feature]) -> str:
    names = [f"**{feature}**" for feature in features]
    if len(names) == 1:
        return names[0]
    return f"{', '.join(names[:-1])} and {names[-1]}"


def refusal_list(target: ExportTarget, capabilities: CapabilityTable = CAPABILITIES) -> str:
    features_by_sentence: dict[str, list[Feature]] = {}
    for feature, cells in capabilities.items():
        if isinstance(capability := cells[target], Rejection):
            features_by_sentence.setdefault(capability.in_the_guide, []).append(feature)
    return "\n".join(
        f"- {_bold_names(features)}: {sentence}." for sentence, features in features_by_sentence.items()
    )


def guide_with_refusal_lists(guide: str, capabilities: CapabilityTable = CAPABILITIES) -> str:
    for target, lead_in in REFUSAL_LEAD_INS.items():
        list_under_lead_in = re.compile(rf"^{re.escape(lead_in)}\n\n(?:- [^\n]*\n)+", re.MULTILINE)
        found = list(list_under_lead_in.finditer(guide))
        if len(found) != 1:
            raise RefusalLeadInError(f"GUIDE.md holds a list under '{lead_in}' {len(found)} times, not once")
        rewritten = f"{lead_in}\n\n{refusal_list(target, capabilities)}\n"
        guide = guide[: found[0].start()] + rewritten + guide[found[0].end() :]
    return guide


def rewrite_guide_when_requested(guide_file: Path, generated: str) -> None:
    if os.environ.get(GUIDE_REWRITE_VARIABLE) != "1":
        return
    if guide_file.read_text(encoding="utf-8") == generated:
        return
    replace_file(guide_file, generated)


def guide_sync_failure(on_disk: str, generated: str) -> str | None:
    if on_disk == generated:
        return None
    return (
        "src/skaldr/skill/GUIDE.md differs from the refusal lists the capability table generates; "
        f"rewrite it with: {GUIDE_REWRITE_COMMAND}"
    )


def _guide_tables(guide: str) -> list[list[list[str]]]:
    tables: list[list[list[str]]] = []
    inside_a_table = False
    for token in MarkdownIt().enable("table").parse(guide):
        if token.type == "table_open":
            inside_a_table = True
            tables.append([])
        elif token.type == "table_close":
            inside_a_table = False
        elif inside_a_table and token.type == "tr_open":
            tables[-1].append([])
        elif inside_a_table and token.type == "inline":
            tables[-1][-1].append(token.content)
    return tables


def refusing_cells_in(guide: str) -> list[RefusingCell]:
    cells: list[RefusingCell] = []
    for header, *rows in _guide_tables(guide):
        columns = header[1:]
        if header[0] != "Block" or not columns or not set(columns) <= set(EXPORT_TABLE_COLUMNS):
            continue
        for row, *prose in rows:
            for column, cell in zip(columns, prose, strict=True):
                if not cell:
                    raise GuideTableRowError(
                        f"the table headed '{' | '.join(header)}' in GUIDE.md has an empty "
                        f"'{column}' cell in the row '{row}'"
                    )
                if SAYS_REFUSED.search(cell):
                    cells.append(RefusingCell(EXPORT_TABLE_COLUMNS[column], row, cell))
    return cells


def refusing_cells() -> list[RefusingCell]:
    return refusing_cells_in(GUIDE_FILE.read_text(encoding="utf-8"))


def features_the_table_does_not_refuse(
    target: ExportTarget, features: tuple[Feature, ...], capabilities: CapabilityTable = CAPABILITIES
) -> tuple[Feature, ...]:
    return tuple(feature for feature in features if not isinstance(capabilities[feature][target], Rejection))
