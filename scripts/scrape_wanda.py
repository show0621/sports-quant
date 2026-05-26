"""抓取威剛賠率。用法: python scripts/scrape_wanda.py --sample"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sportsbet.data.wanda_scraper import WandaScraper
from sportsbet.data.storage import save_odds


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--sport", default="nba")
    p.add_argument("--path", default="")
    p.add_argument("--sample", action="store_true")
    args = p.parse_args()
    scraper = WandaScraper()
    if args.sample:
        df = scraper.load_sample_format()
        save_odds(df)
    else:
        df = scraper.scrape_and_save(args.path, args.sport)
    print(f"完成 {len(df)} 筆")


if __name__ == "__main__":
    main()
