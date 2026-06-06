"""資料同步編排：賽程 / 盤口 / 球員分離，ETL 離線執行。"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Literal

from sportsbet import config
from sportsbet.data.api_sports import calendar_season
from sportsbet.data.database import SportsDatabase
from sportsbet.data.provider import get_data_provider
from sportsbet.data.registry.team_registry import TeamRegistry
from sportsbet.services.data_refresh import (
    run_full_backtest_refresh,
    run_incremental_backtest_refresh,
)
from sportsbet.services.prediction_service import PredictionService
from sportsbet.services.sync_accumulation import (
    accumulate_after_sync,
    capture_ledger_pre,
    ensure_ledger_start_date,
)

logger = logging.getLogger(__name__)

Sport = Literal["nba", "mlb"]


class DataOrchestrator:
    """統一 ETL 入口：UI / CLI / GitHub Actions 共用。"""

    def __init__(self, db: SportsDatabase | None = None):
        self.db = db or SportsDatabase()
        self.provider = get_data_provider(self.db)
        self.registry = TeamRegistry(self.db)

    def sync_games(
        self,
        sport: Sport,
        *,
        from_date: str | None = None,
        to_date: str | None = None,
        incremental: bool = False,
    ) -> int:
        """同步賽程與賽果。"""
        season = calendar_season(sport)
        if not incremental or self.db.get_team_stats(sport).empty:
            self.provider.fetch_historical_stats(sport, season, incremental=incremental)

        start = date.fromisoformat(from_date) if from_date else date.today()
        end = date.fromisoformat(to_date) if to_date else start + timedelta(days=7)
        n = 0
        d = start
        while d <= end:
            ds = d.isoformat()
            self.provider.fetch_daily_schedule(sport, ds)
            n += 1
            d += timedelta(days=1)
        self.db.finalize_games_with_scores(sport)
        return n

    def repair_data_quality(self, sport: Sport) -> dict[str, int]:
        """清理占位 final、補 moneyline、修正 finalize。"""
        from sportsbet.services.data_refresh import prepare_backtest_odds

        return prepare_backtest_odds(self.db, sport, incremental=False)

    def sync_odds(
        self,
        sport: Sport,
        *,
        from_date: str | None = None,
        to_date: str | None = None,
        replace: bool = False,
    ) -> int:
        """同步台灣運彩 Blob 盤口。"""
        start = date.fromisoformat(from_date) if from_date else date.today()
        end = date.fromisoformat(to_date) if to_date else start + timedelta(days=7)
        n = 0
        d = start
        while d <= end:
            ds = d.isoformat()
            if replace or self.db.count_odds_for_date(sport, ds) == 0:
                self.provider.fetch_odds(sport, ds, replace=replace)
                n += 1
            d += timedelta(days=1)
        return n

    def sync_live(self, sport: Sport) -> dict[str, int | str]:
        """委派至 LiveSyncService（輕量即時）。"""
        from sportsbet.services.live_sync import LiveSyncService

        return LiveSyncService(self.db).sync_live(sport)

    def sync_players(self, sport: Sport, *, days_lineup: int = 7, force: bool = False) -> dict[str, int]:
        """同步傷兵、球員統計、預計上場。"""
        today = date.today().isoformat()
        if not force:
            last = self.db.get_backtest_sync_meta(sport, "players_synced_at")
            if last and last[:10] == today:
                from sportsbet.data.espn_injuries import (
                    EspnInjuryClient,
                    sync_espn_injuries,
                    sync_espn_projected_lineups,
                )
                from datetime import timedelta

                client = EspnInjuryClient()
                match_dates = [
                    (date.today() + timedelta(days=i)).isoformat() for i in range(days_lineup)
                ]
                return {
                    "players": 0,
                    "injuries": sync_espn_injuries(
                        self.db, sport, report_date=today, client=client,
                    ),
                    "lineups": sync_espn_projected_lineups(
                        self.db, sport, match_dates=match_dates, client=client,
                    ),
                }

        from sportsbet.data.player_ingestion import sync_v2_player_data

        out = sync_v2_player_data(self.db, sport, days_lineup=days_lineup)
        self.db.set_backtest_sync_meta(sport, "players_synced_at", today)
        return out

    def sync_daily(self, sport: Sport, *, days_ahead: int | None = None, force_players: bool = False) -> dict[str, int]:
        """每日管線：賽程 + 盤口 + 球員 + 預測 + 歷史累積。"""
        days = days_ahead if days_ahead is not None else config.SCHEDULE_SYNC_DAYS_AHEAD
        out: dict[str, int] = {}
        season = calendar_season(sport)
        incremental = self.db.is_backtest_cache_warm(sport)

        ensure_ledger_start_date(self.db)

        if self.db.get_team_stats(sport).empty:
            self.provider.fetch_historical_stats(sport, season, incremental=False)
        else:
            self.provider.fetch_historical_stats(sport, season, incremental=incremental)

        today = date.today()
        for offset in range(days + 1):
            d = (today + timedelta(days=offset)).isoformat()
            self.provider.fetch_daily_schedule(sport, d)

        out["ledger_pre"] = capture_ledger_pre(self.db, sport)

        for offset in range(days + 1):
            d = (today + timedelta(days=offset)).isoformat()
            self.provider.fetch_odds(sport, d, replace=False)

        out["players"] = sum(
            self.sync_players(sport, days_lineup=days, force=force_players).values()
        )

        svc = PredictionService(self.db)
        forecasts = svc.run_upcoming(sport, days_ahead=days)
        out["forecasts"] = len(forecasts)

        acc = accumulate_after_sync(self.db, sport)
        out.update(acc)

        if sport == "nba":
            from sportsbet.data.boxscore_sync import sync_nba_box_scores

            bs = sync_nba_box_scores(
                self.db,
                regular_days_back=min(days, config.BOXSCORE_REGULAR_DAYS_BACK),
                max_regular=min(80, max(30, days * 4)),
            )
            out.update(bs)

        self.db.set_backtest_sync_meta(sport, "daily_synced_at", today.isoformat())
        logger.info("daily sync sport=%s stats=%s", sport, out)

        if config.GITHUB_AUTO_PUSH:
            from sportsbet.data.db_github_sync import persist_database_after_sync

            push = persist_database_after_sync(
                f"chore(data): daily sync {sport}",
                db=self.db,
            )
            logger.info("daily sync github push: %s %s", push.status, push.detail)

        return out

    def sync_backtest_incremental(self, sport: Sport) -> dict[str, int]:
        return run_incremental_backtest_refresh(
            self.db, sport, sync_api=True, sync_injuries=True,
        )

    def sync_backtest_full(self, sport: Sport) -> dict[str, int]:
        return run_full_backtest_refresh(
            self.db, sport, sync_api=True, sync_injuries=True,
        )

    def sync_all_sports_daily(self, *, days_ahead: int = 7) -> dict[str, dict[str, int]]:
        return {
            "nba": self.sync_daily("nba", days_ahead=days_ahead),
            "mlb": self.sync_daily("mlb", days_ahead=days_ahead),
        }
