from collections.abc import Callable, Sequence
from dataclasses import fields, replace
from pathlib import Path
from string import Formatter
from typing import Any, Literal, get_args, get_type_hints

import pytest

from skaldr.cli import main
from skaldr.errors import ExportInvariantError, ExportRejectedError
from skaldr.export import render_export
from skaldr.export.adf import render_adf
from skaldr.export.capabilities import (
    CAPABILITIES,
    TARGET_SUBJECTS,
    Capability,
    Details,
    Feature,
    Rejection,
    Swap,
    swaps,
)
from skaldr.export.check import feature_hits, reject_what_the_target_cannot_show
from skaldr.export.lower import assemble_page, lower_regions, lower_report, lowering_for
from skaldr.export.markdown import render_markdown
from skaldr.export.notion import render_notion
from skaldr.export.slack import render_slack
from skaldr.export.swaps import tabs_as_toggles
from skaldr.export.tree import BlockRegion, LoweredDocument, Node, Paragraph, Tab, Tabs
from skaldr.export_targets import EXPORT_TARGETS, ExportTarget
from skaldr.models import load_report, parse_report
from skaldr.publish import ConnectorRegistry
from skaldr.publish.cli import main as publish_main
from skaldr.publish_block import JiraTarget, NotionTarget
from skaldr.richtext import Plain
from tests.factories import (
    REFUSED_IN_THE_EXAMPLE,
    make_jira_target,
    make_notion_target,
    make_report,
    make_request,
    make_section,
    make_tabs,
    make_toggle,
    refused_block_types,
    write_index_document,
    write_report,
)
from tests.factories.capability_factory import (
    ADF_CASES,
    ALL_REFUSALS,
    CANVAS_CALLOUT_WHY,
    CLEAN_BLOCKS,
    COLOURED_TEXT,
    DIAGRAM_REFUSALS,
    HIGHLIGHTED_TEXT,
    LETTERED_LIST,
    LINK_TO_A_SECTION,
    LINK_TO_ANOTHER_DOCUMENT,
    LIST_IN_A_QUOTE,
    NOTION_CASES,
    SEEDED_CASES,
    SEEDED_REFUSALS,
    TABLE,
    UNDERLINED_TEXT,
    RefusedCase,
    in_a_panel,
    one_cell_grid,
    published_report,
    text_grid,
    two_cell_grid,
    walkthrough_holding,
)
from tests.factories.example_factory import example_for
from tests.factories.publish_factory import FakeConnector, FakeTransport

Verdict = Literal["keep", "reject", "swap"]
FEATURES: tuple[Feature, ...] = get_args(Feature)
DETAILS_KINDS: tuple[type[Details], ...] = get_args(Details)
SEEDED_VERDICTS: dict[Feature, dict[ExportTarget, Verdict]] = {
    "table inside a callout": {"adf": "reject", "slack": "reject"},
    "callout inside a callout": {"adf": "reject", "slack": "reject"},
    "quote inside a callout": {"adf": "reject"},
    "toggle inside a callout": {"adf": "reject", "slack": "reject"},
    "table inside a toggle inside a toggle": {"adf": "reject"},
    "toggle inside a toggle inside a toggle": {"adf": "reject"},
    "block inside a list item": {"slack": "reject"},
    "block inside a walkthrough step": {"slack": "reject"},
    "numbered list starting past 1": {"notion": "reject", "slack": "reject"},
    "table over 300 cells": {"slack": "reject"},
    "grid inside a walkthrough step": {"slack": "reject"},
    "subscript or superscript with no Unicode form": {"slack": "reject"},
    "divider inside a callout": {"slack": "reject"},
    "grid with more than three cells": {"slack": "reject"},
    "table inside a grid cell": {"slack": "reject"},
    "callout inside a grid cell": {"slack": "reject"},
    "divider inside a grid cell": {"slack": "reject"},
    "toned grid cell": {"slack": "reject"},
    "grid inside a grid cell": {"slack": "reject"},
    "divider inside a walkthrough step": {"adf": "reject"},
    "set of tabs": {"notion": "swap", "adf": "swap"},
    "request with several cases": {"notion": "swap", "adf": "swap"},
}
REQUEST_WITH_TWO_CASES = make_request(
    cases=[{"label": "a", "response": {"body": "1"}}, {"label": "b", "response": {"body": "2"}}]
)
SWAPPED_BLOCKS = [
    pytest.param(make_tabs(), id="tabs"),
    pytest.param(REQUEST_WITH_TWO_CASES, id="request-with-two-cases"),
]
SWAPPED_BLOCKS_OF_EACH_FEATURE = [
    pytest.param("set of tabs", make_tabs(), id="tabs"),
    pytest.param("request with several cases", REQUEST_WITH_TWO_CASES, id="request-with-two-cases"),
]
TWO_TABS = Tabs(
    (
        Tab((Plain("One"),), (Paragraph((Plain("a"),)),), "warning"),
        Tab((Plain("Two"),), (Paragraph((Plain("b"),)),)),
    )
)
REQUEST_CASES = replace(TWO_TABS, kind="request cases")
PANES_OF_EACH_FEATURE = [
    pytest.param("set of tabs", TWO_TABS, id="tabs"),
    pytest.param("request with several cases", REQUEST_CASES, id="request-cases"),
]
NODE_OF_EACH_PANES_FEATURE: dict[Feature, Tabs] = {
    "set of tabs": TWO_TABS,
    "request with several cases": REQUEST_CASES,
}
PANES_A_WRITER_SWAPS = [
    pytest.param(feature, node, target, id=f"{target}-{feature.replace(' ', '-')}")
    for feature, node in NODE_OF_EACH_PANES_FEATURE.items()
    for target in EXPORT_TARGETS
    if swaps(feature, target)
]
RENDERERS: dict[ExportTarget, Callable[[Sequence[Node]], object]] = {
    "markdown": render_markdown,
    "notion": render_notion,
    "adf": render_adf,
    "slack": render_slack,
}
PANES_WRITTEN_AS_TITLES: dict[ExportTarget, object] = {
    "markdown": (
        "<details open>\n<summary>⚠️ One</summary>\n\na\n\n</details>\n\n"
        "<details>\n<summary>Two</summary>\n\nb\n\n</details>\n"
    ),
    "slack": "**⚠️ One**\n\na\n\n**Two**\n\nb\n",
}
DIAGRAM_VERDICTS: dict[Feature, dict[ExportTarget, Verdict]] = {
    "range": {"markdown": "reject", "notion": "reject", "adf": "reject", "slack": "reject"},
    "flow diagram": {"adf": "reject", "slack": "reject"},
    "fan diagram": {"adf": "reject", "slack": "reject"},
    "link, citation, math or strikethrough in a flow or fan step's note": {
        "markdown": "reject",
        "notion": "reject",
    },
    "chart": {"adf": "swap", "slack": "swap"},
    "math block": {"adf": "swap", "slack": "swap"},
    "inline math": {"adf": "swap", "slack": "swap"},
    "image from a data: URI": {"markdown": "reject", "notion": "reject", "adf": "reject", "slack": "reject"},
    "chart with several series": {"markdown": "swap", "notion": "swap", "adf": "swap", "slack": "swap"},
}
REJECTION_CELLS: set[tuple[Feature, ExportTarget]] = {
    (feature, target)
    for feature, cells in CAPABILITIES.items()
    for target, capability in cells.items()
    if isinstance(capability, Rejection)
}
TEXT_AND_LIST_VERDICTS: dict[Feature, dict[ExportTarget, Verdict]] = {
    "colour span": {"markdown": "reject", "slack": "reject"},
    "highlight span": {"adf": "reject", "slack": "reject"},
    "colour and highlight span": {
        "markdown": "reject",
        "notion": "reject",
        "adf": "reject",
        "slack": "reject",
    },
    "underline": {"slack": "reject"},
    "link to a heading of the same document": {"notion": "reject", "adf": "reject", "slack": "reject"},
    "link to another skaldr document": {"notion": "reject", "adf": "reject", "slack": "reject"},
    "inline code holding a backtick": {"notion": "reject"},
    "inline code holding a closing tag in a table cell": {"notion": "reject"},
    "inline code holding a closing tag in a coloured, highlighted or underlined span": {"notion": "reject"},
    "highlight span inside a toned walkthrough step title": {"notion": "reject"},
    "list numbered with letters or roman numerals": {"adf": "reject", "slack": "reject"},
    "table, callout, heading, quote, toggle or divider inside a list item or walkthrough step": {
        "adf": "reject"
    },
    "list inside a quote": {"slack": "reject"},
}
VERDICTS: dict[Feature, dict[ExportTarget, Verdict]] = {
    **SEEDED_VERDICTS,
    **DIAGRAM_VERDICTS,
    **TEXT_AND_LIST_VERDICTS,
}


def _targets_refusing(blocks: list[dict[str, Any]]) -> set[ExportTarget]:
    return {case.target for case in SEEDED_REFUSALS.values() if case.blocks == blocks}


KEPT_BY_THE_OTHER_TARGETS = [
    pytest.param(case, other, id=f"{name}-kept-by-{other}")
    for name, case in SEEDED_REFUSALS.items()
    for other in EXPORT_TARGETS
    if other not in _targets_refusing(case.blocks) and other not in case.also_refused_by
]
ALSO_REFUSED_BY = [
    pytest.param(case, other, id=f"{name}-also-refused-by-{other}")
    for name, case in SEEDED_REFUSALS.items()
    for other in case.also_refused_by
]


def _features_carried_by(details: type[Details]) -> tuple[Feature, ...]:
    return get_args(get_type_hints(details)["feature"])


DETAILS_OF_A_FEATURE: dict[Feature, type[Details]] = {
    feature: details for details in DETAILS_KINDS for feature in _features_carried_by(details)
}
REJECTIONS = [
    pytest.param(capability, DETAILS_OF_A_FEATURE[feature], id=f"{target}-{feature}")
    for feature, cells in CAPABILITIES.items()
    for target, capability in cells.items()
    if isinstance(capability, Rejection)
]


def _verdict(capability: Capability) -> Verdict:
    match capability:
        case Rejection():
            return "reject"
        case Swap():
            return "swap"
        case _:
            return capability


def _refused_features(case: RefusedCase) -> list[Feature]:
    report = parse_report(make_report(blocks=case.blocks))
    return [
        hit.details.feature
        for hit in feature_hits(report, lower_report(report))
        if isinstance(CAPABILITIES[hit.details.feature][case.target], Rejection)
    ]


def _first_refused_feature(case: RefusedCase) -> Feature:
    return _refused_features(case)[0]


SEEDED_CASES_REFUSED_FOR_ONE_FEATURE = [
    pytest.param(case, id=name)
    for name, case in SEEDED_REFUSALS.items()
    if set(_refused_features(case)) == {case.feature}
]
SEEDED_CASES_REFUSED_FOR_MORE_FEATURES = [
    pytest.param(case, id=name)
    for name, case in SEEDED_REFUSALS.items()
    if set(_refused_features(case)) != {case.feature}
]


def _adf_expands(*titles: str) -> list[dict[str, Any]]:
    return [
        {
            "type": "expand",
            "attrs": {"title": title},
            "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}],
        }
        for title, text in zip(titles, "ab", strict=True)
    ]


def _template_fields(template: str) -> set[str]:
    return {name for _, name, _, _ in Formatter().parse(template) if name is not None}


def _check(blocks: list[dict[str, Any]], target: ExportTarget) -> None:
    report = parse_report(make_report(blocks=blocks))
    reject_what_the_target_cannot_show(report, lower_report(report), target)


def _publish_with_fake_connectors(data_path: Path, transport: FakeTransport) -> int:
    registry = ConnectorRegistry(
        [FakeConnector(NotionTarget, transport), FakeConnector(JiraTarget, transport, export_target="adf")]
    )
    return publish_main(["publish", str(data_path), "--apply"], registry=registry)


def test_the_table_holds_a_cell_for_every_feature_and_target_and_rejects_only_the_seeded_ones() -> None:
    verdicts = {
        feature: {target: _verdict(capability) for target, capability in cells.items()}
        for feature, cells in CAPABILITIES.items()
    }

    assert verdicts == {
        feature: {target: seeded.get(target, "keep") for target in EXPORT_TARGETS}
        for feature, seeded in VERDICTS.items()
    }


def test_each_feature_is_carried_by_exactly_one_kind_of_details() -> None:
    carried = [feature for details in DETAILS_KINDS for feature in _features_carried_by(details)]

    assert sorted(carried) == sorted(FEATURES)


@pytest.mark.parametrize(("rejection", "details"), REJECTIONS)
def test_every_rejection_names_only_details_its_feature_supplies(
    rejection: Rejection, details: type[Details]
) -> None:
    supplied = {detail.name for detail in fields(details)}

    assert _template_fields(rejection.why) | _template_fields(rejection.instead) <= supplied


def test_every_rejection_in_the_table_has_a_seeded_case_and_every_seeded_case_names_a_rejection() -> None:
    named = [(case.feature, case.target) for case in ALL_REFUSALS.values()]
    refused = [(_first_refused_feature(case), case.target) for case in ALL_REFUSALS.values()]

    assert (refused, set(named)) == (named, REJECTION_CELLS)


@pytest.mark.parametrize("case", SEEDED_CASES_REFUSED_FOR_ONE_FEATURE)
def test_each_seeded_case_passes_once_the_cell_it_names_keeps_the_feature(
    monkeypatch: pytest.MonkeyPatch, case: RefusedCase
) -> None:
    monkeypatch.setitem(CAPABILITIES[case.feature], case.target, "keep")

    _check(case.blocks, case.target)


@pytest.mark.parametrize("case", SEEDED_CASES_REFUSED_FOR_MORE_FEATURES)
def test_a_seeded_case_refused_for_several_features_reports_the_next_once_its_cell_keeps_the_feature(
    monkeypatch: pytest.MonkeyPatch, case: RefusedCase
) -> None:
    next_feature = next(feature for feature in _refused_features(case) if feature != case.feature)
    monkeypatch.setitem(CAPABILITIES[case.feature], case.target, "keep")

    assert _first_refused_feature(case) == next_feature


@pytest.mark.parametrize("case", SEEDED_CASES)
def test_the_check_refuses_each_seeded_case_naming_its_yaml_path(case: RefusedCase) -> None:
    with pytest.raises(ExportRejectedError) as raised:
        _check(case.blocks, case.target)

    assert vars(raised.value) == case.rejection()


@pytest.mark.parametrize(("case", "other"), KEPT_BY_THE_OTHER_TARGETS)
def test_every_other_target_exports_what_one_target_refuses_without_a_refusal(
    case: RefusedCase, other: ExportTarget
) -> None:
    report = parse_report(make_report(blocks=case.blocks))

    assert render_export(report, other).pages != {}


@pytest.mark.parametrize(
    ("blocks", "target", "page"),
    [
        pytest.param(
            COLOURED_TEXT, "notion", 'Zone C is <span color="red">behind</span>.\n', id="colour-on-notion"
        ),
        pytest.param(
            HIGHLIGHTED_TEXT,
            "notion",
            'The recount is <span color="yellow_bg">due Friday</span>.\n',
            id="highlight-on-notion",
        ),
        pytest.param(
            UNDERLINED_TEXT,
            "markdown",
            "# Test Report\n\nEvery label ends in a <ins>check digit</ins>.\n",
            id="underline-on-github",
        ),
        pytest.param(
            HIGHLIGHTED_TEXT,
            "markdown",
            "# Test Report\n\nThe recount is <mark>due Friday</mark>.\n",
            id="highlight-on-github",
        ),
        pytest.param(
            LETTERED_LIST,
            "markdown",
            '# Test Report\n\n<ol type="a">\n<li>\n\na\n\n</li>\n<li>\n\nb\n\n</li>\n</ol>\n',
            id="lettered-list-on-github",
        ),
        pytest.param(
            LIST_IN_A_QUOTE,
            "markdown",
            "# Test Report\n\n> Count:\n>\n> - aisles\n> - bins\n",
            id="list-in-a-quote-on-github",
        ),
        pytest.param(
            LINK_TO_ANOTHER_DOCUMENT,
            "markdown",
            "# Test Report\n\nIt follows [the plan](cold-room-plan.md).\n",
            id="doc-link-on-github",
        ),
        pytest.param(
            LINK_TO_A_SECTION,
            "markdown",
            "# Test Report\n\n## Counts\n\nTen.\n\nSee [the counts](#counts).\n",
            id="same-page-link-on-github",
        ),
        pytest.param(
            LIST_IN_A_QUOTE, "notion", "> Count:<br>• aisles<br>• bins\n", id="list-in-a-quote-on-notion"
        ),
    ],
)
def test_a_target_that_keeps_what_another_refuses_writes_it_as_the_page_shows_it(
    blocks: list[dict[str, Any]], target: ExportTarget, page: str
) -> None:
    report = parse_report(make_report(blocks=blocks))

    assert render_export(report, target).pages == {"page.md": page}


@pytest.mark.parametrize(("case", "other"), ALSO_REFUSED_BY)
def test_every_target_a_case_names_as_also_refusing_it_refuses_it(
    case: RefusedCase, other: ExportTarget
) -> None:
    with pytest.raises(ExportRejectedError) as raised:
        _check(case.blocks, other)

    assert raised.value.target == other


@pytest.mark.parametrize("target", EXPORT_TARGETS)
def test_a_document_no_target_refuses_passes_the_check(target: ExportTarget) -> None:
    _check(CLEAN_BLOCKS, target)


def test_each_target_refuses_these_top_level_blocks_of_the_example() -> None:
    refused = {target: refused_block_types(example_for(target), target) for target in EXPORT_TARGETS}

    assert refused == REFUSED_IN_THE_EXAMPLE


@pytest.mark.parametrize("target", EXPORT_TARGETS)
@pytest.mark.parametrize("block", SWAPPED_BLOCKS)
def test_a_block_a_target_swaps_for_another_form_passes_the_check(
    block: dict[str, Any], target: ExportTarget
) -> None:
    _check([block], target)


@pytest.mark.parametrize("target", EXPORT_TARGETS)
@pytest.mark.parametrize(("feature", "node"), PANES_OF_EACH_FEATURE)
def test_a_writer_writes_panes_as_toggles_exactly_where_the_table_swaps_them(
    feature: Feature, node: Tabs, target: ExportTarget
) -> None:
    render = RENDERERS[target]
    expected = render(tabs_as_toggles(node)) if swaps(feature, target) else PANES_WRITTEN_AS_TITLES[target]

    assert render([node]) == expected


@pytest.mark.parametrize(("feature", "node", "target"), PANES_A_WRITER_SWAPS)
def test_a_writer_that_swaps_panes_refuses_panes_whose_cell_is_not_a_swap(
    monkeypatch: pytest.MonkeyPatch, feature: Feature, node: Tabs, target: ExportTarget
) -> None:
    monkeypatch.setitem(CAPABILITIES[feature], target, "keep")

    with pytest.raises(ExportInvariantError) as raised:
        RENDERERS[target]([node])

    assert str(raised.value) == (
        f"{TARGET_SUBJECTS[target]} has no form for '{feature}'; the export check should have refused it"
    )


@pytest.mark.parametrize(
    ("kept_feature", "swapped_node"),
    [
        pytest.param("set of tabs", REQUEST_CASES, id="tabs-kept-request-cases-swapped"),
        pytest.param("request with several cases", TWO_TABS, id="request-cases-kept-tabs-swapped"),
    ],
)
def test_a_writer_swaps_the_panes_whose_own_cell_says_swap(
    monkeypatch: pytest.MonkeyPatch, kept_feature: Feature, swapped_node: Tabs
) -> None:
    monkeypatch.setitem(CAPABILITIES[kept_feature], "notion", "keep")
    monkeypatch.setitem(CAPABILITIES[kept_feature], "adf", "keep")

    assert (render_notion([swapped_node]), render_adf([swapped_node])["content"]) == (
        "<details>\n<summary>⚠️ One</summary>\n\ta\n</details>\n"
        "<details>\n<summary>Two</summary>\n\tb\n</details>\n",
        _adf_expands("⚠️ One", "Two"),
    )


@pytest.mark.parametrize(("feature", "block"), SWAPPED_BLOCKS_OF_EACH_FEATURE)
def test_a_panes_cell_made_a_rejection_refuses_the_block(
    monkeypatch: pytest.MonkeyPatch, feature: Feature, block: dict[str, Any]
) -> None:
    monkeypatch.setitem(CAPABILITIES[feature], "markdown", Rejection("Markdown cannot show it", "drop it"))

    with pytest.raises(ExportRejectedError) as raised:
        _check([block], "markdown")

    assert vars(raised.value) == {
        "target": "markdown",
        "why": "Markdown cannot show it",
        "instead": "drop it",
        "where": f"at blocks.0.{block['type']}",
    }


@pytest.mark.parametrize(
    "block",
    [
        pytest.param(two_cell_grid(one_cell_grid({"type": "text", "body": "Inner"})), id="in-a-grid-cell"),
        pytest.param(walkthrough_holding(one_cell_grid({"type": "text", "body": "Inner"})), id="in-a-step"),
    ],
)
def test_an_inner_grid_of_one_cell_shows_no_columns_so_a_canvas_keeps_it(block: dict[str, Any]) -> None:
    _check([block], "slack")


def test_a_grid_in_a_walkthrough_step_is_named_before_a_block_inside_the_grid() -> None:
    grid = text_grid()
    grid["cells"][1]["blocks"] = [{"type": "code", "content": "recount"}]

    with pytest.raises(ExportRejectedError) as raised:
        _check([walkthrough_holding(grid)], "slack")

    assert raised.value.where == "at blocks.0.walkthrough.steps.0.detail.0.grid"


def test_a_refusal_in_the_source_line_of_the_footer_names_meta_source() -> None:
    meta = {"title": "Counts", "source": "the [cold room]{tone=danger} log"}
    report = parse_report(make_report(meta=meta))

    with pytest.raises(ExportRejectedError) as raised:
        reject_what_the_target_cannot_show(report, lower_report(report), "markdown")

    assert vars(raised.value) == {
        "target": "markdown",
        "why": "GitHub Markdown cannot colour text, so it cannot show the colour of 'cold room'",
        "instead": "write the text without the colour or export the document elsewhere",
        "where": "at meta.source",
    }


@pytest.mark.parametrize(
    ("blocks", "where"),
    [
        pytest.param([*COLOURED_TEXT, *LETTERED_LIST], "at blocks.0.text", id="text-before-a-list"),
        pytest.param(
            [*in_a_panel({"type": "divider"}), two_cell_grid(text_grid())],
            "at blocks.0.panel.blocks.0.divider",
            id="panel-before-a-grid",
        ),
    ],
)
def test_the_first_refusal_reported_is_the_first_in_the_document(
    blocks: list[dict[str, Any]], where: str
) -> None:
    with pytest.raises(ExportRejectedError) as raised:
        _check(blocks, "slack")

    assert raised.value.where == where


def test_a_refusal_in_a_nested_list_is_reported_before_one_in_the_next_item() -> None:
    blocks = [{"type": "text", "body": "- a\n  - ++u++\n- [c]{tone=danger}"}]

    with pytest.raises(ExportRejectedError) as raised:
        _check(blocks, "slack")

    assert vars(raised.value) == {
        "target": "slack",
        "why": "a Slack canvas cannot underline text, so it cannot show the underline on 'u'",
        "instead": "write the text without the underline or export the document elsewhere",
        "where": "at blocks.0.text",
    }


def test_a_refusal_in_a_walkthrough_step_is_reported_before_one_in_the_next_step_title() -> None:
    steps = [
        {"label": "Scan", "detail": [text_grid()]},
        {
            "label": "Count",
            "sub": "the [cold room]{tone=danger}",
            "detail": [{"type": "text", "body": "Ten."}],
        },
    ]

    with pytest.raises(ExportRejectedError) as raised:
        _check([{"type": "walkthrough", "steps": steps}], "slack")

    assert raised.value.where == "at blocks.0.walkthrough.steps.0.detail.0.grid"


def _filler(count: int) -> list[dict[str, Any]]:
    return [{"type": "text", "body": f"Row {index}."} for index in range(count)]


def _a_panel_refusal_at_9_then_a_model_refusal_at_10() -> list[dict[str, Any]]:
    return [*_filler(9), *in_a_panel({"type": "divider"}), two_cell_grid(text_grid())]


def test_a_refusal_at_block_9_is_reported_before_a_model_refusal_at_block_10() -> None:
    with pytest.raises(ExportRejectedError) as raised:
        _check(_a_panel_refusal_at_9_then_a_model_refusal_at_10(), "slack")

    assert raised.value.where == "at blocks.9.panel.blocks.0.divider"


def test_a_refusal_at_block_9_of_a_part_is_reported_before_a_model_refusal_at_its_block_10(
    tmp_path: Path,
) -> None:
    index = write_index_document(
        tmp_path, {"one.yaml": make_report(blocks=_a_panel_refusal_at_9_then_a_model_refusal_at_10())}
    )
    report = load_report(index)

    with pytest.raises(ExportRejectedError) as raised:
        reject_what_the_target_cannot_show(report, lower_report(report), "slack")

    assert raised.value.where == (
        "at blocks.0.part.blocks.9.panel.blocks.0.divider, under the heading 'Test Report'"
    )


def test_a_refusal_found_on_the_model_is_reported_when_no_lowered_node_follows_it() -> None:
    report = parse_report(make_report(blocks=[walkthrough_holding(text_grid())]))
    page = LoweredDocument(report.meta.title, (BlockRegion(0, ()),))

    with pytest.raises(ExportRejectedError) as raised:
        reject_what_the_target_cannot_show(report, page, "slack")

    assert raised.value.where == "at blocks.0.walkthrough.steps.0.detail.0.grid"


@pytest.mark.parametrize(
    ("blocks", "target", "refusal"),
    [
        pytest.param(
            in_a_panel({"type": "callout", "tone": "info", "body": "The [recount]{bg=warning} is due."}),
            "adf",
            {
                "target": "adf",
                "why": "ADF cannot place a callout inside a panel",
                "instead": "move the callout out of the panel",
                "where": "at blocks.0.panel.blocks.0.callout",
            },
            id="adf-callout-in-a-panel-before-a-highlight-in-its-text",
        ),
        pytest.param(
            in_a_panel(make_toggle(make_toggle(TABLE))),
            "adf",
            {
                "target": "adf",
                "why": "ADF cannot place a toggle inside a panel",
                "instead": "move the toggle out of the panel",
                "where": "at blocks.0.panel.blocks.0.toggle",
            },
            id="adf-toggle-in-a-panel-before-a-table-in-its-inner-toggle",
        ),
        pytest.param(
            in_a_panel(make_toggle({"type": "text", "body": "H~q~"})),
            "slack",
            {
                "target": "slack",
                "why": CANVAS_CALLOUT_WHY.format(held="toggle"),
                "instead": "move the toggle out of the panel",
                "where": "at blocks.0.panel.blocks.0.toggle",
            },
            id="slack-toggle-in-a-panel-before-a-subscript-inside-it",
        ),
    ],
)
def test_a_block_a_container_cannot_hold_is_reported_before_what_it_holds(
    blocks: list[dict[str, Any]], target: ExportTarget, refusal: dict[str, str]
) -> None:
    with pytest.raises(ExportRejectedError) as raised:
        _check(blocks, target)

    assert vars(raised.value) == refusal


def test_a_refusal_found_on_the_model_names_the_heading_above_it() -> None:
    blocks = [{"type": "heading", "text": "Layout"}, two_cell_grid(text_grid())]

    with pytest.raises(ExportRejectedError) as raised:
        _check(blocks, "slack")

    assert raised.value.where == "at blocks.1.grid.cells.1.blocks.0.grid, under the heading 'Layout'"


@pytest.mark.parametrize(
    ("target", "refused_at"),
    [
        pytest.param("adf", "at blocks.2.panel.blocks.0.table", id="adf"),
        pytest.param("slack", "at blocks.1.walkthrough.steps.0.detail.0.grid", id="slack"),
    ],
)
def test_the_check_of_a_page_built_from_some_regions_looks_only_at_their_blocks(
    target: ExportTarget, refused_at: str
) -> None:
    blocks = [{"type": "text", "body": "Fine."}, walkthrough_holding(text_grid()), *in_a_panel(TABLE)]
    report = parse_report(make_report(blocks=blocks))
    lowering = lowering_for(report)
    regions = lower_regions(lowering)

    with pytest.raises(ExportRejectedError) as raised:
        reject_what_the_target_cannot_show(report, assemble_page(regions, lowering), target)
    reject_what_the_target_cannot_show(report, assemble_page(regions[:1], lowering), target)

    assert raised.value.where == refused_at


@pytest.mark.parametrize("case", SEEDED_CASES)
def test_export_refuses_each_seeded_case_and_writes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], case: RefusedCase
) -> None:
    data_path = write_report(tmp_path, make_report(blocks=case.blocks))
    export_dir = tmp_path / "exported"

    assert main([str(data_path), "--export", case.target, "--export-dir", str(export_dir)]) == 1

    captured = capsys.readouterr()
    assert (captured.out, captured.err, export_dir.exists()) == ("", f"error: {case.message()}\n", False)


@pytest.mark.parametrize("target", EXPORT_TARGETS)
def test_a_clean_document_exports_to_every_target(tmp_path: Path, target: ExportTarget) -> None:
    data_path = write_report(tmp_path, make_report(blocks=CLEAN_BLOCKS))

    assert main([str(data_path), "--export", target, "--export-dir", str(tmp_path / "exported")]) == 0


@pytest.mark.parametrize(
    "case",
    [
        *NOTION_CASES,
        *(pytest.param(DIAGRAM_REFUSALS[name], id=name) for name in ("notion-range", "notion-data-image")),
    ],
)
def test_publishing_to_notion_refuses_each_notion_case_before_any_transport_call(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], case: RefusedCase
) -> None:
    data_path = write_report(tmp_path, published_report(case.blocks, make_notion_target()))
    transport = FakeTransport()

    exit_code = _publish_with_fake_connectors(data_path, transport)

    assert (exit_code, capsys.readouterr().err, transport.calls) == (1, f"error: {case.message()}\n", [])


@pytest.mark.parametrize(
    "case",
    [
        *ADF_CASES,
        *(
            pytest.param(DIAGRAM_REFUSALS[name], id=name)
            for name in ("adf-range", "adf-flow", "adf-data-image")
        ),
    ],
)
def test_publishing_to_jira_refuses_each_adf_case_before_any_transport_call(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], case: RefusedCase
) -> None:
    data_path = write_report(tmp_path, published_report(case.blocks, make_jira_target()))
    transport = FakeTransport()

    exit_code = _publish_with_fake_connectors(data_path, transport)

    assert (exit_code, capsys.readouterr().err, transport.calls) == (1, f"error: {case.message()}\n", [])


def test_publishing_a_clean_document_to_notion_sends_it(tmp_path: Path) -> None:
    data_path = write_report(tmp_path, published_report(CLEAN_BLOCKS, make_notion_target()))
    transport = FakeTransport()

    assert _publish_with_fake_connectors(data_path, transport) == 0

    assert transport.writes() != []


def test_publishing_to_jira_checks_only_the_sections_the_target_is_built_from(tmp_path: Path) -> None:
    blocks = [make_section("kept"), make_section("left-out", blocks=in_a_panel(TABLE))]
    target = make_jira_target(**{"from": ["kept"]})
    data_path = write_report(tmp_path, published_report(blocks, target))

    assert _publish_with_fake_connectors(data_path, FakeTransport()) == 0


def test_publishing_a_clean_document_to_jira_sends_it(tmp_path: Path) -> None:
    data_path = write_report(tmp_path, published_report(CLEAN_BLOCKS, make_jira_target()))
    transport = FakeTransport()

    assert _publish_with_fake_connectors(data_path, transport) == 0

    assert transport.writes() != []
