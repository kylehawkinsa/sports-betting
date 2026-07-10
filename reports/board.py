"""THE DAY BOARD (Part 5) — reports/YYYY-MM-DD.md.

ADHD-friendly: verdict-first, scannable, zero narrative filler. Missing
data renders as `—` (model/odds) or `N/A` (splits). A slate with zero
plays is a successful output and says so.
"""
from __future__ import annotations

from pathlib import Path

from adapters.odds_adapter import opener_for
from core.manifest import Manifest
from models.tennis_markov import p_hold
from reports.marketeval import MarketEval, ev_per_unit, fmt_price, fmt_prob
from reports.pipeline_mlb import GameCard, splits_str
from reports.pipeline_tennis import MatchCard

ROOT = Path(__file__).resolve().parent.parent
REPORTS_DIR = ROOT / "reports"


def _game_verdict(evals: list[MarketEval], odds_available: bool,
                  has_model: bool, insufficient: bool = False) -> str:
    if insufficient:
        return "INSUFFICIENT DATA"
    if not odds_available:
        return "ODDS UNAVAILABLE"
    if not has_model:
        return "PASS (no model)"
    verdicts = [e.gate.verdict for e in evals]
    if "PLAY" in verdicts:
        return "PLAY"
    if "LEAN" in verdicts:
        return "LEAN"
    return "PASS"


def _play_block(sport: str, matchup: str, when: str, e: MarketEval,
                why: str, splits: str, preliminary: bool) -> str:
    line_txt = "" if e.line is None else f" {e.line:+g}" if e.market in (
        "rl", "spread") else f" {e.line:g}"
    k = e.gate.kelly
    lines = [
        f"**[{sport}] {matchup} {when} — {e.side} "
        f"{e.market.upper()}{line_txt} {fmt_price(e.best.price if e.best else None)}"
        f" (best: {e.best.book if e.best else '—'})**"
        + ("  `PRELIMINARY`" if preliminary else ""),
        f"model {fmt_prob(e.model_prob)} | fair {fmt_prob(e.fair_prob)} "
        f"(ref: {e.ref_book or '—'}) | edge {e.gate.edge_pp:+.1f}pp | "
        f"ratio {e.gate.ratio:.2f}x | **STAKE {e.gate.stake_units:.2f}u**",
        f"kelly: {k.math_str()}" if k else "",
        f"why: {why}" if why else "",
        f"splits: {splits}" if splits and splits != "N/A" else "splits: N/A",
    ]
    return "\n".join(x for x in lines if x)


def _best_eval(evals: list[MarketEval], market: str) -> MarketEval | None:
    cands = [e for e in evals if e.market == market]
    if not cands:
        return None
    order = {"PLAY": 0, "LEAN": 1, "PASS": 2, "NO MARKET": 3,
             "INSUFFICIENT DATA": 4}
    return sorted(cands, key=lambda e: (order.get(e.gate.verdict, 9),
                                        -(e.gate.edge_pp or -999)))[0]


def _cell(e: MarketEval | None) -> str:
    if e is None or e.best is None:
        return "—"
    line_txt = "" if e.line is None else f" {e.line:+g}" if e.market in (
        "rl", "spread") else f" {e.line:g}"
    side = e.side if e.market not in ("total", "total_games") else e.side[0].upper()
    return f"{side}{line_txt} {fmt_price(e.best.price)} ({e.best.book})"


def _markets_table(card_evals: list[MarketEval], openers: dict,
                   odds_event) -> list[str]:
    """Full per-market breakdown: every number that went into the verdict."""
    rows = ["| MKT | SIDE | LINE | BEST | BOOK | IMPLIED | FAIR | MODEL "
            "| EDGE | RATIO | EV/1u | ¼-KELLY | OPEN→NOW | GATE |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for e in card_evals:
        implied = e.best.implied if e.best else None
        ev1u = ev_per_unit(e.model_prob, e.best.price if e.best else None)
        stake = (f"{e.gate.stake_units:.2f}u" if e.gate.verdict == "PLAY"
                 else "0u")
        move = "—"
        if e.best and openers and odds_event is not None:
            op = opener_for(openers, odds_event, e.market, e.side, e.line)
            if op:
                arrow = ("→" if op["price"] == e.best.price
                         else "▲" if e.best.price > op["price"] else "▼")
                move = f"{fmt_price(op['price'])}→{fmt_price(e.best.price)} {arrow}"
        rows.append(
            f"| {e.market} | {e.side} | {e.line if e.line is not None else '—'} "
            f"| {fmt_price(e.best.price if e.best else None)} "
            f"| {e.best.book if e.best else '—'} | {fmt_prob(implied)} "
            f"| {fmt_prob(e.fair_prob)} | {fmt_prob(e.model_prob)} "
            f"| {f'{e.gate.edge_pp:+.1f}pp' if e.gate.edge_pp is not None else '—'} "
            f"| {f'{e.gate.ratio:.3f}x' if e.gate.ratio is not None else '—'} "
            f"| {f'{ev1u * 100:+.1f}%' if ev1u is not None else '—'} "
            f"| {stake} | {move} | {e.gate.verdict} |")
    return rows


def _sp_line(t) -> str:
    if t is None:
        return "—"
    bits = []
    if t.sp_xera is not None:
        bits.append(f"xERA {t.sp_xera:.2f}")
    if t.sp_xfip is not None:
        bits.append(f"xFIP {t.sp_xfip:.2f}")
    if t.sp_kbb is not None:
        bits.append(f"K-BB% {t.sp_kbb * 100:.1f}")
    if t.sp_exp_ip is not None:
        bits.append(f"exp IP {t.sp_exp_ip:.1f}")
    return ", ".join(bits) if bits else "—"


def _off_line(t) -> str:
    if t is None:
        return "—"
    if t.lineup_xwoba is not None:
        return f"lineup xwOBA {t.lineup_xwoba:.3f} (platoon-adj)"
    if t.off_runs_factor is not None:
        return f"season R/G factor {t.off_runs_factor:.2f}× league (PRELIM fallback)"
    return "—"


def _deep_dive_mlb(c: GameCard) -> str:
    g = c.game
    verdict = _game_verdict(c.evals, c.odds_available, c.sim is not None)
    lines = [f"### [MLB] {g.away_abbr} @ {g.home_abbr} — {g.start_et} — "
             f"**{verdict}**" + ("  `PRELIMINARY`" if c.preliminary else ""),
             f"_{g.venue_name}_" if g.venue_name else ""]
    lines.append(f"- **Pitching**: {g.probable_home or '—'} "
                 f"({g.probable_home_hand or '?'}HP, {_sp_line(c.home_inputs)}) vs "
                 f"{g.probable_away or '—'} "
                 f"({g.probable_away_hand or '?'}HP, {_sp_line(c.away_inputs)})")
    lines.append(f"- **Offense**: {g.home_abbr} {_off_line(c.home_inputs)}; "
                 f"{g.away_abbr} {_off_line(c.away_inputs)}"
                 + ("" if g.lineups_posted else " — lineups unposted"))
    pf = f"{c.park_factor:.2f}" if c.park_factor is not None else "— (neutral)"
    lines.append(f"- **Environment**: park factor {pf}; {c.weather_note}")
    if c.sim is not None:
        s = c.sim
        lines.append(
            f"- **Simulation ({s.n_sims:,} runs)**: {g.home_abbr} win "
            f"{s.home_win * 100:.1f}% | projected {g.home_abbr} "
            f"{s.home_mean:.2f} – {g.away_abbr} {s.away_mean:.2f} "
            f"(total {s.mean_total:.2f}) | one-run game "
            f"{s.p_one_run * 100:.0f}% | extras {s.p_extras * 100:.0f}%"
            + (f" | {s.model_inputs_note}" if s.model_inputs_note else ""))
        if c.total_probs_pm1:
            probs = " / ".join(f"P(over {ln:g}) = {p * 100:.1f}%"
                               for ln, p in sorted(c.total_probs_pm1.items()))
            lines.append(f"- **Total at key numbers**: {probs}")
    else:
        lines.append(f"- **Simulation**: not run — {c.model_note}")
    if c.why:
        lines.append(f"- **Angles**: {c.why}")
    lines.append(f"- **Splits (context only, never gates)**: {splits_str(c)}")
    if c.evals:
        lines.append("")
        lines += _markets_table(c.evals, c.openers, c.odds_event)
    else:
        lines.append("- **Markets**: none evaluated "
                     + ("(odds unavailable)" if not c.odds_available else ""))
    return "\n".join(x for x in lines if x)


def _deep_dive_tennis(c: MatchCard) -> str:
    verdict = _game_verdict(c.evals, c.odds_available, c.dist is not None,
                            insufficient=c.insufficient or not c.format_supported)
    lines = [f"### [TEN] {c.player_a} vs {c.player_b} — **{verdict}**",
             f"_{c.tournament or '—'} | {c.surface or '?'} | Bo{c.best_of} | "
             f"inputs: {c.source_mode or '—'}_"]
    if c.pa is not None and c.pb is not None:
        lines.append(
            f"- **Serve-point win (opponent-adjusted)**: {c.player_a} "
            f"{c.pa * 100:.1f}% / {c.player_b} {c.pb * 100:.1f}% → hold "
            f"{p_hold(c.pa) * 100:.1f}% vs {p_hold(c.pb) * 100:.1f}%")
    if c.dist is not None:
        d = c.dist
        exp_games = sum(t * p for t, p in d.total_games_dist.items())
        sets = sorted(d.set_score_probs.items(), key=lambda kv: -kv[1])[:3]
        sets_txt = ", ".join(f"{a}-{b} {p * 100:.0f}%" for (a, b), p in sets)
        lines.append(
            f"- **Markov chain**: {c.player_a} match win "
            f"{d.p_match_a * 100:.1f}% | expected total games {exp_games:.1f} "
            f"| most likely sets: {sets_txt}")
        if c.total_probs_pm1:
            probs = " / ".join(f"P(over {ln:g}) = {p * 100:.1f}%"
                               for ln, p in sorted(c.total_probs_pm1.items()))
            lines.append(f"- **Game total at key numbers**: {probs}")
    else:
        lines.append(f"- **Model**: not run — {c.model_note or 'inputs missing'}")
    if c.insufficient:
        lines.append(f"- ⚠️ **INSUFFICIENT DATA**: {c.model_note or 'sample < 20 matches'}"
                     " — no stake recommendation is valid on this match")
    if c.why:
        lines.append(f"- **Inputs**: {c.why}")
    if c.evals:
        lines.append("")
        lines += _markets_table(c.evals, {}, None)
    else:
        lines.append("- **Markets**: none evaluated "
                     + ("(odds unavailable)" if not c.odds_available else ""))
    return "\n".join(x for x in lines if x)


def render_board(date_str: str, manifest: Manifest,
                 mlb_cards: list[GameCard], tennis_cards: list[MatchCard],
                 mlb_odds_ok: bool, tennis_odds_ok: bool,
                 clv_section: str = "") -> str:
    header = (f"# EDGE HUB — {date_str} | MLB: {len(mlb_cards)} games | "
              f"TEN: {len(tennis_cards)} matches | "
              f"SOURCES: {manifest.ok_count}/{manifest.total} OK")
    out = [header, ""]
    if manifest.has_failures:
        fails = ", ".join(r.name for r in manifest.failures())
        out += [f"> ⚠️ **SOURCE FAILURES THIS RUN**: {fails}. "
                "Affected fields show `—` and were excluded from the model.", ""]
    if not mlb_odds_ok or not tennis_odds_ok:
        which = [s for s, ok in (("MLB", mlb_odds_ok),
                                 ("TENNIS", tennis_odds_ok)) if not ok]
        out += [f"> 🚫 **ODDS UNAVAILABLE ({'/'.join(which)})** — zero plays "
                "can be issued for these markets this run.", ""]

    # ---------------------------------------------------------- PLAYS
    out.append("## == PLAYS ==\n")
    plays, leans = [], []
    for c in mlb_cards:
        for e in c.evals:
            if e.gate.verdict == "PLAY":
                plays.append(_play_block("MLB", f"{c.game.away_abbr} @ {c.game.home_abbr}",
                                         c.game.start_et, e, c.why,
                                         splits_str(c), c.preliminary))
            elif e.gate.verdict == "LEAN":
                leans.append(f"[MLB] {c.game.away_abbr} @ {c.game.home_abbr} — "
                             f"{e.side} {e.market.upper()} "
                             f"{fmt_price(e.best.price if e.best else None)} "
                             f"(edge {e.gate.edge_pp:+.1f}pp, ratio {e.gate.ratio:.2f}x; "
                             f"{'; '.join(e.gate.reasons)})")
    for c in tennis_cards:
        for e in c.evals:
            if e.gate.verdict == "PLAY":
                plays.append(_play_block("TEN", f"{c.player_a} vs {c.player_b}",
                                         c.tournament, e, c.why, "N/A", False))
            elif e.gate.verdict == "LEAN":
                leans.append(f"[TEN] {c.player_a} vs {c.player_b} — {e.side} "
                             f"{e.market} {fmt_price(e.best.price if e.best else None)} "
                             f"(edge {e.gate.edge_pp:+.1f}pp, ratio {e.gate.ratio:.2f}x)")
    if plays:
        out.append("\n\n".join(plays))
    else:
        out.append("**No plays today.** Both edge gates passed on zero markets "
                   "— this is a successful output, not an error.")
    if leans:
        out += ["", "### LEANS (0u, watch-list only)", ""]
        out += [f"- {x}" for x in leans]
    out.append("")

    # ---------------------------------------------------------- BOARD
    out += ["## == BOARD ==", "",
            "| TIME | GAME | ML best | RL | TOTAL | BETS%/HANDLE% | MODEL% "
            "| FAIR% | EDGE | VERDICT |",
            "|---|---|---|---|---|---|---|---|---|---|"]
    for c in mlb_cards:
        ml = _best_eval(c.evals, "ml")
        rl = _best_eval(c.evals, "rl")
        tot = _best_eval(c.evals, "total")
        verdict = _game_verdict(c.evals, c.odds_available, c.sim is not None)
        if c.preliminary and c.sim is not None:
            verdict += " (PRELIM)"
        edge = f"{ml.gate.edge_pp:+.1f}pp" if ml and ml.gate.edge_pp is not None else "—"
        out.append(
            f"| {c.game.start_et} | {c.game.away_abbr} @ {c.game.home_abbr} "
            f"| {_cell(ml)} | {_cell(rl)} | {_cell(tot)} | {splits_str(c)} "
            f"| {fmt_prob(ml.model_prob) if ml else '—'} "
            f"| {fmt_prob(ml.fair_prob) if ml else '—'} | {edge} | {verdict} |")
    for c in tennis_cards:
        ml = _best_eval(c.evals, "ml")
        sp = _best_eval(c.evals, "spread")
        tot = _best_eval(c.evals, "total_games")
        verdict = _game_verdict(c.evals, c.odds_available, c.dist is not None,
                                insufficient=c.insufficient or not c.format_supported)
        edge = f"{ml.gate.edge_pp:+.1f}pp" if ml and ml.gate.edge_pp is not None else "—"
        out.append(
            f"| {c.start_utc or '—'} | {c.player_a} vs {c.player_b} "
            f"| {_cell(ml)} | {_cell(sp)} | {_cell(tot)} | N/A "
            f"| {fmt_prob(ml.model_prob) if ml else '—'} "
            f"| {fmt_prob(ml.fair_prob) if ml else '—'} | {edge} | {verdict} |")
    out.append("")

    # -------------------------------------------------------- DEEP DIVE
    if mlb_cards or tennis_cards:
        out += ["## == DEEP DIVE ==",
                "",
                "_Every game, full reasoning: model internals, every market "
                "at every book's best price, edge math, EV, Kelly, and line "
                "movement. The verdict is the conclusion — this is the "
                "argument._",
                ""]
        for c in mlb_cards:
            out += [_deep_dive_mlb(c), ""]
        for c in tennis_cards:
            out += [_deep_dive_tennis(c), ""]

    # ---------------------------------------------------------- CLV LOG
    out += ["## == CLV LOG ==", ""]
    out.append(clv_section if clv_section else
               "_No plays logged yet for this date._")
    out += ["",
            "> CLV is the grade, not wins/losses. Positive CLV over 100+ "
            "bets = the model is real; small-sample W/L is noise.", ""]

    out.append(manifest.to_markdown())
    out.append("")
    return "\n".join(out)


def write_board(date_str: str, content: str) -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORTS_DIR / f"{date_str}.md"
    path.write_text(content)
    return path
