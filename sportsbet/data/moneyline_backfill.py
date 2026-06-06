"""為缺 moneyline 的歷史場次補上台灣運彩標準勝負盤（1.75）。"""
from __future__ import annotations

import logging

from sportsbet import config
from sportsbet.data.database import SportsDatabase

logger = logging.getLogger(__name__)

Sport = str


def backfill_tw_moneyline_odds(db: SportsDatabase, sport: Sport) -> int:
    """
    玩運彩歷史僅含讓分/大小時，補上 moneyline 供 EV 回測。
    台灣運彩不讓分制固定賠率 1.75（兩邊相同）。
    """
    odds_val = config.TW_MONEYLINE_ODDS
    with db.connection() as conn:
        rows = conn.execute(
            """
            SELECT g.id AS game_id
            FROM games g
            WHERE g.sport = ?
              AND g.status = 'final'
              AND g.home_score IS NOT NULL
              AND (g.home_score + g.away_score) > 0
              AND g.match_date <= date('now')
              AND NOT EXISTS (
                  SELECT 1 FROM odds o
                  WHERE o.game_id = g.id AND o.market = 'moneyline'
              )
            """,
            (sport,),
        ).fetchall()

    n = 0
    for row in rows:
        gid = int(row["game_id"])
        db.insert_odds(gid, "moneyline", "home", odds_val, bookmaker="tw_standard")
        db.insert_odds(gid, "moneyline", "away", odds_val, bookmaker="tw_standard")
        n += 2

    if n:
        logger.info("補 moneyline sport=%s rows=%d (odds=%.2f)", sport, n, odds_val)
    return n
