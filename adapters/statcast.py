"""Statcast / FanGraphs stats via pybaseball (Baseball Savant), cached daily.

Provides: batter xwOBA (for lineup run expectancy), pitcher xERA + xFIP +
K-BB%, and Savant park factors (3-yr rolling, weekly cache).

pybaseball is an optional heavy dependency; if it is not installed or the
fetch fails, every function returns None plus a FAIL/SKIP manifest record
and the caller shows `—`. Nothing is ever estimated (Right Rule 2).

Platoon adjustment: individual L/R splits are not exposed by the expected-
stats leaderboard, so the lineup aggregator applies the league-average
platoon shift as a MODEL PARAMETER (documented in mlb_pipeline) — the
underlying displayed xwOBA numbers remain the sourced season values.
"""
from __future__ import annotations

import time
from pathlib import Path

import pandas as pd

from core.manifest import Manifest, SourceRecord, utcnow_iso

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "cache"

DAY_SECONDS = 86_400
WEEK_SECONDS = 7 * DAY_SECONDS


def _cache_fresh(path: Path, max_age: int) -> bool:
    return path.exists() and (time.time() - path.stat().st_mtime) < max_age


def _cached_csv(path: Path, max_age: int, fetch, name: str,
                manifest: Manifest, endpoint: str) -> pd.DataFrame | None:
    """Daily/weekly cache wrapper. A cache hit is recorded with its file
    mtime so stale-but-labeled display stays possible (Right Rule 2)."""
    if _cache_fresh(path, max_age):
        df = pd.read_csv(path)
        age_h = (time.time() - path.stat().st_mtime) / 3600.0
        manifest.add(SourceRecord(
            name=name, endpoint=f"CACHE:{path.relative_to(ROOT)}", status="OK",
            rows=len(df), note=f"cached {age_h:.1f}h ago",
        ))
        return df
    try:
        df = fetch()
        if df is None or len(df) == 0:
            raise ValueError("empty dataframe")
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(path, index=False)
        manifest.add(SourceRecord(name=name, endpoint=endpoint, status="OK",
                                  http_status=200, rows=len(df)))
        return df
    except Exception as exc:
        # fall back to a stale cache if one exists — labeled STALE, never silent
        if path.exists():
            df = pd.read_csv(path)
            age_h = (time.time() - path.stat().st_mtime) / 3600.0
            manifest.add(SourceRecord(
                name=name, endpoint=f"CACHE:{path.relative_to(ROOT)}",
                status="STALE", rows=len(df),
                note=f"live fetch failed ({type(exc).__name__}); cache {age_h:.1f}h old",
            ))
            return df
        manifest.add(SourceRecord(name=name, endpoint=endpoint, status="FAIL",
                                  note=f"{type(exc).__name__}: {exc}"))
        return None


def _pybaseball():
    try:
        import pybaseball  # noqa: PLC0415
        pybaseball.cache.disable()  # we manage our own cache
        return pybaseball
    except ImportError:
        return None


def batter_xwoba_table(season: int, manifest: Manifest) -> pd.DataFrame | None:
    """Season expected stats per batter: columns include player_id, est_woba."""
    pb = _pybaseball()
    if pb is None:
        manifest.add(SourceRecord(name="statcast_batters", endpoint="pybaseball",
                                  status="FAIL", note="pybaseball not installed"))
        return None
    return _cached_csv(
        CACHE / f"batter_xstats_{season}.csv", DAY_SECONDS,
        lambda: pb.statcast_batter_expected_stats(season, minPA=50),
        "statcast_batters", manifest,
        f"baseballsavant.mlb.com expected_statistics batters {season}",
    )


def pitcher_xstats_table(season: int, manifest: Manifest) -> pd.DataFrame | None:
    """Season expected stats per pitcher: includes est_era (xERA)."""
    pb = _pybaseball()
    if pb is None:
        manifest.add(SourceRecord(name="statcast_pitchers", endpoint="pybaseball",
                                  status="FAIL", note="pybaseball not installed"))
        return None
    return _cached_csv(
        CACHE / f"pitcher_xstats_{season}.csv", DAY_SECONDS,
        lambda: pb.statcast_pitcher_expected_stats(season, minPA=50),
        "statcast_pitchers", manifest,
        f"baseballsavant.mlb.com expected_statistics pitchers {season}",
    )


def pitcher_fangraphs_table(season: int, manifest: Manifest) -> pd.DataFrame | None:
    """FanGraphs season pitching: xFIP, K-BB%, IP/GS for expected innings."""
    pb = _pybaseball()
    if pb is None:
        manifest.add(SourceRecord(name="fangraphs_pitching", endpoint="pybaseball",
                                  status="FAIL", note="pybaseball not installed"))
        return None
    return _cached_csv(
        CACHE / f"fg_pitching_{season}.csv", DAY_SECONDS,
        lambda: pb.pitching_stats(season, season, qual=10),
        "fangraphs_pitching", manifest,
        f"fangraphs.com pitching leaderboard {season}",
    )


def park_factors_table(manifest: Manifest) -> pd.DataFrame | None:
    """Savant park factors, 3-year rolling, weekly cache (Part 1A)."""
    pb = _pybaseball()
    endpoint = "baseballsavant.mlb.com statcast-park-factors (3yr rolling)"
    if pb is None or not hasattr(pb, "statcast_park_factors"):
        # pybaseball has no park-factor helper in all versions; fetch CSV directly
        import io  # noqa: PLC0415

        import httpx  # noqa: PLC0415
        url = ("https://baseballsavant.mlb.com/leaderboard/statcast-park-factors"
               "?type=year&year=2026&batSide=&stat=index_wOBA&condition=All&rolling=3&csv=true")

        def fetch():
            r = httpx.get(url, timeout=30.0,
                          headers={"User-Agent": "edge-hub/1.0"})
            r.raise_for_status()
            return pd.read_csv(io.StringIO(r.text))

        return _cached_csv(CACHE / "park_factors.csv", WEEK_SECONDS, fetch,
                           "park_factors", manifest, url.split("?")[0])
    return _cached_csv(
        CACHE / "park_factors.csv", WEEK_SECONDS,
        lambda: pb.statcast_park_factors(),
        "park_factors", manifest, endpoint,
    )


def lookup_batter_xwoba(df: pd.DataFrame | None, player_id: int) -> float | None:
    if df is None:
        return None
    col = "est_woba" if "est_woba" in df.columns else None
    idcol = "player_id" if "player_id" in df.columns else None
    if col is None or idcol is None:
        return None
    rows = df[df[idcol] == player_id]
    if rows.empty:
        return None
    try:
        return float(rows.iloc[0][col])
    except (ValueError, TypeError):
        return None


def lookup_pitcher(xstats: pd.DataFrame | None, fg: pd.DataFrame | None,
                   player_id: int | None, name: str | None) -> dict:
    """Returns dict with any of: xera, xfip, kbb, exp_ip. Missing -> absent."""
    out: dict = {}
    if xstats is not None and player_id is not None and "player_id" in xstats.columns:
        rows = xstats[xstats["player_id"] == player_id]
        if not rows.empty and "est_era" in xstats.columns:
            try:
                out["xera"] = float(rows.iloc[0]["est_era"])
            except (ValueError, TypeError):
                pass
    if fg is not None and name is not None and "Name" in fg.columns:
        rows = fg[fg["Name"].str.lower() == name.lower()]
        if not rows.empty:
            r = rows.iloc[0]
            for src, dst in (("xFIP", "xfip"),):
                if src in fg.columns and pd.notna(r[src]):
                    out[dst] = float(r[src])
            if "K-BB%" in fg.columns and pd.notna(r["K-BB%"]):
                out["kbb"] = float(r["K-BB%"]) / 100.0
            if {"IP", "GS"} <= set(fg.columns) and r.get("GS", 0) and r["GS"] > 0:
                out["exp_ip"] = min(float(r["IP"]) / float(r["GS"]), 7.5)
    return out
