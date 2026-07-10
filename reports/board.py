"""THE DAY BOARD (Part 5) — reports/YYYY-MM-DD.md.

ADHD-friendly: verdict-first, scannable, zero narrative filler. Missing
data renders as `—` (model/odds) or `N/A` (splits). A slate with zero
plays is a successful output and says so.
"""
from __future__ import annotations

from pathlib import Path

from core.manifest import Manifest
from reports.marketeval import MarketEval, fmt_price, fmt_prob
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

    # ------------------------------------------------- totals ±1 detail
    detail = []
    for c in mlb_cards:
        if c.total_probs_pm1:
            probs = " / ".join(f"P(o{ln:g})={p * 100:.1f}%"
                               for ln, p in sorted(c.total_probs_pm1.items()))
            detail.append(f"- {c.game.away_abbr} @ {c.game.home_abbr}: {probs}"
                          + (f" — {c.model_note}" if c.model_note else ""))
    for c in tennis_cards:
        if c.total_probs_pm1:
            probs = " / ".join(f"P(o{ln:g})={p * 100:.1f}%"
                               for ln, p in sorted(c.total_probs_pm1.items()))
            detail.append(f"- {c.player_a} vs {c.player_b}: {probs}")
    if detail:
        out += ["### Totals at posted number ±1 (key numbers)", ""]
        out += detail
        out.append("")

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
