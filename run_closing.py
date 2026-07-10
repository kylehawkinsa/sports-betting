#!/usr/bin/env python3
"""EDGE HUB closing run: closing lines -> CLV (cron ~04:00 UTC).

For every logged play of the target date (default: yesterday, since this
runs after midnight UTC) that has no close yet, fetch current odds, take
the de-vig reference book's price (Pinnacle if present) as the closing
price, compute CLV, and append the summary to that date's report.

If the closing price cannot be fetched the play simply stays open — CLV is
never estimated (Right Rule).
"""
from __future__ import annotations

import argparse
import sys
from datetime import date as date_cls
from datetime import timedelta

from adapters.odds_adapter import fetch_odds, reference_book_pair
from core.config import load_config
from core.errorlog import log_error
from core.manifest import Manifest
from models.devig import devig_two_way
from reports import clv
from reports.board import REPORTS_DIR


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date",
                    default=(date_cls.today() - timedelta(days=1)).isoformat())
    args = ap.parse_args()
    date_str = args.date

    config = load_config()
    manifest = Manifest()
    book_priority = (config.get("odds", {}) or {}).get("book_priority",
                                                       ["pinnacle"])

    plays = clv.load_plays(date_str)
    already = {(c["date"], c["sport"], c["event"], c["market"],
                c["side"], c["line"]) for c in clv.load_closes()}
    open_plays = [p for p in plays
                  if (p["date"], p["sport"], p["event"], p["market"],
                      p["side"], p["line"]) not in already]
    if not open_plays:
        print(f"no open plays for {date_str}")
        return 0

    events_by_sport = {}
    for sport in {p["sport"] for p in open_plays}:
        events_by_sport[sport] = fetch_odds(sport, config, manifest) or []

    closed = 0
    for p in open_plays:
        evs = events_by_sport.get(p["sport"], [])
        match = None
        for ev in evs:
            key = (f"{ev.away}@{ev.home}" if p["sport"] == "mlb"
                   else f"{ev.home} vs {ev.away}")
            if key == p["event"] or (p["side"] in (ev.home, ev.away)):
                match = ev
                break
        if match is None:
            continue
        quotes = match.markets.get(p["market"], [])
        if not quotes:
            continue
        sides = sorted({q.side for q in quotes})
        other = next((s for s in sides if s != p["side"]), None)
        if other is None:
            continue
        ref = reference_book_pair(quotes, p["side"], other, book_priority,
                                  line=p["line"])
        if ref is None:
            continue
        book, q_side, q_other = ref
        closing_fair = None
        try:
            closing_fair, _ = devig_two_way(q_side.price, q_other.price)
        except ValueError:
            pass
        clv.record_close(p, q_side.price, closing_fair, book)
        closed += 1

    print(f"closed {closed}/{len(open_plays)} open plays for {date_str}")
    for r in manifest.failures():
        log_error(f"closing run {date_str}", f"source FAIL: {r.name} ({r.note})")

    # append the refreshed CLV summary to the date's report (append-only)
    report = REPORTS_DIR / f"{date_str}.md"
    if report.exists() and closed:
        summary = clv.weekly_summary(date_cls.fromisoformat(date_str))
        with open(report, "a") as f:
            f.write(f"\n---\n### Closing update ({date_str})\n\n{summary}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
