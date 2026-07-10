"""MLB simulator sanity: home-field prior, run-line derivative behavior,
missing-input refusal, and the low-total/one-run-game relationship."""
import pytest

from models.mlb_sim import TeamInputs, simulate_game, weather_multiplier


def team(xwoba=0.320, xera=4.2, xfip=4.2):
    return TeamInputs(lineup_xwoba=xwoba, sp_xera=xera, sp_xfip=xfip)


def test_equal_teams_home_edge_near_54():
    sim = simulate_game(team(), team(), park_factor=1.0, seed=42,
                        n_sims=40_000)
    assert 0.52 <= sim.home_win <= 0.56


def test_probabilities_are_from_one_distribution():
    sim = simulate_game(team(), team(), park_factor=1.0, seed=1)
    # run line is a derivative of the same margin distribution:
    # P(home -1.5) < P(home ML) < P(home +1.5), and complements hold exactly
    assert sim.p_home_minus_15 < sim.home_win < sim.p_home_plus_15
    assert sim.p_home_plus_15 == pytest.approx(1.0 - sim.p_away_minus_15)
    assert sim.p_away_plus_15 == pytest.approx(1.0 - sim.p_home_minus_15)


def test_lower_totals_mean_minus_15_harder_to_cover():
    """Known market relationship (Part 2C sanity): in lower-scoring
    environments more games land on one-run margins, so the favorite
    covering -1.5 gets harder relative to winning at all."""
    good_p = dict(xera=2.8, xfip=2.9)
    bad_p = dict(xera=5.6, xfip=5.5)
    low = simulate_game(team(xwoba=0.335, **good_p), team(xwoba=0.290, **good_p),
                        park_factor=0.90, seed=7, n_sims=60_000)
    high = simulate_game(team(xwoba=0.335, **bad_p), team(xwoba=0.290, **bad_p),
                         park_factor=1.10, seed=7, n_sims=60_000)
    assert low.mean_total < high.mean_total
    # conditional cover rate: P(-1.5 | win) lower in the low-total game
    assert (low.p_home_minus_15 / low.home_win
            < high.p_home_minus_15 / high.home_win)


def test_total_distribution_sane():
    sim = simulate_game(team(), team(), park_factor=1.0, seed=3)
    assert sim.sanity_ok()
    assert 6.0 < sim.mean_total < 12.0
    assert sim.p_over(0.5) > 0.99
    assert sim.p_over(25.5) < 0.01
    # over/under complement (no pushes on .5 lines)
    assert sim.p_over(8.5) + sim.p_under(8.5) == pytest.approx(1.0)


def test_better_offense_scores_more():
    strong = simulate_game(team(xwoba=0.345), team(), park_factor=1.0, seed=5,
                           n_sims=40_000)
    weak = simulate_game(team(xwoba=0.295), team(), park_factor=1.0, seed=5,
                         n_sims=40_000)
    assert strong.home_win > weak.home_win + 0.05


def test_missing_inputs_refuse_to_model():
    # Right Rule 2: no offense metric -> no sim, never a guess
    no_off = TeamInputs(sp_xera=4.0, sp_xfip=4.0)
    assert simulate_game(no_off, team(), park_factor=1.0) is None
    no_pitch = TeamInputs(lineup_xwoba=0.320)
    assert simulate_game(team(), no_pitch, park_factor=1.0) is None


def test_park_and_weather_raise_totals():
    cold = simulate_game(team(), team(), park_factor=1.0,
                         weather_mult=weather_multiplier(45, None, None, False)[0],
                         seed=9, n_sims=40_000)
    hot = simulate_game(team(), team(), park_factor=1.08,
                        weather_mult=weather_multiplier(95, 12, True, True)[0],
                        seed=9, n_sims=40_000)
    assert hot.mean_total > cold.mean_total + 0.5


def test_missing_weather_is_neutral_and_labeled():
    mult, note = weather_multiplier(None, None, None, True)
    assert mult == 1.0
    assert "—" in note
