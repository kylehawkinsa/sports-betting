"""Shared market evaluation: odds -> de-vig fair -> best price -> edge gate.

One MarketEval per SIDE of a market. The de-vig reference is Pinnacle if
present, else the sharpest available book per config book_priority, else
multi-book consensus (Part 3). Edges are always computed against the BEST
available price (line shopping is mandatory).
"""
from __future__ import annotations

from dataclasses import dataclass

from adapters.odds_adapter import (
    Quote,
    all_book_pairs,
    best_price,
    reference_book_pair,
)
from gates.edge_gate import GateResult, evaluate, thresholds_from_config
from models.devig import american_to_decimal, consensus_fair, devig_two_way


@dataclass
class MarketEval:
    market: str
    side: str
    line: float | None
    best: Quote | None
    fair_prob: float | None
    model_prob: float | None
    ref_book: str | None
    gate: GateResult


def eval_two_way(
    market: str,
    quotes: list[Quote],
    side_a: str,
    side_b: str,
    model_prob_a: float | None,
    book_priority: list[str],
    line: float | None = None,
    preliminary: bool = False,
    insufficient: bool = False,
    config: dict | None = None,
) -> tuple[MarketEval, MarketEval]:
    """Evaluate both sides of a two-sided market. model_prob_a is the model
    probability of side_a; side_b gets its complement. Gate thresholds come
    from config.yaml `gates:` when config is given."""
    edge_req, ratio_req = thresholds_from_config(config, preliminary)
    fair_a = fair_b = None
    ref_book = None
    ref = reference_book_pair(quotes, side_a, side_b, book_priority, line=line)
    if ref is not None:
        ref_book, qa, qb = ref
        try:
            fair_a, fair_b = devig_two_way(qa.price, qb.price)
        except ValueError:
            fair_a = fair_b = None
    else:
        pairs = all_book_pairs(quotes, side_a, side_b, line=line)
        if pairs:
            try:
                fair_a, fair_b = consensus_fair(pairs)
                ref_book = f"consensus({len(pairs)})"
            except ValueError:
                fair_a = fair_b = None

    ba = best_price(quotes, side_a, line=line)
    bb = best_price(quotes, side_b, line=line)
    model_b = (1.0 - model_prob_a) if model_prob_a is not None else None

    ga = evaluate(model_prob_a, fair_a, ba.price if ba else None,
                  preliminary=preliminary, insufficient_data=insufficient,
                  edge_pp_req=edge_req, ratio_req=ratio_req)
    gb = evaluate(model_b, fair_b, bb.price if bb else None,
                  preliminary=preliminary, insufficient_data=insufficient,
                  edge_pp_req=edge_req, ratio_req=ratio_req)
    return (
        MarketEval(market, side_a, line, ba, fair_a, model_prob_a, ref_book, ga),
        MarketEval(market, side_b, line, bb, fair_b, model_b, ref_book, gb),
    )


def ev_per_unit(p: float | None, price: int | float | None) -> float | None:
    """Expected value of a 1u bet at `price` given model probability p:
    EV = p·(dec−1) − (1−p). Positive = +EV at the model number."""
    if p is None or price is None:
        return None
    b = american_to_decimal(price) - 1.0
    return p * b - (1.0 - p)


def fmt_price(price: int | float | None) -> str:
    if price is None:
        return "—"
    p = int(price)
    return f"+{p}" if p > 0 else str(p)


def fmt_prob(p: float | None) -> str:
    return f"{p * 100:.1f}%" if p is not None else "—"
