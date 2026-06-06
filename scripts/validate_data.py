"""資料真實性與跨運動污染驗證。"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sportsbet.data.team_names import NBA_TEAMS, MLB_TEAMS, is_cross_sport_game, team_belongs_to_sport

DB = ROOT / "data" / "sportsbet.db"


def main() -> int:
    c = sqlite3.connect(DB)
    issues: list[str] = []

    for sport, known in [("nba", NBA_TEAMS), ("mlb", MLB_TEAMS)]:
        rows = c.execute(
            "SELECT id, home_team, away_team, match_date FROM games WHERE sport=?",
            (sport,),
        ).fetchall()
        cross = [
            r for r in rows
            if is_cross_sport_game(sport, r[1], r[2])
            or not team_belongs_to_sport(r[1], sport)
            or not team_belongs_to_sport(r[2], sport)
        ]
        if cross:
            issues.append(f"{sport}: {len(cross)} polluted games (sample id={cross[0][0]})")

        # forecasts sport mismatch
        bad_f = c.execute(
            """
            SELECT f.id, g.sport, f.sport, g.home_team
            FROM game_forecasts f
            JOIN games g ON g.id = f.game_id
            WHERE f.sport = ? AND (g.sport != f.sport OR g.sport != ?)
            """,
            (sport, sport),
        ).fetchall()
        if bad_f:
            issues.append(f"{sport}: {len(bad_f)} forecast/game sport mismatch")

        # total_line sanity
        if sport == "mlb":
            high = c.execute(
                """
                SELECT COUNT(*) FROM game_forecasts f
                JOIN games g ON g.id=f.game_id
                WHERE f.sport='mlb' AND f.total_line > 20
                """
            ).fetchone()[0]
            if high:
                issues.append(f"mlb: {high} forecasts with NBA-like total_line (>20)")
        if sport == "nba":
            low = c.execute(
                """
                SELECT COUNT(*) FROM game_forecasts f
                WHERE f.sport='nba' AND f.total_line IS NOT NULL AND f.total_line < 150
                """
            ).fetchone()[0]
            if low:
                issues.append(f"nba: {low} forecasts with MLB-like total_line (<150)")

        # odds totals
        tot = c.execute(
            """
            SELECT COUNT(*) FROM odds o
            JOIN games g ON g.id=o.game_id
            WHERE g.sport=? AND o.market='total'
            """,
            (sport,),
        ).fetchone()[0]
        ps_tot = c.execute(
            """
            SELECT COUNT(*) FROM odds o
            JOIN games g ON g.id=o.game_id
            WHERE g.sport=? AND o.market='total' AND o.bookmaker='playsport'
            """,
            (sport,),
        ).fetchone()[0]
        bad_fc = c.execute(
            """
            SELECT COUNT(*) FROM game_forecasts
            WHERE sport=? AND (
                home_team LIKE '%(%' OR away_team LIKE '%(%'
                OR home_team GLOB '*[A-Z][a-z]*[A-Z]*'
            )
            """,
            (sport,),
        ).fetchone()[0]
        # invalid forecast team names
        fc_rows = c.execute(
            "SELECT id, home_team, away_team FROM game_forecasts WHERE sport=?",
            (sport,),
        ).fetchall()
        invalid_fc = [
            r for r in fc_rows
            if not team_belongs_to_sport(r[1], sport) or not team_belongs_to_sport(r[2], sport)
        ]
        if invalid_fc:
            issues.append(f"{sport}: {len(invalid_fc)} forecasts with invalid team names")

        pred_n = c.execute(
            """
            SELECT COUNT(*) FROM predictions p
            JOIN games g ON g.id = p.game_id WHERE g.sport=?
            """,
            (sport,),
        ).fetchone()[0]

        games_final = c.execute(
            "SELECT COUNT(*) FROM games WHERE sport=? AND status='final'",
            (sport,),
        ).fetchone()[0]
        print(
            f"{sport}: games={len(rows)} polluted={len(cross)} "
            f"total_odds={tot} playsport_total={ps_tot} "
            f"invalid_fc={len(invalid_fc)} predictions={pred_n} final={games_final}"
        )

    # sample nba review teams
    sample = c.execute(
        """
        SELECT g.home_team, g.away_team, f.total_line, f.predicted_total
        FROM game_forecasts f JOIN games g ON g.id=f.game_id
        WHERE f.sport='nba' ORDER BY g.match_date DESC LIMIT 5
        """
    ).fetchall()
    print("nba review sample:", sample)

    sample_mlb = c.execute(
        """
        SELECT g.home_team, g.away_team, f.total_line, f.predicted_total
        FROM game_forecasts f JOIN games g ON g.id=f.game_id
        WHERE f.sport='mlb' ORDER BY g.match_date DESC LIMIT 5
        """
    ).fetchall()
    print("mlb review sample:", sample_mlb)

    if issues:
        print("\nISSUES:")
        for i in issues:
            print(" -", i)
        return 1
    print("\nOK: no issues detected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
