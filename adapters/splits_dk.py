"""DraftKings Network public betting splits (Part 1A option a).

DK book only, skews recreational — treated as directional CONTEXT, never a
model input. There is no stable documented API; this adapter makes a
best-effort request to the DK Network splits feed and returns None (column
renders N/A) on any failure. Splits are NEVER scraped from unauthorized
sources and NEVER estimated (Part 7).
"""
from __future__ import annotations

from dataclasses import dataclass

from core.http import fetch_json
from core.manifest import Manifest, SourceRecord

# DK Network publishes splits on dknetwork.draftkings.com; the underlying
# JSON feed has moved before. Endpoint is config-overridable.
DEFAULT_URL = "https://dknetwork.draftkings.com/wp-json/dkn/splits/v1/mlb"


@dataclass
class Splits:
    """Percentages are 0-100 as published. side = team the money is on."""
    market: str          # "ml" | "rl" | "total"
    side: str
    bets_pct: float
    handle_pct: float
    source: str = "DK"


def fetch_dk_splits(manifest: Manifest, url: str | None = None
                    ) -> dict[str, list[Splits]] | None:
    """Returns {'AWAY@HOME': [Splits, ...]} or None -> N/A."""
    endpoint = url or DEFAULT_URL
    data, rec = fetch_json("splits_dk", endpoint)
    manifest.add(rec)
    if data is None:
        return None
    out: dict[str, list[Splits]] = {}
    try:
        for game in data if isinstance(data, list) else data.get("games", []):
            key = f"{game['away']}@{game['home']}"
            for s in game.get("splits", []):
                out.setdefault(key, []).append(Splits(
                    market=s["market"], side=s["side"],
                    bets_pct=float(s["bets_pct"]),
                    handle_pct=float(s["handle_pct"]),
                ))
        rec.rows = sum(len(v) for v in out.values())
        return out
    except (KeyError, TypeError, ValueError) as exc:
        rec.status = "FAIL"
        rec.note = f"unrecognized payload shape: {type(exc).__name__}"
        return None


def sharp_side_flag(bets_pct: float, handle_pct: float) -> str:
    """$SHARP-SIDE when handle exceeds tickets by >= 10 points; STRONG when
    the money side has <= 35% of tickets. Context only — never gates."""
    gap = handle_pct - bets_pct
    if gap >= 10.0 and bets_pct <= 35.0:
        return "$SHARP-SIDE (STRONG)"
    if gap >= 10.0:
        return "$SHARP-SIDE"
    return ""
