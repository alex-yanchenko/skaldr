"""Factories building raw (YAML-shaped) report payloads with sensible defaults + overrides."""

from typing import Any


def make_report(**overrides: Any) -> dict[str, Any]:
    report: dict[str, Any] = {
        "version": 1,
        "meta": {"title": "Test Report"},
        "blocks": [{"type": "text", "body": "Hello."}],
    }
    report.update(overrides)
    return report


NOTION_PAGE_URL = "https://www.notion.so/Team-Plans-0123456789abcdef0123456789abcdef"
NOTION_PAGE_ID = "0123456789abcdef0123456789abcdef"


def make_section(section_id: str, **overrides: Any) -> dict[str, Any]:
    return {
        "type": "section",
        "id": section_id,
        "title": section_id,
        "blocks": [{"type": "text", "body": "x"}],
        **overrides,
    }


def make_notion_target(**overrides: Any) -> dict[str, Any]:
    return {"to": "notion", "where": {"parent_page": NOTION_PAGE_URL}, **overrides}


def make_jira_target(**overrides: Any) -> dict[str, Any]:
    return {"to": "jira", "where": {"project": "PLAN", "issue_type": "Task"}, **overrides}


def make_publish_report(
    publish: dict[str, Any], section_ids: tuple[str, ...] = ("st1", "st2")
) -> dict[str, Any]:
    return make_report(
        publish=publish,
        blocks=[
            {"type": "text", "body": "Intro."},
            *(make_section(section_id) for section_id in section_ids),
        ],
    )


def make_grid(cells: list[dict[str, Any]]) -> dict[str, Any]:
    return {"type": "grid", "cells": cells}


def make_cell(span: Any, blocks: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {"span": span, "blocks": blocks if blocks is not None else [{"type": "text", "body": "x"}]}


def make_toggle(*blocks: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    return {
        "type": "toggle",
        "title": "More",
        "blocks": list(blocks) or [{"type": "text", "body": "x"}],
        **overrides,
    }


def make_tab(label: str, *blocks: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    return {"label": label, "blocks": list(blocks) or [{"type": "text", "body": label}], **overrides}


def make_tabs(*tabs: dict[str, Any]) -> dict[str, Any]:
    return {"type": "tabs", "tabs": list(tabs) or [make_tab("Floor"), make_tab("System")]}


def make_table(columns: list[dict[str, Any]], **overrides: Any) -> dict[str, Any]:
    return {"type": "table", "columns": columns, **overrides}


def make_label_table(kinds: list[str]) -> dict[str, Any]:
    columns: list[dict[str, Any]] = [{"key": "label", "label": "Label"}]
    columns += [{"key": f"c{index}", "label": f"C{index}", "kind": kind} for index, kind in enumerate(kinds)]
    row = {"label": "x"} | {f"c{index}": 1 if kind == "number" else "" for index, kind in enumerate(kinds)}
    return make_table(columns, rows=[row])


def make_swimlane(steps: list[dict[str, Any]], **overrides: Any) -> dict[str, Any]:
    return {
        "type": "swimlane",
        "lanes": list(dict.fromkeys(step["lane"] for step in steps)),
        "columns": list(dict.fromkeys(step["col"] for step in steps)),
        "steps": steps,
        **overrides,
    }


def make_request(**overrides: Any) -> dict[str, Any]:
    """A minimal valid `request`: one reader field the url uses, and one recorded case."""
    block: dict[str, Any] = {
        "type": "request",
        "label": "Read an endpoint",
        "method": "GET",
        "url": "https://{{host}}/widgets",
        "headers": {"Accept": "application/json"},
        "variables": [{"name": "host", "example": "api.example.com"}],
        "cases": [{"label": "one", "response": {"status": 200, "body": "[]"}}],
    }
    block.update(overrides)
    return block


def make_command_request(**overrides: Any) -> dict[str, Any]:
    """A minimal valid `request` that carries a verbatim command, with no reader field at all."""
    block: dict[str, Any] = {
        "type": "request",
        "label": "Tier mappings on the partner API",
        "command": "vault-run -- curl -s https://api.partner.example/v1/tiers | jq 'map({code, mapped})'",
        "cases": [{"label": "all tiers", "response": {"body": '[{"code": "STANDARD", "mapped": null}]'}}],
    }
    block.update(overrides)
    return block


def make_step(**overrides: Any) -> dict[str, Any]:
    """A minimal valid `request_flow` step. Captures nothing unless a caller asks for it."""
    step: dict[str, Any] = {
        "label": "A step",
        "method": "GET",
        "url": "https://{{host}}/a",
        "cases": [{"label": "one", "response": {"status": 200, "body": "{}"}}],
    }
    step.update(overrides)
    return step


def make_flow(**overrides: Any) -> dict[str, Any]:
    """A minimal valid `request_flow`: step one captures a token, step two spends it."""
    block: dict[str, Any] = {
        "type": "request_flow",
        "label": "Token, then read",
        "variables": [{"name": "host", "example": "api.example.com"}],
        "steps": [
            make_step(captures=[{"name": "token", "source": "body"}]),
            make_step(url="https://{{host}}/b", headers={"Authorization": "Bearer {{token}}"}),
        ],
    }
    block.update(overrides)
    return block


def make_reconciled_table(**overrides: Any) -> dict[str, Any]:
    table: dict[str, Any] = {
        "type": "table",
        "columns": [
            {"key": "issue", "label": "Issue", "kind": "text"},
            {"key": "count", "label": "Count", "kind": "number"},
        ],
        "reconcile": {"total": 100, "column": "count", "handled": {"label": "Clean", "value": 90}},
        "groups": [{"name": "Our side", "rows": [{"issue": "Dupes", "count": 10}]}],
    }
    table.update(overrides)
    return table
