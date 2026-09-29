import json
from dataclasses import dataclass
from pathlib import Path

from skaldr.export.lower import lower_report
from skaldr.export.notion import chunk_notion, render_notion
from skaldr.export.publish import load_targets, notion_publish_plan
from skaldr.models import Report

EXPORT_TARGETS = ("notion",)


@dataclass(frozen=True)
class ExportResult:
    files: tuple[Path, ...]
    oversized_sections: tuple[str, ...]


def export_notion(
    report: Report, out_dir: Path, *, chunk: int | None, targets_file: Path | None
) -> ExportResult:
    targets = load_targets(targets_file)
    nodes = lower_report(report)
    if chunk is None:
        chunks: tuple[str, ...] = (render_notion(nodes),)
        oversized: tuple[str, ...] = ()
        names: tuple[str, ...] = ("page.md",)
    else:
        split = chunk_notion(nodes, chunk)
        chunks, oversized = split.chunks, split.oversized
        names = tuple(f"page.{index:02d}.md" for index in range(len(chunks)))
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name, text in zip(names, chunks, strict=True):
        path = out_dir / name
        path.write_text(text, encoding="utf-8")
        written.append(path)
    plan = notion_publish_plan(report.meta.title, chunks, names, targets.notion, targets_file)
    plan_path = out_dir / "publish.json"
    plan_path.write_text(json.dumps(plan, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    written.append(plan_path)
    return ExportResult(tuple(written), oversized)
