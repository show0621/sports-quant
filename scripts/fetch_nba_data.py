"""抓取 NBA 賽季資料。用法: python scripts/fetch_nba_data.py --season 2024"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sportsbet.data.api_sports import ApiSportsClient


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--season", type=int, default=2024)
    args = p.parse_args()
    client = ApiSportsClient()
    df = client.sync_season("nba", args.season)
    print(f"完成，共 {len(df)} 隊")


if __name__ == "__main__":
    main()
