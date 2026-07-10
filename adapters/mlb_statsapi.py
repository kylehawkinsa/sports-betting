"""MLB Stats API adapter — schedule, probables, lineups, venue, stadium weather.
Free, no key. All numbers displayed from this adapter trace to the manifest
record created here. Times converted to ET for display.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

from core.http import fetch_json
from core.manifest import Manifest, SourceRecord

SCHEDULE_URL = "https://statsapi.mlb.com/api/v1/schedule"
VENUE_URL = "https://statsapi.mlb.com/api/v1/venues/{venue_id}"
TEAM_STATS_URL = "https://statsapi.mlb.com/api/v1/teams/{team_id}/stats"
PEOPLE_URL = "https://statsapi.mlb.com/api/v1/people"
ET = ZoneInfo("America/New_York")


@dataclass
class MLBGame:
    game_pk: int
    away: str
    home: str
    away_abbr: str
    home_abbr: str
    start_utc: str                     # ISO from API
    start_et: str                      # "7:10 PM ET"
    away_id: int | None = None
    home_id: int | None = None
    venue_id: int | None = None
    venue_name: str = ""
    probable_away: str | None = None
    probable_away_id: int | None = None
    probable_away_hand: str | None = None
    probable_home: str | None = None
    probable_home_id: int | None = None
    probable_home_hand: str | None = None
    lineups_posted: bool = False
    away_lineup_ids: list[int] = field(default_factory=list)
    home_lineup_ids: list[int] = field(default_factory=list)
    status: str = ""


def _fmt_et(iso_utc: str) -> str:
    try:
        dt = datetime.fromisoformat(iso_utc.replace("Z", "+00:00")).astimezone(ET)
        return dt.strftime("%-I:%M %p ET")
    except Exception:
        return "—"


def fetch_schedule(date_str: str, manifest: Manifest) -> list[MLBGame]:
    params = {
        "sportId": 1,
        "date": date_str,
        "hydrate": "probablePitcher(note),team,lineups,weather",
    }
    data, rec = fetch_json(
        "mlb_schedule", SCHEDULE_URL, params=params,
        row_counter=lambda d: sum(len(x.get("games", [])) for x in d.get("dates", [])),
    )
    manifest.add(rec)
    if data is None:
        return []

    games: list[MLBGame] = []
    for d in data.get("dates", []):
        for g in d.get("games", []):
            teams = g.get("teams", {})
            away_t = teams.get("away", {}).get("team", {})
            home_t = teams.get("home", {}).get("team", {})
            pa = teams.get("away", {}).get("probablePitcher") or {}
            ph = teams.get("home", {}).get("probablePitcher") or {}
            lineups = g.get("lineups") or {}
            away_lineup = [p.get("id") for p in lineups.get("awayPlayers", []) if p.get("id")]
            home_lineup = [p.get("id") for p in lineups.get("homePlayers", []) if p.get("id")]
            games.append(MLBGame(
                game_pk=g.get("gamePk", 0),
                away=away_t.get("name", "—"),
                home=home_t.get("name", "—"),
                away_abbr=away_t.get("abbreviation") or away_t.get("teamName", "—"),
                home_abbr=home_t.get("abbreviation") or home_t.get("teamName", "—"),
                start_utc=g.get("gameDate", ""),
                start_et=_fmt_et(g.get("gameDate", "")),
                away_id=away_t.get("id"),
                home_id=home_t.get("id"),
                venue_id=(g.get("venue") or {}).get("id"),
                venue_name=(g.get("venue") or {}).get("name", ""),
                probable_away=pa.get("fullName"),
                probable_away_id=pa.get("id"),
                probable_away_hand=((pa.get("pitchHand") or {}).get("code")),
                probable_home=ph.get("fullName"),
                probable_home_id=ph.get("id"),
                probable_home_hand=((ph.get("pitchHand") or {}).get("code")),
                lineups_posted=bool(away_lineup and home_lineup
                                    and len(away_lineup) >= 9 and len(home_lineup) >= 9),
                away_lineup_ids=away_lineup,
                home_lineup_ids=home_lineup,
                status=(g.get("status") or {}).get("detailedState", ""),
            ))
    return games


def fetch_venue_coords(venue_id: int, manifest: Manifest) -> tuple[float, float] | None:
    """Venue lat/long from the Stats API (sourced — never hardcoded)."""
    url = VENUE_URL.format(venue_id=venue_id)
    data, rec = fetch_json(
        f"venue_{venue_id}", url, params={"hydrate": "location"},
        row_counter=lambda d: len(d.get("venues", [])),
    )
    manifest.add(rec)
    if data is None:
        return None
    try:
        loc = data["venues"][0]["location"]["defaultCoordinates"]
        return float(loc["latitude"]), float(loc["longitude"])
    except (KeyError, IndexError, TypeError, ValueError):
        rec.note = (rec.note + "; no coordinates in payload").strip("; ")
        return None


def fetch_team_runs_per_game(team_id: int, season: int,
                             manifest: Manifest) -> float | None:
    """Season-typical offense fallback for PRELIMINARY runs: sourced team
    runs per game from the Stats API (never estimated)."""
    url = TEAM_STATS_URL.format(team_id=team_id)
    data, rec = fetch_json(
        f"team_hitting_{team_id}", url,
        params={"stats": "season", "group": "hitting", "season": season},
    )
    manifest.add(rec)
    if data is None:
        return None
    try:
        stat = data["stats"][0]["splits"][0]["stat"]
        runs, games = float(stat["runs"]), float(stat["gamesPlayed"])
        if games < 20:  # too early in season to be "season-typical"
            rec.note = "under 20 games played"
            return None
        return runs / games
    except (KeyError, IndexError, TypeError, ValueError, ZeroDivisionError):
        rec.note = (rec.note + "; no hitting splits in payload").strip("; ")
        return None


def fetch_bat_sides(player_ids: list[int], manifest: Manifest) -> dict[int, str]:
    """batSide codes (L/R/S) for lineup platoon adjustment."""
    if not player_ids:
        return {}
    data, rec = fetch_json(
        "people_batside", PEOPLE_URL,
        params={"personIds": ",".join(str(i) for i in player_ids),
                "fields": "people,id,batSide,code"},
        row_counter=lambda d: len(d.get("people", [])),
    )
    manifest.add(rec)
    if data is None:
        return {}
    out = {}
    for p in data.get("people", []):
        code = ((p.get("batSide") or {}).get("code"))
        if p.get("id") and code:
            out[p["id"]] = code
    return out
