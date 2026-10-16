import re
from collections.abc import Callable, Mapping, Sequence

import pytest

from skaldr.errors import ExportInvariantError
from skaldr.export.adf import adf_json, render_adf
from skaldr.export.budget import character_budget
from skaldr.export.check import FeatureHit, feature_hits
from skaldr.export.folds import cell_text, folded, quote_lines
from skaldr.export.markdown import render_markdown
from skaldr.export.notion import chunk_notion, render_notion, render_notion_regions
from skaldr.export.slack import render_slack
from skaldr.export.tree import BlockRegion, CodeBlock, LoweredDocument, Node, Quote, TableCell
from skaldr.models import parse_report
from tests.factories import FOLD_CASES, FOLD_CONTEXTS, authored, make_paragraph, make_report

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


@pytest.mark.parametrize("context", FOLD_CONTEXTS)
@pytest.mark.parametrize(
    ("writer", "case"),
    [
        (writer, case)
        for writer in WRITERS
        for case in FOLD_CASES
        if case not in WRITTEN_NATIVELY_BY.get(writer, frozenset())
    ],
)
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


@pytest.mark.parametrize("case", FOLD_CASES)
def test_each_fold_case_gives_the_export_check_something_to_find(case: str) -> None:
    named = (authored(FOLD_CASES[case].named),)

    assert [context for context, wrap in FOLD_CONTEXTS.items() if _hits(wrap(named))] != []
