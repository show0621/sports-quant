"""
API-Sports 資料抓取（NBA / MLB）。

免費方案每日請求有限，請妥善快取至本地 CSV。
文件：https://api-sports.io/documentation
"""
from __future__ import annotations

import logging
import time
from typing import Any, Literal

import pandas as pd
import requests

from sportsbet import config
from sportsbet.data.storage import save_games, save_team_stats

logger = logging.getLogger(__name__)

Sport = Literal["nba", "mlb"]


class ApiSportsClient:
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or config.API_SPORTS_KEY
        if not self.api_key:
            logger.warning("未設定 API_SPORTS_KEY，API 請求將失敗。請在 .env 填入金鑰。")

    def _headers(self) -> dict[str, str]:
        return {"x-apisports-key": self.api_key}

    def _base_url(self, sport: Sport) -> str:
        return config.API_SPORTS_BASE if sport == "nba" else config.API_SPORTS_MLB_BASE

    def _get(self, sport: Sport, endpoint: str, params: dict | None = None) -> dict[str, Any]:
        url = f"{self._base_url(sport)}/{endpoint.lstrip('/')}"
        resp = requests.get(url, headers=self._headers(), params=params or {}, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if data.get("errors"):
            logger.error("API-Sports errors: %s", data["errors"])
        return data

    def fetch_games(
        self,
        sport: Sport,
        season: int,
        league_id: int | None = None,
    ) -> pd.DataFrame:
        """
        抓取賽季比賽結果。

        NBA league_id=12, MLB league_id=1（API-Sports 預設，請依文件確認）。
        """
        default_league = 12 if sport == "nba" else 1
        lid = league_id or default_league
        data = self._get(sport, "games", {"league": lid, "season": season})
        rows = []
        for item in data.get("response", []):
            teams = item.get("teams", {})
            scores = item.get("scores", {})
            home = teams.get("home", {})
            away = teams.get("away", {})
            home_score = _extract_total(scores.get("home", {}))
            away_score = _extract_total(scores.get("away", {}))
            rows.append(
                {
                    "game_id": item.get("id"),
                    "date": item.get("date", "")[:10],
                    "season": season,
                    "home_team": home.get("name"),
                    "away_team": away.get("name"),
                    "home_score": home_score,
                    "away_score": away_score,
                    "status": item.get("status", {}).get("short"),
                }
            )
        df = pd.DataFrame(rows)
        if not df.empty:
            path = save_games(df, sport, season)
            logger.info("已儲存 %d 場比賽至 %s", len(df), path)
        return df

    def build_team_stats(self, games_df: pd.DataFrame, sport: Sport) -> pd.DataFrame:
        """由比賽結果彙總各隊得分/失分（賽季累計）。"""
        if games_df.empty:
            return pd.DataFrame()

        finished = games_df[games_df["status"].isin(["FT", "AOT", "Finished", None])].copy()
        finished = finished.dropna(subset=["home_score", "away_score"])

        stats: dict[str, dict[str, float]] = {}

        def _add(team: str, scored: float, allowed: float, won: bool) -> None:
            if team not in stats:
                stats[team] = {"games": 0, "wins": 0, "runs_scored": 0.0, "runs_allowed": 0.0}
            s = stats[team]
            s["games"] += 1
            s["wins"] += int(won)
            s["runs_scored"] += scored
            s["runs_allowed"] += allowed

        for _, row in finished.iterrows():
            hs, aws = float(row["home_score"]), float(row["away_score"])
            _add(row["home_team"], hs, aws, hs > aws)
            _add(row["away_team"], aws, hs, aws > hs)

        records = []
        for team, s in stats.items():
            g = s["games"] or 1
            records.append(
                {
                    "team": team,
                    "sport": sport,
                    "games": int(s["games"]),
                    "wins": int(s["wins"]),
                    "losses": int(s["games"] - s["wins"]),
                    "win_pct": s["wins"] / g,
                    "runs_scored": s["runs_scored"],
                    "runs_allowed": s["runs_allowed"],
                    "rs_per_game": s["runs_scored"] / g,
                    "ra_per_game": s["runs_allowed"] / g,
                }
            )
        df = pd.DataFrame(records)
        save_team_stats(df, sport)
        return df

    def sync_season(self, sport: Sport, season: int, pause_sec: float = 1.0) -> pd.DataFrame:
        """抓取並彙總整季資料。"""
        games = self.fetch_games(sport, season)
        time.sleep(pause_sec)
        return self.build_team_stats(games, sport)


def _extract_total(score_obj: dict) -> float | None:
    if not score_obj:
        return None
    total = score_obj.get("total")
    if total is not None:
        return float(total)
    if isinstance(score_obj, dict):
        vals = [v for v in score_obj.values() if isinstance(v, (int, float))]
        if vals:
            return float(sum(vals))
    return None
