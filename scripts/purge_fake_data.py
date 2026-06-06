"""清除 DB 中的假資料／污染資料／合成賠率。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sportsbet.data.database import SportsDatabase

# 誤植為 sport=nba 的 MLB 玩運彩列（投手名 + 中文隊名格式）
NBA_MLB_POLLUTION_SQL = """
    sport = 'nba'
    AND (
        home_team LIKE '%Lambert%'
        OR home_team LIKE '%Rocker%'
        OR home_team LIKE '%Valdez%'
        OR home_team LIKE '%Messick%'
        OR home_team LIKE '%Woo%'
        OR home_team LIKE '%Peter%'
        OR away_team LIKE '%Lambert%'
        OR away_team LIKE '%Rocker%'
    )
"""


def purge_fake_data(db: SportsDatabase | None = None) -> dict[str, int]:
    db = db or SportsDatabase()
    out: dict[str, int] = {}

    with db.connection() as conn:
        polluted = conn.execute(
            f"SELECT id FROM games WHERE {NBA_MLB_POLLUTION_SQL}"
        ).fetchall()
        ids = [int(r["id"]) for r in polluted]
        out["polluted_nba_games"] = len(ids)

        if ids:
            ph = ",".join("?" for _ in ids)
            for table, col in (
                ("predictions", "game_id"),
                ("odds", "game_id"),
                ("game_forecasts", "game_id"),
            ):
                conn.execute(f"DELETE FROM {table} WHERE {col} IN ({ph})", ids)
            conn.execute(f"DELETE FROM games WHERE id IN ({ph})", ids)

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
