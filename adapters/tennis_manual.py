"""MANUAL INPUT MODE for tennis (Part 1B) — first-class, guaranteed path.

The user pastes a file of match blocks; the model runs entirely off the
pasted inputs. Nothing is fetched, nothing is inferred. Percentages may be
given as 64.2 or 0.642. Surface-specific rates are optional — if omitted
the overall rate is used for both terms of the 60/40 blend (equivalent to
weighting overall at 100%, which is labeled on the board).

Format (one match per block, blank-line separated; keys case-insensitive):

    match: Alcaraz vs Sinner
    surface: clay
    best_of: 5
    A: spw=67.1 rpw=41.2 spw_surface=69.0 rpw_surface=43.1 matches=52 matches_surface=18
    B: spw=68.9 rpw=39.8 matches=61
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from core.manifest import Manifest, SourceRecord

MIN_MATCHES = 20  # same data-quality gate as the fetched path


@dataclass
class ManualPlayer:
    name: str
    spw: float
    rpw: float
    spw_surface: float | None = None
    rpw_surface: float | None = None
    matches: int = 0
    matches_surface: int = 0

    @property
    def insufficient(self) -> bool:
        return self.matches < MIN_MATCHES


@dataclass
class ManualMatch:
    player_a: ManualPlayer
    player_b: ManualPlayer
    surface: str
    best_of: int
    format_supported: bool = True   # no-ad / match-TB set False upstream


def _pct(v: str) -> float:
    x = float(v)
    return x / 100.0 if x > 1.0 else x


def _parse_player(name: str, line: str) -> ManualPlayer | None:
    kv = dict(re.findall(r"(\w+)\s*=\s*([\d.]+)", line))
    if "spw" not in kv or "rpw" not in kv:
        return None
    return ManualPlayer(
        name=name,
        spw=_pct(kv["spw"]), rpw=_pct(kv["rpw"]),
        spw_surface=_pct(kv["spw_surface"]) if "spw_surface" in kv else None,
        rpw_surface=_pct(kv["rpw_surface"]) if "rpw_surface" in kv else None,
        matches=int(float(kv.get("matches", 0))),
        matches_surface=int(float(kv.get("matches_surface", 0))),
    )


def parse_manual_matches(path: str | Path, manifest: Manifest) -> list[ManualMatch]:
    p = Path(path)
    if not p.exists():
        manifest.add(SourceRecord(name="tennis_manual", endpoint=f"PASTE:{path}",
                                  status="FAIL", note="file not found"))
        return []
    matches: list[ManualMatch] = []
    for block in re.split(r"\n\s*\n", p.read_text().strip()):
        fields: dict[str, str] = {}
        for line in block.splitlines():
            if ":" in line:
                k, _, v = line.partition(":")
                fields[k.strip().lower()] = v.strip()
        if "match" not in fields or "a" not in fields or "b" not in fields:
            continue
        names = re.split(r"\s+vs\.?\s+", fields["match"], flags=re.IGNORECASE)
        if len(names) != 2:
            continue
        pa = _parse_player(names[0].strip(), fields["a"])
        pb = _parse_player(names[1].strip(), fields["b"])
        if pa is None or pb is None:
            continue
        fmt = fields.get("format", "standard").lower()
        matches.append(ManualMatch(
            player_a=pa, player_b=pb,
            surface=fields.get("surface", "hard").capitalize(),
            best_of=int(fields.get("best_of", "3")),
            format_supported=fmt not in ("no-ad", "noad", "match-tiebreak", "match-tb"),
        ))
    manifest.add(SourceRecord(name="tennis_manual", endpoint=f"PASTE:{path}",
                              status="OK", rows=len(matches),
                              note="user-pasted manual inputs"))
    return matches
