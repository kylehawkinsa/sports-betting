"""MLB pipeline: schedule -> stats -> weather -> odds -> sim -> gates.

Produces one GameCard per game. Every number on a card traces to a manifest
record; missing inputs surface as None and render as `—`. If odds are
unavailable the card is marked odds_available=False and can never yield a
play (Part 7).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from adapters import mlb_statsapi, statcast
from adapters.odds_adapter import (
    OddsEvent,
    consensus_line,
    opener_for,
    record_openers,
)
from adapters.splits_dk import Splits, sharp_side_flag
from adapters.weather import Weather, fetch_weather, wind_blowing_out
from core.errorlog import log_error
from core.manifest import Manifest
from models.mlb_sim import SimResult, TeamInputs, simulate_game, weather_multiplier
from reports.marketeval import MarketEval, eval_two_way

# League-average platoon shift applied to sourced xwOBA as a MODEL PARAMETER
# (individual L/R splits are not in the expected-stats feed). Values are
# xwOBA points; the displayed number remains the sourced season xwOBA.
PLATOON_SHIFT = 0.008     # opposite-hand batter vs SP: +8 pts; same-hand: -8
SWITCH_SHIFT = 0.004      # switch hitters always bat opposite: half credit
MIN_LINEUP_FOUND = 6      # need >= 6 of 9 lineup xwOBAs or offense is missing


@dataclass
class GameCard:
    game: mlb_statsapi.MLBGame
    odds_available: bool = False
    odds_event: OddsEvent | None = None
    preliminary: bool = False
    sim: SimResult | None = None
    evals: list[MarketEval] = field(default_factory=list)
    total_line: float | None = None
    total_probs_pm1: dict[float, float] = field(default_factory=dict)
    splits: list[Splits] = field(default_factory=list)
    weather: Weather | None = None
    weather_note: str = ""
    home_inputs: "TeamInputs | None" = None
    away_inputs: "TeamInputs | None" = None
    park_factor: float | None = None
    why: str = ""
    model_note: str = ""
    openers: dict = field(default_factory=dict)


def _team_display(*names: str) -> list[str]:
    return [n for n in names if n]


def _match_event(game: mlb_statsapi.MLBGame,
                 events: list[OddsEvent]) -> OddsEvent | None:
    def norm(s: str) -> str:
        return s.lower().strip()
    for ev in events:
        if norm(ev.home) == norm(game.home) and norm(ev.away) == norm(game.away):
            return ev
    for ev in events:  # fallback: substring match on nicknames
        if (norm(game.home).split()[-1] in norm(ev.home)
                and norm(game.away).split()[-1] in norm(ev.away)):
            return ev
    return None


def _lineup_xwoba(lineup_ids: list[int], bat_sides: dict[int, str],
                  sp_hand: str | None,
                  batters: pd.DataFrame | None) -> float | None:
    """Mean lineup xwOBA, platoon-adjusted vs SP handedness. Sourced values
    only; players missing from the table are skipped, and fewer than
    MIN_LINEUP_FOUND hits means the input is unavailable (None)."""
    vals = []
    for pid in lineup_ids[:9]:
        x = statcast.lookup_batter_xwoba(batters, pid)
        if x is None:
            continue
        side = bat_sides.get(pid)
        if sp_hand in ("L", "R") and side in ("L", "R", "S"):
            if side == "S":
                x += SWITCH_SHIFT
            elif side != sp_hand:
                x += PLATOON_SHIFT
            else:
                x -= PLATOON_SHIFT
        vals.append(x)
    if len(vals) < MIN_LINEUP_FOUND:
        return None
    return sum(vals) / len(vals)


def _park_factor(pf_table: pd.DataFrame | None, venue_name: str) -> float | None:
    """Savant 3-yr rolling park factor (100 = neutral) -> multiplier."""
    if pf_table is None or not venue_name:
        return None
    name_col = next((c for c in pf_table.columns
                     if "venue" in c.lower() and "id" not in c.lower()), None)
    fac_col = next((c for c in pf_table.columns if c.lower() in
                    ("index_woba", "park_factor", "index_runs", "factor")), None)
    if name_col is None or fac_col is None:
        return None
    rows = pf_table[pf_table[name_col].astype(str).str.lower()
                    .str.contains(venue_name.split()[0].lower(), na=False)]
    if rows.empty:
        return None
    try:
        v = float(rows.iloc[0][fac_col])
        return v / 100.0 if v > 10.0 else v
    except (ValueError, TypeError):
        return None


def run_mlb(date_str: str, config: dict, manifest: Manifest,
            games: list[mlb_statsapi.MLBGame],
            odds_events: list[OddsEvent] | None,
            splits_by_team: dict[str, list[Splits]] | None) -> list[GameCard]:
    season = int(date_str[:4])
    if not games:
        return []

    batters = statcast.batter_xwoba_table(season, manifest)
    pitch_x = statcast.pitcher_xstats_table(season, manifest)
    pitch_fg = statcast.pitcher_fangraphs_table(season, manifest)
    pf_table = statcast.park_factors_table(manifest)

    openers = {}
    if odds_events:
        openers = record_openers("mlb", date_str, odds_events)

    park_cfg = (config.get("mlb", {}) or {}).get("parks", {}) or {}
    book_priority = (config.get("odds", {}) or {}).get(
        "book_priority", ["pinnacle"])

    cards: list[GameCard] = []
    for g in games:
        card = GameCard(game=g, openers=openers)
        ev = _match_event(g, odds_events) if odds_events else None
        card.odds_event = ev
        card.odds_available = ev is not None and bool(ev.markets.get("ml"))

        # ---- weather (sourced venue coords -> Open-Meteo at first pitch)
        pcfg = park_cfg.get(g.venue_name, {}) or {}
        wx_mult, wx_note = 1.0, "weather — (neutral)"
        if g.venue_id:
            coords = mlb_statsapi.fetch_venue_coords(g.venue_id, manifest)
            if coords:
                card.weather = fetch_weather(coords[0], coords[1], g.start_utc,
                                             manifest, name=f"wx_{g.venue_id}")
        if card.weather:
            out = wind_blowing_out(card.weather.wind_dir_deg,
                                   pcfg.get("cf_bearing_deg"))
            wx_mult, wx_note = weather_multiplier(
                card.weather.temp_f, card.weather.wind_mph, out,
                hr_wind_sensitive=bool(pcfg.get("hr_wind_sensitive")),
            )
        card.weather_note = wx_note

        # ---- offense inputs
        card.preliminary = not g.lineups_posted
        bat_sides: dict[int, str] = {}
        if g.lineups_posted:
            bat_sides = mlb_statsapi.fetch_bat_sides(
                g.away_lineup_ids[:9] + g.home_lineup_ids[:9], manifest)

        def team_inputs(name: str, lineup: list[int], team_id: int | None,
                        sp_name: str | None, sp_id: int | None,
                        opp_sp_hand: str | None) -> TeamInputs:
            t = TeamInputs(name=name)
            if g.lineups_posted:
                t.lineup_xwoba = _lineup_xwoba(lineup, bat_sides,
                                               opp_sp_hand, batters)
            if t.lineup_xwoba is None and team_id:
                rpg = mlb_statsapi.fetch_team_runs_per_game(team_id, season,
                                                            manifest)
                if rpg is not None:
                    from models.mlb_sim import LG_RPG  # noqa: PLC0415
                    t.off_runs_factor = rpg / LG_RPG
            p = statcast.lookup_pitcher(pitch_x, pitch_fg, sp_id, sp_name)
            t.sp_xera = p.get("xera")
            t.sp_xfip = p.get("xfip")
            t.sp_kbb = p.get("kbb")
            t.sp_exp_ip = p.get("exp_ip")
            return t

        away_in = team_inputs(g.away, g.away_lineup_ids, g.away_id,
                              g.probable_away, g.probable_away_id,
                              g.probable_home_hand)
        home_in = team_inputs(g.home, g.home_lineup_ids, g.home_id,
                              g.probable_home, g.probable_home_id,
                              g.probable_away_hand)
        if (home_in.lineup_xwoba is None and home_in.off_runs_factor is not None) \
                or (away_in.lineup_xwoba is None and away_in.off_runs_factor is not None):
            card.preliminary = True  # season-typical offense in use

        pf = _park_factor(pf_table, g.venue_name)
        card.home_inputs, card.away_inputs = home_in, away_in
        card.park_factor = pf

        # ---- simulate (10k joint samples; ML, RL, total from same run)
        sim = simulate_game(home_in, away_in, park_factor=pf,
                            weather_mult=wx_mult, seed=g.game_pk)
        if sim is not None and not sim.sanity_ok():
            log_error(f"MLB {g.away}@{g.home} {date_str}",
                      f"sim sanity fail: mean_total={sim.mean_total:.2f} "
                      "outside 3-20 — markets suppressed")
            sim = None
        card.sim = sim
        if sim is not None:
            card.model_note = sim.model_inputs_note
        else:
            missing = []
            for t in (away_in, home_in):
                if not t.offense_available():
                    missing.append(f"{t.name} offense")
                if not t.pitching_available():
                    missing.append(f"{t.name} SP metrics")
            card.model_note = "no model: missing " + ", ".join(missing) \
                if missing else "no model: sanity fail"

        # ---- splits (context only)
        if splits_by_team:
            for team in (g.away, g.home, g.away_abbr, g.home_abbr):
                card.splits.extend(splits_by_team.get(team, []))

        # ---- market evaluation
        if card.odds_available and ev is not None:
            hs, as_ = ev.home, ev.away  # odds-provider side names
            if sim is not None:
                ml_h, ml_a = eval_two_way("ml", ev.markets.get("ml", []),
                                          hs, as_, sim.home_win, book_priority,
                                          preliminary=card.preliminary,
                                          config=config)
                card.evals += [ml_h, ml_a]

                rl_quotes = ev.markets.get("rl", [])
                if rl_quotes:
                    # derivative of the same distribution (Part 2C)
                    fav_home = sim.home_win >= 0.5
                    if fav_home:
                        p_fav = sim.p_home_minus_15
                        fav, dog = hs, as_
                    else:
                        p_fav = sim.p_away_minus_15
                        fav, dog = as_, hs
                    rl_f, rl_d = eval_two_way(
                        "rl", rl_quotes, fav, dog, p_fav, book_priority,
                        line=-1.5, preliminary=card.preliminary, config=config)
                    # dog quotes carry line +1.5; re-pull best at that line
                    from adapters.odds_adapter import best_price  # noqa: PLC0415
                    from gates.edge_gate import evaluate as _ev  # noqa: PLC0415
                    from gates.edge_gate import thresholds_from_config  # noqa: PLC0415
                    _er, _rr = thresholds_from_config(config, card.preliminary)
                    bd = best_price(rl_quotes, dog, line=1.5)
                    rl_d.best = bd
                    rl_d.line = 1.5
                    rl_d.gate = _ev(rl_d.model_prob, rl_d.fair_prob,
                                    bd.price if bd else None,
                                    preliminary=card.preliminary,
                                    edge_pp_req=_er, ratio_req=_rr)
                    card.evals += [rl_f, rl_d]

                tot_quotes = ev.markets.get("total", [])
                line = consensus_line(tot_quotes, "over")
                if line is not None:
                    p_over = sim.p_over(line)
                    card.total_line = line
                    card.total_probs_pm1 = {
                        line - 1: sim.p_over(line - 1),
                        line: p_over,
                        line + 1: sim.p_over(line + 1),
                    }
                    ov, un = eval_two_way("total", tot_quotes, "over", "under",
                                          p_over, book_priority, line=line,
                                          preliminary=card.preliminary,
                                          config=config)
                    card.evals += [ov, un]

        # ---- "why" line for plays
        why = []
        if home_in.sp_xfip is not None and away_in.sp_xfip is not None:
            why.append(f"SP xFIP {g.probable_home or '?'} {home_in.sp_xfip:.2f} "
                       f"vs {g.probable_away or '?'} {away_in.sp_xfip:.2f}")
        if wx_note and "neutral" not in wx_note:
            why.append(wx_note)
        if pf is not None and abs(pf - 1.0) >= 0.04:
            why.append(f"park factor {pf:.2f}")
        card.why = "; ".join(why)
        cards.append(card)

    return cards


def splits_str(card: GameCard) -> str:
    """Render bets%/handle% context with $SHARP-SIDE flag, or N/A."""
    if not card.splits:
        return "N/A"
    parts = []
    for s in card.splits[:2]:
        flag = sharp_side_flag(s.bets_pct, s.handle_pct)
        parts.append(f"{s.bets_pct:.0f}%/{s.handle_pct:.0f}% on {s.side}"
                     + (f" {flag}" if flag else ""))
    return "; ".join(parts)
