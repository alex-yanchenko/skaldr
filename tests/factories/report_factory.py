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


def make_grid(cells: list[dict[str, Any]]) -> dict[str, Any]:
    return {"type": "grid", "cells": cells}


def make_cell(span: Any, blocks: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {"span": span, "blocks": blocks if blocks is not None else [{"type": "text", "body": "x"}]}


def make_table(columns: list[dict[str, Any]], **overrides: Any) -> dict[str, Any]:
    return {"type": "table", "columns": columns, **overrides}


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
