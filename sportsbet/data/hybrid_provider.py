"""混合資料來源：nba_api/ESPN + 運彩 Blob，API-Sports 為選用備援。"""
from __future__ import annotations

import logging
from datetime import date, timedelta

import pandas as pd

from sportsbet import config
from sportsbet.data.api_sports import ApiSportsClient, calendar_season, infer_season, season_clamped
from sportsbet.data.database import SportsDatabase
from sportsbet.data.espn_schedule import EspnScheduleClient
from sportsbet.data.ingestion import ApiSportsIngestionAdapter, DataIngestionProvider, SportLit
from sportsbet.data.nba_api_stats import sync_nba_season_to_database
from sportsbet.data.sportslottery_odds import SportLotteryOddsMixin

logger = logging.getLogger(__name__)


class EspnIngestionAdapter(SportLotteryOddsMixin, DataIngestionProvider):
    """ESPN 賽程/比分 + 運彩賠率。"""

    def __init__(self, db: SportsDatabase | None = None):
        self.db = db or SportsDatabase()
        self.client = EspnScheduleClient()

    def fetch_daily_schedule(self, sport: SportLit, match_date: str | None = None) -> pd.DataFrame:
        d = match_date or date.today().isoformat()
        return self.client.sync_date_to_database(self.db, sport, d)

    def fetch_historical_stats(self, sport: SportLit, season: str | int | None = None) -> pd.DataFrame:
        season_i = int(season) if season else calendar_season(sport)  # type: ignore[arg-type]
        days = min(config.BACKTEST_DAYS, 120)
        self.client.backfill_dates(self.db, sport, days_back=days)
        return self.client.rebuild_team_stats_from_db(
            self.db, sport, season=season_i, days_back=days
        )


class NbaApiIngestionAdapter(SportLotteryOddsMixin, DataIngestionProvider):
    """nba_api 賽季賽果 + ESPN 每日賽程 + 運彩賠率。"""

    def __init__(self, db: SportsDatabase | None = None):
        self.db = db or SportsDatabase()
        self.espn = EspnScheduleClient()

    def fetch_daily_schedule(self, sport: SportLit, match_date: str | None = None) -> pd.DataFrame:
        if sport != "nba":
            return EspnIngestionAdapter(self.db).fetch_daily_schedule(sport, match_date)
        d = match_date or date.today().isoformat()
        return self.espn.sync_date_to_database(self.db, "nba", d)

    def fetch_historical_stats(self, sport: SportLit, season: str | int | None = None) -> pd.DataFrame:
        if sport != "nba":
            return EspnIngestionAdapter(self.db).fetch_historical_stats(sport, season)
        season_i = int(season) if season else calendar_season("nba")
        return sync_nba_season_to_database(self.db, season_i)


class HybridIngestionProvider(SportLotteryOddsMixin, DataIngestionProvider):
    """
    優先順序：
    - 賽程：API-Sports（若金鑰可用且賽季未受限）→ NBA: nba_api 當季 / ESPN 每日
    - 歷史：NBA nba_api → API-Sports → ESPN 回補
    - 賠率：運彩 Blob
    - 傷兵：ESPN（由 player_ingestion 處理）
    """

    def __init__(self, db: SportsDatabase | None = None):
        self.db = db or SportsDatabase()
        self._espn = EspnIngestionAdapter(self.db)
        self._nba = NbaApiIngestionAdapter(self.db)
        self._api: ApiSportsIngestionAdapter | None = None
        client = ApiSportsClient()
        if client.is_configured:
            self._api = ApiSportsIngestionAdapter(db=self.db, client=client)

    def _try_api(self, fn_name: str, sport: SportLit, *args, **kwargs) -> pd.DataFrame | None:
        if not self._api:
            return None
        if season_clamped(sport) and fn_name == "fetch_historical_stats":
            # 免費 API 賽季受限時跳過，改走 nba_api / ESPN
            return None
        try:
            fn = getattr(self._api, fn_name)
            return fn(sport, *args, **kwargs)
        except Exception as exc:
            logger.warning("API-Sports %s 失敗，改用備援：%s", fn_name, exc)
            return None

    def fetch_daily_schedule(self, sport: SportLit, match_date: str | None = None) -> pd.DataFrame:
        df = self._try_api("fetch_daily_schedule", sport, match_date)
        if df is not None and not df.empty:
            return df
        if sport == "nba":
            return self._nba.fetch_daily_schedule(sport, match_date)
        return self._espn.fetch_daily_schedule(sport, match_date)

    def fetch_historical_stats(self, sport: SportLit, season: str | int | None = None) -> pd.DataFrame:
        season = season or calendar_season(sport)  # type: ignore[arg-type]
        if sport == "nba":
            try:
                stats = self._nba.fetch_historical_stats(sport, season)
                if not stats.empty:
                    _sync_playsport_history(self.db, sport)
                    return stats
            except Exception as exc:
                logger.warning("nba_api 歷史同步失敗：%s", exc)
        df = self._try_api("fetch_historical_stats", sport, season)
        if df is not None and not df.empty:
            _sync_playsport_history(self.db, sport)
            return df
        stats = self._espn.fetch_historical_stats(sport, season)
        _sync_playsport_history(self.db, sport)
        return stats

    def sync_recent_schedule(self, sport: SportLit, days_ahead: int = 7) -> None:
        """同步今日起算多日賽程（混合來源）。"""
        for offset in range(days_ahead + 1):
            d = (date.today() + timedelta(days=offset)).isoformat()
            self.fetch_daily_schedule(sport, d)


def data_source_description(sport: SportLit) -> str:
    parts = ["混合模式"]
    if sport == "nba":
        parts.append("NBA=nba_api+ESPN")
    else:
        parts.append("MLB=ESPN")
    parts.append("賠率=運彩Blob")
    parts.append("傷兵=ESPN")
    if config.resolve_api_sports_key():
        parts.append("API-Sports=備援")
    if config.PLAYSPORT_ENABLED:
        parts.append("歷史=玩運彩")
    return " · ".join(parts)


def _sync_playsport_history(db: SportsDatabase, sport: SportLit) -> int:
    if not config.PLAYSPORT_ENABLED or sport not in ("nba", "mlb"):
        return 0
    from sportsbet.data.playsport_scraper import PlaySportScraper

    scraper = PlaySportScraper()
    df = scraper.sync_sport(
        db,
        sport,  # type: ignore[arg-type]
        max_teams=config.PLAYSPORT_MAX_TEAMS_PER_SYNC,
    )
    return len(df)
