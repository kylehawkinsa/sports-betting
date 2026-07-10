"""Paste-mode parsers: splits (Action Network PRO text) and tennis manual
inputs — the guaranteed no-API paths."""
from core.manifest import Manifest

from adapters.splits_paste import parse_splits_paste
from adapters.tennis_manual import parse_manual_matches


def test_splits_paste_variants(tmp_path):
    f = tmp_path / "splits.txt"
    f.write_text(
        "Reds ML 38% bets / 61% handle\n"
        "PHI bets: 62 handle: 39\n"
        "garbage line with no numbers\n"
        "Cubs total over 45% of bets, 58% of handle\n"
        "Unknown Team 50% bets / 50% handle\n"
    )
    m = Manifest()
    out = parse_splits_paste(f, ["Reds", "PHI", "Cubs"], m)
    assert set(out) == {"Reds", "PHI", "Cubs"}
    s = out["Reds"][0]
    assert (s.bets_pct, s.handle_pct, s.market) == (38.0, 61.0, "ml")
    assert out["Cubs"][0].market == "total"
    assert m.records[-1].rows == 3


def test_splits_paste_ignores_comment_lines(tmp_path):
    # instruction headers in paste/splits.txt must never parse as data
    f = tmp_path / "splits.txt"
    f.write_text("# Reds ML 38% bets / 61% handle\nReds ML 40% bets / 55% handle\n")
    out = parse_splits_paste(f, ["Reds"], Manifest())
    assert len(out["Reds"]) == 1
    assert out["Reds"][0].bets_pct == 40.0


def test_splits_paste_missing_file(tmp_path):
    m = Manifest()
    out = parse_splits_paste(tmp_path / "nope.txt", ["Reds"], m)
    assert out == {}
    assert m.records[-1].status == "FAIL"


def test_tennis_manual_parse(tmp_path):
    f = tmp_path / "manual.txt"
    f.write_text(
        "match: Alcaraz vs Sinner\n"
        "surface: clay\n"
        "best_of: 5\n"
        "A: spw=67.1 rpw=41.2 spw_surface=69.0 rpw_surface=43.1 "
        "matches=52 matches_surface=18\n"
        "B: spw=68.9 rpw=39.8 matches=61\n"
        "\n"
        "match: Nobody vs Someone\n"
        "A: spw=0.61 rpw=0.36 matches=5\n"
        "B: spw=0.63 rpw=0.37 matches=40\n"
    )
    m = Manifest()
    out = parse_manual_matches(f, m)
    assert len(out) == 2
    a = out[0]
    assert a.player_a.name == "Alcaraz" and a.best_of == 5
    assert abs(a.player_a.spw - 0.671) < 1e-9   # percent form normalized
    assert a.player_b.spw_surface is None   # optional field genuinely absent
    assert not a.player_a.insufficient
    # second match: player A has 5 matches -> INSUFFICIENT DATA
    assert out[1].player_a.insufficient
    assert out[1].player_a.spw == 0.61      # fraction form kept as-is
