"""資料刷新：歷史賽果同步、完整覆盤、預測重建。"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Literal

import pandas as pd
from sportsbet import config
from sportsbet.data.database import SportsDatabase
from sportsbet.data.api_sports import calendar_season
from sportsbet.data.provider import get_data_provider
from sportsbet.risk.ev import RiskManager
from sportsbet.services.prediction_service import PredictionService

logger = logging.getLogger(__name__)

Sport = Literal["nba", "mlb"]


def _should_fetch_blob_odds(match_date: str) -> bool:
    """歷史回測不全量抓 Blob（404/慢）；近 N 天才抓即時盤。"""
    try:
        d = date.fromisoformat(str(match_date)[:10])
    except ValueError:
        return False
    return (date.today() - d).days <= config.HISTORICAL_BLOB_ODDS_DAYS


def prepare_backtest_odds(
    db: SportsDatabase,
    sport: Sport,
    *,
    incremental: bool = True,
) -> dict[str, int]:
    """清理占位賽事、同步 JBot、補 moneyline。"""
    out: dict[str, int] = {}
    out["cleaned_placeholders"] = db.cleanup_placeholder_final_games(sport)
    db.finalize_games_with_scores(sport)

    from sportsbet.data.jbot_odds_sync import sync_jbot_odds_to_db
    from sportsbet.data.moneyline_backfill import (
        backfill_playsport_moneyline,
        backfill_tw_moneyline_odds,
    )

    out["jbot_odds"] = sync_jbot_odds_to_db(db, sport, incremental=incremental)

    from sportsbet.data.tw_odds_sync import sync_tw_odds_recent

    tw = sync_tw_odds_recent(db, sport)
    out["tw_odds_sportslottery"] = tw.get("sportslottery_rows", 0)
    out["tw_odds_playsport"] = tw.get("playsport_fallback", 0)

    if out["jbot_odds"] > 0:
        out["moneyline_predictions"] = rebuild_moneyline_predictions(db, sport)
    elif config.PLAYSPORT_MONEYLINE_ENABLED:
        out["playsport_moneyline"] = backfill_playsport_moneyline(db, sport)
        if out["playsport_moneyline"] > 0:
            out["moneyline_predictions"] = rebuild_moneyline_predictions(db, sport)
        out["market_predictions"] = rebuild_predictions_from_forecasts(db, sport)
    else:
        out["moneyline_backfill"] = backfill_tw_moneyline_odds(db, sport)
    if "market_predictions" not in out and out.get("tw_odds_sportslottery", 0) > 0:
        out["market_predictions"] = rebuild_predictions_from_forecasts(db, sport)
    with db.connection() as conn:
        conn.execute(
            """
            DELETE FROM predictions
            WHERE model_line = 'v2'
              AND game_id IN (SELECT id FROM games WHERE sport = ?)
            """,
            (sport,),
        )
    return out


def rebuild_moneyline_predictions(db: SportsDatabase, sport: Sport) -> int:
    """JBot 寫入 moneyline 後，重建對應 predictions。"""
    with db.connection() as conn:
        conn.execute(
            """
            DELETE FROM predictions
            WHERE market = 'moneyline'
              AND game_id IN (SELECT id FROM games WHERE sport = ?)
            """,
            (sport,),
        )
    with db.connection() as conn:
        game_ids = [
            int(r["game_id"])
            for r in conn.execute(
                """
                SELECT DISTINCT o.game_id
                FROM odds o
                JOIN games g ON g.id = o.game_id
                WHERE g.sport = ?
                  AND o.market = 'moneyline'
                  AND g.status = 'final'
                """,
                (sport,),
            ).fetchall()
        ]
    if not game_ids:
        return 0
    return rebuild_predictions_from_forecasts(db, sport, game_ids=game_ids)


def sync_historical_games(
    db: SportsDatabase,
    sport: Sport,
    *,
    incremental: bool = False,
) -> int:
    """混合來源同步歷史賽程與賽果（nba_api / ESPN / API-Sports）。"""
    before = db.count_games_with_scores(sport)
    provider = get_data_provider(db)
    season = calendar_season(sport)

    if incremental and db.is_backtest_cache_warm(sport):
        dates = db.get_dates_needing_backtest_work(sport, days_back=config.BACKTEST_DAYS)
        logger.info(
            "增量歷史同步 sport=%s 待補 %d 天（lookback=%d）",
            sport, len(dates), config.BACKTEST_INCREMENTAL_LOOKBACK_DAYS,
        )
        for d in dates:
            provider.fetch_daily_schedule(sport, d)
            if db.count_odds_for_date(sport, d) == 0 and _should_fetch_blob_odds(d):
                provider.fetch_odds(sport, d)
        provider.fetch_historical_stats(sport, season, incremental=True)
    else:
        provider.fetch_historical_stats(sport, season, incremental=False)
        d = date.today() - timedelta(days=config.BACKTEST_DAYS)
        end = date.today()
        while d <= end:
            ds = d.isoformat()
            provider.fetch_daily_schedule(sport, ds)
            if db.count_odds_for_date(sport, ds) == 0 and _should_fetch_blob_odds(ds):
                provider.fetch_odds(sport, ds)
            db.mark_schedule_date_checked(sport, ds)
            d += timedelta(days=1)

    finalized = db.finalize_games_with_scores(sport)
    if finalized:
        from sportsbet.services.post_final_refresh import refresh_after_finals

        refresh_after_finals(db, sport, finalized)
    after = db.count_games_with_scores(sport)
    db.set_backtest_sync_meta(sport, "historical_synced_at", date.today().isoformat())
    logger.info(
        "歷史賽果同步 sport=%s season=%s games_with_scores=%d finalized=%d incremental=%s",
        sport, season, after, len(finalized), incremental,
    )
    return after


def rebuild_predictions_from_forecasts(
    db: SportsDatabase,
    sport: Sport,
    *,
    game_ids: list[int] | None = None,
    replace_all: bool = False,
) -> int:
    """依 game_forecasts 重建 predictions（含機率校準，供模型健康度/資金回測）。"""
    from sportsbet.models.calibration import (
        calibrate_spread_prob,
        calibrate_total_prob,
        calibrate_win_prob,
    )

    game_filter = ""
    params: list = [sport]
    if game_ids:
        placeholders = ",".join("?" for _ in game_ids)
        game_filter = f" AND g.id IN ({placeholders})"
        params.extend(game_ids)

    with db.connection() as conn:
        rows = conn.execute(
            f"""
            SELECT g.id AS game_id, g.sport, g.match_date,
                   f.home_win_prob, f.away_win_prob,
                   f.prob_over, f.predicted_total, f.total_line,
                   f.predicted_margin,
                   o.market, o.selection, o.odds, o.handicap
            FROM games g
            JOIN game_forecasts f ON f.game_id = g.id
            JOIN odds o ON o.game_id = g.id
            WHERE g.sport = ?
              AND g.status = 'final'
              AND g.home_score IS NOT NULL
              {game_filter}
            """,
            tuple(params),
        ).fetchall()

    if not rows:
        return 0

    risk = RiskManager()
    n = 0
    with db.connection() as conn:
        if replace_all and not game_ids:
            conn.execute(
                """
                DELETE FROM predictions
                WHERE COALESCE(model_line, 'v1') = 'v1'
                  AND game_id IN (SELECT id FROM games WHERE sport = ?)
                """,
                (sport,),
            )
        elif game_ids:
            placeholders = ",".join("?" for _ in game_ids)
            conn.execute(
                f"DELETE FROM predictions WHERE game_id IN ({placeholders})",
                game_ids,
            )

        for row in rows:
            market = row["market"]
            sel = row["selection"]
            row_sport = str(row["sport"])
            if market == "moneyline":
                prob = float(row["home_win_prob"]) if sel == "home" else float(row["away_win_prob"])
                prob = calibrate_win_prob(prob, row_sport)  # type: ignore[arg-type]
            elif market == "total" and row["prob_over"] is not None:
                line = row["handicap"]
                if line is None:
                    line = row["total_line"]
                pred_total = row["predicted_total"]
                if line is None or pred_total is None:
                    continue
                prob_o = calibrate_total_prob(
                    float(line),
                    float(pred_total),
                    row_sport,  # type: ignore[arg-type]
                    poisson_prob=float(row["prob_over"]),
                )
                prob = prob_o if sel == "over" else 1.0 - prob_o
            elif market == "spread":
                margin = row["predicted_margin"]
                line = row["handicap"]
                pred_total = row["predicted_total"]
                if margin is None or line is None:
                    continue
                from sportsbet.models.totals import prob_away_covers_spread, prob_home_covers_spread

                if sel == "home":
                    raw = prob_home_covers_spread(
                        float(line), float(margin), sport=row_sport,
                        pred_total=float(pred_total) if pred_total is not None else None,
                    )
                else:
                    raw = prob_away_covers_spread(
                        float(line), float(margin), sport=row_sport,
                        pred_total=float(pred_total) if pred_total is not None else None,
                    )
                prob = calibrate_spread_prob(raw, row_sport)  # type: ignore[arg-type]
            elif market == "margin":
                margin_val = row["predicted_margin"]
                pred_total = row["predicted_total"]
                if margin_val is None:
                    continue
                from sportsbet.models.margin_bands import prob_margin_selection

                prob_raw = prob_margin_selection(
                    sel,
                    float(margin_val),
                    sport=row_sport,
                    pred_total=float(pred_total) if pred_total is not None else None,
                )
                if prob_raw is None:
                    continue
                prob = float(prob_raw)
            else:
                continue
            prob = max(0.001, min(0.999, prob))
            sig = risk.evaluate(prob, float(row["odds"]))
            conn.execute(
                """
                INSERT INTO predictions (game_id, market, selection, model_prob, ev, kelly_fraction, stake_fraction, model_line)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'v1')
                """,
                (
                    row["game_id"], market, sel, prob,
                    sig.ev, sig.kelly_fraction, sig.recommended_stake_fraction,
                ),
            )
            n += 1
    return n


def run_incremental_backtest_refresh(
    db: SportsDatabase | None = None,
    sport: Sport = "nba",
    *,
    sync_api: bool = True,
    sync_injuries: bool = True,
    days_lineup: int = 7,
) -> dict[str, int]:
    """
    增量覆盤刷新（預設）：
    - 已寫入 DB 的歷史覆盤不重算
    - 只補今天以前缺漏的賽程/賠率/forecast/predictions
    - 最近 N 天會重查（比分可能晚到）
    """
    db = db or SportsDatabase()
    svc = PredictionService(db)
    out: dict[str, int] = {}
    incremental = db.is_backtest_cache_warm(sport)

    if sync_api:
        out["games_with_scores"] = sync_historical_games(
            db, sport, incremental=incremental,
        )
    else:
        out["games_with_scores"] = db.count_games_with_scores(sport)

    odds_prep = prepare_backtest_odds(db, sport, incremental=incremental)
    out.update(odds_prep)

    db.finalize_games_with_scores(sport)

    if sync_injuries:
        from sportsbet.data.player_ingestion import sync_v2_player_data

        v2 = sync_v2_player_data(db, sport, days_lineup=days_lineup)
        out.update(v2)

    missing_fc = db.get_scored_games_missing_forecast(sport)
    out["forecasts_missing_before"] = len(missing_fc)
    need_full = not incremental or len(missing_fc) > 500
    review = svc.run_backtest_reconcile(sport, only_missing=incremental and not need_full)
    out["forecasts"] = len(review)
    out["forecasts_reconciled"] = len(missing_fc) if incremental else len(review)

    if review.empty and db.count_games_with_scores(sport) == 0:
        raise RuntimeError(
            "無法建立覆盤：尚無已結束賽事。請按側欄「同步資料」或確認網路與資料來源。"
        )

    missing_pred = db.get_scored_games_missing_predictions(sport)
    out["predictions_missing_before"] = len(missing_pred)
    if incremental and not missing_pred.empty:
        game_ids = missing_pred["id"].astype(int).tolist()
        out["predictions"] = rebuild_predictions_from_forecasts(
            db, sport, game_ids=game_ids,
        )
    elif incremental:
        out["predictions"] = 0
    else:
        out["predictions"] = rebuild_predictions_from_forecasts(
            db, sport, replace_all=True,
        )

    svc.run_upcoming(sport, days_ahead=days_lineup)

    from sportsbet.services.sync_accumulation import accumulate_after_sync, ensure_ledger_start_date

    ensure_ledger_start_date(db)
    out.update(accumulate_after_sync(db, sport))

    db.set_backtest_sync_meta(sport, "backtest_refreshed_at", date.today().isoformat())
    return out


def run_full_backtest_refresh(
    db: SportsDatabase | None = None,
    sport: Sport = "nba",
    *,
    sync_api: bool = True,
    sync_injuries: bool = True,
    days_lineup: int = 7,
) -> dict[str, int]:
    """
    完整覆盤刷新（手動「重新產生全部覆盤」用）：
    1. 同步 API 歷史賽果（若有金鑰）
    2. 同步 ESPN 傷兵 + 預計先發（供未來/今日預測）
    3. 重算所有已結束賽事 forecast
    4. 重建 predictions
    """
    db = db or SportsDatabase()
    svc = PredictionService(db)
    out: dict[str, int] = {}

    if sync_api:
        out["games_with_scores"] = sync_historical_games(
            db, sport, incremental=False,
        )
    else:
        out["games_with_scores"] = db.count_games_with_scores(sport)

    odds_prep = prepare_backtest_odds(db, sport, incremental=False)
    out.update(odds_prep)

    db.finalize_games_with_scores(sport)

    if sync_injuries:
        from sportsbet.data.player_ingestion import sync_v2_player_data

        v2 = sync_v2_player_data(db, sport, days_lineup=days_lineup)
        out.update(v2)

    review = svc.run_backtest_reconcile(sport, only_missing=False)
    out["forecasts"] = len(review)

    if review.empty and db.count_games_with_scores(sport) == 0:
        raise RuntimeError(
            "無法建立覆盤：尚無已結束賽事。請按側欄「同步資料」或確認網路與資料來源。"
        )

    out["predictions"] = rebuild_predictions_from_forecasts(db, sport, replace_all=True)
    svc.run_upcoming(sport, days_ahead=days_lineup)

    from sportsbet.services.sync_accumulation import accumulate_after_sync, ensure_ledger_start_date

    ensure_ledger_start_date(db)
    out.update(accumulate_after_sync(db, sport))

    db.set_backtest_sync_meta(sport, "backtest_refreshed_at", date.today().isoformat())
    return out
