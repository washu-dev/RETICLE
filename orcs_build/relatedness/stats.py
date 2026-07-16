"""Small, dependency-free statistics for the relatedness pipeline.

All counts here are screen-level (N <= ~33), so the exact hypergeometric via math.comb
is both fast and exact — no SciPy needed.
"""
from __future__ import annotations

import math


# ---------------------------------------------------------------------------
# Fisher's exact test (2x2), right-tailed enrichment + odds ratio
# ---------------------------------------------------------------------------
def fisher_right(a: int, b: int, c: int, d: int) -> float:
    """Right-tail p-value for the 2x2 table [[a, b], [c, d]].

    a = both hit, b = row-only hit, c = col-only hit, d = neither.
    Tests whether the overlap `a` is larger than expected under independence.
    """
    row1, col1, n = a + b, a + c, a + b + c + d
    if row1 == 0 or col1 == 0 or n == 0:
        return 1.0
    col2 = n - col1
    denom = math.comb(n, row1)
    kmax = min(row1, col1)
    total = 0
    for k in range(a, kmax + 1):
        j = row1 - k
        if j < 0 or j > col2:
            continue
        total += math.comb(col1, k) * math.comb(col2, j)
    return min(1.0, total / denom)


def odds_ratio(a: int, b: int, c: int, d: int) -> float:
    """Haldane-corrected odds ratio (adds 0.5 to every cell when any cell is 0)."""
    if 0 in (a, b, c, d):
        a, b, c, d = a + 0.5, b + 0.5, c + 0.5, d + 0.5
    return (a * d) / (b * c)


def binom_right(a: int, n: int, p: float) -> float:
    """P(X >= a) for X ~ Binomial(n, p). Tests co-hit specificity vs a gene's own
    background hit rate `p` (guards against pan-essential 'hub' genes)."""
    if n <= 0 or a <= 0:
        return 1.0
    p = min(max(p, 1e-9), 1.0 - 1e-9)
    total = 0.0
    for k in range(a, n + 1):
        total += math.comb(n, k) * (p ** k) * ((1 - p) ** (n - k))
    return min(1.0, total)


def jaccard(set_a: set, set_b: set) -> float:
    if not set_a and not set_b:
        return 0.0
    return len(set_a & set_b) / len(set_a | set_b)


# ---------------------------------------------------------------------------
# Spearman rank correlation (average-rank ties), stdlib
# ---------------------------------------------------------------------------
def _ranks(xs: list[float]) -> list[float]:
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0     # 1-based average rank
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 0 or syy <= 0:
        return None
    return sxy / math.sqrt(sxx * syy)


def spearman(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) != len(ys) or len(xs) < 3:
        return None
    return _pearson(_ranks(xs), _ranks(ys))


def spearman_pvalue(rho: float, n: int) -> float:
    """Two-sided p-value via the t approximation (fine for a screening prior)."""
    if rho is None or n < 4 or abs(rho) >= 1.0:
        return 1.0
    t = rho * math.sqrt((n - 2) / (1 - rho * rho))
    # survival function of |t| with df=n-2 via the regularized incomplete beta
    df = n - 2
    x = df / (df + t * t)
    p = _betainc(df / 2.0, 0.5, x)      # = 2 * P(T > |t|)
    return max(0.0, min(1.0, p))


def _betainc(a: float, b: float, x: float) -> float:
    """Regularized incomplete beta I_x(a,b) (Numerical Recipes betai)."""
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    lbeta = math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)
    bt = math.exp(-lbeta + a * math.log(x) + b * math.log(1 - x))
    if x < (a + 1) / (a + b + 2):
        return bt * _betacf(a, b, x) / a
    return 1.0 - bt * _betacf(b, a, 1 - x) / b


def _betacf(a: float, b: float, x: float, itmax: int = 200, eps: float = 1e-12) -> float:
    tiny = 1e-30
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < tiny:
        d = tiny
    d = 1.0 / d
    h = d
    for mm in range(1, itmax + 1):
        m2 = 2 * mm
        aa = mm * (b - mm) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + aa / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        h *= d * c
        aa = -(a + mm) * (qab + mm) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + aa / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        de = d * c
        h *= de
        if abs(de - 1.0) < eps:
            break
    return h


# ---------------------------------------------------------------------------
# Benjamini-Hochberg FDR
# ---------------------------------------------------------------------------
def bh_fdr(pvals: list[float]) -> list[float]:
    """Return BH-adjusted q-values in the original order."""
    n = len(pvals)
    if n == 0:
        return []
    order = sorted(range(n), key=lambda i: pvals[i])
    q = [0.0] * n
    prev = 1.0
    for rank in range(n, 0, -1):
        i = order[rank - 1]
        val = min(prev, pvals[i] * n / rank)
        q[i] = val
        prev = val
    return q
