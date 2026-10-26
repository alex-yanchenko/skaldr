from collections.abc import Iterable, Iterator, Sequence
from typing import Any, cast

from typing_extensions import assert_never

from skaldr.models.comparison_matrix import Comparison, Matrix
from skaldr.models.containers import (
    AnyBlock,
    Grid,
    InnerGrid,
    InnerToggle,
    Panel,
    Part,
    Section,
    Tabs,
    Toggle,
    Walkthrough,
)
from skaldr.models.request import Request, RequestFlow
from skaldr.models.simple_blocks import (
    BadgeRef,
    BadgeRow,
    Callout,
    Cards,
    Chart,
    Code,
    DefList,
    Divider,
    FactStrip,
    Fan,
    Flow,
    Heading,
    Image,
    KeyValue,
    Link,
    ListBlock,
    Math,
    Media,
    Meter,
    Note,
    Quote,
    Range,
    ReferenceItem,
    References,
    StatusList,
    Text,
    Timeline,
)
from skaldr.models.swimlane import Swimlane
from skaldr.models.table import Table


def located_child_blocks(block: AnyBlock) -> Sequence[tuple[str, AnyBlock]]:
    match block:
        case Part() | Section() | Panel() | Toggle() | InnerToggle():
            return [(f"blocks.{index}", inner) for index, inner in enumerate(block.blocks)]
        case Grid() | InnerGrid():
            return [
                (f"cells.{cell_index}.blocks.{index}", inner)
                for cell_index, cell in enumerate(block.cells)
                for index, inner in enumerate(cell.blocks)
            ]
        case Walkthrough():
            return [
                (f"steps.{step_index}.detail.{index}", inner)
                for step_index, step in enumerate(block.steps)
                for index, inner in enumerate(step.detail)
            ]
        case Tabs():
            return [
                (f"tabs.{tab_index}.blocks.{index}", inner)
                for tab_index, tab in enumerate(block.tabs)
                for index, inner in enumerate(tab.blocks)
            ]
        case (
            Heading()
            | Text()
            | ListBlock()
            | FactStrip()
            | KeyValue()
            | DefList()
            | Cards()
            | BadgeRow()
            | Callout()
            | StatusList()
            | Meter()
            | Range()
            | Table()
            | Code()
            | Math()
            | Quote()
            | Note()
            | Divider()
            | Image()
            | Media()
            | Link()
            | Timeline()
            | Flow()
            | Fan()
            | Chart()
            | Comparison()
            | Matrix()
            | Swimlane()
            | References()
            | Request()
            | RequestFlow()
        ):
            return ()
        case _:
            assert_never(block)


def child_blocks(block: AnyBlock) -> Sequence[AnyBlock]:
    return [inner for _, inner in located_child_blocks(block)]


def walk_blocks(blocks: Sequence[AnyBlock]) -> Iterator[AnyBlock]:
    for block in blocks:
        yield block
        yield from walk_blocks(child_blocks(block))


def _walk_placed(placed: Iterable[tuple[str, AnyBlock]]) -> Iterator[tuple[str, AnyBlock]]:
    for place, block in placed:
        path = f"{place}.{block.type}"
        yield path, block
        yield from _walk_placed((f"{path}.{child}", inner) for child, inner in located_child_blocks(block))


def walk_located_blocks(blocks: Sequence[AnyBlock]) -> Iterator[tuple[str, AnyBlock]]:
    yield from _walk_placed((f"blocks.{index}", block) for index, block in enumerate(blocks))


def walk_located_block(index: int, block: AnyBlock) -> Iterator[tuple[str, AnyBlock]]:
    yield from _walk_placed([(f"blocks.{index}", block)])


def iter_requests(blocks: Sequence[AnyBlock]) -> Iterator[Request | RequestFlow]:
    """Every `request` and `request_flow` on the page, including ones nested in a section or a panel."""
    for block in walk_blocks(blocks):
        if isinstance(block, Request | RequestFlow):
            yield block


def unresolvable_request_variables(blocks: Sequence[AnyBlock]) -> set[str]:
    """Names a `request` or `request_flow` interpolates but cannot fill: neither a reader's field, nor
    a case axis, nor a value an earlier step captured. A declared name is a runtime blank the reader
    supplies, so it is not an unfilled placeholder; an undeclared one is a typo the strict gate should
    still catch."""
    names: set[str] = set()
    for block in iter_requests(blocks):
        names |= unresolved_request_variables(block)
    return names


def unresolved_request_variables(block: Request | RequestFlow) -> set[str]:
    if isinstance(block, RequestFlow):
        return block.unresolved_variables()
    return block.referenced_variables() - block.resolvable_variables()


def iter_referenced_badge_keys(blocks: Sequence[AnyBlock]) -> Iterator[str]:
    """Every badge key referenced anywhere in the block tree (recursing into sections and grids).

    Single source of truth for both validation (undeclared keys) and the derived legend.
    """
    return (key for _, key in iter_located_badge_keys(blocks))


def iter_located_badge_keys(blocks: Sequence[AnyBlock]) -> Iterator[tuple[str, str]]:
    for path, block in walk_located_blocks(blocks):
        yield from _badge_keys_in(path, block)


def _badge_keys_from(path: str, keys: Sequence[str]) -> Iterator[tuple[str, str]]:
    for index, key in enumerate(keys):
        yield f"{path}.{index}", key


def _badge_keys_in(path: str, block: AnyBlock) -> Iterator[tuple[str, str]]:
    if isinstance(block, BadgeRow):
        for index, item in enumerate(block.items):
            if isinstance(item, BadgeRef):
                yield f"{path}.items.{index}.key", item.key
        for group_index, group in enumerate(block.groups):
            for index, item in enumerate(group.items):
                if isinstance(item, BadgeRef):
                    yield f"{path}.groups.{group_index}.items.{index}.key", item.key
    elif isinstance(block, Cards):
        for index, card in enumerate(block.items):
            yield from _badge_keys_from(f"{path}.items.{index}.badges", card.badges)
            if card.badge is not None:
                yield f"{path}.items.{index}.badge", card.badge
    elif isinstance(block, Timeline):
        for index, item in enumerate(block.items):
            yield from _badge_keys_from(f"{path}.items.{index}.badges", item.badges)
    elif isinstance(block, Flow):
        for index, step in enumerate(block.steps):
            yield from _badge_keys_from(f"{path}.steps.{index}.badges", step.badges)
    elif isinstance(block, Fan):
        yield from _badge_keys_from(f"{path}.hub.badges", block.hub.badges)
        for index, spoke in enumerate(block.spokes):
            yield from _badge_keys_from(f"{path}.spokes.{index}.badges", spoke.badges)
    elif isinstance(block, Matrix):
        for index, cell in enumerate(block.cells):
            if cell.badge is not None:
                yield f"{path}.cells.{index}.badge", cell.badge
    elif isinstance(block, Table):
        badge_columns = [column.key for column in block.columns if column.kind == "badge"]
        for row_path, row in block.located_rows():
            for key in badge_columns:
                yield from _badge_keys_in_cell(f"{path}.{row_path}.{key}", row.get(key))


def _badge_keys_in_cell(path: str, value: Any) -> Iterator[tuple[str, str]]:
    placed = (
        [(f"{path}.{index}", key) for index, key in enumerate(cast("list[Any]", value))]
        if isinstance(value, list)
        else [(path, value)]
    )
    for place, candidate in placed:
        if isinstance(candidate, str) and (trimmed := candidate.strip()):
            yield place, trimmed


def iter_reference_items(blocks: Sequence[AnyBlock]) -> Iterator[ReferenceItem]:
    """Every reference item in the block tree (recursing into sections and grids), in document
    order. One source for both the derived numbering and the global key-uniqueness check."""
    for block in walk_blocks(blocks):
        if isinstance(block, References):
            yield from block.items


def iter_matrices(blocks: Sequence[AnyBlock]) -> Iterator[Matrix]:
    """Every matrix in the block tree (recursing into containers), in document order — for the derived
    cell tallies and the matrix-id uniqueness / `of_matrix` reference checks."""
    for block in walk_blocks(blocks):
        if isinstance(block, Matrix):
            yield block


def iter_tables(blocks: Sequence[AnyBlock]) -> Iterator[Table]:
    """Every table in the block tree (recursing into containers), in document order — for the derived
    row tallies and the table-id uniqueness / `of_tables` reference checks."""
    for block in walk_blocks(blocks):
        if isinstance(block, Table):
            yield block
