"""Statistics for the benchmark's analysis (``evals/analysis.py``) — pure functions, standard library only.

One method per question, stated once:

* **A single rate** ``k / n``: the exact Clopper–Pearson interval (:func:`clopper_pearson`). It never gives a better
  score a lower bound, and it never collapses to a point at 0 or 1 (the scorer's percentile bootstrap switches to a
  Wilson interval over letters there, so 55/56 got [94.5–100] while 56/56 got [91.8–100]).
* **Two conditions on the same items, one read**: the discordant pairs ``b`` (the first right, the second wrong) and
  ``c`` (the other way round) are what a paired test sees. :func:`mcnemar_exact` is the two-sided exact binomial test
  on them, :func:`mcnemar_midp` its mid-p version (less conservative, reported beside it), and
  :func:`bonett_price` the interval of the paired difference ``(b − c) / n``.
* **Clustered items** (a photo and the PDF it was rendered from are one letter; a letter can hold several dates):
  :func:`cluster_signflip`, a sign-flip randomisation test on the per-cluster differences, exact up to
  :data:`SIGNFLIP_EXACT_MAX` non-zero clusters and Monte Carlo beyond; :func:`paired_cluster_bootstrap` for the
  interval of a paired difference, resampling clusters as the scorer does (``evals/metrics.py``).
* **Several comparisons in one family**: :func:`holm`.
* **Repeated reads** of the same letters: :func:`pass_all_k` (right in every read), :func:`pass_any_k` (right in at
  least one), :func:`flip_rate` (the answer is not identical in every read) and :func:`run_noise_share` (the share of
  the variance that lies within items, between reads).
* **Selective prediction** (does a flag catch the wrong dates?): :func:`auroc` with ties counted half, and
  :func:`aurc` — the area under the risk–coverage curve, with ties in the confidence averaged, its oracle and the
  excess over it (E-AURC).
* **Harm-weighted loss**: :func:`harm_loss` (``early + r · harmful`` per 100 dated items) and :func:`crossover`, the
  ratio ``r`` at which two conditions' losses are equal.

Everything that draws random numbers takes a seed, and the draws use only :meth:`random.Random.choices` and
:meth:`random.Random.getrandbits`, whose output is the same on every supported Python. Counts are added as integers or
fractions, so an answer does not depend on the order of its input.
"""

from __future__ import annotations

import math
import random
from bisect import bisect_left, bisect_right
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from fractions import Fraction
from statistics import NormalDist
from typing import Any, Literal

CONFIDENCE_LEVEL = 0.95
#: The seed of the final run's analysis (pre-registered): the sign-flip draws and the paired bootstrap.
SEED = 20261029
#: Up to this many non-zero clusters the sign-flip test is exact; beyond, :data:`SIGNFLIP_DRAWS` random sign patterns.
SIGNFLIP_EXACT_MAX = 20
SIGNFLIP_DRAWS = 100_000
BOOTSTRAP_RESAMPLES = 10_000
#: The largest denominator a float difference is read with (a mean over reads is a fraction like 1/3 or 2/3).
MAX_DENOMINATOR = 1_000_000

_BISECTIONS = 100
_CF_ITERATIONS = 2000
_CF_EPSILON = 3e-16
_TINY = 1e-300

# --------------------------------------------------------------------------------------------------
# Single rates
# --------------------------------------------------------------------------------------------------


def _betacf(a: float, b: float, x: float) -> float:
    """The continued fraction of the incomplete beta function (modified Lentz)."""
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    d = 1.0 / (d if abs(d) > _TINY else _TINY)
    h = d
    for m in range(1, _CF_ITERATIONS):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > _TINY else _TINY)
        c = 1.0 + aa / c
        c = c if abs(c) > _TINY else _TINY
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > _TINY else _TINY)
        c = 1.0 + aa / c
        c = c if abs(c) > _TINY else _TINY
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < _CF_EPSILON:
            break
    return h


def betainc(a: float, b: float, x: float) -> float:
    """The regularised incomplete beta function ``I_x(a, b)`` (``a``, ``b`` > 0)."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    front = math.exp(
        math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log1p(-x)
    )
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def beta_quantile(q: float, a: float, b: float) -> float:
    """The ``q``-quantile of the Beta(``a``, ``b``) distribution, by bisection."""
    lo, hi = 0.0, 1.0
    for _ in range(_BISECTIONS):
        mid = (lo + hi) / 2.0
        if mid in (lo, hi):
            break
        if betainc(a, b, mid) < q:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def clopper_pearson(k: int, n: int, *, level: float = CONFIDENCE_LEVEL) -> tuple[float, float]:
    """The exact (Clopper–Pearson) interval of the rate ``k / n``; ``ValueError`` unless 0 ≤ k ≤ n and n > 0.

    At ``k = 0`` the lower bound is 0 and the upper one ``1 − (α/2)^(1/n)``; at ``k = n`` the upper bound is 1 and
    the lower one ``(α/2)^(1/n)``.
    """
    if n <= 0 or not 0 <= k <= n:
        raise ValueError(f"a rate needs 0 <= k <= n and n > 0, not {k}/{n}")
    tail = (1.0 - level) / 2.0
    if k == 0:
        lo = 0.0
    elif k == n:
        lo = tail ** (1.0 / n)
    else:
        lo = beta_quantile(tail, k, n - k + 1)
    if k == n:
        hi = 1.0
    elif k == 0:
        hi = 1.0 - tail ** (1.0 / n)
    else:
        hi = beta_quantile(1.0 - tail, k + 1, n - k)
    return lo, hi


# --------------------------------------------------------------------------------------------------
# Paired comparisons, one read
# --------------------------------------------------------------------------------------------------


def _half_binomial_cdf(k: int, n: int) -> Fraction:
    """``P(X ≤ k)`` for ``X ~ Binomial(n, 1/2)``, exactly."""
    return Fraction(sum(math.comb(n, i) for i in range(k + 1)), 2**n)


def mcnemar_exact(b: int, c: int) -> float:
    """The two-sided exact McNemar test on ``b`` and ``c`` discordant pairs: ``min(1, 2 · P(X ≤ min(b, c)))`` for
    ``X ~ Binomial(b + c, 1/2)``. 1 without discordant pairs."""
    n = b + c
    if n == 0:
        return 1.0
    return float(min(Fraction(1), 2 * _half_binomial_cdf(min(b, c), n)))


def mcnemar_midp(b: int, c: int) -> float:
    """The mid-p McNemar test: the exact test's tail with half the probability of the observed split,
    ``2 · (P(X < m) + P(X = m) / 2)`` for ``m = min(b, c)``; 1 when ``b == c``."""
    n = b + c
    if n == 0:
        return 1.0
    m = min(b, c)
    below = _half_binomial_cdf(m - 1, n) if m > 0 else Fraction(0)
    p = 2 * below + Fraction(math.comb(n, m), 2**n)
    return float(min(Fraction(1), p))


def _z(level: float) -> float:
    return NormalDist().inv_cdf(0.5 + level / 2.0)


def bonett_price(b: int, c: int, n: int, *, level: float = CONFIDENCE_LEVEL) -> tuple[float, float]:
    """Bonett and Price's (2012) adjusted Wald interval for a paired difference of proportions, ``(b − c) / n``.

    Each discordant cell gets one added (``(b + 1) / (n + 2)``, ``(c + 1) / (n + 2)``), which keeps the interval
    honest at 0 discordant pairs. Clipped to [−1, 1].
    """
    if n <= 0 or b < 0 or c < 0 or b + c > n:
        raise ValueError(f"discordant pairs {b} and {c} do not fit {n} items")
    p12, p21 = (b + 1) / (n + 2), (c + 1) / (n + 2)
    diff = p12 - p21
    se = math.sqrt((p12 + p21 - diff * diff) / (n + 2))
    z = _z(level)
    return max(-1.0, diff - z * se), min(1.0, diff + z * se)


def holm(pvalues: Sequence[float]) -> list[float]:
    """Holm's step-down adjusted p-values, in the order given (the order does not change any value)."""
    m = len(pvalues)
    order = sorted(range(m), key=lambda i: (pvalues[i], i))
    adjusted = [1.0] * m
    running = 0.0
    for rank, index in enumerate(order):
        running = max(running, min(1.0, (m - rank) * pvalues[index]))
        adjusted[index] = running
    return adjusted


# --------------------------------------------------------------------------------------------------
# Clustered comparisons
# --------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class SignFlip:
    """A two-sided sign-flip test: ``p = P(|Σ ±d_j| ≥ |Σ d_j|)`` over independent signs per cluster."""

    statistic: float
    p: float
    clusters: int
    nonzero: int
    method: Literal["exact", "monte-carlo"]
    draws: int | None = None
    seed: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _fraction(value: int | float | Fraction) -> Fraction:
    if isinstance(value, Fraction):
        return value
    if isinstance(value, int):
        return Fraction(value)
    return Fraction(value).limit_denominator(MAX_DENOMINATOR)


def _on_a_lattice(values: Sequence[int | float | Fraction]) -> list[int]:
    """The values as integers on their common denominator (the test does not depend on a common scale)."""
    fractions = [_fraction(value) for value in values]
    denominator = math.lcm(*(f.denominator for f in fractions)) if fractions else 1
    return [int(f * denominator) for f in fractions]


def cluster_signflip(
    differences: Sequence[int | float | Fraction],
    *,
    exact_max: int = SIGNFLIP_EXACT_MAX,
    draws: int = SIGNFLIP_DRAWS,
    seed: int = SEED,
) -> SignFlip:
    """The paired sign-flip randomisation test on per-cluster differences (first condition minus second).

    Under "no difference" each cluster's difference is as likely positive as negative. The statistic is the sum;
    the p-value is the share of sign patterns whose sum is at least as far from 0. With at most ``exact_max``
    non-zero clusters every pattern is counted (exactly); beyond, ``draws`` random patterns are drawn with ``seed``
    and ``p = (hits + 1) / (draws + 1)``, which is never 0. With one item per cluster (differences −1, 0, 1) the exact
    test is the exact McNemar test.
    """
    lattice = _on_a_lattice(differences)
    nonzero = [value for value in lattice if value]
    total = sum(nonzero)
    statistic = float(sum(_fraction(value) for value in differences))
    observed = abs(total)
    if len(nonzero) <= exact_max:
        counts: dict[int, int] = {0: 1}
        for value in nonzero:
            step: dict[int, int] = defaultdict(int)
            for partial, count in counts.items():
                step[partial + value] += count
                step[partial - value] += count
            counts = step
        hits = sum(count for partial, count in counts.items() if abs(partial) >= observed)
        p = float(Fraction(hits, 2 ** len(nonzero)))
        return SignFlip(statistic, p, len(lattice), len(nonzero), "exact")
    # T* = T − 2 · (sum of the flipped values); the flipped set is a random bit mask, summed by 8-bit tables
    chunks: list[tuple[int, list[int]]] = []
    for start in range(0, len(nonzero), 8):
        part = nonzero[start : start + 8]
        table = [
            sum(value for bit, value in enumerate(part) if mask >> bit & 1) for mask in range(1 << len(part))
        ]
        chunks.append((start, table))
    rng = random.Random(seed)
    width = len(nonzero)
    hits = 0
    for _ in range(draws):
        mask = rng.getrandbits(width)
        flipped = sum(table[(mask >> start) & 0xFF] for start, table in chunks)
        if abs(total - 2 * flipped) >= observed:
            hits += 1
    return SignFlip(
        statistic, (hits + 1) / (draws + 1), len(lattice), len(nonzero), "monte-carlo", draws=draws, seed=seed
    )


def percentile(values: Sequence[float], q: float) -> float | None:
    """The ``q``-th percentile (0–100) with linear interpolation, as ``evals.metrics.percentile``; ``None`` for no
    values. Infinite values sort last; a percentile that touches one is infinite."""
    ordered = sorted(values)
    if not ordered:
        return None
    position = (len(ordered) - 1) * q / 100.0
    low, high = math.floor(position), math.ceil(position)
    if math.isinf(ordered[high]) and (high != low or math.isinf(ordered[low])):
        return math.inf
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


@dataclass(frozen=True)
class PairedBootstrap:
    """A paired difference of two rates over the same clusters, with a percentile cluster-bootstrap interval."""

    diff: float | None
    lo: float | None
    hi: float | None
    clusters: int
    resamples: int
    seed: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def paired_cluster_bootstrap(
    clusters: Sequence[tuple[float, float, float]],
    *,
    resamples: int = BOOTSTRAP_RESAMPLES,
    seed: int = SEED,
    level: float = CONFIDENCE_LEVEL,
) -> PairedBootstrap:
    """``Σa / Σn − Σb / Σn`` for clusters ``(a, b, n)`` (the first condition's hits, the second's, the items), with a
    percentile bootstrap that resamples clusters with replacement.

    It draws as :func:`evals.metrics.bootstrap_difference` does, so the same clusters (in the scorer's order), seed
    and resamples give the scorer's published interval.
    """
    pairs = list(clusters)
    total_n = sum(c[2] for c in pairs)
    if total_n <= 0:
        return PairedBootstrap(None, None, None, len(pairs), resamples, seed)
    rng = random.Random(seed)
    draws = []
    for _ in range(resamples):
        drawn = rng.choices(pairs, k=len(pairs))
        n = sum(c[2] for c in drawn)
        if n > 0:
            draws.append(sum(c[0] for c in drawn) / n - sum(c[1] for c in drawn) / n)
    alpha = (1.0 - level) / 2.0 * 100.0
    diff = sum(c[0] for c in pairs) / total_n - sum(c[1] for c in pairs) / total_n
    return PairedBootstrap(
        diff, percentile(draws, alpha), percentile(draws, 100.0 - alpha), len(pairs), resamples, seed
    )


def cluster_bootstrap(
    clusters: Sequence[tuple[float, float]],
    *,
    resamples: int = BOOTSTRAP_RESAMPLES,
    seed: int = SEED,
    level: float = CONFIDENCE_LEVEL,
) -> tuple[float | None, float | None, float | None]:
    """``Σk / Σn`` over clusters ``(k, n)`` with a percentile cluster-bootstrap interval (for a mean over reads, where
    an exact interval does not apply): ``(value, lo, hi)``."""
    pairs = list(clusters)
    total_n = sum(c[1] for c in pairs)
    if total_n <= 0:
        return None, None, None
    rng = random.Random(seed)
    draws = []
    for _ in range(resamples):
        drawn = rng.choices(pairs, k=len(pairs))
        n = sum(c[1] for c in drawn)
        if n > 0:
            draws.append(sum(c[0] for c in drawn) / n)
    alpha = (1.0 - level) / 2.0 * 100.0
    return sum(c[0] for c in pairs) / total_n, percentile(draws, alpha), percentile(draws, 100.0 - alpha)


# --------------------------------------------------------------------------------------------------
# Repeated reads
# --------------------------------------------------------------------------------------------------


def _reads(rows: Sequence[Sequence[Any]]) -> int:
    """The number of reads per item; ``ValueError`` unless every item has the same number, at least one."""
    widths = {len(row) for row in rows}
    if len(widths) > 1 or 0 in widths:
        raise ValueError("every item needs the same number of reads, at least one")
    return widths.pop() if widths else 0


def pass_all_k(reads: Sequence[Sequence[bool]]) -> tuple[int, int]:
    """(items right in every read, items) — pass^k."""
    _reads(reads)
    return sum(1 for row in reads if all(row)), len(reads)


def pass_any_k(reads: Sequence[Sequence[bool]]) -> tuple[int, int]:
    """(items right in at least one read, items) — pass@k."""
    _reads(reads)
    return sum(1 for row in reads if any(row)), len(reads)


def flip_rate(values: Sequence[Sequence[Any]]) -> tuple[int, int]:
    """(items whose answer — a date, or ``None`` for no date — is not identical in every read, items)."""
    _reads(values)
    return sum(1 for row in values if any(value != row[0] for value in row[1:])), len(values)


def run_noise_share(values: Sequence[Sequence[float]]) -> float | None:
    """The share of the variance of item × read values that lies within items: ``mean_i s²_i / s²``, with population
    variances (so it is between 0 and 1; the rest is the variance between items). ``None`` without any variance."""
    _reads(values)
    if not values:
        return None
    rows = [[Fraction(value) for value in row] for row in values]

    def variance(xs: Sequence[Fraction]) -> Fraction:
        mean = sum(xs, Fraction(0)) / len(xs)
        return sum(((x - mean) ** 2 for x in xs), Fraction(0)) / len(xs)

    total = variance([x for row in rows for x in row])
    if total == 0:
        return None
    within = sum((variance(row) for row in rows), Fraction(0)) / len(rows)
    return float(within / total)


# --------------------------------------------------------------------------------------------------
# Selective prediction
# --------------------------------------------------------------------------------------------------


def auroc(positive: Sequence[float], negative: Sequence[float]) -> float | None:
    """``P(a positive scores higher than a negative)``, ties counted half (the Mann–Whitney AUC); ``None`` if either
    side is empty. With "this date is wrong" as the positive and the flag level as the score, 0.5 is chance."""
    if not positive or not negative:
        return None
    ordered = sorted(negative)
    twice = 0
    for score in positive:
        below, through = bisect_left(ordered, score), bisect_right(ordered, score)
        twice += 2 * below + (through - below)
    return float(Fraction(twice, 2 * len(positive) * len(ordered)))


@dataclass(frozen=True)
class RiskCoverage:
    """The area under the risk–coverage curve (AURC), its oracle (every error last) and the excess (E-AURC)."""

    aurc: float
    oracle: float
    excess: float
    n: int
    errors: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def aurc(confidence: Sequence[float], errors: Sequence[bool]) -> RiskCoverage | None:
    """AURC: items are kept from the most confident down; the risk at each coverage is the error rate among the kept.

    Items with the same confidence cannot be ordered, so within a tie group the errors are spread evenly (the
    expected risk over every order of the group). ``None`` for no items.
    """
    if len(confidence) != len(errors):
        raise ValueError("one error flag per confidence value")
    n = len(confidence)
    if n == 0:
        return None
    groups: dict[float, list[int]] = defaultdict(lambda: [0, 0])
    for value, wrong in zip(confidence, errors, strict=True):
        groups[value][0] += 1
        groups[value][1] += int(wrong)
    risks: list[float] = []
    kept, wrong_kept = 0, 0
    for value in sorted(groups, reverse=True):
        size, group_errors = groups[value]
        for j in range(1, size + 1):
            risks.append((wrong_kept + group_errors * j / size) / (kept + j))
        kept += size
        wrong_kept += group_errors
    total_errors = wrong_kept
    area = math.fsum(risks) / n
    oracle = math.fsum(max(0, i - (n - total_errors)) / i for i in range(1, n + 1)) / n
    return RiskCoverage(area, oracle, area - oracle, n, total_errors)


# --------------------------------------------------------------------------------------------------
# Harm-weighted loss
# --------------------------------------------------------------------------------------------------


def harm_loss(early: int, harmful: int, n: int, r: float) -> float:
    """``100 · (early + r · harmful) / n``: the loss per 100 dated items when a harmful (late or missed) date costs
    ``r`` early ones; NaN for no items."""
    if n <= 0:
        return math.nan
    return 100.0 * (early + r * harmful) / n


def crossover(early_a: int, harmful_a: int, early_b: int, harmful_b: int) -> float | None:
    """The cost ratio ``r*`` at which a's and b's losses are equal, when a has more harmful dates than b: below it a's
    loss is lower, above it b's. ``None`` when a has no more harmful dates than b (b never overtakes a as ``r``
    grows). A negative value means b's loss is lower at every ``r ≥ 0``."""
    if harmful_a <= harmful_b:
        return None
    return (early_b - early_a) / (harmful_a - harmful_b)


__all__ = [
    "BOOTSTRAP_RESAMPLES",
    "CONFIDENCE_LEVEL",
    "SEED",
    "SIGNFLIP_DRAWS",
    "SIGNFLIP_EXACT_MAX",
    "PairedBootstrap",
    "RiskCoverage",
    "SignFlip",
    "aurc",
    "auroc",
    "beta_quantile",
    "betainc",
    "bonett_price",
    "clopper_pearson",
    "cluster_bootstrap",
    "cluster_signflip",
    "crossover",
    "flip_rate",
    "harm_loss",
    "holm",
    "mcnemar_exact",
    "mcnemar_midp",
    "paired_cluster_bootstrap",
    "pass_all_k",
    "pass_any_k",
    "percentile",
    "run_noise_share",
]
