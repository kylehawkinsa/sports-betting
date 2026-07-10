"""REQUIRED validation (Part 2D): closed-form Barnett-Clarke probabilities
must match a 100k-iteration brute-force point simulation within 0.1
percentage points, or the build fails.

The simulator is seeded so the check is deterministic. At 100k iterations
the Monte Carlo standard error of a ~50% probability is ~0.16pp, so the
tolerance is tighter than one SE — the closed form and the simulator share
the exact same serving rules, which is what makes agreement achievable.
"""
import random

import pytest

from models.tennis_markov import (
    match_distribution,
    p_hold,
    p_hold_dp,
    p_tiebreak,
    simulate_match,
)

N_SIM = 100_000
TOL_PP = 0.1


@pytest.mark.parametrize("p", [0.50, 0.55, 0.60, 0.646, 0.70, 0.80])
def test_game_closed_form_matches_dp(p):
    assert abs(p_hold(p) - p_hold_dp(p)) < 1e-12


def test_game_symmetry():
    assert abs(p_hold(0.5) - 0.5) < 1e-12


def test_tiebreak_symmetry():
    # equal players, A serves first: tiebreak must be exactly 50/50
    assert abs(p_tiebreak(0.62, 0.62) - 0.5) < 1e-12


@pytest.mark.parametrize("pa,pb,best_of,seed", [
    (0.62, 0.62, 3, 1),     # even match, best-of-3
    (0.66, 0.60, 3, 1),     # moderate favorite, best-of-3
    (0.70, 0.58, 3, 1),     # strong favorite, best-of-3
    (0.64, 0.61, 5, 1),     # close match, best-of-5
    (0.68, 0.59, 5, 1),     # favorite, best-of-5
])
def test_closed_form_vs_bruteforce_100k(pa, pb, best_of, seed):
    closed = match_distribution(pa, pb, best_of=best_of)
    rng = random.Random(seed)
    wins = 0
    total_games_sum = 0
    for _ in range(N_SIM):
        a_won, ga, gb = simulate_match(pa, pb, best_of, rng)
        wins += a_won
        total_games_sum += ga + gb
    sim_p = wins / N_SIM
    diff_pp = abs(closed.p_match_a - sim_p) * 100.0
    assert diff_pp < TOL_PP, (
        f"closed {closed.p_match_a:.4f} vs sim {sim_p:.4f} "
        f"differ by {diff_pp:.3f}pp (tolerance {TOL_PP}pp)"
    )
    # game-count mean should also agree closely (looser: 0.15 games)
    closed_mean = sum(t * p for t, p in closed.total_games_dist.items())
    sim_mean = total_games_sum / N_SIM
    assert abs(closed_mean - sim_mean) < 0.15


def test_distributions_sum_to_one():
    d = match_distribution(0.65, 0.61, best_of=3)
    assert abs(sum(d.total_games_dist.values()) - 1.0) < 1e-9
    assert abs(sum(d.margin_dist.values()) - 1.0) < 1e-9
    assert abs(sum(d.set_score_probs.values()) - 1.0) < 1e-9


def test_even_match_is_50_50():
    d = match_distribution(0.63, 0.63, best_of=3)
    assert abs(d.p_match_a - 0.5) < 1e-9


def test_spread_and_total_helpers():
    d = match_distribution(0.68, 0.58, best_of=3)
    # favorite covering -3.5 must be less likely than winning the match
    assert d.p_spread_a(-3.5) < d.p_match_a
    # over/under complements
    assert abs(d.p_total_over(21.5) + sum(
        p for t, p in d.total_games_dist.items() if t < 21.5) - 1.0) < 1e-12
    # dog +3.5 covers at least as often as dog wins
    assert d.p_spread_a(3.5) >= d.p_match_a


def test_bo5_favorite_stronger_than_bo3():
    # longer format favors the better player
    bo3 = match_distribution(0.68, 0.59, best_of=3).p_match_a
    bo5 = match_distribution(0.68, 0.59, best_of=5).p_match_a
    assert bo5 > bo3


def test_invalid_format_rejected():
    with pytest.raises(ValueError):
        match_distribution(0.65, 0.60, best_of=1)
