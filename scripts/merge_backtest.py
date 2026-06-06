"""合併賠率與賽果、執行回測（僅真實資料）。"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sportsbet.backtest.engine import BacktestEngine
from sportsbet.data.storage import load_odds_history, save_timeline
from sportsbet.data.timeline import build_backtest_dataset, merge_timeline
from sportsbet.data.wanda_scraper import WandaScraper

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def _load_odds(args: argparse.Namespace) -> "pd.DataFrame":
    import pandas as pd

    scraper = WandaScraper()
    frames: list[pd.DataFrame] = []

    if args.live:
        df = scraper.fetch_current(args.sport)
        if not df.empty:
            frames.append(df)

    if args.jbot:
        if not args.start:
            end = date.today()
            start = end - timedelta(days=args.days_back)
        else:
            start = date.fromisoformat(args.start)
            end = date.fromisoformat(args.end) if args.end else date.today()
        hist = scraper.fetch_historical_range(
            args.sport,
            start,
            end,
            args.jbot_mode,  # type: ignore[arg-type]
        )
        if not hist.empty:
            frames.append(hist)

    if not frames:
        hist_odds = load_odds_history()
        if not hist_odds.empty:
            sport_odds = hist_odds[hist_odds["sport"] == args.sport]
            if not sport_odds.empty:
                return sport_odds
        raise RuntimeError(
            "無賠率資料。請加上 --live（運彩 Blob）或 --jbot（需 JBOT_TOKEN）。"
        )

    return pd.concat(frames, ignore_index=True)


def main() -> None:
    p = argparse.ArgumentParser(description="合併 timeline 並執行回測（真實賠率）")
    p.add_argument("--sport", choices=["nba", "mlb"], default="nba")
    p.add_argument("--live", action="store_true", help="抓取運彩 Blob 即時/受注")
    p.add_argument("--jbot", action="store_true", help="抓取 JBot 歷史賠率")
    p.add_argument("--start", help="JBot 起始日期 YYYY-MM-DD")
    p.add_argument("--end", help="JBot 結束日期 YYYY-MM-DD")
    p.add_argument("--days-back", type=int, default=30, help="未指定 start 時往回天數")
    p.add_argument(
        "--jbot-mode",
        default="close",
        choices=["open", "close", "both", "all"],
        help="JBot 賠率模式",
    )
    p.add_argument("--market", default="moneyline", help="回測盤口篩選")
    p.add_argument("--odds-phase", default="close", help="開收盤階段篩選")
    p.add_argument("--min-parlay", type=int, default=1)
    p.add_argument("--save", action="store_true", help="儲存 timeline")
    p.add_argument("--no-backtest", action="store_true", help="僅合併不跑回測")
    args = p.parse_args()

    if not args.live and not args.jbot:
        args.live = True

    odds = _load_odds(args)
    merged = merge_timeline(odds, args.sport)  # type: ignore[arg-type]

    if args.save and not merged.empty:
        path = save_timeline(merged, args.sport, tag="merged")
        logger.info("已儲存 timeline: %s", path)

    dataset = build_backtest_dataset(
        args.sport,  # type: ignore[arg-type]
        merged,
        market=args.market if args.market != "all" else None,
        odds_phase=args.odds_phase if args.odds_phase != "all" else None,
        min_parlay=args.min_parlay,
    )

    print(f"合併列數: {len(merged)} | 回測可用: {len(dataset)}")
    if dataset.empty:
        print("回測資料為空：請先 python main.py sync daily，並確認賠率日期與隊名可對齊")
        sys.exit(1)

    if args.no_backtest:
        print(dataset.head(10).to_string(index=False))
        return

    result = BacktestEngine().run(dataset)
    print("=== 回測摘要 ===")
    for k, v in result.summary.items():
        print(f"  {k}: {v}")
    if result.accuracy:
        print("=== 準確率 ===")
        for k, v in result.accuracy.items():
            print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
