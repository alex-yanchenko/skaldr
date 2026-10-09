import difflib
import json
from collections.abc import Sequence

from pydantic import JsonValue

from skaldr.publish.content import Part
from skaldr.publish.drafts import item_label, section_label
from skaldr.publish.engine import ItemStatus, PublishDiff, RemoteEdit, YamlChange
from skaldr.publish.plan import ItemRef

NO_VISIBLE_CHANGE = "(the service reports an edit here, and its text is unchanged)"


def _part_label(item: ItemRef, part: Part, path: str | None) -> str:
    named = section_label(part.key, path) if part.kind == "section" else part.label
    return f"{item.label}: {named}"


def _lines(text: str | None) -> list[str]:
    return [] if text is None else text.splitlines()


def _unified(
    header: str, before: str | None, after: str | None, before_name: str, after_name: str
) -> list[str]:
    body = list(
        difflib.unified_diff(
            _lines(before), _lines(after), f"{header}, {before_name}", f"{header}, {after_name}", lineterm=""
        )
    )
    return body or [f"--- {header}, {before_name}", f"+++ {header}, {after_name}", NO_VISIBLE_CHANGE]


def _edited_by(edit: RemoteEdit) -> str:
    who = f", edited by {edit.edited_by}" if edit.edited_by else ""
    when = f" at {edit.edited_at}" if edit.edited_at else ""
    return f"now{who}{when}"


def remote_edit_lines(edits: Sequence[RemoteEdit]) -> list[str]:
    return [
        line
        for edit in edits
        for line in _unified(
            _part_label(edit.item, edit.part, edit.path),
            edit.published,
            edit.current,
            "as published",
            _edited_by(edit),
        )
    ]


def _yaml_change_lines(changes: Sequence[YamlChange]) -> list[str]:
    return [
        line
        for change in changes
        for line in _unified(
            _part_label(change.item, change.part, change.path),
            change.published,
            change.next,
            "as published",
            "in the YAML",
        )
    ]


def diff_lines(diff: PublishDiff) -> list[str]:
    remote = (
        ["Remote edits since the last publish:", *remote_edit_lines(diff.remote_edits)]
        if diff.remote_edits
        else ["Remote edits since the last publish: none"]
    )
    missing = (
        [
            "Missing remotely:",
            *(f"{missing.item.label} ({missing.item_id})" for missing in diff.missing_remotely),
        ]
        if diff.missing_remotely
        else []
    )
    yaml = (
        ["What this YAML would change:", *_yaml_change_lines(diff.yaml_changes)]
        if diff.yaml_changes
        else ["What this YAML would change: nothing"]
    )
    return [*remote, *missing, *yaml]


def _located(item: ItemRef, part: Part, path: str | None) -> dict[str, JsonValue]:
    return {
        "target": item.target,
        "item": item_label(item.section_id),
        "part": part.kind,
        "section": part.key if part.kind == "section" else None,
        "yaml_path": path,
    }


def diff_json(diff: PublishDiff) -> str:
    payload: dict[str, JsonValue] = {
        "remote_edits": [
            {
                **_located(edit.item, edit.part, edit.path),
                "published": edit.published,
                "current": edit.current,
                "edited_by": edit.edited_by,
                "edited_at": edit.edited_at,
            }
            for edit in diff.remote_edits
        ],
        "yaml_changes": [
            {
                **_located(change.item, change.part, change.path),
                "published": change.published,
                "next": change.next,
            }
            for change in diff.yaml_changes
        ],
        "missing_remotely": [
            {
                "target": missing.item.target,
                "item": item_label(missing.item.section_id),
                "item_id": missing.item_id,
            }
            for missing in diff.missing_remotely
        ],
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


def status_line(status: ItemStatus) -> str:
    held = "" if status.item_id is None else f" ({status.item_id})"
    return f"{status.item.label}{held}: {', '.join(status.states)}"
