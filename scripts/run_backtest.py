"""執行回測（SQLite 真實資料）。用法: python scripts/run_backtest.py --sport nba"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sportsbet.backtest.engine import BacktestEngine
from sportsbet.data.database import SportsDatabase
from sportsbet.services.data_refresh import run_incremental_backtest_refresh


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--sport", choices=["nba", "mlb"], default="nba")
    args = p.parse_args()

    db = SportsDatabase()
    run_incremental_backtest_refresh(db, args.sport, sync_api=True, sync_injuries=True)
    df = db.get_backtest_frame(args.sport)
    if df.empty:
        print("無回測資料，請先執行 python main.py sync daily --sport", args.sport)
        sys.exit(1)

    result = BacktestEngine().run(df)
    print(result.summary)
    print(result.accuracy)


if __name__ == "__main__":
    main()
