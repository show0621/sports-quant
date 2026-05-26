"""執行回測。用法: python scripts/run_backtest.py --sport nba"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np

from sportsbet.backtest.engine import BacktestEngine
from sportsbet.data.storage import load_team_stats
from sportsbet.data.wanda_scraper import WandaScraper
from sportsbet.models.game_predictor import GamePredictor


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--sport", default="nba")
    args = p.parse_args()

    team_stats = load_team_stats(args.sport)
    if team_stats.empty:
        print("請先抓取 API 資料")
        sys.exit(1)

    odds = WandaScraper().load_sample_format()
    predictor = GamePredictor(args.sport)  # type: ignore[arg-type]
    signals = predictor.scan_dataframe(team_stats, odds)
    rng = np.random.default_rng(0)
    signals["won"] = (rng.random(len(signals)) < signals["model_prob"]).astype(int)
    signals["match_date"] = "2025-01-01"

    result = BacktestEngine().run(signals)
    print(result.summary)
    print(result.accuracy)


if __name__ == "__main__":
    main()
