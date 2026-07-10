# EDGE HUB

Daily sports-betting terminal for **MLB** (BARREL EDGE) and **ATP/WTA tennis**
(ACE EDGE): today's slate, odds at every book, bet%/handle% where available,
a true-probability model for every market, and a hard-gated verdict on every
game. Built to the EDGE HUB master spec — zero hallucination, fail loudly,
default verdict PASS.

## The Right Rule (zero hallucination)

1. Every displayed number traces to a source fetched during the run
   (endpoint + HTTP status + timestamp + rows in the **SOURCE MANIFEST** at
   the bottom of every board).
2. Fetch failed / field missing → `—` on the board, excluded from the model.
   Stale cache is only ever shown labeled with its age.
3. No pick appears unless **both** edge gates pass; the default verdict is
   **PASS**. A zero-play slate is a successful output.
4. Pre-game numbers are never edited after results are known. Errors are
   appended to `ERRORS.md` and left there.

## Quick start

```bash
pip install -r requirements.txt
cp .env.example .env          # add odds API key(s)
python run_daily.py                            # today's board
python run_daily.py --date 2026-07-10 \
    --splits-paste splits.txt \                # Action Network PRO text
    --tennis-manual matches.txt                # manual SPW/RPW inputs
python run_closing.py                          # closing lines -> CLV
pytest                                         # includes the required
                                               # Markov-vs-100k-sim validation
```

Reports land in `reports/YYYY-MM-DD.md`.

## Models

- **MLB** (`models/mlb_sim.py`): 10,000-draw Monte Carlo per game. Lineup
  xwOBA (platoon-adjusted) or sourced team runs/G in PRELIMINARY mode; SP
  xERA/xFIP blend with times-through-order penalty; bullpen xFIP (league-
  neutral and labeled when unavailable); Savant 3-yr park factor × Open-Meteo
  first-pitch weather; ~54% home prior. Moneyline, total (posted number ±1),
  and run line are all read off the **same** run distribution — the run line
  is never priced independently.
- **Tennis** (`models/tennis_markov.py`): Barnett–Clarke hierarchical Markov
  chain, point → game (closed-form O'Malley) → tiebreak → set → match.
  Inputs: last-52-week SPW/RPW, 60% surface / 40% overall, opponent-adjusted
  (exact formula in the module docstring). Match win %, game spread, and
  total games all come from the full game-count distribution. Best-of-3 and
  best-of-5 handled explicitly; no-ad / match-tiebreak formats are excluded
  from plays. `tests/test_markov_vs_sim.py` enforces closed-form agreement
  with a seeded 100k-iteration brute-force point simulation within 0.1pp.

## Market layer

De-vig reference: Pinnacle → sharpest configured book → multi-book consensus
(proportional method). Edges are computed against the **best** available
price (line shopping is mandatory). Openers are stored on first sight
(`data/openers/`). Splits (DK feed or paste mode) are **context only** —
the gate function does not even accept them as a parameter (tested).

## Edge gate + staking (non-negotiable)

PLAY requires **both**: edge ≥ 3.0pp vs fair AND model/implied ≥ 1.15×
(PRELIMINARY: 4.0pp / 1.20×). Exactly one gate → LEAN, 0u, watch-list.
Stake: quarter-Kelly on a 30u roll at the best price, capped at 1.0u, math
shown on the board. Tennis samples under 20 matches → INSUFFICIENT DATA,
never a play.

## CLV is the grade

Every PLAY is logged (`data/clv/plays.jsonl`) with the line taken. The
closing job fetches the final pre-game reference price, computes CLV per
bet, and keeps a rolling weekly summary. Positive CLV over 100+ bets is the
proof; small-sample W/L is noise and the board says so.

## Automation

- `.github/workflows/daily.yml` — 14:00 UTC: pull → model → board → commit.
- `.github/workflows/closing.yml` — 04:00 UTC: closing lines → CLV → commit.
- Odds API keys go in repo **secrets** (`THE_ODDS_API_KEY`, etc.).

## Repo map

```
adapters/   mlb_statsapi, statcast (pybaseball, cached), odds_adapter
            (the_odds_api | sportsgameodds | odds_api_io), splits_dk,
            splits_paste, tennis_data (Sackmann CSVs), tennis_manual, weather
models/     mlb_sim, tennis_markov, devig, kelly
gates/      edge_gate
reports/    marketeval, pipeline_mlb, pipeline_tennis, board, clv
core/       manifest, http, config, errorlog
tests/      gates, devig, kelly, mlb_sim, markov-vs-sim (required),
            paste parsers, offline end-to-end board
```
