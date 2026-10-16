import re
from collections.abc import Callable, Mapping, Sequence
from typing import Final

import pytest

from skaldr.errors import ExportInvariantError
from skaldr.export.adf import adf_json, render_adf
from skaldr.export.budget import character_budget
from skaldr.export.check import FeatureHit, feature_hits
from skaldr.export.folds import cell_text, folded, quote_lines
from skaldr.export.inline import plain
from skaldr.export.markdown import render_markdown
from skaldr.export.notion import chunk_notion, render_notion, render_notion_regions
from skaldr.export.slack import render_slack
from skaldr.export.tree import (
    BlockRegion,
    CodeBlock,
    Definition,
    DefinitionList,
    LoweredDocument,
    Node,
    Quote,
    TableCell,
    TableNode,
)
from skaldr.export_targets import ExportTarget
from skaldr.models import parse_report
from tests.factories import (
    FOLD_CASES,
    FOLD_CONTEXTS,
    authored,
    check_nodes,
    make_paragraph,
    make_report,
    refusal_of,
)

Write = Callable[[Sequence[Node]], str]
NOTION_CHUNK_CHARACTERS = 60


def _notion_regions(nodes: Sequence[Node]) -> str:
    regions = (
        BlockRegion(0, (make_paragraph("first"),)),
        BlockRegion(1, tuple(nodes)),
        BlockRegion(2, (make_paragraph("last"),)),
    )
    return "\n---region---\n".join(render_notion_regions(LoweredDocument("Plan", regions)))


def _notion_chunks(nodes: Sequence[Node]) -> str:
    return repr(chunk_notion(nodes, character_budget(NOTION_CHUNK_CHARACTERS)))


WRITERS: Mapping[str, Write] = {
    "markdown": render_markdown,
    "notion": render_notion,
    "notion full width": lambda nodes: render_notion(nodes, "full"),
    "notion regions": _notion_regions,
    "notion chunks": _notion_chunks,
    "adf": lambda nodes: adf_json(render_adf(nodes)),
    "slack": render_slack,
}


WRITTEN_NATIVELY_BY: Mapping[str, frozenset[str]] = {
    writer: frozenset({"fact strip", "key-value list", "definition list", "cards"})
    for writer in WRITERS
    if writer.startswith("notion")
}


def _outcome(write: Write, nodes: Sequence[Node]) -> str:
    try:
        return write(nodes)
    except ExportInvariantError as refusal:
        return f"refused: {refusal}"


def _hits(nodes: Sequence[Node]) -> list[FeatureHit]:
    report = parse_report(make_report())
    return list(feature_hits(report, LoweredDocument("Plan", (BlockRegion(0, tuple(nodes)),))))


WRITTEN_IN_ITS_OWN_FORM: Mapping[str, frozenset[str]] = {
    "slack": frozenset({"table cell holding a list", "long list cell beside a short cell"}),
}
CONTEXTS_WHERE_ADF_HOLDS_NO_TABLE_CARD_OR_EXPAND: Final = frozenset(
    {
        "in a numbered list item",
        "after a list item's nested list",
        "in a callout",
        "in a toggle in a toggle",
    }
)
ADF_WRITES_THESE_CASES_NATIVELY_EXCEPT_IN: Final[Mapping[str, frozenset[str]]] = {
    "fact strip": CONTEXTS_WHERE_ADF_HOLDS_NO_TABLE_CARD_OR_EXPAND,
    "key-value list": CONTEXTS_WHERE_ADF_HOLDS_NO_TABLE_CARD_OR_EXPAND,
    "definition list": CONTEXTS_WHERE_ADF_HOLDS_NO_TABLE_CARD_OR_EXPAND,
    "cards": CONTEXTS_WHERE_ADF_HOLDS_NO_TABLE_CARD_OR_EXPAND,
    "timeline": CONTEXTS_WHERE_ADF_HOLDS_NO_TABLE_CARD_OR_EXPAND,
    "link card": CONTEXTS_WHERE_ADF_HOLDS_NO_TABLE_CARD_OR_EXPAND - {"in a callout"},
    "link embed": CONTEXTS_WHERE_ADF_HOLDS_NO_TABLE_CARD_OR_EXPAND,
    "open toggle": CONTEXTS_WHERE_ADF_HOLDS_NO_TABLE_CARD_OR_EXPAND,
    "quote holding lists": frozenset(),
    "table cell holding a list": frozenset(),
    "long list cell beside a short cell": frozenset(),
}
WRITTEN_AS_THE_FOLD: Final = [
    pytest.param(writer, case, context, id=f"{writer}-{case}-{context}")
    for writer in WRITERS
    for case in FOLD_CASES
    for context in FOLD_CONTEXTS
    if case not in WRITTEN_NATIVELY_BY.get(writer, frozenset())
    and case not in WRITTEN_IN_ITS_OWN_FORM.get(writer, frozenset())
    and (
        writer != "adf"
        or context in ADF_WRITES_THESE_CASES_NATIVELY_EXCEPT_IN.get(case, frozenset(FOLD_CONTEXTS))
    )
]


@pytest.mark.parametrize(("writer", "case", "context"), WRITTEN_AS_THE_FOLD)
def test_each_writer_writes_a_named_node_exactly_as_it_wrote_the_nodes_the_block_lowered_to_before(
    writer: str, case: str, context: str
) -> None:
    wrap, write, fold = FOLD_CONTEXTS[context], WRITERS[writer], FOLD_CASES[case]

    assert _outcome(write, wrap((fold.named,))) == _outcome(write, wrap(fold.today))


@pytest.mark.parametrize("case", ["cards", "fact strip", "timeline"])
def test_a_named_list_block_folds_to_exactly_the_nodes_it_lowered_to_before(case: str) -> None:
    fold = FOLD_CASES[case]

    assert tuple(folded((fold.named,))) == fold.today


@pytest.mark.parametrize("context", FOLD_CONTEXTS)
@pytest.mark.parametrize("case", FOLD_CASES)
def test_the_export_check_finds_in_a_named_node_what_it_found_in_the_nodes_it_replaces(
    case: str, context: str
) -> None:
    wrap, fold = FOLD_CONTEXTS[context], FOLD_CASES[case]

    assert _hits(wrap((authored(fold.named),))) == _hits(wrap(tuple(map(authored, fold.today))))


@pytest.mark.parametrize(
    "fold",
    [
        pytest.param(lambda: quote_lines(Quote((CodeBlock("x"),))), id="quote"),
        pytest.param(lambda: cell_text(TableCell((), blocks=(CodeBlock("x"),))), id="table-cell"),
    ],
)
def test_a_quote_or_a_table_cell_holding_another_block_is_an_internal_error(
    fold: Callable[[], object],
) -> None:
    with pytest.raises(
        ExportInvariantError,
        match=re.escape(
            "a quote or a table cell holds only paragraphs and lists, not a CodeBlock; "
            "the lowering should not have put one there"
        ),
    ):
        fold()


DEFINITION_BODY_BLOCKS: Mapping[str, Node] = {
    "table": TableNode((TableCell(plain("A")),), ()),
    "quote": Quote((make_paragraph("said"),)),
}


@pytest.mark.parametrize("held", DEFINITION_BODY_BLOCKS)
@pytest.mark.parametrize("target", ["markdown", "notion", "slack"])
def test_a_definition_body_block_a_list_item_cannot_hold_is_accepted_where_the_writer_has_a_place_for_it(
    held: str, target: ExportTarget
) -> None:
    check_nodes([_definition_holding(DEFINITION_BODY_BLOCKS[held])], target)


@pytest.mark.parametrize("held", DEFINITION_BODY_BLOCKS)
def test_a_definition_body_block_adf_cannot_place_in_the_list_item_it_folds_to_is_still_refused(
    held: str,
) -> None:
    assert vars(refusal_of([_definition_holding(DEFINITION_BODY_BLOCKS[held])], "adf")) == {
        "target": "adf",
        "why": f"ADF cannot place a {held} inside a list item",
        "instead": f"move the {held} out of the list, after the list",
        "where": "at blocks.0",
    }


def _definition_holding(held: Node) -> Node:
    return authored(DefinitionList((Definition("Fix", (make_paragraph("lead"), held)),)))


@pytest.mark.parametrize("case", FOLD_CASES)
def test_each_fold_case_gives_the_export_check_something_to_find(case: str) -> None:
    named = (authored(FOLD_CASES[case].named),)

    assert [context for context, wrap in FOLD_CONTEXTS.items() if _hits(wrap(named))] != []
