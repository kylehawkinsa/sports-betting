"""CLV tracking (Part 5) — the grade is closing-line value, not W/L.

Every PLAY is appended to data/clv/plays.jsonl with the line taken. The
closing job (run_closing.py, ~04:00 UTC) fetches the final pre-game price
from the de-vig reference book, computes CLV per bet, and maintains a
rolling weekly summary. Log lines are append-only — pre-game numbers are
never edited after results are known (Right Rule 6).
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path

from core.manifest import utcnow_iso
from models.devig import american_to_implied

ROOT = Path(__file__).resolve().parent.parent
CLV_DIR = ROOT / "data" / "clv"
PLAYS_PATH = CLV_DIR / "plays.jsonl"
CLOSES_PATH = CLV_DIR / "closes.jsonl"


@dataclass
class PlayRecord:
    date: str
    sport: str
    event: str                # "AWY@HOM" or "A vs B"
    market: str
    side: str
    line: float | None
    price_taken: int
    book: str
    model_prob: float
    fair_prob: float
    stake_units: float
    logged_at: str


def log_play(date_str: str, sport: str, event: str, market: str, side: str,
             line: float | None, price: int, book: str, model_prob: float,
             fair_prob: float, stake_units: float) -> PlayRecord:
    rec = PlayRecord(date_str, sport, event, market, side, line, price, book,
                     round(model_prob, 4), round(fair_prob, 4), stake_units,
                     utcnow_iso())
    CLV_DIR.mkdir(parents=True, exist_ok=True)
    key = _play_key(asdict(rec))
    # idempotent within a day: re-runs must not duplicate a logged play
    if key not in {_play_key(p) for p in load_plays(date_str)}:
        with open(PLAYS_PATH, "a") as f:
            f.write(json.dumps(asdict(rec)) + "\n")
    return rec


def _play_key(p: dict) -> tuple:
    return (p["date"], p["sport"], p["event"], p["market"], p["side"], p["line"])


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def load_plays(date_str: str | None = None) -> list[dict]:
    plays = _load_jsonl(PLAYS_PATH)
    return [p for p in plays if date_str is None or p["date"] == date_str]


def load_closes() -> list[dict]:
    return _load_jsonl(CLOSES_PATH)


def record_close(play: dict, closing_price: int, closing_fair: float | None,
                 close_book: str) -> dict:
    """CLV in probability points: implied(close) - implied(taken).
    Positive = the market moved toward the bet (we beat the close).
    clv_fair_pp additionally de-vigs the closing pair when available."""
    taken_imp = american_to_implied(play["price_taken"])
    close_imp = american_to_implied(closing_price)
    close_rec = {
        **{k: play[k] for k in ("date", "sport", "event", "market",
                                "side", "line")},
        "price_taken": play["price_taken"],
        "closing_price": closing_price,
        "close_book": close_book,
        "clv_pp": round((close_imp - taken_imp) * 100.0, 2),
        "clv_fair_pp": (round((closing_fair - taken_imp) * 100.0, 2)
                        if closing_fair is not None else None),
        "closed_at": utcnow_iso(),
    }
    existing = {_play_key(c) for c in load_closes()}
    if _play_key(close_rec) not in existing:
        CLV_DIR.mkdir(parents=True, exist_ok=True)
        with open(CLOSES_PATH, "a") as f:
            f.write(json.dumps(close_rec) + "\n")
    return close_rec


def todays_plays_section(date_str: str) -> str:
    plays = load_plays(date_str)
    if not plays:
        return ""
    lines = ["Plays logged (line taken, pending close):", ""]
    for p in plays:
        ln = "" if p["line"] is None else f" {p['line']:+g}"
        lines.append(f"- `{p['logged_at']}` [{p['sport'].upper()}] {p['event']} "
                     f"— {p['side']} {p['market']}{ln} {p['price_taken']:+d} "
                     f"({p['book']}) {p['stake_units']:.2f}u")
    return "\n".join(lines)


def weekly_summary(as_of: date) -> str:
    closes = load_closes()
    if not closes:
        return "_No closed plays yet — CLV summary starts after the first closing run._"
    week_ago = (as_of - timedelta(days=7)).isoformat()
    recent = [c for c in closes if c["date"] >= week_ago]
    all_pp = [c["clv_pp"] for c in closes]
    lines = [f"**CLV summary** (all-time n={len(closes)}, "
             f"avg {sum(all_pp) / len(all_pp):+.2f}pp)"]
    if recent:
        rpp = [c["clv_pp"] for c in recent]
        lines.append(f"Rolling 7-day: n={len(recent)}, "
                     f"avg {sum(rpp) / len(rpp):+.2f}pp, "
                     f"beat close {sum(1 for x in rpp if x > 0)}/{len(rpp)}")
    if len(closes) < 100:
        lines.append(f"_{len(closes)}/100 bets — sample too small to grade "
                     "the model; W/L at this size is noise._")
    return "\n\n".join(lines)
