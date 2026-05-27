"""V2 球員/傷兵資料獲取：僅使用 ESPN 真實資料。"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date, timedelta

from sportsbet.data.database import SportsDatabase

Sport = str  # nba | mlb



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


def sync_v2_player_data(db: SportsDatabase, sport: str, *, days_lineup: int = 7) -> dict[str, int]:
    """一次同步 V2 球員層資料（僅 ESPN 真實資料）。"""

    from sportsbet.data.provider import api_key_configured

    if not api_key_configured():
        raise RuntimeError("API_SPORTS_KEY 未設定，API-only 模式無法同步球員/傷兵。")

    from sportsbet.data.espn_injuries import (
        EspnInjuryClient,
        sync_espn_injuries,
        sync_espn_projected_lineups,
    )

    match_dates = [(date.today() + timedelta(days=i)).isoformat() for i in range(days_lineup)]
    client = EspnInjuryClient()

    # 清空後重新寫入 ESPN 傷兵
    db.clear_injuries(sport, source=None)
    injuries_n = sync_espn_injuries(db, sport, report_date=date.today().isoformat(), client=client)
    lineups_n = sync_espn_projected_lineups(
        db,
        sport,
        match_dates=match_dates,
        client=client,
    )
    return {"players": 0, "injuries": injuries_n, "lineups": lineups_n}
