from pathlib import Path
from typing import Any, TypeVar, get_args

import yaml

from skaldr.export.budget import RenderedBlock
from skaldr.export.lower import lower_report
from skaldr.export.markdown import render_markdown
from skaldr.export.notion import render_notion
from skaldr.export.tree import Node
from skaldr.models import AnyBlock, AuthoredBlock, parse_report
from tests.factories.report_factory import make_index_report, make_report

BlockT = TypeVar("BlockT", bound=AnyBlock)

API_BADGES: dict[str, Any] = {"API": {"label": "api", "tone": "blue", "legend": "the API"}}
BADGE_AND_STATE_BLOCKS: list[dict[str, Any]] = [
    {
        "type": "fact_strip",
        "facts": [{"label": "Site", "value": "West"}, {"label": "Owner:", "value": "ops"}],
    },
    {"type": "key_value", "pairs": [{"label": "Lead", "value": "**Ana**"}]},
    {
        "type": "def_list",
        "items": [{"term": "Drift", "body": "first\n\nsecond"}, {"term": "Gap", "body": " "}],
    },
    {
        "type": "cards",
        "items": [
            {
                "label": "Clean",
                "value": 9,
                "of": 10,
                "tone": "success",
                "delta": {"label": "+1", "direction": "up", "tone": "success"},
                "badges": ["API"],
                "note": "since Monday",
            },
            {"label": "Lag", "value": "3 days", "delta": {"label": "flat", "direction": "flat"}},
        ],
    },
    {"type": "badge_row", "label": "Affects", "items": [{"key": "API"}, {"label": "ops", "tone": "teal"}]},
    {"type": "badge_row", "groups": [{"label": "Owners", "items": [{"label": "web", "tone": "violet"}]}]},
    {
        "type": "status_list",
        "items": [{"state": "done", "text": "Ship"}, {"state": "blocked", "text": "Vendor"}],
    },
    {
        "type": "timeline",
        "items": [
            {"time": "Mon", "title": "Start", "state": "current", "badges": ["API"], "body": "kick-off"},
            {"title": "Later"},
        ],
    },
    {"type": "meter", "items": [{"label": "Zone", "value": 3, "max": 7, "tone": "warning"}]},
    {
        "type": "range",
        "axis": {"min": "Jan", "max": "Dec"},
        "segments": [
            {"label": "Q1", "span": 1, "tone": "danger", "sub": "slow"},
            {"label": "Rest", "span": 3},
        ],
    },
]


def authored_block_types() -> set[str]:
    return {get_args(model.model_fields["type"].annotation)[0] for model in get_args(AuthoredBlock)}


def parsed_block(kind: type[BlockT], block: dict[str, Any], **overrides: Any) -> BlockT:
    parsed = parse_report(make_report(blocks=[block], **overrides)).blocks[0]
    if not isinstance(parsed, kind):
        raise TypeError(f"expected a {kind.__name__} block, got {type(parsed).__name__}")
    return parsed


def lowered(blocks: list[dict[str, Any]], **overrides: Any) -> tuple[Node, ...]:
    return lower_report(parse_report(make_report(blocks=blocks, **overrides))).body


def rendered_block_count(block: RenderedBlock) -> int:
    return 1 if block.lines else 0


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


def folder_texts(folder: Path) -> dict[str, str]:
    return {path.name: path.read_text(encoding="utf-8") for path in sorted(folder.iterdir())}


def write_report(directory: Path, data: dict[str, Any], name: str = "doc.yaml") -> Path:
    path = directory / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return path


def write_index_document(directory: Path, parts: dict[str, dict[str, Any]], **overrides: Any) -> Path:
    for name, part in parts.items():
        write_report(directory, part, name)
    return write_report(directory, make_index_report(list(parts), **overrides), "index.yaml")
