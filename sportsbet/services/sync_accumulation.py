"""同步後累積寫入 DB：今日/未來賽事隨每次同步形成歷史資料。"""
from __future__ import annotations

import logging
import os
from datetime import date
from typing import Literal

from sportsbet import config
from sportsbet.data.database import SportsDatabase
from sportsbet.services.data_refresh import rebuild_predictions_from_forecasts
from sportsbet.services.prediction_service import PredictionService

logger = logging.getLogger(__name__)

Sport = Literal["nba", "mlb"]

_LEDGER_META_KEY = "ledger_start_date"


def ensure_ledger_start_date(db: SportsDatabase) -> str:
    """
    帳本累積起始日（固定不往前推）。
    優先讀 DB；首次同步寫入後不再變更（除非 .env 強制覆寫且 DB 尚無紀錄）。
    """
    for sport in ("nba", "mlb"):
        val = db.get_backtest_sync_meta(sport, _LEDGER_META_KEY)  # type: ignore[arg-type]
        if val:
            return str(val)[:10]

    env = os.getenv("GAME_LEDGER_START_DATE", "").strip()
    start = env if env else date.today().isoformat()
    for sport in ("nba", "mlb"):
        db.set_backtest_sync_meta(sport, _LEDGER_META_KEY, start)  # type: ignore[arg-type]
    logger.info("ledger start date initialized: %s", start)
    return start


def capture_ledger_pre(db: SportsDatabase, sport: Sport) -> int:
    """賽前快照（每場只保留第一次，在盤口覆寫前呼叫）。"""
    if not config.GAME_LEDGER_ENABLED:
        return 0
    from sportsbet.services.game_ledger import GameLedgerService

    ensure_ledger_start_date(db)
    n = GameLedgerService(db).capture_pre_only(sport)
    logger.debug("ledger pre sport=%s captured=%d", sport, n)
    return n


def accumulate_after_sync(db: SportsDatabase, sport: Sport) -> dict[str, int]:
    """
    同步收尾：完賽標記 → 賽後帳本 → 覆盤寫入 game_forecasts → predictions。
    從 ledger 起始日起的每場完賽都會累積進歷史表。
    """
    out: dict[str, int] = {"finalized": 0, "ledger_post": 0, "reconciled_finals": 0, "predictions": 0}
    out["finalized"] = db.finalize_games_with_scores(sport)

    if not config.GAME_LEDGER_ENABLED:
        return out

    start = ensure_ledger_start_date(db)
    pending = db.get_games_for_ledger_post(sport, start_date=start)
    pending_ids = pending["id"].astype(int).tolist() if not pending.empty else []

    from sportsbet.services.game_ledger import GameLedgerService

    ledger = GameLedgerService(db).capture_post_only(sport, start_date=start)
    out["ledger_post"] = ledger

    if pending_ids:
        svc = PredictionService(db)
        svc.run_backtest_reconcile(sport, game_ids=pending_ids)
        out["reconciled_finals"] = len(pending_ids)
        out["predictions"] = rebuild_predictions_from_forecasts(
            db, sport, game_ids=pending_ids,
        )
        logger.info(
            "accumulated finals sport=%s count=%d predictions=%d",
            sport, len(pending_ids), out["predictions"],
        )

    return out
