"""Oracle aggregation math — mirror of CarbonOracle.sol (Phase 4). STATUS: IMPLEMENTED. Pure, stdlib only."""
from __future__ import annotations

from collections.abc import Sequence


def median_lower(values: Sequence[int]) -> int:
    """Lower median sorted[(k - 1) // 2]; k >= 1 (CarbonOracle.medianLower)."""
    if not values:
        raise ValueError("empty")
    s = sorted(values)
    return s[(len(s) - 1) // 2]


def spread(values: Sequence[int]) -> int:
    return max(values) - min(values)
