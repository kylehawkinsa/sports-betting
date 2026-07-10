"""Tennis — Barnett-Clarke hierarchical Markov model (ACE EDGE core, Part 2D).

Chain: point -> game (closed-form O'Malley) -> tiebreak -> set -> match,
under the iid serve assumption (Klaassen & Magnus: violations are small and
tolerable). Best-of-3 vs best-of-5 handled explicitly. No-ad and
match-tiebreak formats are NOT modeled here — the pipeline excludes them
from plays before ever calling this module.

INPUT COMBINING FORMULA (exact, per spec):
    spw_i = 0.60 * spw_surface_i + 0.40 * spw_overall_i        (last 52 weeks)
    rpw_i = 0.60 * rpw_surface_i + 0.40 * rpw_overall_i
    Opponent adjustment (subtract opponent return strength relative to tour):
    p_a = spw_a - (rpw_b - TOUR_AVG_RPW)   # P(A wins a point on A's serve)
    p_b = spw_b - (rpw_a - TOUR_AVG_RPW)   # P(B wins a point on B's serve)
All quantities are fractions in [0, 1]. TOUR_AVG_RPW is computed from the
Sackmann dataset when available, else supplied via config for manual mode.

Outputs come from the FULL game-count distribution of the match:
match win %, P(game spread), P(total games over/under) — all from one chain.

Validation (required by spec, see tests/test_markov_vs_sim.py): closed-form
match probabilities must agree with a 100k-iteration brute-force point
simulation within 0.1 percentage points or the build fails.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from functools import lru_cache

SURFACE_WEIGHT = 0.60
OVERALL_WEIGHT = 0.40

# Plausibility clamp for serve-point win probability. Values outside this
# range indicate corrupt inputs; the caller must raise, not silently clamp.
P_MIN, P_MAX = 0.25, 0.90


def combine_inputs(
    spw_surface_a: float, spw_overall_a: float,
    rpw_surface_a: float, rpw_overall_a: float,
    spw_surface_b: float, spw_overall_b: float,
    rpw_surface_b: float, rpw_overall_b: float,
    tour_avg_rpw: float,
) -> tuple[float, float]:
    """Apply the exact combining formula documented in the module docstring."""
    spw_a = SURFACE_WEIGHT * spw_surface_a + OVERALL_WEIGHT * spw_overall_a
    rpw_a = SURFACE_WEIGHT * rpw_surface_a + OVERALL_WEIGHT * rpw_overall_a
    spw_b = SURFACE_WEIGHT * spw_surface_b + OVERALL_WEIGHT * spw_overall_b
    rpw_b = SURFACE_WEIGHT * rpw_surface_b + OVERALL_WEIGHT * rpw_overall_b
    p_a = spw_a - (rpw_b - tour_avg_rpw)
    p_b = spw_b - (rpw_a - tour_avg_rpw)
    for label, p in (("p_a", p_a), ("p_b", p_b)):
        if not (P_MIN <= p <= P_MAX):
            raise ValueError(
                f"{label}={p:.4f} outside plausible serve-win range "
                f"[{P_MIN}, {P_MAX}] — inputs rejected, no play may be issued"
            )
    return p_a, p_b


# ---------------------------------------------------------------- game level

def p_hold(p: float) -> float:
    """P(server wins a standard deuce game), O'Malley closed form:
    G(p) = p^4 * (15 - 4p - 10 p^2 / (1 - 2 p (1-p)))"""
    return p ** 4 * (15.0 - 4.0 * p - (10.0 * p * p) / (1.0 - 2.0 * p * (1.0 - p)))


def p_hold_dp(p: float) -> float:
    """Same quantity by explicit Markov recursion — used in tests to verify
    the closed form."""
    @lru_cache(maxsize=None)
    def rec(a: int, b: int) -> float:
        if a >= 4 and a - b >= 2:
            return 1.0
        if b >= 4 and b - a >= 2:
            return 0.0
        if a == b >= 3:  # deuce: closed form P(win from deuce) = p^2/(p^2+q^2)
            q = 1.0 - p
            return p * p / (p * p + q * q)
        return p * rec(a + 1, b) + (1.0 - p) * rec(a, b + 1)
    return rec(0, 0)


# ------------------------------------------------------------ tiebreak level

def p_tiebreak(pa: float, pb: float) -> float:
    """P(A wins a 7-point tiebreak, win by 2) given A serves the first point.

    pa = P(A wins point on A's serve), pb = P(B wins point on B's serve).
    Serving order: A serves point 1; thereafter pairs alternate (2-3 B,
    4-5 A, ...): server of point k (1-based) is A iff (k // 2) is even.
    From any tied score >= 6-6 each subsequent pair contains exactly one
    point on each serve, so
        P(A | tied) = pa(1-pb) / (pa(1-pb) + (1-pa)pb).
    """
    tied = pa * (1.0 - pb) / (pa * (1.0 - pb) + (1.0 - pa) * pb)

    @lru_cache(maxsize=None)
    def rec(a: int, b: int) -> float:
        if a >= 7 and a - b >= 2:
            return 1.0
        if b >= 7 and b - a >= 2:
            return 0.0
        if a == b and a >= 6:
            return tied
        k = a + b + 1  # next point number, 1-based
        a_serving = (k // 2) % 2 == 0
        p_point = pa if a_serving else (1.0 - pb)
        return p_point * rec(a + 1, b) + (1.0 - p_point) * rec(a, b + 1)

    return rec(0, 0)


# ----------------------------------------------------------------- set level

def set_score_dist(pa: float, pb: float, a_serves_first: bool) -> dict[tuple[int, int], float]:
    """Distribution over final set scores {(games_a, games_b): prob}.

    Standard tiebreak set: first to 6 win-by-2, else 7-5, else tiebreak at
    6-6 (recorded as 7-6 / 6-7; the tiebreak counts as one game, 13 total).
    Servers alternate each game; the tiebreak's first server is the set's
    first server (game 13 falls to them).
    """
    ga_hold = p_hold(pa)   # P(A holds serve)
    gb_hold = p_hold(pb)   # P(B holds serve)
    out: dict[tuple[int, int], float] = {}

    def rec(a: int, b: int, prob: float) -> None:
        if prob == 0.0:
            return
        if (a >= 6 and a - b >= 2) or (a == 7 and b == 5):
            out[(a, b)] = out.get((a, b), 0.0) + prob
            return
        if (b >= 6 and b - a >= 2) or (b == 7 and a == 5):
            out[(a, b)] = out.get((a, b), 0.0) + prob
            return
        if a == 6 and b == 6:
            tb_first_is_a = a_serves_first
            p_tb_a = p_tiebreak(pa, pb) if tb_first_is_a else 1.0 - p_tiebreak(pb, pa)
            out[(7, 6)] = out.get((7, 6), 0.0) + prob * p_tb_a
            out[(6, 7)] = out.get((6, 7), 0.0) + prob * (1.0 - p_tb_a)
            return
        game_no = a + b + 1
        a_serving = a_serves_first if game_no % 2 == 1 else not a_serves_first
        p_a_wins_game = ga_hold if a_serving else 1.0 - gb_hold
        rec(a + 1, b, prob * p_a_wins_game)
        rec(a, b + 1, prob * (1.0 - p_a_wins_game))

    rec(0, 0, 1.0)
    return out


def set_games(score: tuple[int, int]) -> int:
    """Total games in a finished set; a 7-6 set is 13 games (TB = one game)."""
    return score[0] + score[1]


# --------------------------------------------------------------- match level

@dataclass
class MatchDistribution:
    p_match_a: float
    total_games_dist: dict[int, float]          # P(total games = t)
    margin_dist: dict[int, float]               # P(games_a - games_b = m)
    set_score_probs: dict[tuple[int, int], float]  # P(sets_a, sets_b)

    def p_total_over(self, line: float) -> float:
        return sum(p for t, p in self.total_games_dist.items() if t > line)

    def p_spread_a(self, line: float) -> float:
        """P(A covers 'A line' games), e.g. line=-3.5 -> P(margin >= 4);
        line=+4.5 -> P(margin >= -4) = P(margin > -5)."""
        return sum(p for m, p in self.margin_dist.items() if m + line > 0)


def match_distribution(pa: float, pb: float, best_of: int = 3) -> MatchDistribution:
    """Full match distribution by convolving per-set score distributions.

    Serve continuity across sets: the player due to serve next keeps
    rotating game by game, so the next set's first server flips iff the
    finished set had an odd number of games. (After a tiebreak set — 13
    games, odd — the first receiver of the TB serves first next set, which
    this parity rule reproduces.) The match's first server is decided by
    coin toss, so we average over A-first and B-first.
    """
    if best_of not in (3, 5):
        raise ValueError("best_of must be 3 or 5 (other formats are excluded)")
    sets_to_win = best_of // 2 + 1

    # cache per-set distributions for both first-server cases
    dists = {
        True: set_score_dist(pa, pb, a_serves_first=True),
        False: set_score_dist(pa, pb, a_serves_first=False),
    }

    def run(first_server_a: bool) -> MatchDistribution:
        # state: (sets_a, sets_b, a_first_next_set, games_a, games_b) -> prob
        states: dict[tuple[int, int, bool, int, int], float] = {
            (0, 0, first_server_a, 0, 0): 1.0
        }
        p_match_a = 0.0
        total_dist: dict[int, float] = {}
        margin_dist: dict[int, float] = {}
        set_probs: dict[tuple[int, int], float] = {}

        while states:
            nxt: dict[tuple[int, int, bool, int, int], float] = {}
            for (sa, sb, a_first, ga, gb), prob in states.items():
                for (x, y), ps in dists[a_first].items():
                    p = prob * ps
                    if p == 0.0:
                        continue
                    nsa, nsb = sa + (1 if x > y else 0), sb + (1 if y > x else 0)
                    nga, ngb = ga + x, gb + y
                    if nsa == sets_to_win or nsb == sets_to_win:
                        if nsa == sets_to_win:
                            p_match_a += p
                        t, m = nga + ngb, nga - ngb
                        total_dist[t] = total_dist.get(t, 0.0) + p
                        margin_dist[m] = margin_dist.get(m, 0.0) + p
                        set_probs[(nsa, nsb)] = set_probs.get((nsa, nsb), 0.0) + p
                    else:
                        flip = (x + y) % 2 == 1
                        na_first = (not a_first) if flip else a_first
                        key = (nsa, nsb, na_first, nga, ngb)
                        nxt[key] = nxt.get(key, 0.0) + p
            states = nxt

        return MatchDistribution(p_match_a, total_dist, margin_dist, set_probs)

    d1, d2 = run(True), run(False)
    keys_t = set(d1.total_games_dist) | set(d2.total_games_dist)
    keys_m = set(d1.margin_dist) | set(d2.margin_dist)
    keys_s = set(d1.set_score_probs) | set(d2.set_score_probs)
    avg = MatchDistribution(
        p_match_a=0.5 * (d1.p_match_a + d2.p_match_a),
        total_games_dist={
            k: 0.5 * (d1.total_games_dist.get(k, 0.0) + d2.total_games_dist.get(k, 0.0))
            for k in sorted(keys_t)
        },
        margin_dist={
            k: 0.5 * (d1.margin_dist.get(k, 0.0) + d2.margin_dist.get(k, 0.0))
            for k in sorted(keys_m)
        },
        set_score_probs={
            k: 0.5 * (d1.set_score_probs.get(k, 0.0) + d2.set_score_probs.get(k, 0.0))
            for k in keys_s
        },
    )
    # Part 7 sanity: distribution must sum to 1
    if abs(sum(avg.total_games_dist.values()) - 1.0) > 1e-9:
        raise ValueError("tennis game-count distribution does not sum to 1")
    return avg


# ------------------------------------------------ brute-force point simulator

def simulate_match(pa: float, pb: float, best_of: int, rng: random.Random) -> tuple[bool, int, int]:
    """Simulate one match point-by-point with the exact same serving rules.
    Returns (a_won, games_a, games_b). Used only by the validation test."""
    sets_to_win = best_of // 2 + 1
    sa = sb = ga_total = gb_total = 0
    a_first = rng.random() < 0.5  # coin toss

    def play_game(server_a: bool) -> bool:
        """True if A wins the game."""
        p = pa if server_a else pb
        w = l = 0
        while True:
            if rng.random() < p:
                w += 1
            else:
                l += 1
            if w >= 4 and w - l >= 2:
                return server_a
            if l >= 4 and l - w >= 2:
                return not server_a

    def play_tiebreak(first_a: bool) -> bool:
        a = b = 0
        k = 0
        while True:
            k += 1
            serving_a = first_a if (k // 2) % 2 == 0 else not first_a
            p_point = pa if serving_a else (1.0 - pb)
            if rng.random() < p_point:
                a += 1
            else:
                b += 1
            if a >= 7 and a - b >= 2:
                return True
            if b >= 7 and b - a >= 2:
                return False

    while sa < sets_to_win and sb < sets_to_win:
        ga = gb = 0
        set_first_a = a_first
        while True:
            if ga == 6 and gb == 6:
                if play_tiebreak(set_first_a):
                    ga += 1
                else:
                    gb += 1
                break
            game_no = ga + gb + 1
            serving_a = set_first_a if game_no % 2 == 1 else not set_first_a
            if play_game(serving_a):
                ga += 1
            else:
                gb += 1
            if (ga >= 6 and ga - gb >= 2) or (ga == 7 and gb == 5):
                break
            if (gb >= 6 and gb - ga >= 2) or (gb == 7 and ga == 5):
                break
        ga_total += ga
        gb_total += gb
        if ga > gb:
            sa += 1
        else:
            sb += 1
        if (ga + gb) % 2 == 1:
            a_first = not a_first

    return sa == sets_to_win, ga_total, gb_total
