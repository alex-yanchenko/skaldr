from collections.abc import Callable, Mapping

import pytest

from skaldr.export_targets import ExportTarget
from tests.factories import (
    EDGE_BADGES,
    HAVE_BADGE,
    MATRIX_OF_EDGE_BADGE_LABELS,
    MATRIX_OF_EVERY_CELL_SHAPE,
    markdown_of,
    notion_of,
    slack_of,
)

WRITERS: Mapping[ExportTarget, Callable[..., str]] = {
    "markdown": markdown_of,
    "notion": notion_of,
    "slack": slack_of,
}

ESCAPED_LEADING_MARKER = {
    "- not a list": "\\- not a list\n",
    "# not a heading": "\\# not a heading\n",
    "1. not a list": "1\\. not a list\n",
}
ESCAPED_BY_MARKDOWN_AND_NOTION = {
    "--- not a rule": "\\--- not a rule\n",
    "2024. was the year": "2024\\. was the year\n",
    "123456789. x": "123456789\\. x\n",
}

PARAGRAPH_CASES = [
    pytest.param(body, target, expected, id=f"{target}-{body}")
    for target in WRITERS
    for body, expected in {
        **ESCAPED_LEADING_MARKER,
        **(ESCAPED_BY_MARKDOWN_AND_NOTION if target != "slack" else {}),
    }.items()
]


@pytest.mark.parametrize(("body", "target", "expected"), PARAGRAPH_CASES)
def test_a_paragraph_that_starts_like_a_block_marker_stays_a_paragraph(
    body: str, target: ExportTarget, expected: str
) -> None:
    assert WRITERS[target]([{"type": "text", "body": body}]) == expected


MATRIX_WITH_A_BADGE_AND_A_LABEL: Mapping[ExportTarget, str] = {
    "markdown": (
        "|  | Badge | Both | Tone | Label |\n"
        "| --- | --- | --- | --- | --- |\n"
        "| **Receiving** | 🟢 Have | 🟢 **Have** · runbook v2 | 🔴 none yet | n/a |\n"
    ),
    "notion": (
        '<table fit-page-width="true" header-row="true" header-column="true">\n'
        "\t<tr>\n\t\t<td></td>\n\t\t<td>**Badge**</td>\n\t\t<td>**Both**</td>\n\t\t<td>**Tone**</td>\n"
        "\t\t<td>**Label**</td>\n\t</tr>\n"
        "\t<tr>\n\t\t<td>**Receiving**</td>\n"
        '\t\t<td color="green_bg">Have</td>\n'
        '\t\t<td color="green_bg">**Have** · runbook v2</td>\n'
        '\t\t<td color="red_bg">none yet</td>\n'
        "\t\t<td>n/a</td>\n\t</tr>\n"
        "</table>\n"
    ),
    "slack": (
        "|  | Badge | Both | Tone | Label |\n"
        "| --- | --- | --- | --- | --- |\n"
        "| **Receiving** | 🟢 Have | 🟢 **Have** · runbook v2 | 🔴 none yet | n/a |\n"
    ),
}

MATRIX_WITH_BADGE_LABELS_THAT_ADD_NO_STATE: Mapping[ExportTarget, str] = {
    "markdown": (
        "|  | Blank | Spaces | Same | Special |\n"
        "| --- | --- | --- | --- | --- |\n"
        "| **Receiving** | 🔴 lbl | 🟡 lbl | 🟢 Have | 🔵 **A\\|B \\*x\\*** · a\\_b \\[c\\] \\<d\\> \\| e |\n"
    ),
    "notion": (
        '<table fit-page-width="true" header-row="true" header-column="true">\n'
        "\t<tr>\n\t\t<td></td>\n\t\t<td>**Blank**</td>\n\t\t<td>**Spaces**</td>\n\t\t<td>**Same**</td>\n"
        "\t\t<td>**Special**</td>\n\t</tr>\n"
        "\t<tr>\n\t\t<td>**Receiving**</td>\n"
        '\t\t<td color="red_bg">lbl</td>\n'
        '\t\t<td color="yellow_bg">lbl</td>\n'
        '\t\t<td color="green_bg">Have</td>\n'
        '\t\t<td color="blue_bg">**A\\|B \\*x\\*** · a\\_b \\[c\\] \\<d\\> \\| e</td>\n'
        "\t</tr>\n"
        "</table>\n"
    ),
    "slack": (
        "|  | Blank | Spaces | Same | Special |\n"
        "| --- | --- | --- | --- | --- |\n"
        "| **Receiving** | 🔴 lbl | 🟡 lbl | 🟢 Have | 🔵 **A\\|B \\*x\\*** · a\\_b \\[c\\] \\<d\\> \\| e |\n"
    ),
}


DECISION_LIST_PAGES: Mapping[ExportTarget, str] = {
    "markdown": "- ❓ open\n- ☑️ done\n",
    "notion": "- ❓ open\n- ☑️ done\n",
}


@pytest.mark.parametrize("target", DECISION_LIST_PAGES)
def test_a_decision_list_is_a_bullet_list_led_by_decided_and_open_glyphs(target: ExportTarget) -> None:
    block = {"type": "list", "style": "decision", "items": ["open", {"text": "done", "decided": True}]}

    assert WRITERS[target]([block]) == DECISION_LIST_PAGES[target]


NESTED_DECISION_LIST_PAGES: Mapping[ExportTarget, str] = {
    "markdown": "- ☑️ region\n  - ❓ failover\n  - ☑️ zone\n\n* [x] shipped\n* [ ] tested\n\n- ✅ rolled out\n",
    "notion": (
        "- ☑️ region\n\t- ❓ failover\n\t- ☑️ zone\n- [x] shipped\n- [ ] tested\n"
        '- <span color="green">✓</span> rolled out\n'
    ),
}


@pytest.mark.parametrize("target", NESTED_DECISION_LIST_PAGES)
def test_a_nested_decision_list_marks_every_level_and_reads_apart_from_a_check_list(
    target: ExportTarget,
) -> None:
    blocks = [
        {
            "type": "list",
            "style": "decision",
            "items": [
                {"text": "region", "decided": True, "items": ["failover", {"text": "zone", "decided": True}]}
            ],
        },
        {"type": "list", "style": "check", "items": [{"text": "shipped", "checked": True}, "tested"]},
        {"type": "status_list", "items": [{"state": "done", "text": "rolled out"}]},
    ]

    assert WRITERS[target](blocks) == NESTED_DECISION_LIST_PAGES[target]


@pytest.mark.parametrize("target", WRITERS)
def test_a_matrix_cell_with_a_badge_and_a_label_shows_the_badge_name_in_bold_then_the_label(
    target: ExportTarget,
) -> None:
    page = WRITERS[target]([MATRIX_OF_EVERY_CELL_SHAPE], badges=HAVE_BADGE)

    assert page == MATRIX_WITH_A_BADGE_AND_A_LABEL[target]


@pytest.mark.parametrize("target", WRITERS)
def test_a_matrix_cell_names_no_state_the_badge_label_does_not_add_and_escapes_the_ones_it_does(
    target: ExportTarget,
) -> None:
    page = WRITERS[target]([MATRIX_OF_EDGE_BADGE_LABELS], badges=EDGE_BADGES)

    assert page == MATRIX_WITH_BADGE_LABELS_THAT_ADD_NO_STATE[target]
