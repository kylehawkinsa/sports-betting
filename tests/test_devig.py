"""De-vig math (required): proportional method, sanity guards."""
import pytest

from models.devig import (
    american_to_decimal,
    american_to_implied,
    consensus_fair,
    devig_two_way,
    proportional_devig,
)


def test_american_to_implied_known_values():
    assert american_to_implied(100) == pytest.approx(0.5)
    assert american_to_implied(-110) == pytest.approx(110 / 210)
    assert american_to_implied(150) == pytest.approx(0.4)
    assert american_to_implied(-200) == pytest.approx(2 / 3)


def test_american_to_decimal_known_values():
    assert american_to_decimal(100) == pytest.approx(2.0)
    assert american_to_decimal(-110) == pytest.approx(1 + 100 / 110)
    assert american_to_decimal(250) == pytest.approx(3.5)


def test_proportional_devig_sums_to_one():
    fair = proportional_devig([0.55, 0.52])
    assert sum(fair) == pytest.approx(1.0)
    # proportions preserved
    assert fair[0] / fair[1] == pytest.approx(0.55 / 0.52)


def test_devig_standard_110_market():
    a, b = devig_two_way(-110, -110)
    assert a == pytest.approx(0.5)
    assert b == pytest.approx(0.5)


def test_devig_asymmetric_market():
    a, b = devig_two_way(-150, 130)
    imp_a, imp_b = american_to_implied(-150), american_to_implied(130)
    assert a == pytest.approx(imp_a / (imp_a + imp_b))
    assert a + b == pytest.approx(1.0)
    assert a > 0.5 > b


def test_devig_rejects_garbage():
    with pytest.raises(ValueError):
        proportional_devig([0.0, 0.5])
    with pytest.raises(ValueError):
        proportional_devig([1.2, 0.5])
    with pytest.raises(ValueError):
        american_to_implied(0)


def test_consensus_fair_averages_books():
    pairs = {"bookA": (-110, -110), "bookB": (-120, 100)}
    a, b = consensus_fair(pairs)
    assert a + b == pytest.approx(1.0)
    # book A says 50/50; book B leans to side A -> consensus side A > 0.5
    assert a > 0.5


def test_consensus_fair_empty_raises():
    with pytest.raises(ValueError):
        consensus_fair({})


def test_best_price_orders_across_sign_boundary():
    """Line shopping must rank by payout: +100 beats -105 beats -115 beats
    -200. (Regression: a bad sort key preferred bigger negative numbers.)"""
    from adapters.odds_adapter import Quote, best_price
    quotes = [Quote(book=b, side="A", price=p)
              for b, p in [("w", -200), ("x", -115), ("y", -105), ("z", 100)]]
    assert best_price(quotes, "A").price == 100
    assert best_price(quotes[:3], "A").price == -105
    assert best_price(quotes[:2], "A").price == -115
