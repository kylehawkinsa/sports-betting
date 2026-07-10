"""EDGE GATE (Part 4) — NON-NEGOTIABLE.

A market is a PLAY only if BOTH gates pass:
  1. Absolute gate:  model_prob − fair_prob ≥ 3.0 percentage points
  2. Ratio gate:     model_prob ÷ implied_prob(best price) ≥ 1.15
LEAN  = exactly one gate passes → 0u, watch-list only.
PASS  = default for everything else. A slate of all-PASS is a success.
PRELIMINARY runs (MLB lineups unposted) tighten to 4.0pp and 1.20×.
INSUFFICIENT DATA (tennis sample < 20 matches) can never be a play.

Splits (bets%/handle%) are context only — they are deliberately NOT an
input to this function and must never open or close the gate.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from models.devig import american_to_implied
from models.kelly import KellyResult, quarter_kelly

EDGE_PP = 3.0
RATIO = 1.15
PRELIM_EDGE_PP = 4.0
PRELIM_RATIO = 1.20


@dataclass
class GateResult:
    verdict: str                 # "PLAY" | "LEAN" | "PASS" | "INSUFFICIENT DATA" | "NO MARKET"
    edge_pp: float | None = None
    ratio: float | None = None
    stake_units: float = 0.0
    kelly: KellyResult | None = None
    preliminary: bool = False
    reasons: list[str] = field(default_factory=list)
    abs_gate: bool = False
    ratio_gate: bool = False


def evaluate(
    model_prob: float | None,
    fair_prob: float | None,
    best_price: int | float | None,
    preliminary: bool = False,
    insufficient_data: bool = False,
) -> GateResult:
    """Gate a single side of a single market. Default verdict is PASS."""
    if insufficient_data:
        return GateResult(verdict="INSUFFICIENT DATA",
                          reasons=["sample below data-quality gate"])
    if model_prob is None:
        return GateResult(verdict="PASS", reasons=["no model probability"])
    if fair_prob is None or best_price is None:
        # Odds missing → cannot price an edge → no play, ever (Part 7).
        return GateResult(verdict="NO MARKET", reasons=["odds unavailable"])
    if not (0.0 < model_prob < 1.0):
        return GateResult(verdict="PASS",
                          reasons=[f"model prob failed sanity: {model_prob}"])

    edge_pp_req = PRELIM_EDGE_PP if preliminary else EDGE_PP
    ratio_req = PRELIM_RATIO if preliminary else RATIO

    edge_pp = (model_prob - fair_prob) * 100.0
    implied_best = american_to_implied(best_price)
    ratio = model_prob / implied_best

    abs_gate = edge_pp >= edge_pp_req
    ratio_gate = ratio >= ratio_req

    result = GateResult(
        verdict="PASS", edge_pp=round(edge_pp, 2), ratio=round(ratio, 3),
        preliminary=preliminary, abs_gate=abs_gate, ratio_gate=ratio_gate,
    )
    if abs_gate and ratio_gate:
        kelly = quarter_kelly(model_prob, best_price)
        if kelly.full_kelly <= 0:
            # Part 7 sanity: gates passed but Kelly non-positive → suppress.
            result.verdict = "PASS"
            result.reasons.append("SANITY FAIL: non-positive Kelly with gates passed")
            return result
        result.verdict = "PLAY"
        result.stake_units = kelly.stake_units
        result.kelly = kelly
    elif abs_gate or ratio_gate:
        result.verdict = "LEAN"
        result.reasons.append(
            "abs gate only" if abs_gate else "ratio gate only"
        )
    return result
