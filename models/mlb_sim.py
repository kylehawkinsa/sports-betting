"""MLB Monte Carlo game simulator (Part 2A/2B/2C — BARREL EDGE core).

10,000 simulations per game. One simulation produces one joint sample of
(home runs, away runs), so the moneyline, the total AND the run line are
all read off the SAME distribution — the run line is never priced
independently (Part 2C).

Model parameters (constants below) are model choices, not data: they are
documented here and never displayed on the board as if they were fetched
facts. Data INPUTS (xwOBA, xERA/xFIP, park factor, weather) must come from
sourced adapters; if an input is missing the caller passes None and this
module either uses the league-neutral value for that component (labeled in
model_inputs_note) or refuses to run, per the Right Rule.

2026 note (Part 2B): ABS challenge system compresses umpire strike-zone
effects — no umpire O/U tendency input exists in this model by design.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

N_SIMS = 10_000

# ---- league-environment model parameters (documented model choices) ----
LG_RPG = 4.5          # league runs per team-game baseline
LG_XWOBA = 0.320      # league xwOBA baseline
LG_RA9 = 4.5          # league runs allowed / 9
LG_XERA = 4.20        # league xERA baseline (ERA-scale metrics run under RA9)
LG_KBB = 0.14         # league K-BB%
XWOBA_RUN_EXPONENT = 1.85   # runs scale ~ (xwOBA ratio)^1.85 (BaseRuns-style elasticity)
TTO_PENALTY_R9 = 0.35       # +runs/9 per times-through-order pass after the second
DEFAULT_SP_IP = 5.3         # expected starter innings when no projection input
HOME_RUN_MULT = 1.045       # home offense boost -> ~54% home win for equal teams
AWAY_RUN_MULT = 1.0 / 1.045
EXTRA_INNING_BONUS_MU = 0.55  # ghost-runner raises expected runs/extra inning
TEMP_PCT_PER_10F = 0.01     # ~+1% run scoring per 10°F above 70
NONZERO_MEAN_BASE = 1.35    # zero-inflated-geometric shape: mean of a scoring inning
                            # = NONZERO_MEAN_BASE + mu (≈1.85 at league mu 0.5,
                            # matching observed inning-run overdispersion)

MAX_EXTRA_INNINGS = 15      # safety bound; ties beyond this are split 50/50


@dataclass
class TeamInputs:
    """All fields optional; None = input unavailable from a sourced adapter.
    lineup_xwoba: weighted lineup xwOBA (platoon-adjusted upstream).
    sp_xera / sp_xfip: starter expected-run metrics.
    sp_kbb: starter K-BB% (fraction).
    sp_exp_ip: projected starter innings.
    bullpen_xfip: rolling-30-day bullpen xFIP; None -> league-neutral, labeled.
    """
    name: str = ""
    lineup_xwoba: float | None = None
    off_runs_factor: float | None = None   # sourced team runs/G ÷ league —
                                           # PRELIMINARY fallback when lineups unposted
    sp_xera: float | None = None
    sp_xfip: float | None = None
    sp_kbb: float | None = None
    sp_exp_ip: float | None = None
    bullpen_xfip: float | None = None

    def offense_available(self) -> bool:
        return self.lineup_xwoba is not None or self.off_runs_factor is not None

    def pitching_available(self) -> bool:
        return self.sp_xera is not None or self.sp_xfip is not None


@dataclass
class SimResult:
    home_win: float
    p_home_minus_15: float       # P(home margin >= 2)
    p_away_minus_15: float       # P(away margin >= 2)
    p_home_plus_15: float        # P(home wins) + P(home loses by exactly 1)
    p_away_plus_15: float
    mean_total: float
    total_samples: np.ndarray = field(repr=False)
    margin_samples: np.ndarray = field(repr=False)   # home - away
    n_sims: int = N_SIMS
    model_inputs_note: str = ""

    def p_over(self, line: float) -> float:
        return float(np.mean(self.total_samples > line))

    def p_under(self, line: float) -> float:
        return float(np.mean(self.total_samples < line))

    def sanity_ok(self) -> bool:
        """Part 7: mean total outside 3–20 runs -> suppress markets."""
        return 3.0 <= self.mean_total <= 20.0


def _starter_ra9(t: TeamInputs) -> float:
    """xERA/xFIP blend + small K-BB% adjustment (K-BB is mostly baked into
    xFIP already, so the extra term is deliberately mild)."""
    metrics = [m for m in (t.sp_xera, t.sp_xfip) if m is not None]
    ra9 = sum(metrics) / len(metrics)
    if t.sp_kbb is not None:
        ra9 -= 1.5 * (t.sp_kbb - LG_KBB)
    return ra9


def _inning_mus(offense: TeamInputs, pitching: TeamInputs,
                park_weather_mult: float, home: bool) -> np.ndarray:
    """Expected runs for each of 9 innings for `offense` batting against
    `pitching`, multiplicative factor model:
        mu_i = (LG_RPG/9) * off_factor * pitch_factor_i * park*weather * HFA
    Starter covers innings 1..exp_ip with TTO penalty applied from the
    third time through the order (~inning 5-6 onward); bullpen covers the
    rest at its xFIP (league-neutral if unavailable)."""
    if offense.lineup_xwoba is not None:
        off_factor = (offense.lineup_xwoba / LG_XWOBA) ** XWOBA_RUN_EXPONENT
    else:
        off_factor = offense.off_runs_factor  # already a runs ratio
    sp_ra9 = _starter_ra9(pitching)
    exp_ip = pitching.sp_exp_ip if pitching.sp_exp_ip is not None else DEFAULT_SP_IP
    bp_ra9 = pitching.bullpen_xfip if pitching.bullpen_xfip is not None else LG_RA9
    hfa = HOME_RUN_MULT if home else AWAY_RUN_MULT

    mus = np.empty(9)
    for i in range(9):  # inning index 0..8
        if i + 1 <= exp_ip:
            ra9 = sp_ra9
            # third time through the order begins ~inning 5 for a typical
            # lineup turnover; penalty per pass after the second
            if i + 1 >= 5:
                ra9 += TTO_PENALTY_R9
            if i + 1 >= 8:
                ra9 += TTO_PENALTY_R9  # fourth pass, rare
        else:
            ra9 = bp_ra9
        pitch_factor = ra9 / LG_RA9
        mus[i] = (LG_RPG / 9.0) * off_factor * pitch_factor * park_weather_mult * hfa
    return mus


def _sample_inning_runs(mu: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Zero-inflated geometric inning-run model, vectorized.
    A scoring inning yields Geometric(1/mean_nz) runs with
    mean_nz = NONZERO_MEAN_BASE + mu; P(scoring inning) = mu / mean_nz.
    This reproduces MLB's per-inning zero-inflation (~73% scoreless at
    league mu≈0.5) and per-game run variance far better than Poisson."""
    mu = np.maximum(mu, 0.02)
    mean_nz = NONZERO_MEAN_BASE + mu
    p_score = np.clip(mu / mean_nz, 0.0, 0.95)
    scoring = rng.random(mu.shape) < p_score
    bursts = rng.geometric(np.clip(1.0 / mean_nz, 0.02, 1.0))
    return np.where(scoring, bursts, 0)


def weather_multiplier(temp_f: float | None, wind_mph: float | None,
                       wind_blowing_out: bool | None,
                       hr_wind_sensitive: bool) -> tuple[float, str]:
    """Park-weather run multiplier from SOURCED weather only.
    Missing weather -> 1.0, labeled. Wind matters only at flagged parks."""
    if temp_f is None:
        return 1.0, "weather — (neutral)"
    mult = 1.0 + TEMP_PCT_PER_10F * (temp_f - 70.0) / 10.0
    note = f"temp {temp_f:.0f}F"
    if hr_wind_sensitive and wind_mph is not None and wind_blowing_out is not None:
        # ±0.5% run scoring per mph of out/in wind at HR-sensitive parks
        sign = 1.0 if wind_blowing_out else -1.0
        mult *= 1.0 + sign * 0.005 * min(wind_mph, 20.0)
        note += f", wind {'out' if wind_blowing_out else 'in'} {wind_mph:.0f}mph"
    return mult, note


def simulate_game(home: TeamInputs, away: TeamInputs,
                  park_factor: float | None,
                  weather_mult: float = 1.0,
                  n_sims: int = N_SIMS,
                  seed: int | None = None) -> SimResult | None:
    """Run the joint simulation. Returns None if required inputs are missing
    (offense xwOBA and starter metrics for both sides) — the caller then
    shows `—` and the game defaults to PASS. Optional inputs fall back to
    league-neutral values and are labeled in model_inputs_note."""
    if not (home.offense_available() and away.offense_available()
            and home.pitching_available() and away.pitching_available()):
        return None

    notes = []
    pf = park_factor if park_factor is not None else 1.0
    if park_factor is None:
        notes.append("park factor — (neutral)")
    if home.bullpen_xfip is None:
        notes.append("home bullpen — (league avg)")
    if away.bullpen_xfip is None:
        notes.append("away bullpen — (league avg)")
    env = pf * weather_mult

    rng = np.random.default_rng(seed)
    mus_home = _inning_mus(home, away, env, home=True)    # home bats vs away pitching
    mus_away = _inning_mus(away, home, env, home=False)   # away bats vs home pitching

    # innings 1-8 for both; top 9 for away always; bottom 9 conditional
    away_runs = np.zeros(n_sims, dtype=np.int64)
    home_runs = np.zeros(n_sims, dtype=np.int64)
    for i in range(9):
        away_runs += _sample_inning_runs(np.full(n_sims, mus_away[i]), rng)
    for i in range(8):
        home_runs += _sample_inning_runs(np.full(n_sims, mus_home[i]), rng)

    # bottom 9: skipped if home already leads; walk-off caps the margin at 1
    need_b9 = home_runs <= away_runs
    b9 = _sample_inning_runs(np.full(n_sims, mus_home[8]), rng)
    deficit = away_runs - home_runs  # >= 0 where bottom 9 is played
    walkoff_cap = deficit + 1
    b9_applied = np.where(need_b9, np.minimum(b9, walkoff_cap), 0)
    home_runs += b9_applied

    # extra innings, ghost-runner era: elevated per-inning mu, walk-off logic
    mu_x_home = mus_home[8] + EXTRA_INNING_BONUS_MU
    mu_x_away = mus_away[8] + EXTRA_INNING_BONUS_MU
    tied = home_runs == away_runs
    for _ in range(MAX_EXTRA_INNINGS):
        if not tied.any():
            break
        n_t = int(tied.sum())
        xa = _sample_inning_runs(np.full(n_t, mu_x_away), rng)
        xh = _sample_inning_runs(np.full(n_t, mu_x_home), rng)
        xh = np.minimum(xh, xa + 1)  # walk-off: home stops one run ahead
        away_runs[tied] += xa
        home_runs[tied] += xh
        tied = home_runs == away_runs
    if tied.any():
        # split residual ties 50/50 deterministically by giving home one run
        # in half of them (bounded-loop safety valve, ~never triggered)
        idx = np.flatnonzero(tied)
        home_runs[idx[: len(idx) // 2]] += 1
        away_runs[idx[len(idx) // 2:]] += 1

    margin = home_runs - away_runs
    total = home_runs + away_runs

    result = SimResult(
        home_win=float(np.mean(margin > 0)),
        p_home_minus_15=float(np.mean(margin >= 2)),
        p_away_minus_15=float(np.mean(margin <= -2)),
        p_home_plus_15=float(np.mean(margin >= -1)),
        p_away_plus_15=float(np.mean(margin <= 1)),
        mean_total=float(np.mean(total)),
        total_samples=total,
        margin_samples=margin,
        n_sims=n_sims,
        model_inputs_note="; ".join(notes),
    )
    return result
