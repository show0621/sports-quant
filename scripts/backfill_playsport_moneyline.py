"""從既有玩運彩讓分/大小盤口，補 moneyline 並重建 predictions。"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sportsbet.data.database import SportsDatabase
from sportsbet.data.moneyline_backfill import backfill_playsport_moneyline
from sportsbet.services.data_refresh import rebuild_moneyline_predictions


def main() -> None:
    p = argparse.ArgumentParser(description="玩運彩 moneyline 補值")
    p.add_argument("--sport", default="all", choices=["nba", "mlb", "all"])
    p.add_argument("--rebuild", action="store_true", help="重建 moneyline predictions")
    args = p.parse_args()

    db = SportsDatabase()
    sports = ["nba", "mlb"] if args.sport == "all" else [args.sport]
    for sp in sports:
        n = backfill_playsport_moneyline(db, sp)
        print(f"{sp}: moneyline odds rows={n}")
        if args.rebuild and n > 0:
            pn = rebuild_moneyline_predictions(db, sp)
            print(f"{sp}: predictions={pn}")


if __name__ == "__main__":
    main()
