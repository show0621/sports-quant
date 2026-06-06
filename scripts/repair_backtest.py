"""一次性修復並重建回測。"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sportsbet.data.database import SportsDatabase
from sportsbet.evaluation.ev_report import build_ev_backtest_report
from sportsbet.services.data_refresh import prepare_backtest_odds, run_full_backtest_refresh


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--sport", choices=["nba", "mlb", "all"], default="nba")
    p.add_argument("--sync-api", action="store_true", help="重新抓 API 賽程（MLB 首次需開）")
    args = p.parse_args()

    sports = ["nba", "mlb"] if args.sport == "all" else [args.sport]
    db = SportsDatabase()

    for sport in sports:
        print(f"\n=== {sport.upper()} ===")
        prep = prepare_backtest_odds(db, sport, incremental=False)
        print("prepare:", prep)

        sync_api = args.sync_api or (sport == "mlb" and db.count_games_with_scores(sport) == 0)
        if sync_api and sport == "mlb" and db.count_games_with_scores(sport) == 0:
            from sportsbet.data.espn_schedule import EspnScheduleClient

            EspnScheduleClient().backfill_dates(db, "mlb", days_back=120, only_missing=False)

        out = run_full_backtest_refresh(
            db, sport, sync_api=sync_api, sync_injuries=False,
        )
        print("refresh:", out)

        with db.connection() as conn:
            fc = conn.execute(
                "SELECT COUNT(*) FROM game_forecasts f JOIN games g ON g.id=f.game_id WHERE g.sport=?",
                (sport,),
            ).fetchone()[0]
            pr = conn.execute(
                "SELECT COUNT(*) FROM predictions p JOIN games g ON g.id=p.game_id WHERE g.sport=?",
                (sport,),
            ).fetchone()[0]
            ml = conn.execute(
                """
                SELECT COUNT(*) FROM odds o JOIN games g ON g.id=o.game_id
                WHERE g.sport=? AND o.market='moneyline'
                """,
                (sport,),
            ).fetchone()[0]
        print(f"forecasts={fc} predictions={pr} moneyline_odds={ml}")

        df = db.get_backtest_frame(sport)
        if not df.empty and "market" in df.columns:
            df = df[df["market"] == "moneyline"]
        if not df.empty:
            rep = build_ev_backtest_report(df)
            print(rep.summary_text)


if __name__ == "__main__":
    main()
