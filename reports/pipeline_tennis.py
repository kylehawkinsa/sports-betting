"""Tennis pipeline: odds -> Sackmann SPW/RPW (or manual paste) -> Markov
model -> gates. Produces one MatchCard per match.

Data-quality gate: a player under 20 matches in the 52-week window is
INSUFFICIENT DATA and the match can never be a play. Unsupported formats
(no-ad, match-tiebreak) are likewise excluded from plays.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date as date_cls

from adapters.odds_adapter import OddsEvent, consensus_line, record_openers
from adapters.tennis_data import PlayerRates, load_matches, player_rates, tour_avg_rpw
from adapters.tennis_manual import ManualMatch
from core.errorlog import log_error
from core.manifest import Manifest
from models.tennis_markov import MatchDistribution, combine_inputs, match_distribution
from reports.marketeval import MarketEval, eval_two_way

GRAND_SLAMS = ("australian open", "roland garros", "french open",
               "wimbledon", "us open")


@dataclass
class MatchCard:
    player_a: str                    # odds "home" side
    player_b: str
    start_utc: str = ""
    tournament: str = ""
    surface: str = ""
    best_of: int = 3
    odds_available: bool = False
    odds_event: OddsEvent | None = None
    insufficient: bool = False
    format_supported: bool = True
    dist: MatchDistribution | None = None
    evals: list[MarketEval] = field(default_factory=list)
    total_line: float | None = None
    total_probs_pm1: dict[float, float] = field(default_factory=dict)
    spread_line: float | None = None
    source_mode: str = ""            # "sackmann" | "manual"
    model_note: str = ""
    why: str = ""


def _blend_inputs(a: PlayerRates, b: PlayerRates, avg_rpw: float
                  ) -> tuple[float, float] | None:
    """Surface rate missing -> overall used for the surface term (labeled)."""
    def pick(surf: float | None, overall: float) -> float:
        return surf if surf is not None else overall
    try:
        return combine_inputs(
            pick(a.spw_surface, a.spw_overall), a.spw_overall,
            pick(a.rpw_surface, a.rpw_overall), a.rpw_overall,
            pick(b.spw_surface, b.spw_overall), b.spw_overall,
            pick(b.rpw_surface, b.rpw_overall), b.rpw_overall,
            tour_avg_rpw=avg_rpw,
        )
    except ValueError as exc:
        log_error(f"TEN {a.name} vs {b.name}", str(exc))
        return None


def _best_of_for(ev: OddsEvent, tour: str) -> int:
    t = (ev.tournament or "").lower()
    if tour == "atp" and any(s in t for s in GRAND_SLAMS):
        return 5
    return ev.best_of or 3


def _evaluate_markets(card: MatchCard, book_priority: list[str]) -> None:
    ev, dist = card.odds_event, card.dist
    if ev is None or dist is None:
        return
    insufficient = card.insufficient or not card.format_supported
    ml = ev.markets.get("ml", [])
    if ml:
        a, b = eval_two_way("ml", ml, ev.home, ev.away, dist.p_match_a,
                            book_priority, insufficient=insufficient)
        card.evals += [a, b]
    sp = ev.markets.get("spread", [])
    line_a = consensus_line(sp, ev.home)
    if line_a is not None:
        card.spread_line = line_a
        p_cover = dist.p_spread_a(line_a)
        a, b = eval_two_way("spread", sp, ev.home, ev.away, p_cover,
                            book_priority, line=line_a,
                            insufficient=insufficient)
        # opposite side has mirrored line; refresh its best price/gate
        from adapters.odds_adapter import best_price  # noqa: PLC0415
        from gates.edge_gate import evaluate as _ev  # noqa: PLC0415
        bb = best_price(sp, ev.away, line=-line_a)
        b.best, b.line = bb, -line_a
        b.gate = _ev(b.model_prob, b.fair_prob, bb.price if bb else None,
                     insufficient_data=insufficient)
        card.evals += [a, b]
    tg = ev.markets.get("total_games", [])
    line = consensus_line(tg, "over")
    if line is not None:
        card.total_line = line
        p_over = dist.p_total_over(line)
        card.total_probs_pm1 = {
            line - 1: dist.p_total_over(line - 1),
            line: p_over,
            line + 1: dist.p_total_over(line + 1),
        }
        o, u = eval_two_way("total_games", tg, "over", "under", p_over,
                            book_priority, line=line, insufficient=insufficient)
        card.evals += [o, u]


def run_tennis(date_str: str, config: dict, manifest: Manifest,
               odds_events: list[OddsEvent] | None,
               manual_matches: list[ManualMatch]) -> list[MatchCard]:
    tcfg = config.get("tennis", {}) or {}
    book_priority = (config.get("odds", {}) or {}).get("book_priority",
                                                       ["pinnacle"])
    default_avg_rpw = float(tcfg.get("tour_avg_rpw", 0.38))
    cards: list[MatchCard] = []

    if odds_events:
        record_openers("tennis", date_str, odds_events)

    # ---- manual mode first: guaranteed path, overrides fetched data
    manual_names: set[str] = set()
    for m in manual_matches:
        card = MatchCard(
            player_a=m.player_a.name, player_b=m.player_b.name,
            surface=m.surface, best_of=m.best_of, source_mode="manual",
            format_supported=m.format_supported,
            insufficient=m.player_a.insufficient or m.player_b.insufficient,
        )
        manual_names.update({m.player_a.name.lower(), m.player_b.name.lower()})
        combine_pair = None
        try:
            combine_pair = combine_inputs(
                m.player_a.spw_surface if m.player_a.spw_surface is not None else m.player_a.spw,
                m.player_a.spw,
                m.player_a.rpw_surface if m.player_a.rpw_surface is not None else m.player_a.rpw,
                m.player_a.rpw,
                m.player_b.spw_surface if m.player_b.spw_surface is not None else m.player_b.spw,
                m.player_b.spw,
                m.player_b.rpw_surface if m.player_b.rpw_surface is not None else m.player_b.rpw,
                m.player_b.rpw,
                tour_avg_rpw=default_avg_rpw,
            )
        except ValueError as exc:
            log_error(f"TEN manual {m.player_a.name} vs {m.player_b.name}", str(exc))
            card.model_note = "inputs rejected (implausible serve-win prob)"
        if combine_pair and m.format_supported:
            pa, pb = combine_pair
            card.dist = match_distribution(pa, pb, best_of=m.best_of)
            card.why = (f"manual SPW/RPW: pa={pa:.3f} pb={pb:.3f}, "
                        f"{m.surface}, Bo{m.best_of}")
        # match odds by player-name substring
        if odds_events:
            for ev in odds_events:
                names = f"{ev.home} {ev.away}".lower()
                if (m.player_a.name.split()[-1].lower() in names
                        and m.player_b.name.split()[-1].lower() in names):
                    card.odds_event = ev
                    card.odds_available = bool(ev.markets.get("ml"))
                    card.player_a, card.player_b = ev.home, ev.away
                    card.start_utc = ev.start_utc
                    card.tournament = ev.tournament
                    break
        _evaluate_markets(card, book_priority)
        cards.append(card)

    # ---- fetched path: Sackmann rates for remaining odds events
    if odds_events:
        remaining = [ev for ev in odds_events
                     if not ({ev.home.lower(), ev.away.lower()} & manual_names)
                     and not any(n in f"{ev.home} {ev.away}".lower()
                                 for n in manual_names)]
        frames = {}
        for tour in ("atp", "wta"):
            if tcfg.get(tour, True):
                frames[tour] = load_matches(tour, date_cls.fromisoformat(date_str),
                                            manifest)
        for ev in remaining:
            surface = ev.surface or tcfg.get("default_surface", "Hard")
            card = MatchCard(
                player_a=ev.home, player_b=ev.away, start_utc=ev.start_utc,
                tournament=ev.tournament, surface=surface,
                odds_event=ev, odds_available=bool(ev.markets.get("ml")),
                source_mode="sackmann",
            )
            ra = rb = None
            avg_rpw = default_avg_rpw
            for tour, df in frames.items():
                if df is None:
                    continue
                ra_t = player_rates(df, ev.home, surface)
                rb_t = player_rates(df, ev.away, surface)
                if ra_t and rb_t:
                    ra, rb = ra_t, rb_t
                    avg = tour_avg_rpw(df)
                    if avg is not None:
                        avg_rpw = avg
                    card.best_of = _best_of_for(ev, tour)
                    break
            if ra is None or rb is None:
                card.insufficient = True
                card.model_note = "player SPW/RPW not found in 52-wk window"
            else:
                card.insufficient = ra.insufficient or rb.insufficient
                if card.insufficient:
                    card.model_note = (f"sample: {ra.name} {ra.matches_overall} / "
                                       f"{rb.name} {rb.matches_overall} matches (<20)")
                pair = _blend_inputs(ra, rb, avg_rpw)
                if pair:
                    pa, pb = pair
                    card.dist = match_distribution(pa, pb, best_of=card.best_of)
                    surf_note = ("" if ra.spw_surface is not None
                                 and rb.spw_surface is not None
                                 else " (surface sample missing — overall used)")
                    card.why = (f"52-wk SPW/RPW: pa={pa:.3f} pb={pb:.3f}, "
                                f"{surface}, Bo{card.best_of}{surf_note}")
            _evaluate_markets(card, book_priority)
            cards.append(card)

    return cards
