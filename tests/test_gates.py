"""Gate logic edge cases (required). Both gates must pass for a PLAY;
default verdict is PASS; PRELIMINARY tightens thresholds; INSUFFICIENT
DATA and missing odds can never produce a play."""
import pytest

from gates.edge_gate import evaluate
from models.devig import american_to_implied


def test_both_gates_pass_is_play():
    # +150 -> implied 40.0%; model 48%, fair 44% -> edge 4pp, ratio 1.2
    r = evaluate(model_prob=0.48, fair_prob=0.44, best_price=150)
    assert r.verdict == "PLAY"
    assert r.stake_units > 0
    assert r.kelly is not None and r.kelly.full_kelly > 0


def test_abs_gate_exactly_at_threshold_passes():
    # edge exactly 3.0pp and ratio comfortably over
    r = evaluate(model_prob=0.50, fair_prob=0.47, best_price=150)
    assert r.abs_gate is True
    assert r.verdict == "PLAY"


def test_abs_gate_just_below_threshold_is_not_play():
    r = evaluate(model_prob=0.4999, fair_prob=0.47, best_price=150)
    assert r.abs_gate is False
    assert r.verdict in ("LEAN", "PASS")


def test_ratio_gate_only_is_lean():
    # big price: ratio passes, absolute edge under 3pp
    p = american_to_implied(400) * 1.2       # ratio = 1.2
    fair = p - 0.02                          # edge only 2pp
    r = evaluate(model_prob=p, fair_prob=fair, best_price=400)
    assert r.ratio_gate and not r.abs_gate
    assert r.verdict == "LEAN"
    assert r.stake_units == 0.0


def test_abs_gate_only_is_lean():
    # short price: edge 4pp but ratio under 1.15
    r = evaluate(model_prob=0.72, fair_prob=0.68, best_price=-220)
    assert r.abs_gate and not r.ratio_gate
    assert r.verdict == "LEAN"
    assert r.stake_units == 0.0


def test_neither_gate_is_pass():
    r = evaluate(model_prob=0.45, fair_prob=0.44, best_price=130)
    assert r.verdict == "PASS"


def test_preliminary_tightens_gates():
    # edge 3.5pp, ratio 1.17: PLAY normally, not in PRELIMINARY (needs 4.0/1.20)
    fair = 0.42
    model = fair + 0.035
    price = 160  # implied 38.46% -> ratio ~1.18
    normal = evaluate(model, fair, price, preliminary=False)
    prelim = evaluate(model, fair, price, preliminary=True)
    assert normal.verdict == "PLAY"
    assert prelim.verdict == "PASS"


def test_insufficient_data_never_plays():
    r = evaluate(model_prob=0.60, fair_prob=0.40, best_price=200,
                 insufficient_data=True)
    assert r.verdict == "INSUFFICIENT DATA"
    assert r.stake_units == 0.0


def test_missing_model_prob_is_pass():
    assert evaluate(None, 0.5, 100).verdict == "PASS"


def test_missing_odds_is_no_market():
    assert evaluate(0.55, None, None).verdict == "NO MARKET"
    assert evaluate(0.55, 0.5, None).verdict == "NO MARKET"


def test_insane_model_prob_is_pass():
    assert evaluate(1.2, 0.5, 100).verdict == "PASS"
    assert evaluate(0.0, 0.5, 100).verdict == "PASS"


def test_stake_capped_at_one_unit():
    # absurd edge -> full Kelly huge -> quarter-Kelly capped at 1.0u
    r = evaluate(model_prob=0.90, fair_prob=0.40, best_price=250)
    assert r.verdict == "PLAY"
    assert r.stake_units <= 1.0
    assert r.kelly.capped


def test_splits_have_no_gate_parameter():
    """Splits are context, never a model input: the gate API must not even
    accept them."""
    import inspect

    from gates import edge_gate
    params = inspect.signature(edge_gate.evaluate).parameters
    assert not any("split" in p or "handle" in p or "bets" in p for p in params)
