"""清除 DB 中的假資料／污染資料／合成賠率。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sportsbet.data.database import SportsDatabase


def purge_fake_data(db: SportsDatabase | None = None) -> dict[str, int]:
    db = db or SportsDatabase()
    out: dict[str, int] = {}

    out["cross_sport_games"] = db.purge_cross_sport_games()
    out["prob_clipped"] = db.clip_prediction_probabilities()

    with db.connection() as conn:
        cur = conn.execute("DELETE FROM odds WHERE bookmaker = 'tw_standard'")
        out["tw_standard_odds_removed"] = cur.rowcount

        cur = conn.execute(
            """
            DELETE FROM predictions
            WHERE market = 'moneyline'
              AND game_id NOT IN (
                  SELECT DISTINCT game_id FROM odds WHERE market = 'moneyline'
              )
            """
        )
        out["synthetic_moneyline_predictions_removed"] = cur.rowcount

    out["placeholders_cleaned"] = db.cleanup_placeholder_final_games("nba")
    out["placeholders_cleaned"] += db.cleanup_placeholder_final_games("mlb")

    return out


if __name__ == "__main__":
    stats = purge_fake_data()
    print("purge_fake_data:", stats)
