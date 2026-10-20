import json
from pathlib import Path
from uuid import UUID

from pydantic import TypeAdapter, ValidationError

from skaldr.auth import CaughtWithoutChaining
from skaldr.auth.store import state_directory
from skaldr.errors import AuthError
from skaldr.replace_file import replace_file

TEMPLATE_FILE_NAME = "notion-templates.json"
_TEMPLATES_SHAPE = TypeAdapter(dict[str, str])


def template_file() -> Path:
    return state_directory() / TEMPLATE_FILE_NAME


def notion_templates() -> dict[str, str]:
    path = template_file()
    try:
        stored = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError as exc:
        raise AuthError(_unreadable(path)) from exc
    with CaughtWithoutChaining(ValidationError):
        return _TEMPLATES_SHAPE.validate_json(stored)
    raise AuthError(_unreadable(path))


def notion_template_for(workspace_id: UUID | None) -> str | None:
    if workspace_id is None:
        return None
    return notion_templates().get(str(workspace_id))


def save_notion_template(workspace_id: UUID, page_id: str) -> None:
    _write({**notion_templates(), str(workspace_id): page_id})


def clear_notion_template(workspace_id: UUID) -> bool:
    templates = notion_templates()
    if str(workspace_id) not in templates:
        return False
    del templates[str(workspace_id)]
    _write(templates)
    return True


def _write(templates: dict[str, str]) -> None:
    path = template_file()
    try:
        replace_file(path, json.dumps(templates, indent=2, sort_keys=True) + "\n")
    except OSError as exc:
        raise AuthError(
            f"skaldr cannot write the file {path} that holds the Notion page templates ({exc})"
        ) from exc


def _unreadable(path: Path) -> str:
    return (
        f"The file {path} that holds the Notion page templates is unreadable; fix it or remove it, then set "
        "the template again with `skaldr auth template notion <link>`"
    )
