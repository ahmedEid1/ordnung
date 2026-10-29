"""Known values and properties of the benchmark's statistics (``evals/stats.py``).

The known values come from the published held-out results, recomputed by hand or by independent scripts in the
evaluation plan: Clopper–Pearson 55/56, 56/56, 163/168 and 0/112; exact McNemar 31 vs 4 and 14 vs 5; Bonett–Price
on the pooled held-out discordant pairs. The properties are the ones the plan names: a better score never gets a
lower lower bound, Holm does not depend on the order of its input, and the cluster sign-flip test is exact McNemar
when every cluster holds one item.
"""

from __future__ import annotations

import itertools
import math
import sys
from fractions import Fraction
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals import metrics, stats  # noqa: E402

# --------------------------------------------------------------------------------------------------
# Clopper–Pearson
# --------------------------------------------------------------------------------------------------


def test_clopper_pearson_known_values() -> None:
    lo, hi = stats.clopper_pearson(55, 56)
    assert lo == pytest.approx(0.9045, abs=5e-5) and hi == pytest.approx(0.99955, abs=5e-6)
    lo, hi = stats.clopper_pearson(56, 56)
    assert lo == pytest.approx(0.9362, abs=5e-5) and hi == 1.0
    lo, hi = stats.clopper_pearson(163, 168)
    assert lo == pytest.approx(0.9319, abs=5e-5) and hi == pytest.approx(0.9903, abs=5e-5)
    lo, hi = stats.clopper_pearson(0, 112)
    assert lo == 0.0 and hi == pytest.approx(0.0324, abs=5e-5)
    # textbook: 5 of 10 → [0.187, 0.813]; 0 of 10 → upper 0.308
    lo, hi = stats.clopper_pearson(5, 10)
    assert lo == pytest.approx(0.1871, abs=5e-5) and hi == pytest.approx(0.8129, abs=5e-5)
    assert stats.clopper_pearson(0, 10)[1] == pytest.approx(0.3085, abs=5e-5)


def test_clopper_pearson_closed_forms_at_the_edges() -> None:
    """k = n: the lower bound is (α/2)^(1/n); k = 0: the upper bound is 1 − (α/2)^(1/n)."""
    for n in (1, 7, 56, 168):
        assert stats.clopper_pearson(n, n)[0] == pytest.approx(0.025 ** (1 / n), rel=1e-12)
        assert stats.clopper_pearson(0, n)[1] == pytest.approx(1 - 0.025 ** (1 / n), rel=1e-12)


@pytest.mark.parametrize("n", [1, 2, 5, 13, 56, 112])
def test_a_better_score_never_gets_a_lower_bound(n: int) -> None:
    """The published flaw: 55/56 got [94.5–100] while 56/56 got [91.8–100]. Exact intervals are monotone in k."""
    bounds = [stats.clopper_pearson(k, n) for k in range(n + 1)]
    for k in range(n):
        assert bounds[k + 1][0] >= bounds[k][0]
        assert bounds[k + 1][1] >= bounds[k][1]
    for k, (lo, hi) in enumerate(bounds):
        assert lo <= k / n <= hi


def test_clopper_pearson_refuses_impossible_counts() -> None:
    for k, n in ((1, 0), (-1, 5), (6, 5)):
        with pytest.raises(ValueError):
            stats.clopper_pearson(k, n)


# --------------------------------------------------------------------------------------------------
# McNemar
# --------------------------------------------------------------------------------------------------


def test_exact_mcnemar_known_values() -> None:
    assert stats.mcnemar_exact(31, 4) == pytest.approx(3.4655e-6, rel=1e-4)
    assert stats.mcnemar_exact(14, 5) == pytest.approx(0.063568, rel=1e-4)
    # exact rationals: 2 · P(X ≤ min) for X ~ Bin(b + c, 1/2)
    assert stats.mcnemar_exact(1, 5) == 2 * 7 / 64
    assert stats.mcnemar_exact(13, 0) == 2 / 8192
    assert stats.mcnemar_exact(2, 13) == 2 * (1 + 15 + 105) / 32768
    assert stats.mcnemar_exact(0, 0) == 1.0
    assert stats.mcnemar_exact(5, 5) == 1.0


def test_mid_p_mcnemar_known_values() -> None:
    assert stats.mcnemar_midp(14, 5) == pytest.approx(21700 / 524288, rel=1e-12)  # 0.0414
    assert stats.mcnemar_midp(31, 4) == pytest.approx(1.94e-6, rel=1e-2)
    assert stats.mcnemar_midp(1, 5) == 0.125
    assert stats.mcnemar_midp(5, 5) == 1.0
    assert stats.mcnemar_midp(0, 0) == 1.0


def test_mcnemar_is_symmetric_and_mid_p_is_smaller() -> None:
    for b, c in itertools.product(range(0, 12), repeat=2):
        assert stats.mcnemar_exact(b, c) == stats.mcnemar_exact(c, b)
        assert stats.mcnemar_midp(b, c) == stats.mcnemar_midp(c, b)
        assert stats.mcnemar_midp(b, c) <= stats.mcnemar_exact(b, c)


# --------------------------------------------------------------------------------------------------
# Bonett–Price
# --------------------------------------------------------------------------------------------------


def test_bonett_price_known_values() -> None:
    """The pooled held-out discordant pairs (168 items), against an independent implementation's output."""
    expected = {
        (31, 4): (9.3, 22.5),  # Ordnung vs LLM only, accuracy
        (14, 5): (0.1, 10.5),  # vs rules text
        (1, 5): (-5.6, 0.9),  # vs rules tool
        (2, 13): (-11.1, -1.8),  # late dates vs LLM only
    }
    for (b, c), (lo, hi) in expected.items():
        got = stats.bonett_price(b, c, 168)
        assert (round(got[0] * 100, 1), round(got[1] * 100, 1)) == (lo, hi)


def test_bonett_price_is_centred_on_the_adjusted_difference_and_bounded() -> None:
    lo, hi = stats.bonett_price(0, 0, 10)
    assert lo == pytest.approx(-hi) and lo < 0 < hi
    lo, hi = stats.bonett_price(50, 0, 50)
    assert -1.0 <= lo <= hi <= 1.0
    with pytest.raises(ValueError):
        stats.bonett_price(3, 4, 5)


# --------------------------------------------------------------------------------------------------
# Holm
# --------------------------------------------------------------------------------------------------


def test_holm_known_values() -> None:
    assert stats.holm([0.01, 0.04, 0.03]) == pytest.approx([0.03, 0.06, 0.06])
    assert stats.holm([0.6, 0.7]) == [1.0, 1.0]
    assert stats.holm([]) == []
    # the pooled held-out mid-p values, Ordnung vs each baseline: rules text becomes 0.083
    adjusted = stats.holm([stats.mcnemar_midp(31, 4), stats.mcnemar_midp(14, 5), stats.mcnemar_midp(1, 5)])
    assert adjusted[1] == pytest.approx(0.0828, abs=5e-5)
    assert adjusted[2] == 0.125


def test_holm_does_not_depend_on_input_order() -> None:
    raw = [0.04, 0.001, 0.2, 0.04, 0.03]
    reference = stats.holm(raw)
    for order in itertools.permutations(range(len(raw))):
        adjusted = stats.holm([raw[i] for i in order])
        assert adjusted == [reference[i] for i in order]
    assert all(a >= p for a, p in zip(reference, raw, strict=True))


# --------------------------------------------------------------------------------------------------
# Cluster sign-flip test
# --------------------------------------------------------------------------------------------------


def test_sign_flip_equals_exact_mcnemar_with_one_item_per_cluster() -> None:
    for b, c in itertools.product(range(0, 11), repeat=2):
        diffs = [1] * b + [-1] * c + [0] * 3
        result = stats.cluster_signflip(diffs)
        assert result.method == "exact"
        assert result.p == stats.mcnemar_exact(b, c)
    # more than 20 discordant clusters: exact when allowed to be
    result = stats.cluster_signflip([1] * 31 + [-1] * 4, exact_max=40)
    assert result.method == "exact" and result.p == stats.mcnemar_exact(31, 4)


def test_sign_flip_exact_on_a_hand_example() -> None:
    """Differences 2, −1, 1: of the 8 sign patterns, 6 give |sum| ≥ 2."""
    result = stats.cluster_signflip([2, -1, 1, 0])
    assert result.p == 0.75 and result.statistic == 2 and result.clusters == 4 and result.nonzero == 3
    assert stats.cluster_signflip([0, 0]).p == 1.0


def test_sign_flip_takes_means_over_reads_exactly() -> None:
    """Thirds (a mean over three reads) are compared exactly, given as fractions or as floats."""
    thirds = [Fraction(1, 3), Fraction(2, 3), Fraction(-1, 3)]
    assert stats.cluster_signflip(thirds).p == stats.cluster_signflip([1, 2, -1]).p
    assert stats.cluster_signflip([1 / 3, 2 / 3, -1 / 3]).p == stats.cluster_signflip([1, 2, -1]).p


def test_sign_flip_monte_carlo_is_seeded_and_close_to_exact() -> None:
    diffs = [1] * 18 + [-1] * 8 + [2, -2, 1]
    exact = stats.cluster_signflip(diffs, exact_max=40).p
    first = stats.cluster_signflip(diffs, draws=20_000, seed=7)
    again = stats.cluster_signflip(diffs, draws=20_000, seed=7)
    assert first.method == "monte-carlo" and first.draws == 20_000 and first.seed == 7
    assert first == again
    assert first.p == pytest.approx(exact, abs=0.01)
    # the Monte Carlo p-value is never 0: (hits + 1) / (draws + 1)
    tiny = stats.cluster_signflip([1] * 40, draws=1000, seed=1)
    assert tiny.p == 1 / 1001


# --------------------------------------------------------------------------------------------------
# Paired cluster bootstrap
# --------------------------------------------------------------------------------------------------


def test_paired_cluster_bootstrap_reproduces_the_scorers_paired_difference() -> None:
    """With the scorer's seed and resamples, the same clusters give the published bootstrap interval exactly."""
    units_a = [("c1", 1.0, 1.0), ("c2", 2.0, 2.0), ("c3", 0.0, 1.0), ("c4", 1.0, 2.0), ("c5", 1.0, 1.0)]
    units_b = [("c1", 0.0, 1.0), ("c2", 1.0, 2.0), ("c3", 0.0, 1.0), ("c4", 2.0, 2.0), ("c5", 0.0, 1.0)]
    published = metrics.bootstrap_difference(units_a, units_b, resamples=2000, seed=metrics.DEFAULT_SEED)
    clusters = [(a[1], b[1], a[2]) for a, b in zip(units_a, units_b, strict=True)]
    ours = stats.paired_cluster_bootstrap(clusters, resamples=2000, seed=metrics.DEFAULT_SEED)
    assert (ours.diff, ours.lo, ours.hi) == (published.value, published.lo, published.hi)


def test_paired_cluster_bootstrap_is_deterministic_and_degenerate_when_nothing_differs() -> None:
    clusters = [(1.0, 1.0, 1.0)] * 5 + [(2.0, 2.0, 2.0)] * 3
    result = stats.paired_cluster_bootstrap(clusters, resamples=500, seed=3)
    assert (result.diff, result.lo, result.hi) == (0.0, 0.0, 0.0)
    varied = [(1.0, 0.0, 1.0), (0.0, 0.0, 1.0), (1.0, 1.0, 1.0), (0.0, 1.0, 1.0), (1.0, 0.0, 1.0)]
    first = stats.paired_cluster_bootstrap(varied, resamples=500, seed=3)
    assert first == stats.paired_cluster_bootstrap(varied, resamples=500, seed=3)
    assert first.lo <= first.diff <= first.hi and first.resamples == 500 and first.clusters == 5


# --------------------------------------------------------------------------------------------------
# Stability over repeated reads
# --------------------------------------------------------------------------------------------------


def test_pass_all_and_pass_any_k() -> None:
    reads = [[True, True, True], [True, False, True], [False, False, False]]
    assert stats.pass_all_k(reads) == (1, 3)
    assert stats.pass_any_k(reads) == (2, 3)
    with pytest.raises(ValueError):
        stats.pass_all_k([[True, True], [True]])


def test_flip_rate_counts_items_whose_reads_differ() -> None:
    dates = [
        ["2026-01-05", "2026-01-05", "2026-01-05"],
        ["2026-01-05", None, "2026-01-05"],
        [None, None, None],
    ]
    assert stats.flip_rate(dates) == (1, 3)


def test_run_noise_share_known_value() -> None:
    """Item 1 reads [1, 0], item 2 [1, 1]: within-item variance 0.125 of a total 0.1875, so 2/3 is run noise."""
    assert stats.run_noise_share([[1, 0], [1, 1]]) == pytest.approx(2 / 3)
    assert stats.run_noise_share([[1, 1], [0, 0]]) == 0.0  # all between items
    assert stats.run_noise_share([[1, 0], [0, 1]]) == 1.0  # all run noise
    assert stats.run_noise_share([[1, 1], [1, 1]]) is None  # no variance at all


# --------------------------------------------------------------------------------------------------
# Selective prediction
# --------------------------------------------------------------------------------------------------


def test_auroc_counts_ties_as_half() -> None:
    """Ordnung's held-out tiers: its 5 wrong dates all at 'no flag' (0); its right ones 123 at 0, 34 at 1, 6 at 2."""
    wrong = [0] * 5
    right = [0] * 123 + [1] * 34 + [2] * 6
    assert stats.auroc(wrong, right) == pytest.approx(0.5 * 123 / 163)
    assert stats.auroc([2, 2], [0, 1]) == 1.0
    assert stats.auroc([], [1]) is None


def test_aurc_averages_over_ties() -> None:
    """Confidence 2, 2, 1, 0 with one error among the two most confident: risks 1/2, 1/2, 1/3, 1/4."""
    result = stats.aurc([2, 2, 1, 0], [False, True, False, False])
    assert result is not None
    assert result.aurc == pytest.approx((0.5 + 0.5 + 1 / 3 + 0.25) / 4)
    assert result.oracle == pytest.approx(0.25 / 4)
    assert result.excess == pytest.approx(result.aurc - result.oracle)
    assert stats.aurc([], []) is None


def test_aurc_of_ordnungs_held_out_tiers() -> None:
    """5 errors among 128 unflagged dates, none among the 40 flagged: AURC 0.038, E-AURC 0.037."""
    confidence = [2] * 128 + [1] * 34 + [0] * 6
    errors = [True] * 5 + [False] * 163
    result = stats.aurc(confidence, errors)
    assert result is not None
    assert round(result.aurc, 3) == 0.038 and round(result.excess, 3) == 0.037


# --------------------------------------------------------------------------------------------------
# Harm-weighted loss
# --------------------------------------------------------------------------------------------------


def test_harm_weighted_loss_and_crossover() -> None:
    """Pooled held-out: Ordnung 2 early, 3 late or missed; rules text 13 early, 1 late, of 168."""
    assert stats.harm_loss(2, 3, 168, 1) == pytest.approx(100 * 5 / 168)
    assert round(stats.harm_loss(2, 3, 168, 5), 1) == 10.1
    assert stats.crossover(2, 3, 13, 1) == 5.5
    assert stats.crossover(2, 3, 19, 13) is None  # the other has more harmful dates: it never overtakes
    assert stats.crossover(2, 3, 0, 1) == -1.0  # the other is lower at every r ≥ 0
    assert math.isnan(stats.harm_loss(0, 0, 0, 1))
