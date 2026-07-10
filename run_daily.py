#!/usr/bin/env python3
"""EDGE HUB daily run: pull -> model -> board (cron ~14:00 UTC).

Usage:
    python run_daily.py [--date YYYY-MM-DD]
                        [--splits-paste FILE]    # Action Network PRO text
                        [--tennis-manual FILE]   # manual SPW/RPW inputs
                        [--no-mlb] [--no-tennis]

Prime Directive enforcement lives in the layers below; this file only
orchestrates. A run with source failures still writes a board — it says so
in the header and the affected fields show `—`.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date as date_cls

from adapters import mlb_statsapi
from adapters.odds_adapter import fetch_odds
from adapters.splits_dk import fetch_dk_splits
from adapters.splits_paste import parse_splits_paste
from adapters.tennis_manual import parse_manual_matches
from core.config import load_config
from core.errorlog import log_error
from core.manifest import Manifest
from reports import clv
from reports.board import render_board, write_board
from reports.pipeline_mlb import run_mlb
from reports.pipeline_tennis import run_tennis


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=date_cls.today().isoformat())
    ap.add_argument("--splits-paste")
    ap.add_argument("--tennis-manual")
    ap.add_argument("--no-mlb", action="store_true")
    ap.add_argument("--no-tennis", action="store_true")
    args = ap.parse_args()

    config = load_config()
    manifest = Manifest()
    date_str = args.date

    mlb_cards, tennis_cards = [], []
    mlb_odds_ok = tennis_odds_ok = True

    if not args.no_mlb:
        games = mlb_statsapi.fetch_schedule(date_str, manifest)
        odds_mlb = fetch_odds("mlb", config, manifest)
        mlb_odds_ok = odds_mlb is not None
        splits_by_team = None
        if (config.get("splits", {}) or {}).get("dk_enabled", False):
            dk = fetch_dk_splits(manifest,
                                 url=(config.get("splits", {}) or {}).get("dk_url"))
            if dk:
                splits_by_team = {}
                for game_key, ss in dk.items():
                    away, _, home = game_key.partition("@")
                    for s in ss:
                        splits_by_team.setdefault(s.side, []).append(s)
        if args.splits_paste:
            names = [n for g in games for n in
                     (g.away, g.home, g.away_abbr, g.home_abbr)]
            pasted = parse_splits_paste(args.splits_paste, names, manifest)
            splits_by_team = {**(splits_by_team or {}), **pasted}
        mlb_cards = run_mlb(date_str, config, manifest, games,
                            odds_mlb, splits_by_team)

    if not args.no_tennis:
        odds_ten = fetch_odds("tennis", config, manifest)
        tennis_odds_ok = odds_ten is not None
        manual = (parse_manual_matches(args.tennis_manual, manifest)
                  if args.tennis_manual else [])
        tennis_cards = run_tennis(date_str, config, manifest, odds_ten, manual)

    # ---- log PLAYS to the CLV ledger (append-only, idempotent per day)
    for c in mlb_cards:
        for e in c.evals:
            if e.gate.verdict == "PLAY" and e.best is not None:
                clv.log_play(date_str, "mlb",
                             f"{c.game.away_abbr}@{c.game.home_abbr}",
                             e.market, e.side, e.line, e.best.price,
                             e.best.book, e.model_prob, e.fair_prob,
                             e.gate.stake_units)
    for c in tennis_cards:
        for e in c.evals:
            if e.gate.verdict == "PLAY" and e.best is not None:
                clv.log_play(date_str, "tennis",
                             f"{c.player_a} vs {c.player_b}",
                             e.market, e.side, e.line, e.best.price,
                             e.best.book, e.model_prob, e.fair_prob,
                             e.gate.stake_units)

    clv_section = "\n\n".join(x for x in (
        clv.todays_plays_section(date_str),
        clv.weekly_summary(date_cls.fromisoformat(date_str)),
    ) if x)

    content = render_board(date_str, manifest, mlb_cards, tennis_cards,
                           mlb_odds_ok, tennis_odds_ok, clv_section)
    path = write_board(date_str, content)
    print(f"board written: {path}")
    print(f"sources: {manifest.ok_count}/{manifest.total} OK"
          + (" — FAILURES present" if manifest.has_failures else ""))
    for r in manifest.failures():
        log_error(f"daily run {date_str}", f"source FAIL: {r.name} ({r.note})")
    n_plays = sum(1 for c in mlb_cards for e in c.evals
                  if e.gate.verdict == "PLAY") + \
        sum(1 for c in tennis_cards for e in c.evals
            if e.gate.verdict == "PLAY")
    print(f"plays: {n_plays} (a zero-play slate is a successful output)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
