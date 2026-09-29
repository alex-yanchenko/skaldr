import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from skaldr.errors import ReportError

CREATED_PAGE_ID = "{{page_id_from_call_1}}"


class NotionTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page_id: str | None = Field(
        default=None,
        description="The Notion page this document publishes to. Once set, an export replaces that page's "
        "content; while unset, the export creates a page and asks for its id to be recorded here.",
    )
    parent_page_id: str | None = Field(
        default=None,
        description="Where a new page is created. Omit to create a private draft at the workspace level.",
    )


class PublishTargets(BaseModel):
    model_config = ConfigDict(extra="allow")

    notion: NotionTarget = Field(default_factory=NotionTarget)


def load_targets(path: Path | None) -> PublishTargets:
    if path is None:
        return PublishTargets()
    try:
        return PublishTargets.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except OSError as error:
        raise ReportError(f"could not read the targets file {path}: {error}") from error
    except json.JSONDecodeError as error:
        raise ReportError(f"the targets file {path} is not valid JSON: {error}") from error
    except ValidationError as error:
        raise ReportError(f"the targets file {path} has an unexpected shape: {error}") from error


@dataclass(frozen=True)
class McpCall:
    server: str
    tool: str
    arguments: dict[str, Any]
    content_file: str

    def as_json(self) -> dict[str, Any]:
        return {
            "server": self.server,
            "tool": self.tool,
            "content_file": self.content_file,
            "arguments": self.arguments,
        }


def _create_page_call(title: str, content: str, target: NotionTarget, content_file: str) -> McpCall:
    arguments: dict[str, Any] = {"pages": [{"properties": {"title": title}, "content": content}]}
    if target.parent_page_id:
        arguments["parent"] = {"type": "page_id", "page_id": target.parent_page_id}
    else:
        arguments["creation_mode"] = "draft"
    return McpCall("notion", "notion-create-pages", arguments, content_file)


def _replace_call(page_id: str, content: str, content_file: str) -> McpCall:
    arguments = {"page_id": page_id, "command": "replace_content", "new_str": content}
    return McpCall("notion", "notion-update-page", arguments, content_file)


def _append_call(page_id: str, content: str, content_file: str) -> McpCall:
    arguments = {
        "page_id": page_id,
        "command": "insert_content",
        "content": content,
        "position": {"type": "end"},
    }
    return McpCall("notion", "notion-update-page", arguments, content_file)


def notion_publish_plan(
    title: str,
    chunks: tuple[str, ...],
    files: tuple[str, ...],
    target: NotionTarget,
    targets_file: Path | None,
) -> dict[str, Any]:
    if target.page_id:
        page_id = target.page_id
        calls = [_replace_call(page_id, chunks[0], files[0])]
    else:
        page_id = CREATED_PAGE_ID
        calls = [_create_page_call(title, chunks[0], target, files[0])]
    calls += [_append_call(page_id, chunk, file) for chunk, file in zip(chunks[1:], files[1:], strict=True)]
    plan: dict[str, Any] = {
        "target": "notion",
        "title": title,
        "calls": [call.as_json() for call in calls],
    }
    if not target.page_id:
        plan["record"] = {
            "value": "the id of the page call 1 creates",
            "replaces": CREATED_PAGE_ID,
            "targets_file": str(targets_file) if targets_file else None,
            "key": "notion.page_id",
        }
    return plan
