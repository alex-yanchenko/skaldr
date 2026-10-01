from pathlib import Path
from typing import Any

import yaml

from skaldr.export.lower import lower_report
from skaldr.export.markdown import render_markdown
from skaldr.export.notion import render_notion
from skaldr.export.tree import Node
from skaldr.models import parse_report
from tests.factories.report_factory import make_report


def lowered(blocks: list[dict[str, Any]], **overrides: Any) -> tuple[Node, ...]:
    return lower_report(parse_report(make_report(blocks=blocks, **overrides))).body


def notion_of(blocks: list[dict[str, Any]], **overrides: Any) -> str:
    return render_notion(lowered(blocks, **overrides))


def markdown_of(blocks: list[dict[str, Any]], **overrides: Any) -> str:
    return render_markdown(lowered(blocks, **overrides))


def heading_sections(count: int, body: str) -> list[dict[str, Any]]:
    return [
        block
        for index in range(count)
        for block in ({"type": "heading", "text": f"Part {index}"}, {"type": "code", "content": body})
    ]


def write_report(directory: Path, data: dict[str, Any]) -> Path:
    path = directory / "doc.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return path
