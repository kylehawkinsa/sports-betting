"""Pluggable odds adapter (Part 1A/1B) — provider chosen in config.yaml.

Providers implemented:
  - the_odds_api      (the-odds-api.com; free tier = MLB moneyline only)
  - sportsgameodds    (sportsgameodds.com; free tier, includes Pinnacle)
  - odds_api_io       (odds-api.io; free pre-match)

All providers normalize into the same schema (OddsEvent / MarketOdds /
Quote). Openers: the first snapshot ever seen for an event-market-side is
persisted to data/openers/ and shown as the opener with movement direction.
If the pull fails, the pipeline renders ODDS UNAVAILABLE and zero plays are
issued (Part 7).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from core.config import get_api_key
from core.http import fetch_json
from core.manifest import Manifest, SourceRecord, utcnow_iso
from models.devig import american_to_decimal, american_to_implied

ROOT = Path(__file__).resolve().parent.parent
OPENERS_DIR = ROOT / "data" / "openers"

# market keys used across the codebase:
#   MLB:    "ml", "rl" (spread ±1.5), "total"
#   Tennis: "ml", "spread" (games), "total_games"


@dataclass
class Quote:
    book: str
    side: str            # team/player name, or "over"/"under"
    price: int           # american odds
    line: float | None = None   # spread/total number; None for ML

    @property
    def implied(self) -> float:
        return american_to_implied(self.price)


@dataclass
class OddsEvent:
    sport: str                       # "mlb" | "tennis"
    event_id: str
    home: str
    away: str
    start_utc: str
    markets: dict[str, list[Quote]] = field(default_factory=dict)
    tournament: str = ""
    round: str = ""
    surface: str = ""                # tennis only, if provider supplies it
    best_of: int | None = None       # tennis only
    fetched_at: str = field(default_factory=utcnow_iso)


# ---------------------------------------------------------------- providers

def _fetch_the_odds_api(sport: str, manifest: Manifest) -> list[OddsEvent] | None:
    key = get_api_key("THE_ODDS_API_KEY")
    if not key:
        manifest.add(SourceRecord(name=f"odds_{sport}", endpoint="the-odds-api.com",
                                  status="FAIL", note="THE_ODDS_API_KEY not set"))
        return None
    if sport == "mlb":
        sport_keys = ["baseball_mlb"]
    else:
        # tennis sport keys vary by tournament; pull the index and select active
        idx, rec = fetch_json("odds_sports_index",
                              "https://api.the-odds-api.com/v4/sports",
                              params={"apiKey": key})
        manifest.add(rec)
        if idx is None:
            return None
        sport_keys = [s["key"] for s in idx
                      if s.get("group") == "Tennis" and s.get("active")]
        if not sport_keys:
            manifest.add(SourceRecord(name="odds_tennis",
                                      endpoint="the-odds-api.com", status="OK",
                                      rows=0, note="no active tennis sports"))
            return []
    events: list[OddsEvent] = []
    for sk in sport_keys:
        url = f"https://api.the-odds-api.com/v4/sports/{sk}/odds"
        data, rec = fetch_json(
            f"odds_{sk}", url,
            params={"apiKey": key, "regions": "us,eu",
                    "markets": "h2h,spreads,totals", "oddsFormat": "american"},
        )
        rec.endpoint = url  # never log the apiKey param
        manifest.add(rec)
        if data is None:
            continue
        for ev in data:
            home, away = ev.get("home_team", ""), ev.get("away_team", "")
            markets: dict[str, list[Quote]] = {}
            for bk in ev.get("bookmakers", []):
                book = bk.get("key", "?")
                for mkt in bk.get("markets", []):
                    mkey = {"h2h": "ml",
                            "spreads": "rl" if sport == "mlb" else "spread",
                            "totals": "total" if sport == "mlb" else "total_games",
                            }.get(mkt.get("key"))
                    if mkey is None:
                        continue
                    for oc in mkt.get("outcomes", []):
                        side = oc.get("name", "")
                        if mkey in ("total", "total_games"):
                            side = side.lower()
                        markets.setdefault(mkey, []).append(Quote(
                            book=book, side=side,
                            price=int(oc.get("price", 0)),
                            line=oc.get("point"),
                        ))
            events.append(OddsEvent(
                sport=sport, event_id=ev.get("id", ""), home=home, away=away,
                start_utc=ev.get("commence_time", ""),
                markets=markets, tournament=ev.get("sport_title", ""),
            ))
    return events


def _fetch_sportsgameodds(sport: str, manifest: Manifest) -> list[OddsEvent] | None:
    key = get_api_key("SPORTSGAMEODDS_API_KEY")
    if not key:
        manifest.add(SourceRecord(name=f"odds_{sport}", endpoint="sportsgameodds.com",
                                  status="FAIL", note="SPORTSGAMEODDS_API_KEY not set"))
        return None
    league = "MLB" if sport == "mlb" else "ATP"
    url = "https://api.sportsgameodds.com/v2/events"
    data, rec = fetch_json(
        f"odds_{sport}", url,
        params={"leagueID": league, "oddsAvailable": "true"},
        headers={"X-Api-Key": key},
        row_counter=lambda d: len(d.get("data", [])),
    )
    manifest.add(rec)
    if data is None:
        return None
    events: list[OddsEvent] = []
    for ev in data.get("data", []):
        teams = ev.get("teams", {})
        home = (teams.get("home") or {}).get("names", {}).get("long", "")
        away = (teams.get("away") or {}).get("names", {}).get("long", "")
        markets: dict[str, list[Quote]] = {}
        for odd_id, odd in (ev.get("odds") or {}).items():
            # sportsgameodds oddIDs look like "points-home-game-ml-home"
            parts = odd_id.split("-")
            if "ml" in parts:
                mkey = "ml"
            elif "sp" in parts or "spread" in parts:
                mkey = "rl" if sport == "mlb" else "spread"
            elif "ou" in parts:
                mkey = "total" if sport == "mlb" else "total_games"
            else:
                continue
            for book, bo in (odd.get("byBookmaker") or {}).items():
                price = bo.get("odds")
                if price is None:
                    continue
                side = "over" if parts[-1] == "over" else (
                    "under" if parts[-1] == "under" else (
                        home if "home" in parts else away))
                try:
                    markets.setdefault(mkey, []).append(Quote(
                        book=book, side=side, price=int(str(price).replace("+", "")),
                        line=float(bo["spread"]) if bo.get("spread") is not None
                        else (float(bo["overUnder"]) if bo.get("overUnder") is not None else None),
                    ))
                except (ValueError, TypeError):
                    continue
        events.append(OddsEvent(
            sport=sport, event_id=str(ev.get("eventID", "")), home=home, away=away,
            start_utc=(ev.get("status") or {}).get("startsAt", ""), markets=markets,
        ))
    return events


def _fetch_odds_api_io(sport: str, manifest: Manifest) -> list[OddsEvent] | None:
    key = get_api_key("ODDS_API_IO_KEY")
    if not key:
        manifest.add(SourceRecord(name=f"odds_{sport}", endpoint="odds-api.io",
                                  status="FAIL", note="ODDS_API_IO_KEY not set"))
        return None
    # odds-api.io pre-match endpoint; sport slugs per their docs
    slug = "baseball" if sport == "mlb" else "tennis"
    url = "https://api.odds-api.io/v2/events"
    data, rec = fetch_json(f"odds_{sport}", url,
                           params={"apiKey": key, "sport": slug, "status": "pending"})
    rec.endpoint = url
    manifest.add(rec)
    if data is None:
        return None
    events: list[OddsEvent] = []
    for ev in data if isinstance(data, list) else data.get("events", []):
        markets: dict[str, list[Quote]] = {}
        for bk in ev.get("bookmakers", []) or []:
            book = bk.get("name", "?")
            for mkt in bk.get("markets", []) or []:
                mname = (mkt.get("name") or "").lower()
                if "moneyline" in mname or mname == "h2h":
                    mkey = "ml"
                elif "spread" in mname or "handicap" in mname:
                    mkey = "rl" if sport == "mlb" else "spread"
                elif "total" in mname or "over/under" in mname:
                    mkey = "total" if sport == "mlb" else "total_games"
                else:
                    continue
                for oc in mkt.get("odds", []) or []:
                    try:
                        markets.setdefault(mkey, []).append(Quote(
                            book=book, side=str(oc.get("label", "")).lower()
                            if mkey in ("total", "total_games") else oc.get("label", ""),
                            price=int(oc.get("american", oc.get("price", 0))),
                            line=oc.get("points"),
                        ))
                    except (ValueError, TypeError):
                        continue
        events.append(OddsEvent(
            sport=sport, event_id=str(ev.get("id", "")),
            home=ev.get("home", ev.get("homeTeam", "")),
            away=ev.get("away", ev.get("awayTeam", "")),
            start_utc=ev.get("starts", ev.get("commence_time", "")),
            markets=markets,
        ))
    return events


PROVIDERS = {
    "the_odds_api": _fetch_the_odds_api,
    "sportsgameodds": _fetch_sportsgameodds,
    "odds_api_io": _fetch_odds_api_io,
}


def fetch_odds(sport: str, config: dict, manifest: Manifest) -> list[OddsEvent] | None:
    """Returns None on total failure (=> ODDS UNAVAILABLE, zero plays)."""
    provider = (config.get("odds", {}) or {}).get("provider", "the_odds_api")
    fn = PROVIDERS.get(provider)
    if fn is None:
        manifest.add(SourceRecord(name=f"odds_{sport}", endpoint=provider,
                                  status="FAIL", note=f"unknown provider '{provider}'"))
        return None
    return fn(sport, manifest)


# ------------------------------------------------------------------ openers

def _opener_path(sport: str, date_str: str) -> Path:
    return OPENERS_DIR / f"{sport}_{date_str}.json"


def record_openers(sport: str, date_str: str, events: list[OddsEvent]) -> dict:
    """Persist the first snapshot seen per event/market/side (best price).
    Returns the opener map {event_key: {market: {side: {price, line, ts}}}}."""
    path = _opener_path(sport, date_str)
    openers: dict = {}
    if path.exists():
        openers = json.loads(path.read_text())
    changed = False
    for ev in events:
        ekey = f"{ev.away}@{ev.home}"
        for mkey, quotes in ev.markets.items():
            for q in quotes:
                skey = f"{q.side}|{q.line if q.line is not None else ''}"
                slot = openers.setdefault(ekey, {}).setdefault(mkey, {})
                if skey not in slot:
                    slot[skey] = {"price": q.price, "line": q.line,
                                  "book": q.book, "ts": utcnow_iso()}
                    changed = True
    if changed:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(openers, indent=1))
    return openers


def opener_for(openers: dict, ev: OddsEvent, mkey: str, side: str,
               line: float | None) -> dict | None:
    ekey = f"{ev.away}@{ev.home}"
    skey = f"{side}|{line if line is not None else ''}"
    return openers.get(ekey, {}).get(mkey, {}).get(skey)


# ----------------------------------------------------------- market helpers

def best_price(quotes: list[Quote], side: str,
               line: float | None = None) -> Quote | None:
    """Best (highest-payout) american price for a side, at a specific line
    when given. Line shopping is mandatory (Part 3)."""
    cands = [q for q in quotes if q.side == side
             and (line is None or q.line == line)]
    if not cands:
        return None
    # decimal odds are monotone in payout across the +/- american boundary
    return max(cands, key=lambda q: american_to_decimal(q.price))


def consensus_line(quotes: list[Quote], side: str) -> float | None:
    """Most common posted line for a side (e.g. the market total)."""
    lines = [q.line for q in quotes if q.side == side and q.line is not None]
    if not lines:
        return None
    return max(set(lines), key=lines.count)


def reference_book_pair(quotes: list[Quote], side_a: str, side_b: str,
                        book_priority: list[str],
                        line: float | None = None) -> tuple[str, Quote, Quote] | None:
    """Two-sided prices from the de-vig reference book: Pinnacle if present,
    else the sharpest book per priority list; None -> caller falls back to
    multi-book consensus."""
    by_book: dict[str, dict[str, Quote]] = {}
    for q in quotes:
        if line is not None and q.line != line:
            continue
        by_book.setdefault(q.book, {})[q.side] = q
    for book in book_priority:
        pair = by_book.get(book)
        if pair and side_a in pair and side_b in pair:
            return book, pair[side_a], pair[side_b]
    return None


def all_book_pairs(quotes: list[Quote], side_a: str, side_b: str,
                   line: float | None = None) -> dict[str, tuple[float, float]]:
    by_book: dict[str, dict[str, Quote]] = {}
    for q in quotes:
        if line is not None and q.line != line:
            continue
        by_book.setdefault(q.book, {})[q.side] = q
    return {b: (p[side_a].price, p[side_b].price)
            for b, p in by_book.items() if side_a in p and side_b in p}
