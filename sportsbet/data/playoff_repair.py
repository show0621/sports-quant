"""修補季後賽 metadata（同對手未來場次 season_type）。"""
from __future__ import annotations

from sportsbet.data.database import SportsDatabase


def repair_playoff_season_types(db: SportsDatabase, sport: str = "nba") -> int:
    """將已有季後賽標記場次之同對手未來賽程補上 season_type。"""
    with db.connection() as conn:
        rows = conn.execute(
            """
            SELECT id, home_team, away_team, match_date, season_type, competition_note
            FROM games
            WHERE sport = ?
              AND status = 'scheduled'
              AND (season_type IS NULL OR season_type = '')
              AND match_date >= date('now', '-1 day')
            """,
            (sport,),
        ).fetchall()
        n = 0
        for row in rows:
            ht, at = row["home_team"], row["away_team"]
            ref = conn.execute(
                """
                SELECT season_type, competition_note
                FROM games
                WHERE sport = ?
                  AND status IN ('final', 'scheduled', 'in_progress')
                  AND season_type IS NOT NULL AND season_type != ''
                  AND (
                        (home_team = ? AND away_team = ?)
                     OR (home_team = ? AND away_team = ?)
                  )
                ORDER BY match_date DESC
                LIMIT 1
                """,
                (sport, ht, at, at, ht),
            ).fetchone()
            if not ref:
                continue
            conn.execute(
                """
                UPDATE games
                SET season_type = ?, competition_note = COALESCE(competition_note, ?)
                WHERE id = ?
                """,
                (ref["season_type"], ref["competition_note"], row["id"]),
            )
            n += 1
    return n
