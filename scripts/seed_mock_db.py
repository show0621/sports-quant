"""將 MOCK 資料寫入 SQLite，供看板與回測使用。"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sportsbet.data.database import SportsDatabase  # noqa: E402
from sportsbet.data.ingestion import MockDataProvider  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="寫入 MOCK 資料到 SQLite")
    parser.add_argument("--sport", choices=["nba", "mlb"], default="nba")
    parser.add_argument("--days", type=int, default=60, help="歷史回測天數")
    parser.add_argument("--no-history", action="store_true")
    args = parser.parse_args()

    db = SportsDatabase()
    provider = MockDataProvider(db)
    provider.fetch_historical_stats(args.sport)
    provider.fetch_daily_schedule(args.sport)
    provider.fetch_odds(args.sport)
    if not args.no_history:
        df = provider.seed_historical_backtest(args.sport, days=args.days)
        print(f"歷史回測列數: {len(df)}")
    print(f"資料庫: {db.db_path}")


if __name__ == "__main__":
    main()
