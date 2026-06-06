"""抓取運彩賠率（Blob / JBot）。用法: python scripts/scrape_wanda.py --sport nba"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sportsbet.data.wanda_scraper import WandaScraper
from sportsbet.data.storage import save_odds


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--sport", default="nba", choices=["nba", "mlb"])
    p.add_argument("--jbot", action="store_true", help="一併抓取 JBot 歷史")
    p.add_argument("--days-back", type=int, default=7)
    args = p.parse_args()
    scraper = WandaScraper()
    df = scraper.scrape_and_save(
        args.sport,  # type: ignore[arg-type]
        use_jbot=args.jbot,
        days_back=args.days_back,
    )
    save_odds(df)
    print(f"完成 {len(df)} 筆")


if __name__ == "__main__":
    main()
