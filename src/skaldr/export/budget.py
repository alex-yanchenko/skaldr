from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace

from typing_extensions import Self

from skaldr.export.tree import Node


@dataclass(frozen=True)
class RenderedBlock:
    node: Node
    lines: tuple[str, ...]


Measure = Callable[[RenderedBlock], int]


@dataclass(frozen=True)
class Cost:
    amounts: tuple[int, ...]

    def __add__(self, other: Self) -> Self:
        return replace(
            self,
            amounts=tuple(mine + theirs for mine, theirs in zip(self.amounts, other.amounts, strict=True)),
        )


@dataclass(frozen=True)
class Limit:
    measure: Measure
    most: int


@dataclass(frozen=True)
class Budget:
    limits: tuple[Limit, ...]

    @property
    def nothing(self) -> Cost:
        return Cost((0,) * len(self.limits))

    def cost(self, block: RenderedBlock) -> Cost:
        return Cost(tuple(limit.measure(block) for limit in self.limits))

    def total(self, costs: Iterable[Cost]) -> Cost:
        return sum(costs, self.nothing)

    def allows(self, cost: Cost) -> bool:
        return all(amount <= limit.most for amount, limit in zip(cost.amounts, self.limits, strict=True))


def characters(block: RenderedBlock) -> int:
    return sum(len(line) + 1 for line in block.lines)


def character_budget(most: int) -> Budget:
    return Budget((Limit(characters, most),))
