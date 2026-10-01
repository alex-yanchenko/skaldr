import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, get_args

from skaldr.export.inline import plain
from skaldr.export.lower import lower_report
from skaldr.export.markdown import render_markdown
from skaldr.export.notion import chunk_notion, render_notion
from skaldr.export.tree import Heading
from skaldr.models import Report

ExportTarget = Literal["notion", "markdown"]
EXPORT_TARGETS: tuple[ExportTarget, ...] = get_args(ExportTarget)
EXPORTED_PAGE = re.compile(r"page(\.\d{2})?\.md")


@dataclass(frozen=True)
class ExportResult:
    files: tuple[Path, ...]
    oversized_sections: tuple[str, ...] = ()


def _write_pages(out_dir: Path, pages: Mapping[str, str]) -> tuple[Path, ...]:
    out_dir.mkdir(parents=True, exist_ok=True)
    for stale in out_dir.iterdir():
        if EXPORTED_PAGE.fullmatch(stale.name) and stale.name not in pages and stale.is_file():
            stale.unlink()
    written: list[Path] = []
    for name, text in pages.items():
        path = out_dir / name
        path.write_text(text, encoding="utf-8")
        written.append(path)
    return tuple(written)


def export_notion(report: Report, out_dir: Path, *, chunk: int | None) -> ExportResult:
    nodes = lower_report(report)
    if chunk is None:
        return ExportResult(_write_pages(out_dir, {"page.md": render_notion(nodes)}))
    split = chunk_notion(nodes, chunk)
    pages = {f"page.{index:02d}.md": text for index, text in enumerate(split.chunks)}
    return ExportResult(_write_pages(out_dir, pages), split.oversized_sections)


def export_markdown(report: Report, out_dir: Path) -> ExportResult:
    nodes = (Heading(1, plain(report.meta.title)), *lower_report(report))
    return ExportResult(_write_pages(out_dir, {"page.md": render_markdown(nodes)}))
