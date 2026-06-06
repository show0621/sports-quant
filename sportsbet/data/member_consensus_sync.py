"""玩運彩會員共識寫入 DB + 對應 game_id。"""
from __future__ import annotations

import logging
from datetime import date, timedelta

from sportsbet import config
from sportsbet.data.database import SportsDatabase
from sportsbet.data.playsport_predict_scraper import PlaySportPredictScraper
from sportsbet.data.team_logos import resolve_team_in_database

logger = logging.getLogger(__name__)

Sport = str


def _match_game_id(
    db: SportsDatabase,
    sport: Sport,
    match_date: str,
    team_a: str,
    team_b: str,
) -> int | None:
    games = db.get_games(sport, match_date)
    if games.empty:
        return None
    a = resolve_team_in_database(db, sport, team_a)  # type: ignore[arg-type]
    b = resolve_team_in_database(db, sport, team_b)  # type: ignore[arg-type]
    for ha, aa in ((a, b), (b, a)):
        hit = games[(games["home_team"] == ha) & (games["away_team"] == aa)]
        if not hit.empty:
            return int(hit.iloc[0]["id"])
    return None


def sync_member_consensus_for_date(
    db: SportsDatabase,
    sport: Sport,
    match_date: str,
    *,
    member_tier: str | None = None,
) -> int:
    if not config.MEMBER_CONSENSUS_ENABLED:
        return 0
    tier = member_tier or config.MEMBER_CONSENSUS_TIER
    scraper = PlaySportPredictScraper()
    try:
        games = scraper.fetch_games_for_date(sport, match_date, member_tier=tier)  # type: ignore[arg-type]
    except Exception as exc:
        logger.warning("玩運彩會員預測 %s %s: %s", sport, match_date, exc)
        return 0

    n = 0
    for g in games:
        gid = _match_game_id(db, sport, match_date, g.team_a_en, g.team_b_en)
        if gid is None:
            continue
        for row in g.to_consensus_rows():
            row["game_id"] = gid
            db.upsert_member_consensus(row)
            n += 1
    if n:
        db.set_backtest_sync_meta(sport, "member_consensus_synced_at", date.today().isoformat())
    return n


def sync_member_consensus_recent(
    db: SportsDatabase,
    sport: Sport,
    *,
    days_ahead: int | None = None,
) -> int:
    span = days_ahead if days_ahead is not None else config.MEMBER_CONSENSUS_DAYS_AHEAD
    total = 0
    for offset in range(-1, span + 1):
        d = (date.today() + timedelta(days=offset)).isoformat()
        total += sync_member_consensus_for_date(db, sport, d)
    return total
