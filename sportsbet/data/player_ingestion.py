"""V2 球員/傷兵資料獲取：MOCK + 介面預留（ESPN / CBS）。"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import date, timedelta

import numpy as np
import pandas as pd

from sportsbet.data.database import SportsDatabase
from sportsbet.data.ingestion import MLB_TEAMS, NBA_TEAMS
from sportsbet.data.team_logos import canonical_team_name

logger = logging.getLogger(__name__)

Sport = str  # nba | mlb

INJURY_STATUSES = ("Out", "Doubtful", "Questionable", "Probable", "Available")
INJURY_TYPES = ("Ankle", "Knee", "Hamstring", "Back", "Illness", "Rest")


class PlayerDataProvider(ABC):
    @abstractmethod
    def fetch_players_and_stats(self, sport: str, season: str | int | None = None) -> int:
        """同步球員與高階數據，回傳筆數。"""

    @abstractmethod
    def fetch_injury_reports(self, sport: str, report_date: str | None = None) -> int:
        """同步傷兵名單。"""

    @abstractmethod
    def fetch_projected_lineups(self, sport: str, match_date: str | None = None) -> int:
        """同步預計上場名單。"""


class MockPlayerDataProvider(PlayerDataProvider):
    """產生 MOCK 球員、滾動數據、傷兵與預計先發。"""

    def __init__(self, db: SportsDatabase | None = None, seed: int = 7):
        self.db = db or SportsDatabase()
        self.rng = np.random.default_rng(seed)

    def _nba_roster_template(self, team: str) -> list[dict]:
        positions = ["PG", "SG", "SF", "PF", "C", "G", "F"]
        # 每位球員唯一名稱，避免跑馬燈出現重複顯示
        first = ["Jay", "Marcus", "Tyler", "Devin", "Chris", "Kyle", "Jordan", "Alex", "Derrick", "Bobby"]
        last = ["Allen", "Brown", "Clark", "Davis", "Evans", "Foster", "Green", "Harris", "Irving", "Jones"]
        tag = team.split()[-1][:3].upper()
        return [
            {
                "player_id": f"{tag}-{i}",
                "name": f"{first[i]} {last[i]}",
                "position": positions[i % len(positions)],
            }
            for i in range(10)
        ]

    def _mlb_roster_template(self, team: str) -> list[dict]:
        roles = ["SP", "RP", "C", "1B", "2B", "SS", "3B", "OF", "DH"]
        return [
            {
                "player_id": f"{team[:3].upper()}-{i}",
                "name": f"{team.split()[-1]} Player {i+1}",
                "position": roles[i % len(roles)],
            }
            for i in range(12)
        ]

    def fetch_players_and_stats(self, sport: str, season: str | int | None = None) -> int:
        season = str(season or date.today().year)
        teams = NBA_TEAMS if sport == "nba" else MLB_TEAMS
        today = date.today().isoformat()
        n = 0
        for team in teams:
            canon = canonical_team_name(team, sport)  # type: ignore[arg-type]
            roster = self._nba_roster_template(canon) if sport == "nba" else self._mlb_roster_template(canon)
            for p in roster:
                self.db.upsert_player(sport, p["player_id"], p["name"], canon, p["position"])
                if sport == "nba":
                    vorp = float(self.rng.normal(1.5, 1.2))
                    bpm = float(self.rng.normal(0.0, 3.0))
                    usg = float(np.clip(self.rng.normal(0.22, 0.06), 0.1, 0.38))
                    pace = float(np.clip(self.rng.normal(100, 4), 92, 108))
                    hot = float(self.rng.normal(0, 0.15))
                    self.db.upsert_player_stats(
                        sport, p["player_id"], today, season=season,
                        bpm=bpm, vorp=vorp, usg_pct=usg, pace=pace,
                        rolling_off_rating=bpm, hot_cold_index=hot,
                    )
                else:
                    war = float(self.rng.normal(2.0, 1.5))
                    wrc = float(np.clip(self.rng.normal(100, 20), 70, 150))
                    fip = float(np.clip(self.rng.normal(4.0, 0.8), 2.5, 5.5))
                    hot = float(self.rng.normal(0, 0.12))
                    self.db.upsert_player_stats(
                        sport, p["player_id"], today, season=season,
                        war=war, wrc_plus=wrc, fip=fip,
                        rolling_off_rating=wrc, hot_cold_index=hot,
                    )
                n += 1
        return n

    def fetch_injury_reports(self, sport: str, report_date: str | None = None) -> int:
        d = report_date or date.today().isoformat()
        with self.db.connection() as conn:
            players = pd.read_sql_query(
                "SELECT player_id, team, name FROM players WHERE sport = ?",
                conn,
                params=(sport,),
            )
        if players.empty:
            self.fetch_players_and_stats(sport)
            return self.fetch_injury_reports(sport, d)

        n = 0
        for _, row in players.iterrows():
            roll = self.rng.random()
            if roll < 0.78:
                status = "Available"
            elif roll < 0.86:
                status = self.rng.choice(["Out", "Doubtful"])
            elif roll < 0.94:
                status = "Questionable"
            else:
                status = "Probable"
            if status == "Available":
                continue
            self.db.upsert_injury(
                sport,
                row["player_id"],
                row["team"],
                d,
                status,
                injury_type=self.rng.choice(INJURY_TYPES),
                expected_return=(date.fromisoformat(d) + timedelta(days=int(self.rng.integers(3, 21)))).isoformat(),
            )
            n += 1
        return n

    def fetch_projected_lineups(self, sport: str, match_date: str | None = None) -> int:
        d = match_date or date.today().isoformat()
        games = self.db.get_games(sport, d)
        if games.empty:
            return 0
        n = 0
        for team in pd.unique(pd.concat([games["home_team"], games["away_team"]])):
            roster = self.db.get_players_by_team(sport, team)
            if roster.empty:
                continue
            roster = roster.drop_duplicates(subset=["player_id"]).head(8 if sport == "nba" else 9)
            for i, p in roster.iterrows():
                mins = 34 - i * 2.5 if sport == "nba" else None
                inn = 6.0 - i * 0.4 if sport == "mlb" and i < 5 else 0.0
                self.db.upsert_projected_lineup(
                    sport, team, d, p["player_id"],
                    expected_minutes=mins,
                    expected_innings=inn if sport == "mlb" else None,
                    is_starter=i < (5 if sport == "nba" else 5),
                )
                n += 1
        return n


class EspnInjuryProvider(PlayerDataProvider):
    """預留 ESPN/CBS 傷兵介面；目前委派 MOCK。"""

    def __init__(self, fallback: MockPlayerDataProvider | None = None):
        self._fallback = fallback or MockPlayerDataProvider()

    def fetch_players_and_stats(self, sport: str, season: str | int | None = None) -> int:
        return self._fallback.fetch_players_and_stats(sport, season)

    def fetch_injury_reports(self, sport: str, report_date: str | None = None) -> int:
        logger.info("ESPN 傷兵爬蟲尚未實作，使用 MOCK")
        return self._fallback.fetch_injury_reports(sport, report_date)

    def fetch_projected_lineups(self, sport: str, match_date: str | None = None) -> int:
        return self._fallback.fetch_projected_lineups(sport, match_date)


def sync_v2_player_data(db: SportsDatabase, sport: str, *, days_lineup: int = 7) -> dict[str, int]:
    """一次同步 V2 球員層資料。"""
    provider = MockPlayerDataProvider(db)
    out = {
        "players": provider.fetch_players_and_stats(sport),
        "injuries": provider.fetch_injury_reports(sport),
    }
    lineup_n = 0
    for offset in range(days_lineup):
        d = (date.today() + timedelta(days=offset)).isoformat()
        lineup_n += provider.fetch_projected_lineups(sport, d)
    out["lineups"] = lineup_n
    return out
