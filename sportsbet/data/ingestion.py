"""資料獲取層：抽象介面與 API 適配器。"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import date
from typing import Any, Literal

import pandas as pd

from sportsbet.data.database import SportsDatabase
from sportsbet.data.sportslottery_odds import SportLotteryOddsMixin

logger = logging.getLogger(__name__)

SportLit = Literal["nba", "mlb"]


class DataIngestionProvider(ABC):
    """資料來源介面。"""

    @abstractmethod
    def fetch_daily_schedule(self, sport: SportLit, match_date: str | None = None) -> pd.DataFrame:
        """取得指定日期賽程。"""

    @abstractmethod
    def fetch_historical_stats(
        self,
        sport: SportLit,
        season: str | int | None = None,
        *,
        incremental: bool = False,
    ) -> pd.DataFrame:
        """取得球隊賽季統計（得分/失分、近況等）。"""

    @abstractmethod
    def fetch_odds(
        self,
        sport: SportLit,
        match_date: str | None = None,
        *,
        replace: bool = False,
    ) -> pd.DataFrame:
        """取得台灣運彩賠率。"""


class ApiSportsIngestionAdapter(SportLotteryOddsMixin, DataIngestionProvider):
    """API-Sports 賽程/統計 + 台灣運彩 Blob 賠率（付費 optional）。"""

    def __init__(
        self,
        db: SportsDatabase | None = None,
        client: Any | None = None,
    ):
        from sportsbet.data.api_sports import ApiSportsClient, infer_season

        self.db = db or SportsDatabase()
        self.client = client or ApiSportsClient()
        self._infer_season = infer_season

    def fetch_daily_schedule(self, sport: SportLit, match_date: str | None = None) -> pd.DataFrame:
        d = match_date or date.today().isoformat()
        if not self.client.is_configured:
            raise RuntimeError("API_SPORTS_KEY 未設定，API-only 模式下不可抓取賽程。")
        return self.client.sync_daily_to_database(self.db, sport, d)

    def fetch_historical_stats(
        self,
        sport: SportLit,
        season: str | int | None = None,
        *,
        incremental: bool = False,
    ) -> pd.DataFrame:
        if not self.client.is_configured:
            raise RuntimeError("API_SPORTS_KEY 未設定，API-only 模式下不可抓取歷史統計。")
        season_int = int(season) if season else self._infer_season(sport)
        self.client.sync_team_logos(self.db, sport, season_int)
        stats = self.client.sync_to_database(self.db, sport, season_int)
        if stats.empty:
            logger.warning("API-Sports 未回傳球隊統計，賽季=%s", season_int)
        return stats
