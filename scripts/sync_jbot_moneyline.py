"""同步 JBot 真實 moneyline（及 spread/total）至 SQLite 並重建 predictions。

用法:
  python scripts/setup_jbot_token.py YOUR_TOKEN   # 首次設定
  python scripts/sync_jbot_moneyline.py --sport nba --days 14
  python scripts/sync_jbot_moneyline.py --sport all --days 14 --rebuild
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sportsbet import config
from sportsbet.data.database import SportsDatabase
from sportsbet.data.jbot_odds_sync import sync_jbot_odds_to_db
from sportsbet.services.data_refresh import rebuild_moneyline_predictions


def main() -> None:
    p = argparse.ArgumentParser(description="JBot moneyline 同步")
    p.add_argument("--sport", default="all", choices=["nba", "mlb", "all"])
    p.add_argument("--days", type=int, default=14, help="回溯天數（受 JBOT_MAX_DAYS_PER_RUN 限制）")
    p.add_argument("--mode", default="close", choices=["open", "close", "both", "all"])
    p.add_argument("--rebuild", action="store_true", help="同步後重建 moneyline predictions")
    args = p.parse_args()

    if not config.jbot_configured():
        print("未設定 JBOT_TOKEN。請先執行:")
        print("  python scripts/setup_jbot_token.py YOUR_TOKEN")
        sys.exit(1)

    end_d = date.today() - timedelta(days=1)
    start_d = end_d - timedelta(days=max(1, args.days) - 1)
    sports = ["nba", "mlb"] if args.sport == "all" else [args.sport]
    db = SportsDatabase()

    for sp in sports:
        n = sync_jbot_odds_to_db(
            db,
            sp,
            start=start_d.isoformat(),
            end=end_d.isoformat(),
            mode=args.mode,
            incremental=False,
        )
        print(f"{sp}: jbot rows={n}")
        if args.rebuild and n > 0:
            pred_n = rebuild_moneyline_predictions(db, sp)
            print(f"{sp}: moneyline predictions={pred_n}")


if __name__ == "__main__":
    main()
