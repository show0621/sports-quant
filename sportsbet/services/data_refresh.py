"""資料刷新：歷史賽果同步、完整覆盤、預測重建。"""
from __future__ import annotations

import logging
from typing import Literal

import pandas as pd
from sportsbet.data.database import SportsDatabase
from sportsbet.data.api_sports import calendar_season
from sportsbet.data.provider import get_data_provider
from sportsbet.risk.ev import RiskManager
from sportsbet.services.prediction_service import PredictionService

logger = logging.getLogger(__name__)

Sport = Literal["nba", "mlb"]


def sync_historical_games(db: SportsDatabase, sport: Sport) -> int:
    """混合來源同步歷史賽程與賽果（nba_api / ESPN / API-Sports）。"""
    before = db.count_games_with_scores(sport)
    provider = get_data_provider(db)
    season = calendar_season(sport)
    provider.fetch_historical_stats(sport, season)
    finalized = db.finalize_games_with_scores(sport)
    after = db.count_games_with_scores(sport)
    logger.info(
        "歷史賽果同步 sport=%s season=%s games_with_scores=%d finalized=%d",
        sport, season, after, finalized,
    )
    return after


def rebuild_predictions_from_forecasts(db: SportsDatabase, sport: Sport) -> int:
    """依 game_forecasts 的傷兵修正勝率重建 predictions（供模型健康度/資金回測）。"""
    with db.connection() as conn:
        rows = conn.execute(
            """
            SELECT g.id AS game_id, g.match_date, f.home_win_prob, f.away_win_prob,
                   f.prob_over, o.market, o.selection, o.odds, o.handicap
            FROM games g
            JOIN game_forecasts f ON f.game_id = g.id
            JOIN odds o ON o.game_id = g.id
            WHERE g.sport = ?
              AND g.status = 'final'
              AND g.home_score IS NOT NULL
            """,
            (sport,),
        ).fetchall()

    if not rows:
        return 0

    risk = RiskManager()
    n = 0
    with db.connection() as conn:
        conn.execute(
            "DELETE FROM predictions WHERE game_id IN (SELECT id FROM games WHERE sport = ?)",
            (sport,),
        )
        for row in rows:
            market = row["market"]
            sel = row["selection"]
            if market == "moneyline":
                prob = float(row["home_win_prob"]) if sel == "home" else float(row["away_win_prob"])
            elif market == "total" and row["prob_over"] is not None:
                prob_o = float(row["prob_over"])
                prob = prob_o if sel == "over" else 1.0 - prob_o
            else:
                continue
            sig = risk.evaluate(prob, float(row["odds"]))
            conn.execute(
                """
                INSERT INTO predictions (game_id, market, selection, model_prob, ev, kelly_fraction, stake_fraction)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["game_id"], market, sel, prob,
                    sig.ev, sig.kelly_fraction, sig.recommended_stake_fraction,
                ),
            )
            n += 1
    return n


def run_full_backtest_refresh(
    db: SportsDatabase | None = None,
    sport: Sport = "nba",
    *,
    sync_api: bool = True,
    sync_injuries: bool = True,
    days_lineup: int = 7,
) -> dict[str, int]:
    """
    完整覆盤刷新：
    1. 同步 API 歷史賽果（若有金鑰）
    2. 同步 ESPN 傷兵 + 預計先發（供未來/今日預測）
    3. 重算所有已結束賽事 forecast
    4. 重建 predictions
    """
    db = db or SportsDatabase()
    svc = PredictionService(db)
    out: dict[str, int] = {}

    if sync_api:
        out["games_with_scores"] = sync_historical_games(db, sport)
    else:
        out["games_with_scores"] = db.count_games_with_scores(sport)

    db.finalize_games_with_scores(sport)

    if sync_injuries:
        from sportsbet.data.player_ingestion import sync_v2_player_data

        v2 = sync_v2_player_data(db, sport, days_lineup=days_lineup)
        out.update(v2)

    review = svc.run_backtest_reconcile(sport)
    out["forecasts"] = len(review)

    if review.empty and db.count_games_with_scores(sport) == 0:
        raise RuntimeError(
            "無法建立覆盤：尚無已結束賽事。請按側欄「同步資料」或確認網路與資料來源。"
        )

    out["predictions"] = rebuild_predictions_from_forecasts(db, sport)
    svc.run_upcoming(sport, days_ahead=days_lineup)
    return out
