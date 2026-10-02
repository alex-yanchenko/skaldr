from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Final, Literal, get_args

from pydantic import StringConstraints, ValidationError

from skaldr.export.lower import lower_report
from skaldr.export.markdown import render_markdown_document
from skaldr.export.notion import chunk_notion, render_notion
from skaldr.frozen_model import FrozenModel
from skaldr.models import Report
from skaldr.replace_file import replace_file

__all__ = [
    "EXPORT_MANIFEST",
    "EXPORT_TARGETS",
    "ExportResult",
    "ExportTarget",
    "export_markdown",
    "export_notion",
]

ExportTarget = Literal["notion", "markdown"]
EXPORT_TARGETS: Final[tuple[ExportTarget, ...]] = get_args(ExportTarget)
EXPORT_MANIFEST: Final = ".skaldr-export.json"
ExportedPageName = Annotated[str, StringConstraints(pattern=r"^page(?:\.[0-9]{2,})?\.md$")]


class ExportManifest(FrozenModel):
    title: str
    files: tuple[ExportedPageName, ...]


@dataclass(frozen=True)
class ExportResult:
    title: str
    files: tuple[Path, ...]
    oversized_sections: tuple[str, ...] = ()
    unreadable_manifest: bool = False


@dataclass(frozen=True)
class _EarlierExport:
    pages: frozenset[str]
    unreadable_manifest: bool = False


def _earlier_export(manifest_path: Path) -> _EarlierExport:
    try:
        manifest = ExportManifest.model_validate_json(manifest_path.read_bytes())
    except FileNotFoundError:
        return _EarlierExport(frozenset())
    except (OSError, ValidationError):
        return _EarlierExport(frozenset(), unreadable_manifest=True)
    return _EarlierExport(frozenset(manifest.files))


def _write_manifest(out_dir: Path, title: str, names: Collection[str]) -> None:
    manifest = ExportManifest(title=title, files=tuple(sorted(names)))
    replace_file(out_dir / EXPORT_MANIFEST, manifest.model_dump_json(indent=2) + "\n")


def _export_pages(
    out_dir: Path, title: str, pages: Mapping[str, str], oversized_sections: tuple[str, ...] = ()
) -> ExportResult:
    out_dir.mkdir(parents=True, exist_ok=True)
    earlier = _earlier_export(out_dir / EXPORT_MANIFEST)
    _write_manifest(out_dir, title, earlier.pages | set(pages))
    written: list[Path] = []
    for name, text in pages.items():
        path = out_dir / name
        replace_file(path, text)
        written.append(path)
    for stale in sorted(earlier.pages - set(pages)):
        path = out_dir / stale
        if path.is_file():
            path.unlink()
    _write_manifest(out_dir, title, pages)
    return ExportResult(title, tuple(written), oversized_sections, earlier.unreadable_manifest)


def _chunk_pages(chunks: Sequence[str]) -> dict[str, str]:
    width = max(2, len(str(len(chunks) - 1)))
    return {f"page.{index:0{width}d}.md": text for index, text in enumerate(chunks)}


def export_notion(report: Report, out_dir: Path, *, chunk: int | None = None) -> ExportResult:
    document = lower_report(report)
    if chunk is None:
        return _export_pages(out_dir, document.title, {"page.md": render_notion(document.body)})
    split = chunk_notion(document.body, chunk)
    return _export_pages(out_dir, document.title, _chunk_pages(split.chunks), split.oversized_sections)


def export_markdown(report: Report, out_dir: Path) -> ExportResult:
    document = lower_report(report)
    return _export_pages(out_dir, document.title, {"page.md": render_markdown_document(document)})
