"""De-vig math (Market Layer, Part 3).

Reference book for the fair number: Pinnacle if present, else the sharpest
book available per config book_priority, else the multi-book consensus.
Method: proportional (normalize-to-1). fair_i = implied_i / sum(implied).
"""
from __future__ import annotations


def american_to_implied(price: int | float) -> float:
    """American odds -> implied probability (vig included)."""
    price = float(price)
    if price == 0:
        raise ValueError("American odds of 0 are not valid")
    if price < 0:
        return -price / (-price + 100.0)
    return 100.0 / (price + 100.0)


def american_to_decimal(price: int | float) -> float:
    price = float(price)
    if price == 0:
        raise ValueError("American odds of 0 are not valid")
    if price < 0:
        return 1.0 + 100.0 / -price
    return 1.0 + price / 100.0


def proportional_devig(implied: list[float]) -> list[float]:
    """Normalize implied probabilities to sum to 1 (proportional method).

    Raises ValueError if inputs are unusable — caller suppresses the market
    and logs to ERRORS.md (Part 7 sanity rules) rather than guessing.
    """
    if any(p <= 0.0 or p >= 1.0 for p in implied):
        raise ValueError(f"implied probabilities out of (0,1): {implied}")
    total = sum(implied)
    if total <= 0:
        raise ValueError("implied probabilities sum to zero")
    fair = [p / total for p in implied]
    # sanity: must sum to 1 within float tolerance
    if abs(sum(fair) - 1.0) > 1e-9:
        raise ValueError("de-vig failed to normalize to 1")
    return fair


def devig_two_way(price_a: int | float, price_b: int | float) -> tuple[float, float]:
    """Fair probabilities for a two-sided market from one book's two prices."""
    fair = proportional_devig(
        [american_to_implied(price_a), american_to_implied(price_b)]
    )
    return fair[0], fair[1]


def consensus_fair(prices_by_book: dict[str, tuple[float, float]]) -> tuple[float, float]:
    """Multi-book consensus: de-vig each book two-way, then average the fair
    probabilities across books, then re-normalize."""
    if not prices_by_book:
        raise ValueError("no books available for consensus")
    fa, fb, n = 0.0, 0.0, 0
    for a, b in prices_by_book.values():
        pa, pb = devig_two_way(a, b)
        fa += pa
        fb += pb
        n += 1
    fa, fb = fa / n, fb / n
    return tuple(proportional_devig([fa, fb]))  # type: ignore[return-value]
