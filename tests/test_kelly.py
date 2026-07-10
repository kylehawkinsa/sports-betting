"""Quarter-Kelly staking math."""
import pytest

from models.kelly import quarter_kelly


def test_known_kelly_value():
    # p=0.5 at +120 (b=1.2): f* = (1.2*0.5 - 0.5)/1.2 = 0.08333
    r = quarter_kelly(0.5, 120)
    assert r.full_kelly == pytest.approx(1 / 12, abs=1e-9)
    # 0.25 * f* * 30u roll = 0.625u
    assert r.stake_units == pytest.approx(0.625, abs=0.01)
    assert not r.capped


def test_spec_worked_example():
    # spec Part 5: CIN ML +142, model 44.8% -> STAKE ~0.42u
    r = quarter_kelly(0.448, 142)
    assert 0.35 <= r.stake_units <= 0.55


def test_negative_edge_floors_at_zero():
    r = quarter_kelly(0.40, -110)
    assert r.full_kelly < 0
    assert r.stake_units == 0.0


def test_cap_at_one_unit():
    r = quarter_kelly(0.95, 300)
    assert r.stake_units == 1.0
    assert r.capped


def test_math_string_shows_work():
    s = quarter_kelly(0.48, 150).math_str()
    assert "f* =" in s and "¼-Kelly" in s and "stake" in s


def test_invalid_prob_rejected():
    with pytest.raises(ValueError):
        quarter_kelly(0.0, 150)
    with pytest.raises(ValueError):
        quarter_kelly(1.0, 150)
