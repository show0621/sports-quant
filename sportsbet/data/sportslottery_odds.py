"""台灣運彩 Blob 賠率寫入（混合模式共用）。"""
from __future__ import annotations

import logging

import pandas as pd

from sportsbet.data.database import SportsDatabase
from sportsbet.data.tw_odds_sync import sync_tw_odds_for_date

logger = logging.getLogger(__name__)

SportLit = str


class SportLotteryOddsMixin:
    """需由 DataIngestionProvider 子類設定 self.db。"""

    db: SportsDatabase

    def fetch_odds(
        self,
        sport: SportLit,
        match_date: str | None = None,
        *,
        replace: bool = False,
    ) -> pd.DataFrame:
        from datetime import date

        d = match_date or date.today().isoformat()
        stats = sync_tw_odds_for_date(self.db, sport, d, replace=replace)
        logger.info(
            "台灣盤口 %s %s → 運彩 %d 列 · 玩運彩補 %d",
            sport, d, stats.get("sportslottery_rows", 0), stats.get("playsport_fallback", 0),
        )
        games = self.db.get_games(sport, d)
        if games.empty:
            return pd.DataFrame()
        with self.db.connection() as conn:
            return pd.read_sql_query(
                """
                SELECT o.*, g.home_team, g.away_team, g.match_date
                FROM odds o
                JOIN games g ON g.id = o.game_id
                WHERE g.sport = ? AND g.match_date = ?
                ORDER BY o.id
                """,
                conn,
                params=(sport, d),
            )
