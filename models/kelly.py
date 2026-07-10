"""Quarter-Kelly staking (Part 4).

full Kelly fraction f* = (b*p - q) / b
  b = decimal odds - 1 (net odds at the BEST available price)
  p = model probability, q = 1 - p
stake_units = 0.25 * f* * BANKROLL_UNITS, hard-capped at 1.0u, floored at 0.

BANKROLL_UNITS = 30 expresses the bankroll in betting units (a standard
30-unit roll); it reproduces the spec's worked example (+142, model 44.8%
-> ~0.4u). The math is carried on the result so the board can show it
("Show the Kelly math"). Negative Kelly is a Part 7 sanity failure: the
caller must suppress the market — a gate-passing play can never have
negative Kelly, so if it does, something upstream is wrong.
"""
from __future__ import annotations

from dataclasses import dataclass

from models.devig import american_to_decimal

KELLY_MULTIPLIER = 0.25
BANKROLL_UNITS = 30.0
STAKE_CAP_UNITS = 1.0


@dataclass
class KellyResult:
    p: float
    price: float          # american
    b: float              # net decimal odds
    full_kelly: float     # f*
    stake_units: float    # quarter-Kelly, capped
    capped: bool

    def math_str(self) -> str:
        return (
            f"f* = (b·p − q)/b = ({self.b:.3f}·{self.p:.4f} − {1 - self.p:.4f})"
            f"/{self.b:.3f} = {self.full_kelly:.4f}; "
            f"¼-Kelly = {KELLY_MULTIPLIER * self.full_kelly:.4f} of a "
            f"{BANKROLL_UNITS:.0f}u roll "
            f"→ stake {self.stake_units:.2f}u{' (capped 1.0u)' if self.capped else ''}"
        )


def quarter_kelly(p: float, american_price: int | float) -> KellyResult:
    if not 0.0 < p < 1.0:
        raise ValueError(f"model probability out of (0,1): {p}")
    b = american_to_decimal(american_price) - 1.0
    q = 1.0 - p
    full = (b * p - q) / b
    stake = KELLY_MULTIPLIER * full * BANKROLL_UNITS
    capped = False
    if stake > STAKE_CAP_UNITS:
        stake = STAKE_CAP_UNITS
        capped = True
    if stake < 0.0:
        stake = 0.0
    return KellyResult(
        p=p, price=float(american_price), b=b,
        full_kelly=full, stake_units=round(stake, 2), capped=capped,
    )
