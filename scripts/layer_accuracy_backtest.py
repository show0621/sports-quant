"""各管線層級勝負／讓分準確率回測。

用法:
  python scripts/layer_accuracy_backtest.py
  python scripts/layer_accuracy_backtest.py --sport nba
  python scripts/layer_accuracy_backtest.py --sport mlb --csv out.csv
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sportsbet.data.database import SportsDatabase
from sportsbet.evaluation.layer_backtest import format_layer_report, run_layer_backtest


def main() -> None:
    p = argparse.ArgumentParser(description="管線各層勝負／讓分準確率回測")
    p.add_argument("--sport", choices=["nba", "mlb", "both"], default="both")
    p.add_argument("--csv", type=str, default="", help="輸出 summary CSV 路徑（可選）")
    args = p.parse_args()

    db = SportsDatabase()
    sports = ["nba", "mlb"] if args.sport == "both" else [args.sport]
    all_summary = []

    for sport in sports:
        result = run_layer_backtest(db, sport)  # type: ignore[arg-type]
        print(format_layer_report(result))
        print()
        if not result.summary.empty:
            s = result.summary.copy()
            s["sport"] = sport
            all_summary.append(s)

    if args.csv and all_summary:
        out = Path(args.csv)
        pd = __import__("pandas")
        pd.concat(all_summary, ignore_index=True).to_csv(out, index=False, encoding="utf-8-sig")
        print(f"已寫入 {out}")


if __name__ == "__main__":
    main()
