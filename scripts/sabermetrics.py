#!/usr/bin/env python3
"""
Shared "stat" math for the profile cards, so every card speaks the same
sabermetric dialect and the Glossary card can describe one implementation.

- plus_stat: a 100-neutral split stat (like OPS+ / wRC+). 100 = your normal
  rate, 130 = 30% above it. Small recent samples are regressed toward 100.
- percentile: rank of a value within a reference population (0-99).
- savant_color: Baseball Savant percentile-bubble color (cold blue -> neutral
  gray -> hot red).
"""

import math
from typing import List, Sequence

# Pseudo-count for regressing small splits toward the baseline rate: a split
# needs ~this many events before it can move far from 100.
PLUS_PRIOR = 25.0


def plus_stat(split_count: float, split_total: float, base_count: float, base_total: float,
              prior: float = PLUS_PRIOR) -> int:
    """100 * (split rate / baseline rate), with the split shrunk toward the
    baseline by `prior` pseudo-events. Returns 100 when there is no baseline."""
    if base_total <= 0 or base_count <= 0:
        return 100
    base_rate = base_count / base_total
    split_rate = (split_count + prior * base_rate) / (split_total + prior)
    return int(round(100 * split_rate / base_rate))


def rate_plus(split_events: float, split_days: float, base_events: float, base_days: float,
              prior_days: float = 7.0) -> int:
    """100-neutral pace stat for daily rates (events per day), regressing the
    split toward the baseline by `prior_days` of baseline-rate activity."""
    if base_days <= 0 or base_events <= 0:
        return 100
    base_rate = base_events / base_days
    split_rate = (split_events + prior_days * base_rate) / (split_days + prior_days)
    return int(round(100 * split_rate / base_rate))


def percentile(value: float, population: Sequence[float]) -> int:
    """Savant-style percentile: share of the population strictly below the
    value plus half the ties, clamped to 1-99 like Savant's bubbles."""
    if not population:
        return 50
    below = sum(1 for p in population if p < value)
    ties = sum(1 for p in population if p == value)
    pct = 100 * (below + 0.5 * ties) / len(population)
    return max(1, min(99, int(round(pct))))


def wrp_reps(lines: float, cap: float = 400.0) -> float:
    """Reps credited to one skill in one commit: sqrt of changed lines, capped.
    The sqrt rewards many focused commits over one giant dump."""
    return math.sqrt(max(0.0, min(cap, lines)))


# Savant poles. The neutral midpoint is a darker gray than Savant's so the
# white number inside the bubble stays legible at 50th percentile.
_COLD = (0x2B, 0x5F, 0xAD)
_NEUTRAL = (0x73, 0x7B, 0x86)
_HOT = (0xD2, 0x2D, 0x36)


def savant_color(pct: float) -> str:
    t = max(0.0, min(100.0, pct)) / 100.0
    if t < 0.5:
        a, b, f = _COLD, _NEUTRAL, t / 0.5
    else:
        a, b, f = _NEUTRAL, _HOT, (t - 0.5) / 0.5
    r, g, bl = (round(a[i] + (b[i] - a[i]) * f) for i in range(3))
    return f"#{r:02x}{g:02x}{bl:02x}"


def weighted_recent(weekly: List[float], weights: Sequence[float] = (1.0, 0.6, 0.36, 0.22)) -> float:
    """Recency-weighted sum over the newest-first weekly values."""
    return sum(w * v for w, v in zip(weights, weekly))


def era(failures: float, total: float, prior_failures: float = 0.5) -> float:
    """Actions ERA: failed workflow runs per 9 runs, like earned runs per 9
    innings. Lower is better; 4.50 is roughly baseball's league average.
    Small samples are regressed toward 4.50 by `prior_failures` phantom runs."""
    if total <= 0:
        return 4.50
    regressed = failures + prior_failures * (4.50 / 9.0) * 9.0 / 4.50
    return round(9.0 * regressed / (total + 9.0), 2)


def era_color(e: float) -> str:
    """Savant-ish poles for ERA: under 3.00 is elite green, over 6.00 is red."""
    if e <= 3.0:
        return "#1a7f37"
    if e >= 6.0:
        return "#cf222e"
    t = (e - 3.0) / 3.0
    a, b = (0x1A, 0x7F, 0x37), (0xCF, 0x22, 0x2E)
    r, g, bl = (round(a[i] + (b[i] - a[i]) * t) for i in range(3))
    return f"#{r:02x}{g:02x}{bl:02x}"
