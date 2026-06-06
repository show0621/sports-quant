"""修復污染資料、還原玩運彩盤口、重建 predictions 並驗證。"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sportsbet import config
from sportsbet.data.database import SportsDatabase
from sportsbet.data.moneyline_backfill import backfill_playsport_moneyline
from sportsbet.data.playsport_scraper import PlaySportScraper
from sportsbet.services.data_refresh import rebuild_predictions_from_forecasts
from sportsbet.services.prediction_service import PredictionService

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def repair_sport(db: SportsDatabase, sport: str, *, sync_playsport: bool) -> dict[str, int]:
    out: dict[str, int] = {}

    if sync_playsport and config.PLAYSPORT_ENABLED:
        scraper = PlaySportScraper()
        df = scraper.sync_sport(db, sport, max_teams=config.PLAYSPORT_MAX_TEAMS_PER_SYNC)  # type: ignore[arg-type]
        out["playsport_rows"] = len(df)
        out["playsport_moneyline"] = backfill_playsport_moneyline(db, sport)  # type: ignore[arg-type]

    out["purged_games"] = db.purge_invalid_team_games(sport)  # type: ignore[arg-type]
    out["purged_cross"] = db.purge_cross_sport_games(sport)  # type: ignore[arg-type]
    out["purged_forecasts"] = db.purge_invalid_forecasts(sport)  # type: ignore[arg-type]

    svc = PredictionService(db)
    missing = db.get_scored_games_missing_forecast(sport)  # type: ignore[arg-type]
    if len(missing) > 0:
        review = svc.run_backtest_reconcile(sport, only_missing=True)  # type: ignore[arg-type]
        out["forecasts_new"] = len(review)
    # 更新已有 forecast 的大小盤口線（有 odds 時）
    with db.connection() as conn:
        rows = conn.execute(
            """
            SELECT g.id FROM games g
            JOIN game_forecasts f ON f.game_id = g.id
            JOIN odds o ON o.game_id = g.id AND o.market = 'total'
            WHERE g.sport = ?
            GROUP BY g.id
            """,
            (sport,),
        ).fetchall()
    out["forecasts_with_total_odds"] = len(rows)

    from scripts.refresh_forecast_totals import refresh_forecast_totals

    out["forecasts_total_refreshed"] = refresh_forecast_totals(db, sport)

    out["predictions"] = rebuild_predictions_from_forecasts(
        db, sport, replace_all=True,  # type: ignore[arg-type]
    )
    return out


def main() -> int:
    p = argparse.ArgumentParser(description="修復跨運動污染並還原盤口")
    p.add_argument("--sport", choices=["nba", "mlb", "all"], default="all")
    p.add_argument("--skip-playsport", action="store_true")
    args = p.parse_args()

    db = SportsDatabase()
    sports = ["nba", "mlb"] if args.sport == "all" else [args.sport]
    for sp in sports:
        logger.info("=== repair %s ===", sp)
        stats = repair_sport(db, sp, sync_playsport=not args.skip_playsport)
        logger.info("%s: %s", sp, stats)

    from scripts.validate_data import main as validate

    logger.info("=== validate ===")
    return validate()


if __name__ == "__main__":
    raise SystemExit(main())
