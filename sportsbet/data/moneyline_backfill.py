"""Moneyline 補值：玩運彩不讓分（台灣運彩固定賠率）。"""
from __future__ import annotations

import logging

from sportsbet import config
from sportsbet.data.database import SportsDatabase

logger = logging.getLogger(__name__)

Sport = str


def backfill_playsport_moneyline(db: SportsDatabase, sport: Sport) -> int:
    """
    對已有玩運彩讓分/大小盤口的場次，補上 moneyline。

    玩運彩歷史頁的 td-bank-bet03 = 台灣運彩「不讓分」；
    該玩法在運彩為固定賠率（預設 1.75），非浮動莊家盤。
    bookmaker=playsport，與讓分/大小同源。
    """
    if not config.PLAYSPORT_MONEYLINE_ENABLED:
        return 0

    odds_val = config.TW_MONEYLINE_ODDS
    with db.connection() as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT g.id AS game_id
            FROM games g
            JOIN odds o ON o.game_id = g.id AND o.bookmaker = 'playsport'
            WHERE g.sport = ?
              AND g.status = 'final'
              AND g.home_score IS NOT NULL
              AND (g.home_score + g.away_score) > 0
              AND g.match_date <= date('now')
              AND NOT EXISTS (
                  SELECT 1 FROM odds m
                  WHERE m.game_id = g.id AND m.market = 'moneyline'
              )
            """,
            (sport,),
        ).fetchall()

    n = 0
    for row in rows:
        gid = int(row["game_id"])
        db.upsert_odds(gid, "moneyline", "home", odds_val, bookmaker="playsport")
        db.upsert_odds(gid, "moneyline", "away", odds_val, bookmaker="playsport")
        n += 2

    if n:
        logger.info(
            "玩運彩 moneyline sport=%s rows=%d (fixed odds=%.2f)",
            sport, n, odds_val,
        )
    return n


def backfill_tw_moneyline_odds(db: SportsDatabase, sport: Sport) -> int:
    """
    舊版全域補值（ALLOW_TW_MONEYLINE_BACKFILL=true）。
    無玩運彩/JBot 驗證，預設關閉。
    """
    if not config.ALLOW_TW_MONEYLINE_BACKFILL:
        return 0

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
        logger.info("全域補 moneyline sport=%s rows=%d (odds=%.2f)", sport, n, odds_val)
    return n
