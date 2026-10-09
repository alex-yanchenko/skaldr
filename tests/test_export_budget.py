import pytest

from skaldr.export.budget import Budget, Cost, Limit, RenderedBlock, character_budget, characters
from skaldr.export.tree import Heading, Paragraph, TableCell, TableNode, TableRow
from skaldr.richtext import Plain


def _rendered_blocks(block: RenderedBlock) -> int:
    return 1 if block.lines else 0


CHARACTERS_AND_BLOCKS = Budget((Limit(characters, 10), Limit(_rendered_blocks, 2)))


def test_characters_count_each_line_and_its_newline() -> None:
    assert characters(RenderedBlock(Paragraph((Plain("abc"),)), ("abc", "de"))) == len("abc\nde\n")


def test_a_character_budget_holds_one_character_limit() -> None:
    assert character_budget(40) == Budget((Limit(characters, 40),))


def test_a_budget_costs_a_rendered_block_once_per_limit() -> None:
    assert CHARACTERS_AND_BLOCKS.cost(RenderedBlock(Heading(2, (Plain("A"),)), ("## A",))) == Cost((5, 1))


def test_a_measure_reads_the_node_as_well_as_its_lines() -> None:
    def table_rows(block: RenderedBlock) -> int:
        return len(block.node.rows) if isinstance(block.node, TableNode) else 0

    table = TableNode((TableCell((Plain("H"),)),), (TableRow((TableCell((Plain("x"),)),)),) * 3)

    assert Budget((Limit(table_rows, 5),)).cost(RenderedBlock(table, ())) == Cost((3,))


@pytest.mark.parametrize(
    ("cost", "allowed"),
    [
        pytest.param(Cost((10, 2)), True, id="every-amount-at-its-limit"),
        pytest.param(Cost((0, 0)), True, id="nothing"),
        pytest.param(Cost((11, 2)), False, id="characters-over"),
        pytest.param(Cost((10, 3)), False, id="blocks-over"),
        pytest.param(Cost((11, 3)), False, id="both-over"),
    ],
)
def test_a_budget_allows_a_cost_only_when_every_amount_is_within_its_limit(cost: Cost, allowed: bool) -> None:
    assert CHARACTERS_AND_BLOCKS.allows(cost) is allowed


def test_a_budget_with_no_limits_allows_any_cost() -> None:
    assert Budget(()).allows(Cost(())) is True


def test_nothing_costs_zero_in_every_measure_of_the_budget() -> None:
    assert CHARACTERS_AND_BLOCKS.nothing == Cost((0, 0))


def test_costs_add_and_subtract_amount_by_amount() -> None:
    assert (Cost((7, 1)) + Cost((3, 2)), Cost((7, 1)) - Cost((3, 2))) == (Cost((10, 3)), Cost((4, -1)))


def test_the_total_of_no_costs_is_nothing() -> None:
    assert CHARACTERS_AND_BLOCKS.total([]) == Cost((0, 0))


def test_the_total_adds_every_cost() -> None:
    assert CHARACTERS_AND_BLOCKS.total([Cost((4, 1)), Cost((5, 1)), Cost((1, 0))]) == Cost((10, 2))


def test_a_budget_less_what_was_spent_lowers_each_limit_by_its_amount() -> None:
    assert CHARACTERS_AND_BLOCKS.less(Cost((4, 3))) == Budget(
        (Limit(characters, 6), Limit(_rendered_blocks, -1))
    )


def test_costs_measured_against_different_budgets_do_not_add() -> None:
    with pytest.raises(ValueError, match=r"^zip\(\) argument 2 is longer than argument 1$"):
        _ = Cost((1,)) + Cost((1, 1))


def test_a_cost_measured_against_another_budget_is_not_judged() -> None:
    with pytest.raises(ValueError, match=r"^zip\(\) argument 2 is shorter than argument 1$"):
        CHARACTERS_AND_BLOCKS.allows(Cost((1, 1, 1)))
