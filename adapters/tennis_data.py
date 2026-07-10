"""Jeff Sackmann tennis_atp / tennis_wta historical data (free CSV, GitHub).

Computes last-52-week serve-points-won % (SPW) and return-points-won %
(RPW) per player, overall and by surface, plus match sample counts and the
tour-average RPW used by the opponent adjustment.

Data-quality gate (Part 1B): a player with < 20 matches in the window is
INSUFFICIENT DATA — no play may be issued on that match.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import httpx
import pandas as pd

from core.manifest import Manifest, SourceRecord

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "cache"
DAY_SECONDS = 86_400

BASE = "https://raw.githubusercontent.com/JeffSackmann/{repo}/master/{repo}_matches_{year}.csv"

MIN_MATCHES = 20
SURFACES = ("Hard", "Clay", "Grass")


@dataclass
class PlayerRates:
    name: str
    spw_overall: float
    rpw_overall: float
    spw_surface: float | None
    rpw_surface: float | None
    matches_overall: int
    matches_surface: int
    surface: str

    @property
    def insufficient(self) -> bool:
        return self.matches_overall < MIN_MATCHES


def _load_year(tour: str, year: int, manifest: Manifest) -> pd.DataFrame | None:
    repo = f"tennis_{tour}"
    url = BASE.format(repo=repo, year=year)
    path = CACHE / f"{repo}_{year}.csv"
    if path.exists() and (time.time() - path.stat().st_mtime) < DAY_SECONDS:
        df = pd.read_csv(path, low_memory=False)
        manifest.add(SourceRecord(name=f"sackmann_{tour}_{year}",
                                  endpoint=f"CACHE:{path.relative_to(ROOT)}",
                                  status="OK", rows=len(df)))
        return df
    try:
        r = httpx.get(url, timeout=60.0, follow_redirects=True)
        r.raise_for_status()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(r.content)
        df = pd.read_csv(path, low_memory=False)
        manifest.add(SourceRecord(name=f"sackmann_{tour}_{year}", endpoint=url,
                                  status="OK", http_status=200, rows=len(df)))
        return df
    except Exception as exc:
        if path.exists():
            df = pd.read_csv(path, low_memory=False)
            manifest.add(SourceRecord(
                name=f"sackmann_{tour}_{year}",
                endpoint=f"CACHE:{path.relative_to(ROOT)}", status="STALE",
                rows=len(df), note=f"live fetch failed: {type(exc).__name__}"))
            return df
        manifest.add(SourceRecord(name=f"sackmann_{tour}_{year}", endpoint=url,
                                  status="FAIL", note=f"{type(exc).__name__}: {exc}"))
        return None


def load_matches(tour: str, as_of: date, manifest: Manifest) -> pd.DataFrame | None:
    """52-week window ending as_of; needs current + previous year files."""
    frames = []
    for year in {as_of.year, (as_of - timedelta(weeks=52)).year}:
        df = _load_year(tour, year, manifest)
        if df is not None:
            frames.append(df)
    if not frames:
        return None
    df = pd.concat(frames, ignore_index=True)
    df["tourney_date"] = pd.to_datetime(df["tourney_date"], format="%Y%m%d",
                                        errors="coerce")
    lo = pd.Timestamp(as_of - timedelta(weeks=52))
    hi = pd.Timestamp(as_of)
    return df[(df["tourney_date"] >= lo) & (df["tourney_date"] <= hi)]


def _accumulate(df: pd.DataFrame, player: str) -> tuple[float, float, int] | None:
    """(spw, rpw, matches) for one player over the given frame.
    Sackmann columns: w_svpt/w_1stWon/w_2ndWon (winner serve), l_* (loser).
    Return points won = opponent serve points - opponent serve points won."""
    need = ["w_svpt", "w_1stWon", "w_2ndWon", "l_svpt", "l_1stWon", "l_2ndWon"]
    if any(c not in df.columns for c in need):
        return None
    as_w = df[df["winner_name"] == player].dropna(subset=need)
    as_l = df[df["loser_name"] == player].dropna(subset=need)
    matches = len(as_w) + len(as_l)
    if matches == 0:
        return None
    srv_pts = as_w["w_svpt"].sum() + as_l["l_svpt"].sum()
    srv_won = (as_w["w_1stWon"].sum() + as_w["w_2ndWon"].sum()
               + as_l["l_1stWon"].sum() + as_l["l_2ndWon"].sum())
    ret_pts = as_w["l_svpt"].sum() + as_l["w_svpt"].sum()
    ret_lost = (as_w["l_1stWon"].sum() + as_w["l_2ndWon"].sum()
                + as_l["w_1stWon"].sum() + as_l["w_2ndWon"].sum())
    if srv_pts == 0 or ret_pts == 0:
        return None
    return (float(srv_won / srv_pts), float((ret_pts - ret_lost) / ret_pts), matches)


def player_rates(df: pd.DataFrame, player: str, surface: str) -> PlayerRates | None:
    overall = _accumulate(df, player)
    if overall is None:
        return None
    surf = _accumulate(df[df["surface"] == surface], player)
    return PlayerRates(
        name=player,
        spw_overall=overall[0], rpw_overall=overall[1],
        spw_surface=surf[0] if surf else None,
        rpw_surface=surf[1] if surf else None,
        matches_overall=overall[2],
        matches_surface=surf[2] if surf else 0,
        surface=surface,
    )


def tour_avg_rpw(df: pd.DataFrame) -> float | None:
    """Tour-average RPW over the window = total return points won / total
    return points = 1 - (total serve points won / serve points)."""
    need = ["w_svpt", "w_1stWon", "w_2ndWon", "l_svpt", "l_1stWon", "l_2ndWon"]
    if any(c not in df.columns for c in need):
        return None
    d = df.dropna(subset=need)
    svpt = d["w_svpt"].sum() + d["l_svpt"].sum()
    svwon = (d["w_1stWon"].sum() + d["w_2ndWon"].sum()
             + d["l_1stWon"].sum() + d["l_2ndWon"].sum())
    if svpt == 0:
        return None
    return float(1.0 - svwon / svpt)
