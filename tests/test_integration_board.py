"""End-to-end (offline): manual tennis inputs + synthetic odds through the
Markov model, de-vig, both gates, and the board renderer. Verifies the
PLAY path, the INSUFFICIENT DATA hard stop, and the ODDS UNAVAILABLE rule
without touching the network."""
import pytest
from core.manifest import Manifest, SourceRecord

import adapters.odds_adapter as odds_adapter
from adapters.odds_adapter import OddsEvent, Quote
from adapters.tennis_manual import ManualMatch, ManualPlayer
from reports.board import render_board
from reports.pipeline_tennis import run_tennis

CONFIG = {
    "odds": {"provider": "the_odds_api",
             "book_priority": ["pinnacle", "circa"]},
    "tennis": {"tour_avg_rpw": 0.38},
}


@pytest.fixture(autouse=True)
def _sandbox_openers(tmp_path, monkeypatch):
    """Keep opener snapshots out of the real data/ directory during tests."""
    monkeypatch.setattr(odds_adapter, "OPENERS_DIR", tmp_path / "openers")


def strong_vs_weak(matches_a=50, matches_b=50):
    # A is meaningfully better on serve and return
    return ManualMatch(
        player_a=ManualPlayer("Alpha Server", spw=0.67, rpw=0.40,
                              matches=matches_a),
        player_b=ManualPlayer("Beta Returner", spw=0.62, rpw=0.36,
                              matches=matches_b),
        surface="Hard", best_of=3,
    )


def odds_event(a_price_pinny=-120, b_price_pinny=100, a_best=-105):
    return OddsEvent(
        sport="tennis", event_id="t1",
        home="Alpha Server", away="Beta Returner", start_utc="2026-07-10T15:00:00Z",
        tournament="ATP Test Open",
        markets={"ml": [
            Quote(book="pinnacle", side="Alpha Server", price=a_price_pinny),
            Quote(book="pinnacle", side="Beta Returner", price=b_price_pinny),
            Quote(book="draftkings", side="Alpha Server", price=a_best),
            Quote(book="draftkings", side="Beta Returner", price=-115),
        ]},
    )


def test_play_path_end_to_end(tmp_path, monkeypatch):
    import reports.clv as clv_mod
    monkeypatch.setattr(clv_mod, "PLAYS_PATH", tmp_path / "plays.jsonl")
    manifest = Manifest()
    manifest.add(SourceRecord(name="odds_tennis", endpoint="test", status="OK"))
    cards = run_tennis("2026-07-10", CONFIG, manifest,
                       [odds_event()], [strong_vs_weak()])
    assert len(cards) == 1
    c = cards[0]
    assert c.dist is not None and c.dist.p_match_a > 0.60
    ml_a = next(e for e in c.evals if e.side == "Alpha Server")
    assert ml_a.ref_book == "pinnacle"          # de-vig reference selection
    assert ml_a.best.book == "draftkings"       # line shopping: best price
    assert ml_a.gate.verdict == "PLAY"
    assert 0 < ml_a.gate.stake_units <= 1.0

    board = render_board("2026-07-10", manifest, [], cards,
                         mlb_odds_ok=True, tennis_odds_ok=True)
    assert "== PLAYS ==" in board
    assert "Alpha Server" in board and "STAKE" in board
    assert "kelly: f*" in board                 # Kelly math is shown
    # DEEP DIVE: full reasoning present for every match, not just verdicts
    assert "== DEEP DIVE ==" in board
    assert "Serve-point win" in board and "hold" in board
    assert "Markov chain" in board and "expected total games" in board
    assert "EV/1u" in board and "IMPLIED" in board and "FAIR" in board


def test_owner_loosened_gates_apply_via_config():
    cfg = {**CONFIG, "gates": {"edge_pp": 0.01, "ratio": 1.00,
                               "prelim_edge_pp": 0.5, "prelim_ratio": 1.01}}
    manifest = Manifest()
    # small model edge: fair ~52.4/47.6 from -115/-105; model 54% on A
    ev = OddsEvent(
        sport="tennis", event_id="t2", home="Alpha Server",
        away="Beta Returner", start_utc="", tournament="ATP Test",
        markets={"ml": [
            Quote(book="pinnacle", side="Alpha Server", price=-115),
            Quote(book="pinnacle", side="Beta Returner", price=-105),
            # line shopping: a softer book hangs +100 on A
            Quote(book="draftkings", side="Alpha Server", price=100),
            Quote(book="draftkings", side="Beta Returner", price=-125),
        ]})
    m = ManualMatch(
        player_a=ManualPlayer("Alpha Server", spw=0.641, rpw=0.380, matches=50),
        player_b=ManualPlayer("Beta Returner", spw=0.638, rpw=0.378, matches=50),
        surface="Hard", best_of=3)
    cards = run_tennis("2026-07-10", cfg, manifest, [ev], [m])
    ml_a = next(e for e in cards[0].evals if e.side == "Alpha Server")
    # this small an edge is a PASS under spec gates but a PLAY here
    assert 0 < (ml_a.gate.edge_pp or 0) < 3.0
    assert ml_a.gate.verdict == "PLAY"


def test_insufficient_data_blocks_play_despite_huge_edge():
    manifest = Manifest()
    cards = run_tennis("2026-07-10", CONFIG, manifest,
                       [odds_event()], [strong_vs_weak(matches_a=5)])
    c = cards[0]
    assert c.insufficient
    assert all(e.gate.verdict == "INSUFFICIENT DATA" for e in c.evals)
    board = render_board("2026-07-10", manifest, [], cards, True, True)
    assert "INSUFFICIENT DATA" in board
    assert "No plays today" in board


def test_no_odds_means_no_play_ever():
    manifest = Manifest()
    cards = run_tennis("2026-07-10", CONFIG, manifest, None,
                       [strong_vs_weak()])
    c = cards[0]
    assert not c.odds_available
    assert not any(e.gate.verdict == "PLAY" for e in c.evals)
    board = render_board("2026-07-10", manifest, [], cards,
                         mlb_odds_ok=True, tennis_odds_ok=False)
    assert "ODDS UNAVAILABLE" in board


def test_unsupported_format_blocks_play():
    m = strong_vs_weak()
    m.format_supported = False   # e.g. match-tiebreak deciding set
    manifest = Manifest()
    cards = run_tennis("2026-07-10", CONFIG, manifest, [odds_event()], [m])
    assert not any(e.gate.verdict == "PLAY" for e in cards[0].evals)
