"""
metrics/stats.py — inferential statistics for the architecture comparison.

Until now the campaign reported per-cell Wilson intervals only. An
interval says how precisely one cell was measured; it does not test
whether two architectures differ. A reviewer asking "is C actually
different from A, or did you just draw two bars?" needs a test.

Pure Python — no scipy. The sample sizes here (n <= 30 per cell) are
small enough that exact and normal-approximation methods are cheap, and
adding a heavyweight dependency to a reproducibility artefact costs more
than it buys.

Contents
--------
fisher_exact        two-sided exact test for a 2x2 detection table
mann_whitney_u      two-sided rank test for MTTD / continuous metrics
bootstrap_diff_median   CI for a difference of medians (skewed metrics)
newcombe_diff_ci    CI for a difference of proportions (score-based)
holm                Holm-Bonferroni adjustment over a declared family

On multiplicity
---------------
Correction is applied ONLY over the pre-declared primary family (the
takeout comparisons that carry the thesis claim). Everything else is
reported uncorrected and labelled exploratory. Correcting over every
comparison ever computed would penalise the primary claim for the
existence of secondary curiosity, which is the wrong trade.
"""

from __future__ import annotations

import math
import random
from typing import Optional


# --- normal helpers ----------------------------------------------------


def normal_cdf(z: float) -> float:
    """Phi(z) via the error function. Exact enough for reporting."""
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


# --- categorical -------------------------------------------------------


def fisher_exact(a: int, b: int, c: int, d: int) -> float:
    """Two-sided Fisher exact p for the table [[a, b], [c, d]].

    Rows are groups, columns are outcome (detected / not). Two-sided is
    taken by summing every table at least as extreme as the observed one
    in probability, which is the standard definition and does not assume
    symmetry of the null distribution.
    """
    r1, r2 = a + b, c + d
    c1 = a + c
    n = r1 + r2
    if n == 0 or r1 == 0 or r2 == 0 or c1 == 0 or (b + d) == 0:
        return 1.0

    def prob(k: int) -> float:
        return (math.comb(r1, k) * math.comb(r2, c1 - k)) / math.comb(n, c1)

    lo = max(0, c1 - r2)
    hi = min(r1, c1)
    p_obs = prob(a)
    total = 0.0
    for k in range(lo, hi + 1):
        p = prob(k)
        if p <= p_obs * (1.0 + 1e-9):
            total += p
    return min(1.0, total)


def wilson_bounds(k: int, n: int, z: float = 1.96) -> tuple:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1.0 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def newcombe_diff_ci(k1: int, n1: int, k2: int, n2: int, z: float = 1.96) -> tuple:
    """Newcombe hybrid-score CI for p1 - p2.

    Behaves at the boundaries (0/28, 30/30) where a Wald interval runs
    off the end of the scale — which is exactly where this campaign
    lives, so the choice matters rather than being pedantry.
    """
    if n1 == 0 or n2 == 0:
        return (0.0, 0.0)
    p1, p2 = k1 / n1, k2 / n2
    l1, u1 = wilson_bounds(k1, n1, z)
    l2, u2 = wilson_bounds(k2, n2, z)
    lower = (p1 - p2) - math.sqrt((p1 - l1) ** 2 + (u2 - p2) ** 2)
    upper = (p1 - p2) + math.sqrt((u1 - p1) ** 2 + (p2 - l2) ** 2)
    return (max(-1.0, lower), min(1.0, upper))


# --- continuous --------------------------------------------------------


def _rank(values: list) -> list:
    """Average ranks, 1-based, ties shared."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def mann_whitney_u(x: list, y: list) -> Optional[tuple]:
    """(U, two-sided p) by normal approximation with tie and continuity
    correction. Returns None when either sample is empty.

    Rank-based on purpose: MTTD and mission degradation are not normal
    and contain a heavy tail from false-positive recoveries.
    """
    x = [v for v in x if isinstance(v, (int, float))]
    y = [v for v in y if isinstance(v, (int, float))]
    n1, n2 = len(x), len(y)
    if n1 == 0 or n2 == 0:
        return None
    pooled = x + y
    ranks = _rank(pooled)
    r1 = sum(ranks[:n1])
    u1 = r1 - n1 * (n1 + 1) / 2.0
    mu = n1 * n2 / 2.0

    counts = {}
    for v in pooled:
        counts[v] = counts.get(v, 0) + 1
    n = n1 + n2
    tie_term = sum(t ** 3 - t for t in counts.values())
    if n < 2:
        return (u1, 1.0)
    var = (n1 * n2 / 12.0) * ((n + 1) - tie_term / (n * (n - 1)))
    if var <= 0:
        return (u1, 1.0)
    z = (abs(u1 - mu) - 0.5) / math.sqrt(var)
    p = 2.0 * (1.0 - normal_cdf(max(0.0, z)))
    return (u1, min(1.0, p))


def bootstrap_diff_median(
    x: list, y: list, iterations: int = 10000, seed: int = 20260731
) -> Optional[tuple]:
    """(observed diff of medians, lo, hi) percentile CI for median(x) - median(y).

    Seeded so the reported interval is reproducible from the artefact.
    """
    x = [v for v in x if isinstance(v, (int, float))]
    y = [v for v in y if isinstance(v, (int, float))]
    if len(x) < 2 or len(y) < 2:
        return None
    rng = random.Random(seed)

    def median(vals: list) -> float:
        s = sorted(vals)
        m = len(s)
        return s[m // 2] if m % 2 else (s[m // 2 - 1] + s[m // 2]) / 2.0

    observed = median(x) - median(y)
    diffs = []
    for _ in range(iterations):
        bx = [x[rng.randrange(len(x))] for _ in range(len(x))]
        by = [y[rng.randrange(len(y))] for _ in range(len(y))]
        diffs.append(median(bx) - median(by))
    diffs.sort()
    lo = diffs[int(0.025 * len(diffs))]
    hi = diffs[min(len(diffs) - 1, int(0.975 * len(diffs)))]
    return (observed, lo, hi)


# --- multiplicity ------------------------------------------------------


def holm(pvalues: dict) -> dict:
    """Holm-Bonferroni adjusted p-values, keyed as the input.

    Step-down: controls the family-wise error rate without assuming the
    tests are independent, which they are not (the same runs feed
    several comparisons).
    """
    items = sorted(pvalues.items(), key=lambda kv: kv[1])
    m = len(items)
    adjusted = {}
    running = 0.0
    for i, (key, p) in enumerate(items):
        val = min(1.0, (m - i) * p)
        running = max(running, val)
        adjusted[key] = running
    return adjusted


def stars(p: Optional[float]) -> str:
    if p is None:
        return ""
    if p < 0.001:
        return "***"
    if p < 0.01:
        return "**"
    if p < 0.05:
        return "*"
    return "ns"
