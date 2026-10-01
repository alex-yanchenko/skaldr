from dataclasses import dataclass
from pathlib import Path
from typing import Literal, get_args

from skaldr.export.lower import lower_report
from skaldr.export.markdown import render_markdown_document
from skaldr.models import Report

ExportTarget = Literal["markdown"]
EXPORT_TARGETS: tuple[ExportTarget, ...] = get_args(ExportTarget)


@dataclass(frozen=True)
class ExportResult:
    title: str
    files: tuple[Path, ...]


def export_markdown(report: Report, out_dir: Path) -> ExportResult:
    document = lower_report(report)
    out_dir.mkdir(parents=True, exist_ok=True)
    page = out_dir / "page.md"
    page.write_text(render_markdown_document(document), encoding="utf-8")
    return ExportResult(document.title, (page,))
