from typing import Any

from tests.factories import make_tab, make_tabs


def in_a_tab(block: dict[str, Any]) -> dict[str, Any]:
    return make_tabs(make_tab("Floor", block), make_tab("System"))


def make_rollup_table(tid: str, *, rollup: bool = True) -> dict[str, object]:
    table: dict[str, object] = {
        "type": "table",
        "id": tid,
        "columns": [
            {"key": "item", "label": "Item", "kind": "text"},
            {"key": "st", "label": "", "kind": "badge"},
        ],
        "rows": [{"item": "a", "st": "HAVE"}],
    }
    if rollup:
        table["rollup"] = {"by": "st"}
    return table


def make_matrix(cells: list[dict[str, object]], **overrides: object) -> dict[str, object]:
    block: dict[str, object] = {
        "type": "matrix",
        "rows": ["r1", "r2"],
        "columns": ["c1", "c2"],
        "cells": cells,
    }
    block.update(overrides)
    return block
