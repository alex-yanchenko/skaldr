import math
from collections.abc import Sequence
from fractions import Fraction
from typing import Final

from skaldr.errors import ExportInvariantError

SHARE_DENOMINATOR_LIMIT: Final = 1_000_000


def apportioned(weights: Sequence[float], total: int) -> list[int]:
    exact = [Fraction(weight).limit_denominator(SHARE_DENOMINATOR_LIMIT) for weight in weights]
    if exact and not sum(exact):
        raise ExportInvariantError(f"cannot apportion {total} over weights that add up to nothing")
    quotas = [weight / sum(exact) * total for weight in exact]
    parts = [math.floor(quota) for quota in quotas]
    by_remainder = sorted(range(len(quotas)), key=lambda index: parts[index] - quotas[index])
    for index in by_remainder[: total - sum(parts)]:
        parts[index] += 1
    return parts


def apportioned_at_least(weights: Sequence[float], total: int, minimum: int) -> list[int]:
    floored: set[int] = set()
    while True:
        free = [index for index in range(len(weights)) if index not in floored]
        shared = apportioned([weights[index] for index in free], total - minimum * len(floored))
        too_small = {index for index, part in zip(free, shared, strict=True) if part < minimum}
        if not too_small:
            parts = dict.fromkeys(floored, minimum) | dict(zip(free, shared, strict=True))
            return [parts[index] for index in range(len(weights))]
        floored |= too_small
