"""將 MOCK 資料寫入 SQLite，供看板與回測使用。"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sportsbet import config  # noqa: E402
from sportsbet.data.database import SportsDatabase  # noqa: E402
from sportsbet.data.ingestion import MockDataProvider  # noqa: E402
from sportsbet.data.player_ingestion import sync_v2_player_data  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="寫入 MOCK 資料到 SQLite")
    parser.add_argument("--sport", choices=["nba", "mlb"], default="nba")
    parser.add_argument("--days", type=int, default=None, help="歷史回測天數（預設 3 年）")
    parser.add_argument("--no-history", action="store_true")
    args = parser.parse_args()

    db = SportsDatabase()
    provider = MockDataProvider(db)
    provider.fetch_historical_stats(args.sport)
    provider.fetch_daily_schedule(args.sport)
    provider.fetch_odds(args.sport)
    sync_v2_player_data(db, args.sport)
    days = args.days if args.days is not None else config.BACKTEST_DAYS
    if not args.no_history:
        print(f"產生 {days} 天歷史回測資料（約 {config.BACKTEST_YEARS} 年）…")
        df = provider.seed_historical_backtest(args.sport, days=days)
        print(f"歷史回測列數: {len(df)}")
    print(f"資料庫: {db.db_path}")


if __name__ == "__main__":
    main()
