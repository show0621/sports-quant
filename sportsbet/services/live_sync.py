"""輕量即時同步：盤口 + 傷兵 + 今日賽程 + 預測（穩定、可高頻執行）。"""
from __future__ import annotations

import logging
import time
from datetime import date, timedelta
from typing import Literal

from sportsbet import config
from sportsbet.data.database import SportsDatabase
from sportsbet.data.orchestrator import DataOrchestrator
from sportsbet.services.prediction_service import PredictionService

logger = logging.getLogger(__name__)

Sport = Literal["nba", "mlb"]


class LiveSyncService:
    """
    即時同步層（約 30–60 秒完成）：
    - 不跑 nba_api 全季 / 玩運彩 / 完整 backtest
    - 專供 watch 背景程序與看板 auto-refresh 觸發
    """

    def __init__(self, db: SportsDatabase | None = None):
        self.db = db or SportsDatabase()
        self.orch = DataOrchestrator(self.db)

    def sync_live(self, sport: Sport) -> dict[str, int | str]:
        t0 = time.perf_counter()
        out: dict[str, int | str] = {}
        try:
            self.db.purge_invalid_team_games(sport)
            self.db.purge_cross_sport_games(sport)

            if self.db.get_team_stats(sport).empty:
                from sportsbet.data.api_sports import calendar_season

                self.orch.provider.fetch_historical_stats(
                    sport, calendar_season(sport), incremental=True,
                )

            days = config.LIVE_SYNC_DAYS_AHEAD
            today = date.today()
            from sportsbet.data.espn_schedule import EspnScheduleClient

            EspnScheduleClient().sync_window_to_database(
                self.db, sport, center=today, days_before=1, days_after=days,
            )

            for offset in range(days + 1):
                d = (today + timedelta(days=offset)).isoformat()
                self.orch.provider.fetch_odds(sport, d, replace=True)

            player_stats = self.orch.sync_players(sport, days_lineup=days, force=False)
            out.update({k: int(v) for k, v in player_stats.items()})

            svc = PredictionService(self.db)
            forecasts = svc.run_upcoming(sport, days_ahead=days)
            out["forecasts"] = len(forecasts)

            self.db.finalize_games_with_scores(sport)
            if config.GAME_LEDGER_ENABLED:
                from sportsbet.services.game_ledger import GameLedgerService

                ledger = GameLedgerService(self.db).sync_sport(sport)
                out["ledger_pre"] = ledger["pre"]
                out["ledger_post"] = ledger["post"]
            now = date.today().isoformat()
            self.db.set_backtest_sync_meta(sport, "live_synced_at", now)

            elapsed = int((time.perf_counter() - t0) * 1000)
            self.db.record_sync_health(sport, "live", "ok", duration_ms=elapsed)
            out["duration_ms"] = elapsed
            logger.info("live sync sport=%s %s", sport, out)
            return out
        except Exception as exc:
            elapsed = int((time.perf_counter() - t0) * 1000)
            self.db.record_sync_health(
                sport, "live", "error", message=str(exc), duration_ms=elapsed,
            )
            logger.exception("live sync failed sport=%s", sport)
            raise

    def sync_all_live(self) -> dict[str, dict[str, int | str]]:
        return {"nba": self.sync_live("nba"), "mlb": self.sync_live("mlb")}


def run_watch_loop(
    *,
    sports: list[Sport] | None = None,
    interval_sec: int | None = None,
    push_github: bool = False,
) -> None:
    """背景常駐：週期性 live sync。"""
    import signal

    sports = sports or ["nba", "mlb"]
    interval = interval_sec or config.LIVE_SYNC_INTERVAL_SEC
    svc = LiveSyncService()
    running = True

    def _stop(*_args: object) -> None:
        nonlocal running
        running = False
        logger.info("watch 收到停止信號")

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    logger.info("watch 啟動 sports=%s interval=%ds", sports, interval)
    while running:
        for sp in sports:
            if not running:
                break
            try:
                svc.sync_live(sp)
            except Exception:
                pass
        if push_github:
            try:
                from sportsbet.data.db_github_sync import push_database_to_github

                push_database_to_github(message="chore(data): live watch sync")
            except Exception as exc:
                logger.warning("GitHub push 略過: %s", exc)
        for _ in range(interval):
            if not running:
                break
            time.sleep(1)
    logger.info("watch 已停止")
