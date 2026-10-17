from collections import Counter
from collections.abc import Mapping
from typing import get_args

import pytest

from skaldr.export.capabilities import CAPABILITIES, Capability, Feature, Rejection, Swap
from skaldr.export_targets import EXPORT_TARGETS, ExportTarget
from tests.factories.guide_factory import (
    GUIDE_FILE,
    GUIDE_REWRITE_COMMAND,
    GUIDE_REWRITE_VARIABLE,
    REFUSAL_LEAD_INS,
    RefusalLeadInError,
    features_the_table_does_not_refuse,
    guide_sync_failure,
    guide_text_to_check,
    guide_with_refusal_lists,
    refusal_list,
    refusing_cells,
    refusing_cells_matching,
)

FEATURES: tuple[Feature, ...] = get_args(Feature)
GITHUB_NESTED_SPANS_ROW = "a colour span inside a colour span, or a highlight inside a highlight"
CANVAS_TABLE_ROW = "`table`, `comparison`, `matrix`, `swimlane`"
COLOUR_OR_HIGHLIGHT_NESTED_ROW = "a highlight inside a colour or a colour inside a highlight"

PROSE_CELLS_THAT_REFUSE: dict[tuple[ExportTarget, str], tuple[Feature, ...]] = {
    ("notion", "a decimal `number` list's `start`"): ("numbered list starting past 1",),
    ("markdown", "`[text]{tone=…}`"): ("colour span",),
    ("markdown", "`[text]{tone=… bg=…}`"): ("colour and highlight span",),
    ("notion", "`[text]{tone=… bg=…}`"): ("colour and highlight span",),
    ("markdown", GITHUB_NESTED_SPANS_ROW): ("colour span",),
    ("markdown", COLOUR_OR_HIGHLIGHT_NESTED_ROW): ("colour and highlight span",),
    ("notion", COLOUR_OR_HIGHLIGHT_NESTED_ROW): ("colour and highlight span",),
    ("notion", "`[the plan](doc:onboarding-plan#st2)`"): (
        "link to another skaldr document",
        "link to a heading of the same document",
    ),
    ("notion", "an inline `` `code` `` span holding a closing tag"): (
        "inline code holding a backtick",
        "inline code holding a closing tag in a table cell",
        "inline code holding a closing tag in a coloured, highlighted or underlined span",
    ),
    ("adf", "a list"): ("list numbered with letters or roman numerals",),
    ("adf", "`link` card or embed"): (
        "quote inside a callout",
        "table, callout, heading, quote, toggle or divider inside a list item or walkthrough step",
    ),
    ("adf", "`[text](doc:id)`"): (
        "link to another skaldr document",
        "link to a heading of the same document",
    ),
    ("adf", "a same-page `[…](#id)` link"): ("link to a heading of the same document",),
    ("slack", "`heading`"): ("heading deeper than a canvas holds",),
    ("slack", "a list"): (
        "block inside a list item",
        "numbered list starting past 1",
        "list numbered with letters or roman numerals",
    ),
    ("slack", "`callout`, `note`, `panel`"): (
        "table inside a callout",
        "callout inside a callout",
        "toggle inside a callout",
        "divider inside a callout",
    ),
    ("slack", "`quote`"): ("list inside a quote",),
    ("slack", "`divider`"): (
        "divider inside a callout",
        "divider inside a grid cell",
        "block inside a walkthrough step",
    ),
    ("slack", "`grid`"): (
        "grid with more than three cells",
        "toned grid cell",
        "table inside a grid cell",
        "callout inside a grid cell",
        "divider inside a grid cell",
        "grid inside a grid cell",
    ),
    ("slack", "`++underline++`, `[text]{tone=…}`, `[text]{bg=…}`"): (
        "underline",
        "colour span",
        "highlight span",
        "colour and highlight span",
    ),
    ("slack", "`H~2~O`, `10^3^`"): ("subscript or superscript with no Unicode form",),
    ("slack", "a same-page `[…](#id)` link"): ("link to a heading of the same document",),
    ("slack", "`[the plan](doc:…)`"): ("link to another skaldr document",),
}
PROSE_CELLS_THAT_SAY_REFUSES_WITHOUT_REFUSING_A_FEATURE: frozenset[tuple[ExportTarget, str]] = frozenset(
    {("slack", CANVAS_TABLE_ROW)}
)


def _rejecting(why: str, in_the_guide: str) -> Rejection:
    return Rejection(why, "instead", in_the_guide=in_the_guide)


SMALL_TABLE: Mapping[Feature, Mapping[ExportTarget, Capability]] = {
    "range": {
        "markdown": _rejecting("a", "this export cannot draw a range bar; use a `meter` or a `table`"),
        "notion": "keep",
        "adf": _rejecting("b", "this export cannot draw a range bar; use a `meter` or a `table`"),
        "slack": "keep",
    },
    "chart": {
        "markdown": "keep",
        "notion": "keep",
        "adf": Swap("its data table"),
        "slack": _rejecting("c", "a canvas draws no chart"),
    },
    "underline": {
        "markdown": "keep",
        "notion": _rejecting("e", "Notion has no underline here"),
        "adf": "keep",
        "slack": _rejecting("d", "a canvas has no underline"),
    },
}

STALE_LISTS_GUIDE = """\
Intro.

The GitHub-flavored export refuses:

- old

Between.

The Notion export refuses:

- old
- older

Between again.

The ADF export refuses:

- old

Another.

The canvas export refuses:

- old

Outro.
"""

FRESH_LISTS_GUIDE = """\
Intro.

The GitHub-flavored export refuses:

- range: this export cannot draw a range bar; use a `meter` or a `table`.

Between.

The Notion export refuses:

- underline: Notion has no underline here.

Between again.

The ADF export refuses:

- range: this export cannot draw a range bar; use a `meter` or a `table`.

Another.

The canvas export refuses:

- chart: a canvas draws no chart.
- underline: a canvas has no underline.

Outro.
"""


def test_each_target_has_its_own_lead_in_for_its_refusal_list() -> None:
    assert REFUSAL_LEAD_INS == {
        "markdown": "The GitHub-flavored export refuses:",
        "notion": "The Notion export refuses:",
        "adf": "The ADF export refuses:",
        "slack": "The canvas export refuses:",
    }


@pytest.mark.parametrize(
    ("target", "expected"),
    [
        pytest.param(
            "markdown",
            "- range: this export cannot draw a range bar; use a `meter` or a `table`.",
            id="markdown",
        ),
        pytest.param("notion", "- underline: Notion has no underline here.", id="notion"),
        pytest.param(
            "adf",
            "- range: this export cannot draw a range bar; use a `meter` or a `table`.",
            id="adf-skips-a-swap",
        ),
        pytest.param(
            "slack",
            "- chart: a canvas draws no chart.\n- underline: a canvas has no underline.",
            id="slack-in-table-order",
        ),
    ],
)
def test_a_refusal_list_has_one_line_per_rejection_of_its_target_in_table_order(
    target: ExportTarget, expected: str
) -> None:
    assert refusal_list(target, SMALL_TABLE) == expected


def test_the_refusal_lists_of_a_guide_are_rewritten_from_the_table() -> None:
    assert guide_with_refusal_lists(STALE_LISTS_GUIDE, SMALL_TABLE) == FRESH_LISTS_GUIDE


def test_rewriting_the_refusal_lists_twice_changes_nothing_more() -> None:
    once = guide_with_refusal_lists(STALE_LISTS_GUIDE, SMALL_TABLE)

    assert guide_with_refusal_lists(once, SMALL_TABLE) == once


@pytest.mark.parametrize(
    ("guide", "lead_in", "times"),
    [
        pytest.param(
            STALE_LISTS_GUIDE.replace("The ADF export refuses:\n\n- old\n", ""),
            "The ADF export refuses:",
            0,
            id="lead-in-removed",
        ),
        pytest.param(
            STALE_LISTS_GUIDE.replace("The ADF export refuses:\n\n- old\n", "The ADF export refuses:\n"),
            "The ADF export refuses:",
            0,
            id="list-removed",
        ),
        pytest.param(
            STALE_LISTS_GUIDE + "\nThe ADF export refuses:\n\n- again\n",
            "The ADF export refuses:",
            2,
            id="lead-in-twice",
        ),
    ],
)
def test_a_guide_that_does_not_hold_each_refusal_list_once_is_refused(
    guide: str, lead_in: str, times: int
) -> None:
    with pytest.raises(RefusalLeadInError) as raised:
        guide_with_refusal_lists(guide, SMALL_TABLE)

    assert str(raised.value) == f"GUIDE.md holds a list under '{lead_in}' {times} times, not once"


def test_a_guide_that_matches_what_the_table_generates_has_no_sync_failure() -> None:
    assert guide_sync_failure(FRESH_LISTS_GUIDE, FRESH_LISTS_GUIDE) is None


def test_a_guide_that_differs_from_what_the_table_generates_fails_naming_the_command_that_rewrites_it() -> (
    None
):
    assert guide_sync_failure(STALE_LISTS_GUIDE, FRESH_LISTS_GUIDE) == (
        "src/skaldr/skill/GUIDE.md differs from the refusal lists the capability table generates; "
        f"rewrite it with: {GUIDE_REWRITE_COMMAND}"
    )


def test_the_command_that_rewrites_the_guide_sets_the_variable_the_check_reads() -> None:
    assert f"{GUIDE_REWRITE_VARIABLE}=1 uv run pytest tests/test_guide_refusals.py" == GUIDE_REWRITE_COMMAND


def test_the_guide_is_checked_unchanged_while_its_variable_is_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(GUIDE_REWRITE_VARIABLE, raising=False)
    before = GUIDE_FILE.read_text(encoding="utf-8")

    assert guide_text_to_check(before, "something else") == before
    assert GUIDE_FILE.read_text(encoding="utf-8") == before


def test_the_guide_holds_the_refusal_lists_the_capability_table_generates() -> None:
    on_disk = GUIDE_FILE.read_text(encoding="utf-8")
    generated = guide_with_refusal_lists(on_disk, CAPABILITIES)

    failure = guide_sync_failure(guide_text_to_check(on_disk, generated), generated)

    assert failure is None


def _rejections() -> list[tuple[Feature, ExportTarget, Rejection]]:
    return [
        (feature, target, capability)
        for feature in FEATURES
        for target, capability in CAPABILITIES[feature].items()
        if isinstance(capability, Rejection)
    ]


def test_every_rejection_has_a_guide_sentence_without_placeholders_dashes_or_a_closing_period() -> None:
    offenders = [
        (feature, target, rejection.in_the_guide)
        for feature, target, rejection in _rejections()
        if not rejection.in_the_guide
        or any(mark in rejection.in_the_guide for mark in ("{", "}", "\N{EM DASH}", "\N{EN DASH}"))
        or rejection.in_the_guide.endswith(".")
    ]

    assert offenders == []


def test_each_target_lists_one_line_per_rejection_the_table_holds_for_it() -> None:
    lines_listed = {target: len(refusal_list(target).splitlines()) for target in EXPORT_TARGETS}
    rejections_held = {
        target: sum(1 for _, rejected, _ in _rejections() if rejected == target) for target in EXPORT_TARGETS
    }

    assert lines_listed == rejections_held


def test_every_prose_cell_that_says_refused_is_mapped_to_the_features_it_refuses() -> None:
    unmapped = [
        (cell.target, cell.row)
        for cell in refusing_cells()
        if not refusing_cells_matching(cell, PROSE_CELLS_THAT_REFUSE)
        and (cell.target, cell.row) not in PROSE_CELLS_THAT_SAY_REFUSES_WITHOUT_REFUSING_A_FEATURE
    ]

    assert unmapped == []


def test_every_mapped_prose_cell_is_found_once_in_the_guide() -> None:
    found = Counter(
        key for cell in refusing_cells() for key in refusing_cells_matching(cell, PROSE_CELLS_THAT_REFUSE)
    )

    assert found == dict.fromkeys(PROSE_CELLS_THAT_REFUSE, 1)


@pytest.mark.parametrize(
    ("target", "features"),
    [
        pytest.param(target, features, id=f"{target}-{row[:30]}")
        for (target, row), features in PROSE_CELLS_THAT_REFUSE.items()
    ],
)
def test_a_prose_cell_that_says_refused_names_only_features_the_table_refuses(
    target: ExportTarget, features: tuple[Feature, ...]
) -> None:
    assert features_the_table_does_not_refuse(target, features) == ()


def test_a_refusal_lifted_from_the_table_is_found_by_the_prose_cell_check() -> None:
    lifted: Mapping[Feature, Mapping[ExportTarget, Capability]] = {
        "colour span": dict.fromkeys(EXPORT_TARGETS, "keep")
    }

    assert features_the_table_does_not_refuse("markdown", ("colour span",), lifted) == ("colour span",)
