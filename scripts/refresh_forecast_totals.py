"""快速更新已有 forecast 的大小盤口線（從 odds 表）。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sportsbet.data.database import SportsDatabase
from sportsbet.services.prediction_service import PredictionService


def refresh_forecast_totals(db: SportsDatabase, sport: str) -> int:
    svc = PredictionService(db)
    stats = db.get_team_stats(sport).set_index("team")  # type: ignore[arg-type]
    with db.connection() as conn:
        rows = conn.execute(
            """
            SELECT g.* FROM games g
            JOIN odds o ON o.game_id = g.id AND o.market = 'total'
            JOIN game_forecasts f ON f.game_id = g.id
            WHERE g.sport = ?
            GROUP BY g.id
            """,
            (sport,),
        ).fetchall()
    n = 0
    import pandas as pd

    for r in rows:
        g = pd.Series(dict(r))
        line = db.get_market_line(int(g["id"]), "total")
        if line is None:
            continue
        if g["home_team"] not in stats.index or g["away_team"] not in stats.index:
            continue
        fc = svc.forecast_game_row(sport, g, stats, total_line=line, use_roster=False)  # type: ignore[arg-type]
        if fc:
            db.upsert_game_forecast(fc)
            n += 1
    return n


if __name__ == "__main__":
    db = SportsDatabase()
    for sp in ("nba", "mlb"):
        print(sp, refresh_forecast_totals(db, sp))
