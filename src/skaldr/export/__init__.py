import os
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Final, assert_never

from pydantic import StringConstraints, ValidationError

from skaldr.errors import ReportError
from skaldr.export.adf import JIRA_DESCRIPTION_LIMIT, adf_json, compact_adf_length, render_adf_document
from skaldr.export.budget import character_budget
from skaldr.export.check import reject_what_the_target_cannot_show
from skaldr.export.data_images import data_image_files
from skaldr.export.glyphs import title_led_by_its_icon
from skaldr.export.lower import lower_report
from skaldr.export.markdown import render_markdown_document
from skaldr.export.notion import chunk_notion, render_notion
from skaldr.export.slack import canvas_title, render_slack_document
from skaldr.export.tree import LoweredDocument
from skaldr.export_targets import EXPORT_TARGETS, ExportTarget
from skaldr.frozen_model import FrozenModel
from skaldr.models import Report
from skaldr.replace_file import replace_bytes, replace_file

__all__ = [
    "EXPORT_MANIFEST",
    "EXPORT_TARGETS",
    "ExportResult",
    "ExportTarget",
    "RenderedExport",
    "export_adf",
    "export_markdown",
    "export_notion",
    "export_slack",
    "render_export",
]

EXPORT_MANIFEST: Final = ".skaldr-export.json"
MARKDOWN_PAGE_NAME: Final = "page.md"
ADF_PAGE_NAME: Final = "page.adf.json"
ExportedFileName = Annotated[
    str,
    StringConstraints(
        pattern=r"^(?:page(?:\.[0-9]{2,})?\.md|page\.adf\.json|image-[1-9][0-9]*\.(?:png|jpg|gif|webp|svg|avif|bmp))$"
    ),
]


class ExportManifest(FrozenModel):
    title: str
    files: tuple[ExportedFileName, ...]
    icon: str | None = None
    cover: str | None = None


@dataclass(frozen=True)
class PageChrome:
    icon: str | None = None
    cover: str | None = None


NO_PAGE_CHROME: Final = PageChrome()


@dataclass(frozen=True)
class ExportResult:
    title: str
    files: tuple[Path, ...]
    oversized_sections: tuple[str, ...] = ()
    unreadable_manifest: bool = False


@dataclass(frozen=True)
class RenderedExport:
    title: str
    pages: Mapping[str, str]
    oversized_sections: tuple[str, ...] = ()
    icon: str | None = None
    cover: str | None = None
    files: Mapping[str, bytes] = field(default_factory=dict[str, bytes])


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


def _write_manifest(out_dir: Path, title: str, names: Collection[str], chrome: PageChrome) -> None:
    manifest = ExportManifest(title=title, files=tuple(sorted(names)), icon=chrome.icon, cover=chrome.cover)
    replace_file(out_dir / EXPORT_MANIFEST, manifest.model_dump_json(indent=2, exclude_none=True) + "\n")


def _refusal(paths: Sequence[Path], what_they_are: str) -> ReportError:
    which, pronoun = ("which is", "it") if len(paths) == 1 else ("which are", "them")
    return ReportError(
        f"refusing to overwrite {', '.join(map(str, paths))}, {which} {what_they_are}; "
        f"move {pronoun} away or choose another --export-dir"
    )


def _is_folder(path: Path) -> bool:
    return path.is_dir() and not path.is_symlink()


def _is_taken_by_something_skaldr_did_not_write(path: Path, earlier: _EarlierExport) -> bool:
    return path.name not in earlier.pages and os.path.lexists(path)


def _refuse_to_overwrite_what_skaldr_did_not_write(
    out_dir: Path, names: Collection[str], earlier: _EarlierExport
) -> None:
    targets = [out_dir / name for name in sorted(names)]
    folders = [path for path in targets if _is_folder(path)]
    if folders:
        raise _refusal(folders, "a folder, not a page file")
    foreign = [path for path in targets if _is_taken_by_something_skaldr_did_not_write(path, earlier)]
    if not foreign:
        return
    reason = ", since that list could not be read" if earlier.unreadable_manifest else ""
    raise _refusal(foreign, f"not on the {EXPORT_MANIFEST} list of files skaldr wrote{reason}")


def _export_pages(
    out_dir: Path,
    title: str,
    pages: Mapping[str, str],
    oversized_sections: tuple[str, ...] = (),
    chrome: PageChrome = NO_PAGE_CHROME,
    image_files: Mapping[str, bytes] | None = None,
) -> ExportResult:
    images = image_files or {}
    names = [*images, *pages]
    out_dir.mkdir(parents=True, exist_ok=True)
    earlier = _earlier_export(out_dir / EXPORT_MANIFEST)
    _refuse_to_overwrite_what_skaldr_did_not_write(out_dir, names, earlier)
    written: list[Path] = []
    contents: Mapping[str, str | bytes] = {**images, **pages}
    for name, content in contents.items():
        path = out_dir / name
        if isinstance(content, bytes):
            replace_bytes(path, content)
        else:
            replace_file(path, content)
        written.append(path)
        _write_manifest(out_dir, title, earlier.pages | {page.name for page in written}, chrome)
    for stale in sorted(earlier.pages - set(names)):
        path = out_dir / stale
        if path.is_file():
            path.unlink()
    _write_manifest(out_dir, title, names, chrome)
    return ExportResult(title, tuple(written), oversized_sections, earlier.unreadable_manifest)


def _chunk_pages(chunks: Sequence[str]) -> dict[str, str]:
    width = max(2, len(str(len(chunks) - 1)))
    return {f"page.{index:0{width}d}.md": text for index, text in enumerate(chunks)}


def _checked_document(report: Report, target: ExportTarget) -> LoweredDocument:
    document = lower_report(report)
    reject_what_the_target_cannot_show(report, document, target)
    return document


def _adf_pages(document: LoweredDocument) -> RenderedExport:
    adf = render_adf_document(document)
    size = compact_adf_length(adf)
    over_the_limit = (
        (f"the ADF description is {size:,} characters, over Jira's limit of {JIRA_DESCRIPTION_LIMIT:,}",)
        if size > JIRA_DESCRIPTION_LIMIT
        else ()
    )
    title = title_led_by_its_icon(document.title, document.icon)
    return RenderedExport(title, {ADF_PAGE_NAME: adf_json(adf)}, over_the_limit)


def render_export(report: Report, target: ExportTarget) -> RenderedExport:
    document = _checked_document(report, target)
    match target:
        case "notion":
            page = render_notion(document.body, report.meta.notion_width)
            return RenderedExport(
                document.title, {MARKDOWN_PAGE_NAME: page}, icon=document.icon, cover=document.cover
            )
        case "markdown":
            images = data_image_files(document.body)
            page = render_markdown_document(document, {src: image.name for src, image in images.items()})
            return RenderedExport(
                document.title,
                {MARKDOWN_PAGE_NAME: page},
                files={image.name: image.content for image in images.values()},
            )
        case "adf":
            return _adf_pages(document)
        case "slack":
            return RenderedExport(
                canvas_title(document), {MARKDOWN_PAGE_NAME: render_slack_document(document)}
            )
        case _:
            assert_never(target)


def _write_rendered(out_dir: Path, rendered: RenderedExport) -> ExportResult:
    chrome = PageChrome(rendered.icon, rendered.cover)
    return _export_pages(
        out_dir, rendered.title, rendered.pages, rendered.oversized_sections, chrome, rendered.files
    )


def export_notion(report: Report, out_dir: Path, *, chunk: int | None = None) -> ExportResult:
    if chunk is None:
        return _write_rendered(out_dir, render_export(report, "notion"))
    document = _checked_document(report, "notion")
    split = chunk_notion(document.body, character_budget(chunk), report.meta.notion_width)
    chrome = PageChrome(document.icon, document.cover)
    return _export_pages(
        out_dir, document.title, _chunk_pages(split.chunks), split.oversized_sections, chrome
    )


def export_markdown(report: Report, out_dir: Path) -> ExportResult:
    return _write_rendered(out_dir, render_export(report, "markdown"))


def export_adf(report: Report, out_dir: Path) -> ExportResult:
    return _write_rendered(out_dir, render_export(report, "adf"))


def export_slack(report: Report, out_dir: Path) -> ExportResult:
    return _write_rendered(out_dir, render_export(report, "slack"))
