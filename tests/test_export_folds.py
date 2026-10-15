from collections.abc import Callable, Mapping, Sequence

import pytest

from skaldr.errors import ExportInvariantError
from skaldr.export.adf import adf_json, render_adf
from skaldr.export.check import FeatureHit, feature_hits
from skaldr.export.markdown import render_markdown
from skaldr.export.notion import render_notion, render_notion_regions
from skaldr.export.slack import render_slack
from skaldr.export.tree import BlockRegion, LoweredDocument, Node
from skaldr.models import parse_report
from tests.factories import FOLD_CASES, FOLD_CONTEXTS, authored, make_report

Write = Callable[[Sequence[Node]], str]


def _notion_regions(nodes: Sequence[Node]) -> str:
    regions = (BlockRegion(0, tuple(nodes[:1])), BlockRegion(1, tuple(nodes[1:])))
    return "\n---region---\n".join(render_notion_regions(LoweredDocument("Plan", regions)))


WRITERS: Mapping[str, Write] = {
    "markdown": render_markdown,
    "notion": render_notion,
    "notion regions": _notion_regions,
    "adf": lambda nodes: adf_json(render_adf(nodes)),
    "slack": render_slack,
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
@pytest.mark.parametrize("case", FOLD_CASES)
@pytest.mark.parametrize("writer", WRITERS)
def test_each_writer_writes_a_named_node_exactly_as_it_wrote_the_node_the_block_lowered_to_before(
    writer: str, case: str, context: str
) -> None:
    wrap, write = FOLD_CONTEXTS[context], WRITERS[writer]

    assert _outcome(write, wrap(FOLD_CASES[case].named)) == _outcome(write, wrap(FOLD_CASES[case].today))


@pytest.mark.parametrize("context", FOLD_CONTEXTS)
@pytest.mark.parametrize("case", FOLD_CASES)
def test_the_export_check_finds_in_a_named_node_what_it_found_in_the_node_it_replaces(
    case: str, context: str
) -> None:
    wrap = FOLD_CONTEXTS[context]

    assert _hits(wrap(authored(FOLD_CASES[case].named))) == _hits(wrap(authored(FOLD_CASES[case].today)))


@pytest.mark.parametrize("case", FOLD_CASES)
def test_each_fold_case_gives_the_export_check_something_to_find(case: str) -> None:
    found = [
        context for context, wrap in FOLD_CONTEXTS.items() if _hits(wrap(authored(FOLD_CASES[case].named)))
    ]

    assert found != []
