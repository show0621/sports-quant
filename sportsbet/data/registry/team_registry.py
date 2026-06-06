"""隊名 canonical 對齊：台灣運彩 / ESPN / nba_api 統一入口。"""
from __future__ import annotations

from typing import Literal

from sportsbet.data.database import SportsDatabase
from sportsbet.data.team_names import (
    NBA_ZH_TO_EN,
    MLB_ZH_TO_EN,
    normalize_team_name,
)

Sport = Literal["nba", "mlb"]


class TeamRegistry:
    """集中管理隊名別名，優先內建表再查 DB。"""

    def __init__(self, db: SportsDatabase | None = None):
        self.db = db or SportsDatabase()
        self._seeded = False

    def ensure_seeded(self) -> None:
        if self._seeded:
            return
        rows: list[tuple[str, str, str, str]] = []
        for sport, mapping in (("nba", NBA_ZH_TO_EN), ("mlb", MLB_ZH_TO_EN)):
            for alias, canonical in mapping.items():
                rows.append((sport, canonical, alias, "builtin"))
                rows.append((sport, canonical, canonical, "canonical"))
        with self.db.connection() as conn:
            for sport, canonical, alias, source in rows:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO team_aliases (sport, canonical_name, alias, source)
                    VALUES (?, ?, ?, ?)
                    """,
                    (sport, canonical, alias, source),
                )
        self._seeded = True

    def canonical(self, name: str, sport: Sport) -> str:
        self.ensure_seeded()
        if not name:
            return ""
        mapped = normalize_team_name(name, sport)
        with self.db.connection() as conn:
            row = conn.execute(
                """
                SELECT canonical_name FROM team_aliases
                WHERE sport = ? AND alias = ?
                LIMIT 1
                """,
                (sport, name.strip()),
            ).fetchone()
            if row:
                return str(row["canonical_name"])
            row = conn.execute(
                """
                SELECT canonical_name FROM team_aliases
                WHERE sport = ? AND alias = ?
                LIMIT 1
                """,
                (sport, mapped),
            ).fetchone()
            if row:
                return str(row["canonical_name"])
        return mapped

    def matchup(self, home: str, away: str, sport: Sport) -> tuple[str, str]:
        return self.canonical(home, sport), self.canonical(away, sport)

    def register_alias(
        self,
        sport: Sport,
        canonical: str,
        alias: str,
        *,
        source: str = "manual",
    ) -> None:
        self.ensure_seeded()
        with self.db.connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO team_aliases (sport, canonical_name, alias, source)
                VALUES (?, ?, ?, ?)
                """,
                (sport, canonical, alias, source),
            )
