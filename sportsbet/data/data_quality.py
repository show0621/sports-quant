"""資料品質檢查：決定是否啟用 Bottom-Up / 熱區等功能。"""
from __future__ import annotations

from typing import Literal

from sportsbet.data.database import SportsDatabase

Sport = Literal["nba", "mlb"]


def has_real_player_stats(db: SportsDatabase, sport: Sport) -> bool:
    """至少 5 名球員有非空 rolling_off_rating（來自真實 API）。"""
    with db.connection() as conn:
        row = conn.execute(
            """
            SELECT COUNT(DISTINCT player_id) AS n
            FROM player_advanced_stats
            WHERE sport = ?
              AND rolling_off_rating IS NOT NULL
              AND hot_cold_index IS NOT NULL
            """,
            (sport,),
        ).fetchone()
    return int(row["n"] or 0) >= 5


def roster_rating_enabled(db: SportsDatabase, sport: Sport) -> bool:
    from sportsbet import config

    if not config.USE_ROSTER_RATING:
        return False
    return has_real_player_stats(db, sport)


def data_quality_summary(db: SportsDatabase, sport: Sport) -> dict[str, bool]:
    stats = db.get_team_stats(sport)
    with db.connection() as conn:
        games_n = conn.execute(
            "SELECT COUNT(*) AS n FROM games WHERE sport = ? AND status = 'final'",
            (sport,),
        ).fetchone()["n"]
        odds_n = conn.execute(
            """
            SELECT COUNT(DISTINCT game_id) AS n FROM odds o
            JOIN games g ON g.id = o.game_id
            WHERE g.sport = ? AND o.bookmaker = 'sportslottery'
            """,
            (sport,),
        ).fetchone()["n"]
        ml_n = conn.execute(
            """
            SELECT COUNT(DISTINCT o.game_id) AS n FROM odds o
            JOIN games g ON g.id = o.game_id
            WHERE g.sport = ? AND o.market = 'moneyline'
            """,
            (sport,),
        ).fetchone()["n"]
        inj_n = conn.execute(
            "SELECT COUNT(*) AS n FROM injury_reports WHERE sport = ? AND source = 'espn'",
            (sport,),
        ).fetchone()["n"]
    return {
        "team_stats": not stats.empty,
        "historical_games": int(games_n or 0) > 0,
        "tw_odds": int(odds_n or 0) > 0,
        "moneyline_odds": int(ml_n or 0) > 0,
        "injuries": int(inj_n or 0) > 0,
        "player_rolling": has_real_player_stats(db, sport),
    }
