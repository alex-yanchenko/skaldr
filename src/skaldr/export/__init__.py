from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from skaldr.export.inline import plain
from skaldr.export.lower import lower_report
from skaldr.export.markdown import render_markdown
from skaldr.export.notion import chunk_notion, render_notion
from skaldr.export.tree import Heading
from skaldr.models import Report

ExportTarget = Literal["notion", "markdown"]
EXPORT_TARGETS: tuple[ExportTarget, ...] = ("notion", "markdown")


@dataclass(frozen=True)
class ExportResult:
    files: tuple[Path, ...]
    oversized_sections: tuple[str, ...] = ()


def _write_pages(out_dir: Path, names: Sequence[str], pages: Sequence[str]) -> tuple[Path, ...]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name, text in zip(names, pages, strict=True):
        path = out_dir / name
        path.write_text(text, encoding="utf-8")
        written.append(path)
    return tuple(written)


def export_notion(report: Report, out_dir: Path, *, chunk: int | None) -> ExportResult:
    nodes = lower_report(report)
    if chunk is None:
        return ExportResult(_write_pages(out_dir, ["page.md"], [render_notion(nodes)]))
    split = chunk_notion(nodes, chunk)
    names = [f"page.{index:02d}.md" for index in range(len(split.chunks))]
    return ExportResult(_write_pages(out_dir, names, split.chunks), split.oversized)


def export_markdown(report: Report, out_dir: Path) -> ExportResult:
    nodes = (Heading(1, plain(report.meta.title)), *lower_report(report))
    return ExportResult(_write_pages(out_dir, ["page.md"], [render_markdown(nodes)]))
