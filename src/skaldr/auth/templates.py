import json
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar
from uuid import UUID

from filelock import FileLock, Timeout
from pydantic import TypeAdapter, ValidationError

from skaldr.auth import CaughtWithoutChaining, store
from skaldr.errors import AuthError
from skaldr.replace_file import replace_file

TEMPLATE_FILE_NAME = "notion-templates.json"
_TEMPLATES_SHAPE = TypeAdapter(dict[str, str])
Answer = TypeVar("Answer")


class UnreadableTemplatesError(AuthError):
    pass


def template_file() -> Path:
    return store.state_directory() / TEMPLATE_FILE_NAME


def notion_templates() -> dict[str, str]:
    path = template_file()
    try:
        stored = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError as exc:
        raise UnreadableTemplatesError(_unreadable(path)) from exc
    with CaughtWithoutChaining(ValidationError):
        return _TEMPLATES_SHAPE.validate_json(stored)
    raise UnreadableTemplatesError(_unreadable(path))


def notion_template_for(workspace_id: UUID | None) -> str | None:
    if workspace_id is None:
        return None
    return notion_templates().get(str(workspace_id))


def save_notion_template(workspace_id: UUID, page_id: str) -> None:
    def save() -> None:
        _write({**_templates_or_none(), str(workspace_id): page_id})

    _under_the_lock(save)


def clear_notion_template(workspace_id: UUID) -> bool:
    def clear() -> bool:
        try:
            templates = notion_templates()
            had_one = str(workspace_id) in templates
        except UnreadableTemplatesError:
            templates, had_one = {}, True
        if had_one:
            templates.pop(str(workspace_id), None)
            _write(templates)
        return had_one

    return _under_the_lock(clear)


def _templates_or_none() -> dict[str, str]:
    try:
        return notion_templates()
    except UnreadableTemplatesError:
        return {}


def _under_the_lock(change: Callable[[], Answer]) -> Answer:
    try:
        with FileLock(store.lock_file(), timeout=store.LOCK_TIMEOUT_SECONDS):
            return change()
    except Timeout as exc:
        raise AuthError(
            f"Another skaldr auth command has held the lock for {store.LOCK_TIMEOUT_SECONDS:g} seconds; "
            "run this again when it finishes"
        ) from exc


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
