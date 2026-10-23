import re
from collections import Counter
from pathlib import Path
from typing import get_args

import pytest

import tests.factories.guide_factory as guide_factory
from skaldr.export.capabilities import CAPABILITIES, Feature, Rejection, Swap
from skaldr.export_targets import EXPORT_TARGETS, ExportTarget
from tests.factories.guide_factory import (
    EXPORT_TABLE_COLUMNS,
    GUIDE_FILE,
    GUIDE_REWRITE_COMMAND,
    GUIDE_REWRITE_VARIABLE,
    REFUSAL_LEAD_INS,
    CapabilityTable,
    GuideTableRowError,
    RefusalLeadInError,
    features_the_table_does_not_refuse,
    guide_sync_failure,
    guide_with_refusal_lists,
    refusal_list,
    refusing_cells,
    refusing_cells_in,
    rewrite_guide_when_requested,
)

FEATURES: tuple[Feature, ...] = get_args(Feature)
GITHUB_NESTED_SPANS_ROW = (
    "a colour span inside a colour span, or a highlight inside a highlight, "
    "such as `[a [b]{tone=info} c]{tone=danger}`"
)
COLOUR_OR_HIGHLIGHT_NESTED_ROW = (
    "a highlight inside a colour or a colour inside a highlight, nested either way, "
    "or a highlight in a toned walkthrough step's title"
)
NOTION_INLINE_CODE_ROW = (
    "an inline `` `code` `` span holding a closing tag (`</`) or a backtick, "
    "including a `code` block's `label`"
)
NOTION_CODE_LINE_ROW = (
    "a `code` block with a line that is only `</callout>`, `</details>`, `</column>` or `</tab>`, "
    "or only `<callout>`"
)
CANVAS_TABLE_ROW = "`table`, `comparison`, `matrix`, `swimlane`"

PROSE_CELLS_THAT_REFUSE: dict[tuple[ExportTarget, str], tuple[Feature, ...]] = {
    ("notion", "a decimal `number` list's `start`"): ("numbered list starting past 1",),
    ("notion", "`image` with a `data:` URI"): ("image from a data: URI",),
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
    ("notion", NOTION_INLINE_CODE_ROW): (
        "inline code holding a backtick",
        "inline code holding a closing tag in a table cell",
        "inline code holding a closing tag in a coloured, highlighted or underlined span",
    ),
    ("notion", NOTION_CODE_LINE_ROW): ("code line reading as a tag of the container around it",),
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


def _rejecting(in_the_guide: str) -> Rejection:
    return Rejection("why", "instead", in_the_guide=in_the_guide)


SAME_SLACK_SENTENCE = "a canvas draws none of it"
SMALL_TABLE: CapabilityTable = {
    "range": {
        "markdown": _rejecting("GitHub cannot draw a range bar; use a meter or a table"),
        "notion": "keep",
        "adf": _rejecting("ADF cannot draw a range bar; use a meter or a table"),
        "slack": "keep",
    },
    "chart": {
        "markdown": "keep",
        "notion": "keep",
        "adf": Swap("its data table"),
        "slack": _rejecting(SAME_SLACK_SENTENCE),
    },
    "highlight span": {
        "markdown": "keep",
        "notion": "keep",
        "adf": "keep",
        "slack": _rejecting("a canvas cannot highlight text"),
    },
    "underline": {
        "markdown": "keep",
        "notion": _rejecting("Notion has no underline here"),
        "adf": "keep",
        "slack": _rejecting(SAME_SLACK_SENTENCE),
    },
    "colour span": {
        "markdown": "keep",
        "notion": "keep",
        "adf": "keep",
        "slack": _rejecting(SAME_SLACK_SENTENCE),
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

- **range**: GitHub cannot draw a range bar; use a meter or a table.

Between.

The Notion export refuses:

- **underline**: Notion has no underline here.

Between again.

The ADF export refuses:

- **range**: ADF cannot draw a range bar; use a meter or a table.

Another.

The canvas export refuses:

- **chart**, **underline** and **colour span**: a canvas draws none of it.
- **highlight span**: a canvas cannot highlight text.

Outro.
"""

SHORT_ROW_GUIDE = """\
| Block | GitHub-flavored | Notion |
| --- | --- | --- |
| `a` | refused |
"""


def test_every_export_target_has_a_lead_in_for_its_refusal_list() -> None:
    assert set(REFUSAL_LEAD_INS) == set(EXPORT_TARGETS)


def test_every_export_target_has_a_column_in_the_export_tables_of_the_guide() -> None:
    assert set(EXPORT_TABLE_COLUMNS.values()) == set(EXPORT_TARGETS)


@pytest.mark.parametrize(
    ("target", "expected"),
    [
        pytest.param(
            "markdown", "- **range**: GitHub cannot draw a range bar; use a meter or a table.", id="one"
        ),
        pytest.param("notion", "- **underline**: Notion has no underline here.", id="notion"),
        pytest.param(
            "adf", "- **range**: ADF cannot draw a range bar; use a meter or a table.", id="swap-skipped"
        ),
        pytest.param(
            "slack",
            "- **chart**, **underline** and **colour span**: a canvas draws none of it.\n"
            "- **highlight span**: a canvas cannot highlight text.",
            id="same-sentence-grouped-at-its-first-feature",
        ),
    ],
)
def test_a_refusal_list_groups_the_features_sharing_a_sentence_in_table_order(
    target: ExportTarget, expected: str
) -> None:
    assert refusal_list(target, SMALL_TABLE) == expected


def test_two_features_sharing_a_sentence_are_joined_with_and() -> None:
    two: CapabilityTable = {
        "chart": {**dict.fromkeys(EXPORT_TARGETS, "keep"), "slack": _rejecting("same")},
        "underline": {**dict.fromkeys(EXPORT_TARGETS, "keep"), "slack": _rejecting("same")},
    }

    assert refusal_list("slack", two) == "- **chart** and **underline**: same."


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


def test_the_rewrite_command_sets_the_variable_that_rewrites_the_guide(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    guide = tmp_path / "GUIDE.md"
    guide.write_text(STALE_LISTS_GUIDE, encoding="utf-8")
    variable, value = GUIDE_REWRITE_COMMAND.split(" ", 1)[0].split("=")
    monkeypatch.setenv(variable, value)

    rewrite_guide_when_requested(guide, FRESH_LISTS_GUIDE)

    assert (variable, guide.read_text(encoding="utf-8")) == (GUIDE_REWRITE_VARIABLE, FRESH_LISTS_GUIDE)


@pytest.mark.parametrize("value", [pytest.param(None, id="unset"), "", "0", "true"])
def test_the_guide_is_left_alone_unless_the_variable_is_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, value: str | None
) -> None:
    guide = tmp_path / "GUIDE.md"
    guide.write_text(STALE_LISTS_GUIDE, encoding="utf-8")
    if value is None:
        monkeypatch.delenv(GUIDE_REWRITE_VARIABLE, raising=False)
    else:
        monkeypatch.setenv(GUIDE_REWRITE_VARIABLE, value)

    rewrite_guide_when_requested(guide, FRESH_LISTS_GUIDE)

    assert guide.read_text(encoding="utf-8") == STALE_LISTS_GUIDE


def test_a_guide_that_is_already_current_is_not_written_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    guide = tmp_path / "GUIDE.md"
    guide.write_text(FRESH_LISTS_GUIDE, encoding="utf-8")
    monkeypatch.setenv(GUIDE_REWRITE_VARIABLE, "1")
    writes: list[Path] = []

    def record_write(path: Path, _text: str) -> None:
        writes.append(path)

    monkeypatch.setattr(guide_factory, "replace_file", record_write)

    rewrite_guide_when_requested(guide, FRESH_LISTS_GUIDE)

    assert writes == []


def test_the_rewrite_leaves_only_the_guide_in_its_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    guide = tmp_path / "GUIDE.md"
    guide.write_text(STALE_LISTS_GUIDE, encoding="utf-8")
    monkeypatch.setenv(GUIDE_REWRITE_VARIABLE, "1")

    rewrite_guide_when_requested(guide, FRESH_LISTS_GUIDE)

    assert [path.name for path in tmp_path.iterdir()] == ["GUIDE.md"]


def test_the_guide_holds_the_refusal_lists_the_capability_table_generates() -> None:
    generated = guide_with_refusal_lists(GUIDE_FILE.read_text(encoding="utf-8"), CAPABILITIES)

    rewrite_guide_when_requested(GUIDE_FILE, generated)

    assert guide_sync_failure(GUIDE_FILE.read_text(encoding="utf-8"), generated) is None


def _rejections() -> list[tuple[Feature, ExportTarget, Rejection]]:
    return [
        (feature, target, capability)
        for feature in FEATURES
        for target, capability in CAPABILITIES[feature].items()
        if isinstance(capability, Rejection)
    ]


PLACEHOLDER = re.compile(r"\{\w+\}")
SPACED_DOUBLE_HYPHEN = " -- "
DASHES = ("\N{EM DASH}", "\N{EN DASH}", SPACED_DOUBLE_HYPHEN)


def _defects(sentence: str) -> list[str]:
    defects = [f"placeholder {found}" for found in PLACEHOLDER.findall(sentence)]
    defects += [f"dash {dash!r}" for dash in DASHES if dash in sentence]
    if not sentence:
        defects.append("empty")
    if sentence.endswith("."):
        defects.append("closing period")
    return defects


def test_every_rejection_has_a_guide_sentence_without_placeholders_dashes_or_a_closing_period() -> None:
    offenders = [
        (feature, target, _defects(rejection.in_the_guide))
        for feature, target, rejection in _rejections()
        if _defects(rejection.in_the_guide)
    ]

    assert offenders == []


@pytest.mark.parametrize(
    ("sentence", "defects"),
    [
        pytest.param("a {held} here", ["placeholder {held}"], id="placeholder"),
        pytest.param("a \N{EM DASH} b", [f"dash {chr(0x2014)!r}"], id="em-dash"),
        pytest.param("a \N{EN DASH} b", [f"dash {chr(0x2013)!r}"], id="en-dash"),
        pytest.param("a -- b", ["dash ' -- '"], id="spaced-double-hyphen"),
        pytest.param("", ["empty"], id="empty"),
        pytest.param("a b.", ["closing period"], id="closing-period"),
        pytest.param("a mapping like {} or { a: b } or a--b", [], id="braces-and-hyphens-that-are-fine"),
    ],
)
def test_the_guide_sentence_check_finds_each_defect(sentence: str, defects: list[str]) -> None:
    assert _defects(sentence) == defects


def test_each_target_names_in_its_list_exactly_the_features_the_table_rejects_for_it() -> None:
    named = {target: sorted(re.findall(r"\*\*(.+?)\*\*", refusal_list(target))) for target in EXPORT_TARGETS}
    rejected = {
        target: sorted(feature for feature, rejecting, _ in _rejections() if rejecting == target)
        for target in EXPORT_TARGETS
    }

    assert named == rejected


def test_every_export_refuses_a_range_and_every_one_but_github_refuses_an_image_from_a_data_uri() -> None:
    features: tuple[Feature, ...] = ("range", "image from a data: URI")

    not_refused = {target: features_the_table_does_not_refuse(target, features) for target in EXPORT_TARGETS}

    assert not_refused == {
        "markdown": ("image from a data: URI",),
        "notion": (),
        "adf": (),
        "slack": (),
    }


def test_every_prose_cell_that_says_refused_is_mapped_to_the_features_it_refuses() -> None:
    unmapped = [
        (cell.target, cell.row)
        for cell in refusing_cells()
        if (cell.target, cell.row) not in PROSE_CELLS_THAT_REFUSE
        and (cell.target, cell.row) not in PROSE_CELLS_THAT_SAY_REFUSES_WITHOUT_REFUSING_A_FEATURE
    ]

    assert unmapped == []


def test_every_mapped_prose_cell_is_found_once_in_the_guide() -> None:
    found = Counter((cell.target, cell.row) for cell in refusing_cells())

    assert {key: found[key] for key in PROSE_CELLS_THAT_REFUSE} == dict.fromkeys(PROSE_CELLS_THAT_REFUSE, 1)


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
    lifted: CapabilityTable = {"colour span": dict.fromkeys(EXPORT_TARGETS, "keep")}

    assert features_the_table_does_not_refuse("markdown", ("colour span",), lifted) == ("colour span",)


def test_a_prose_cell_saying_refused_in_capitals_is_found() -> None:
    guide = "| Block | Notion |\n| --- | --- |\n| `a` | REFUSED here |\n"

    assert [(cell.target, cell.row) for cell in refusing_cells_in(guide)] == [("notion", "`a`")]


def test_a_short_row_in_an_export_table_is_refused_naming_the_table_and_the_row() -> None:
    with pytest.raises(GuideTableRowError) as raised:
        refusing_cells_in(SHORT_ROW_GUIDE)

    assert str(raised.value) == (
        "the table headed 'Block | GitHub-flavored | Notion' in GUIDE.md has an empty 'Notion' cell "
        "in the row '`a`'"
    )
