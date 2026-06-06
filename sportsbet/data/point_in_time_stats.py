"""賽前球隊統計（僅使用 as_of 日期之前的完賽，避免回測前視偏差）。"""
from __future__ import annotations

from typing import Literal

import pandas as pd

from sportsbet.data.database import SportsDatabase
from sportsbet.data.team_stats import build_team_stats_from_games

Sport = Literal["nba", "mlb"]

_VALID_FINAL_SQL = """
    status IN ('final', 'FT', 'AOT', 'Finished', 'POST')
    AND home_score IS NOT NULL
    AND away_score IS NOT NULL
    AND (home_score + away_score) > 0
    AND match_date <= date('now')
"""


class PointInTimeStatsBuilder:
    """依時間序累積賽果，對每場比賽提供開賽前 stats。"""

    def __init__(self, sport: Sport, games: pd.DataFrame):
        self.sport = sport
        self._games = games.sort_values(["match_date", "id"]).reset_index(drop=True)
        self._cursor = 0
        self._accum: pd.DataFrame = pd.DataFrame()

    @classmethod
    def from_db(cls, db: SportsDatabase, sport: Sport) -> PointInTimeStatsBuilder:
        with db.connection() as conn:
            games = pd.read_sql_query(
                f"""
                SELECT id, match_date, home_team, away_team, home_score, away_score, status
                FROM games
                WHERE sport = ? AND {_VALID_FINAL_SQL}
                ORDER BY match_date, id
                """,
                conn,
                params=(sport,),
            )
        return cls(sport, games)

    def snapshot_before(self, as_of_date: str) -> pd.DataFrame:
        """推進累積至 as_of_date 之前，回傳 team stats（含 rs/ra/win_pct）。"""
        as_of = str(as_of_date)[:10]
        while self._cursor < len(self._games):
            row = self._games.iloc[self._cursor]
            if str(row["match_date"])[:10] >= as_of:
                break
            self._accum = pd.concat(
                [self._accum, pd.DataFrame([row])],
                ignore_index=True,
            )
            self._cursor += 1
        if self._accum.empty:
            return pd.DataFrame(
                columns=["team", "rs_per_game", "ra_per_game", "games", "win_pct", "recent_win_pct"],
            )
        stats = build_team_stats_from_games(self._accum, self.sport)
        if stats.empty:
            return stats
        return stats.set_index("team")

    def reset(self) -> None:
        self._cursor = 0
        self._accum = pd.DataFrame()


def stats_as_of(db: SportsDatabase, sport: Sport, as_of_date: str) -> pd.DataFrame:
    """單次查詢：as_of 之前的球隊 stats（供單場預測）。"""
    as_of = str(as_of_date)[:10]
    with db.connection() as conn:
        games = pd.read_sql_query(
            f"""
            SELECT match_date, home_team, away_team, home_score, away_score, status
            FROM games
            WHERE sport = ? AND match_date < ? AND {_VALID_FINAL_SQL}
            ORDER BY match_date
            """,
            conn,
            params=(sport, as_of),
        )
    stats = build_team_stats_from_games(games, sport)
    if stats.empty:
        return stats
    return stats.set_index("team")
