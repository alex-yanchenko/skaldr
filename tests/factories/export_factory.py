from collections.abc import Sequence
from pathlib import Path
from typing import Any, TypeVar, cast, get_args

import pytest
import yaml

from skaldr.errors import ExportRejectedError
from skaldr.export.budget import RenderedBlock
from skaldr.export.check import reject_what_the_target_cannot_show
from skaldr.export.lower import assemble_item_page, lower_regions, lower_report, lowering_for
from skaldr.export.markdown import render_markdown
from skaldr.export.notion import render_notion
from skaldr.export.runs import Chip
from skaldr.export.slack import render_slack
from skaldr.export.tree import (
    BlockRegion,
    ListEntry,
    ListNode,
    LoweredDocument,
    Node,
    Paragraph,
    TableCell,
    Toggle,
)
from skaldr.export_targets import ExportTarget
from skaldr.models import (
    BUILT_BY_AN_INDEX,
    AnyBlock,
    AuthoredBlock,
    Part,
    Report,
    Request,
    Text,
    parse_report,
)
from skaldr.richtext import Plain, Rich
from tests.factories.example_factory import EXAMPLE, example_for
from tests.factories.report_factory import make_index_report, make_report

REFUSED_IN_THE_EXAMPLE: dict[ExportTarget, list[str]] = {
    "markdown": ["range"],
    "notion": ["range", "image"],
    "adf": ["range", "flow", "image", "fan"],
    "slack": ["range", "flow", "image", "grid", "fan", "walkthrough"],
}

BlockT = TypeVar("BlockT", bound=AnyBlock)

API_BADGES: dict[str, Any] = {"API": {"label": "api", "tone": "blue", "legend": "the API"}}
API_AND_RISK_BADGES: dict[str, Any] = {
    **API_BADGES,
    "RISK": {"label": "risk", "tone": "red", "legend": False},
}
TEXT_X_BLOCK: dict[str, Any] = {"type": "text", "body": "x"}
HAVE_BADGE: dict[str, Any] = {"HAVE": {"label": "Have", "tone": "green", "legend": False}}
EDGE_BADGES: dict[str, Any] = {
    "BLANK": {"label": "", "tone": "red", "legend": False},
    "SPACES": {"label": "   ", "tone": "amber", "legend": False},
    "HAVE": HAVE_BADGE["HAVE"],
    "SPECIAL": {"label": "A|B *x*", "tone": "blue", "legend": False},
}
MATRIX_OF_EDGE_BADGE_LABELS: dict[str, Any] = {
    "type": "matrix",
    "rows": ["Receiving"],
    "columns": ["Blank", "Spaces", "Same", "Special"],
    "cells": [
        {"row": "Receiving", "col": "Blank", "badge": "BLANK", "label": "lbl"},
        {"row": "Receiving", "col": "Spaces", "badge": "SPACES", "label": "lbl"},
        {"row": "Receiving", "col": "Same", "badge": "HAVE", "label": " HAVE "},
        {"row": "Receiving", "col": "Special", "badge": "SPECIAL", "label": "a_b [c] <d> | e"},
    ],
}
MATRIX_OF_EVERY_CELL_SHAPE: dict[str, Any] = {
    "type": "matrix",
    "rows": ["Receiving"],
    "columns": ["Badge", "Both", "Tone", "Label"],
    "cells": [
        {"row": "Receiving", "col": "Badge", "badge": "HAVE"},
        {"row": "Receiving", "col": "Both", "badge": "HAVE", "label": "runbook v2"},
        {"row": "Receiving", "col": "Tone", "tone": "red", "label": "none yet"},
        {"row": "Receiving", "col": "Label", "label": "n/a"},
    ],
}
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
]


def make_rich_text(text: str) -> Rich:
    return (Plain(text),)


def make_paragraph(text: str) -> Paragraph:
    return Paragraph(make_rich_text(text))


def make_list_entry(text: str, *children: Node, checked: bool = False) -> ListEntry:
    return ListEntry(make_rich_text(text), checked, children)


def make_bullets(*entries: ListEntry | str) -> ListNode:
    return ListNode(
        "bullet", tuple(make_list_entry(entry) if isinstance(entry, str) else entry for entry in entries)
    )


def make_table_cell(text: str) -> TableCell:
    return TableCell(make_rich_text(text))


def authored_block_types() -> set[str]:
    return {get_args(model.model_fields["type"].annotation)[0] for model in get_args(AuthoredBlock)}


def parsed_block(kind: type[BlockT], block: dict[str, Any], **overrides: Any) -> BlockT:
    parsed = parse_report(make_report(blocks=[block], **overrides)).blocks[0]
    if not isinstance(parsed, kind):
        raise TypeError(f"expected a {kind.__name__} block, got {type(parsed).__name__}")
    return parsed


def parsed_request(block: dict[str, Any]) -> Request:
    return parsed_block(Request, block)


def dumped_text(body: str) -> dict[str, Any]:
    return Text(type="text", body=body).model_dump(mode="json")


def dumped_part(title: str, *bodies: str, collapsed: bool = False) -> dict[str, Any]:
    authored = {
        "type": "part",
        "title": title,
        "collapsed": collapsed,
        "blocks": [{"type": "text", "body": body} for body in bodies],
    }
    return Part.model_validate(authored, context={BUILT_BY_AN_INDEX: True}).model_dump(mode="json")


def lowered(blocks: list[dict[str, Any]], **overrides: Any) -> tuple[Node, ...]:
    return lower_report(parse_report(make_report(blocks=blocks, **overrides))).body


def rendered_block_count(block: RenderedBlock) -> int:
    return 1 if block.lines else 0


def notion_of(blocks: list[dict[str, Any]], **overrides: Any) -> str:
    return render_notion(lowered(blocks, **overrides))


def markdown_of(blocks: list[dict[str, Any]], **overrides: Any) -> str:
    return render_markdown(lowered(blocks, **overrides))


def check_nodes(nodes: Sequence[Node], target: ExportTarget) -> None:
    report = parse_report(make_report())
    page = LoweredDocument(report.meta.title, (BlockRegion(0, tuple(nodes)),))
    reject_what_the_target_cannot_show(report, page, target)


def _refuses(report: Report, page: LoweredDocument, target: ExportTarget) -> bool:
    try:
        reject_what_the_target_cannot_show(report, page, target)
    except ExportRejectedError:
        return True
    return False


def blocks_the_target_refuses(report: Report, target: ExportTarget) -> list[int]:
    lowering = lowering_for(report)
    return [
        region.source_index
        for region in lower_regions(lowering)
        if _refuses(
            report,
            assemble_item_page(report.meta.title, [region], lowering, opens_the_document=False),
            target,
        )
    ]


def accepted_by(data: dict[str, Any], target: ExportTarget) -> dict[str, Any]:
    refused = set(blocks_the_target_refuses(parse_report(data), target))
    return {**data, "blocks": [block for index, block in enumerate(data["blocks"]) if index not in refused]}


def read_yaml(path: Path) -> dict[str, Any]:
    return cast("dict[str, Any]", yaml.safe_load(path.read_text(encoding="utf-8")))


def example_data() -> dict[str, Any]:
    return read_yaml(EXAMPLE)


def accepted_example(target: ExportTarget, data: dict[str, Any] | None = None) -> Report:
    return parse_report(accepted_by(example_for(target) if data is None else data, target))


def refused_block_types(data: dict[str, Any], target: ExportTarget) -> list[str]:
    report = parse_report(data)
    return [report.blocks[index].type for index in blocks_the_target_refuses(report, target)]


def refusal_of(nodes: Sequence[Node], target: ExportTarget) -> ExportRejectedError:
    with pytest.raises(ExportRejectedError) as refused:
        check_nodes(nodes, target)
    return refused.value


def slack_of(blocks: list[dict[str, Any]], **overrides: Any) -> str:
    report = parse_report(make_report(blocks=blocks, **overrides))
    document = lower_report(report)
    reject_what_the_target_cannot_show(report, document, "slack")
    return render_slack(document.body)


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


API_LEGEND = Toggle(
    (Plain("Legend: badges used on this page"),),
    None,
    (ListNode("bullet", (ListEntry((Chip("api", "blue"), Plain(" "), Plain("the API"))),)),),
)


def cell_texts_of(*texts: str) -> tuple[TableCell, ...]:
    return tuple(TableCell((Plain(text),) if text else ()) for text in texts)
