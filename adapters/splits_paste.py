"""PASTE MODE splits parser (Part 1A option b).

Accepts Action Network PRO splits text pasted by the user into a file
(--splits-paste path). Parses lines mentioning a team plus a bets % and a
handle %, and maps them to today's games by team-name substring. Anything
it cannot parse is skipped — nothing is inferred (Right Rule).

Accepted line shapes (case-insensitive, flexible whitespace):
    Yankees ML  38% bets / 61% handle
    CIN  bets 38  handle 61
    Reds: 38% of bets, 61% of handle (total, over)
A market tag [ml|rl|total|spread|over|under] anywhere on the line sets the
market; default is ml.
"""
from __future__ import annotations

import re
from pathlib import Path

from adapters.splits_dk import Splits
from core.manifest import Manifest, SourceRecord

_PCT = r"(\d{1,2}(?:\.\d)?)\s*%?"
PATTERNS = [
    re.compile(rf"{_PCT}\s*(?:%\s*)?(?:of\s+)?bets.*?{_PCT}\s*(?:%\s*)?(?:of\s+)?handle",
               re.IGNORECASE),
    re.compile(rf"bets\s*:?\s*{_PCT}.*?handle\s*:?\s*{_PCT}", re.IGNORECASE),
]
MARKET_TAG = re.compile(r"\b(ml|moneyline|rl|run\s*line|total|spread|over|under)\b",
                        re.IGNORECASE)


def _market_of(line: str) -> tuple[str, str | None]:
    m = MARKET_TAG.search(line)
    if not m:
        return "ml", None
    tag = m.group(1).lower().replace(" ", "")
    if tag in ("ml", "moneyline"):
        return "ml", None
    if tag in ("rl", "runline", "spread"):
        return "rl", None
    if tag in ("over", "under"):
        return "total", tag
    return "total", None


def parse_splits_paste(path: str | Path, team_names: list[str],
                       manifest: Manifest) -> dict[str, list[Splits]]:
    """team_names: all team names/abbrs on today's slate, used for mapping.
    Returns {matched_team_name: [Splits...]}."""
    p = Path(path)
    if not p.exists():
        manifest.add(SourceRecord(name="splits_paste", endpoint=f"PASTE:{path}",
                                  status="FAIL", note="file not found"))
        return {}
    text = p.read_text()
    out: dict[str, list[Splits]] = {}
    parsed = 0
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):  # comment lines are never parsed
            continue
        pcts = None
        for pat in PATTERNS:
            m = pat.search(line)
            if m:
                pcts = (float(m.group(1)), float(m.group(2)))
                break
        if pcts is None:
            continue
        team = next((t for t in team_names if t and t.lower() in line.lower()), None)
        if team is None:
            continue
        market, ou_side = _market_of(line)
        out.setdefault(team, []).append(Splits(
            market=market, side=ou_side or team,
            bets_pct=pcts[0], handle_pct=pcts[1], source="AN-PRO (pasted)",
        ))
        parsed += 1
    manifest.add(SourceRecord(name="splits_paste", endpoint=f"PASTE:{path}",
                              status="OK", rows=parsed,
                              note="user-pasted Action Network PRO text"))
    return out
