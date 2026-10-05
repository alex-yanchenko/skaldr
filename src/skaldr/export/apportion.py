import math
from collections.abc import Sequence
from fractions import Fraction
from typing import Final

SHARE_DENOMINATOR_LIMIT: Final = 1_000_000


def apportioned(weights: Sequence[float], total: int) -> list[int]:
    exact = [Fraction(weight).limit_denominator(SHARE_DENOMINATOR_LIMIT) for weight in weights]
    quotas = [weight / sum(exact) * total for weight in exact]
    parts = [math.floor(quota) for quota in quotas]
    by_remainder = sorted(range(len(quotas)), key=lambda index: parts[index] - quotas[index])
    for index in by_remainder[: total - sum(parts)]:
        parts[index] += 1
    return parts
