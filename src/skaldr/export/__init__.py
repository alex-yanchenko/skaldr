import json
import re
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal, cast, get_args

from skaldr.export.lower import lower_report
from skaldr.export.markdown import render_markdown_document
from skaldr.export.notion import chunk_notion, render_notion
from skaldr.models import Report

__all__ = ["EXPORT_TARGETS", "ExportResult", "ExportTarget", "export_markdown", "export_notion"]

ExportTarget = Literal["notion", "markdown"]
EXPORT_TARGETS: Final[tuple[ExportTarget, ...]] = get_args(ExportTarget)
EXPORT_MANIFEST: Final = ".skaldr-export.json"
EXPORTED_PAGE_NAME: Final = re.compile(r"page(?:\.\d{2,})?\.md")


@dataclass(frozen=True)
class ExportResult:
    title: str
    files: tuple[Path, ...]
    oversized_sections: tuple[str, ...] = ()


def _previously_written(out_dir: Path) -> set[str]:
    try:
        recorded: object = json.loads((out_dir / EXPORT_MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError):
        return set()
    files = cast("dict[str, object]", recorded).get("files") if isinstance(recorded, dict) else None
    if not isinstance(files, list):
        return set()
    names = cast("list[object]", files)
    return {name for name in names if isinstance(name, str) and EXPORTED_PAGE_NAME.fullmatch(name)}


def _write_manifest(out_dir: Path, title: str, names: Collection[str]) -> None:
    manifest = json.dumps({"title": title, "files": sorted(names)}, indent=2, ensure_ascii=False) + "\n"
    (out_dir / EXPORT_MANIFEST).write_text(manifest, encoding="utf-8")


def _write_pages(out_dir: Path, title: str, pages: Mapping[str, str]) -> tuple[Path, ...]:
    out_dir.mkdir(parents=True, exist_ok=True)
    earlier = _previously_written(out_dir)
    _write_manifest(out_dir, title, earlier | set(pages))
    written: list[Path] = []
    for name, text in pages.items():
        path = out_dir / name
        path.write_text(text, encoding="utf-8")
        written.append(path)
    for stale in sorted(earlier - set(pages)):
        path = out_dir / stale
        if path.is_file():
            path.unlink()
    _write_manifest(out_dir, title, pages)
    return tuple(written)


def _chunk_pages(chunks: tuple[str, ...]) -> dict[str, str]:
    width = max(2, len(str(len(chunks) - 1)))
    return {f"page.{index:0{width}d}.md": text for index, text in enumerate(chunks)}


def export_notion(report: Report, out_dir: Path, *, chunk: int | None = None) -> ExportResult:
    document = lower_report(report)
    if chunk is None:
        pages = {"page.md": render_notion(document.body)}
        return ExportResult(document.title, _write_pages(out_dir, document.title, pages))
    split = chunk_notion(document.body, chunk)
    files = _write_pages(out_dir, document.title, _chunk_pages(split.chunks))
    return ExportResult(document.title, files, split.oversized_sections)


def export_markdown(report: Report, out_dir: Path) -> ExportResult:
    document = lower_report(report)
    pages = {"page.md": render_markdown_document(document)}
    return ExportResult(document.title, _write_pages(out_dir, document.title, pages))
