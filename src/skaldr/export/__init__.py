import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast, get_args

from skaldr.export.lower import lower_report
from skaldr.export.markdown import render_markdown_document
from skaldr.export.notion import chunk_notion, render_notion
from skaldr.models import Report

ExportTarget = Literal["notion", "markdown"]
EXPORT_TARGETS: tuple[ExportTarget, ...] = get_args(ExportTarget)
EXPORT_MANIFEST = ".skaldr-export.json"


@dataclass(frozen=True)
class ExportResult:
    title: str
    files: tuple[Path, ...]
    oversized_sections: tuple[str, ...] = ()


def _previously_written(out_dir: Path) -> set[str]:
    try:
        recorded: object = json.loads((out_dir / EXPORT_MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    files = cast("dict[str, object]", recorded).get("files") if isinstance(recorded, dict) else None
    if not isinstance(files, list):
        return set()
    names = cast("list[object]", files)
    return {name for name in names if isinstance(name, str) and Path(name).name == name}


def _write_pages(out_dir: Path, pages: Mapping[str, str]) -> tuple[Path, ...]:
    out_dir.mkdir(parents=True, exist_ok=True)
    earlier = _previously_written(out_dir)
    written: list[Path] = []
    for name, text in pages.items():
        path = out_dir / name
        path.write_text(text, encoding="utf-8")
        written.append(path)
    for stale in sorted(earlier - set(pages)):
        path = out_dir / stale
        if path.is_file():
            path.unlink()
    manifest = json.dumps({"files": sorted(pages)}, indent=2) + "\n"
    (out_dir / EXPORT_MANIFEST).write_text(manifest, encoding="utf-8")
    return tuple(written)


def export_notion(report: Report, out_dir: Path, *, chunk: int | None = None) -> ExportResult:
    document = lower_report(report)
    if chunk is None:
        return ExportResult(document.title, _write_pages(out_dir, {"page.md": render_notion(document.body)}))
    split = chunk_notion(document.body, chunk)
    pages = {f"page.{index:02d}.md": text for index, text in enumerate(split.chunks)}
    return ExportResult(document.title, _write_pages(out_dir, pages), split.oversized_sections)


def export_markdown(report: Report, out_dir: Path) -> ExportResult:
    document = lower_report(report)
    return ExportResult(
        document.title, _write_pages(out_dir, {"page.md": render_markdown_document(document)})
    )
