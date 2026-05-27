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

from datetime import date

from sportsbet import config
from sportsbet.data.database import SportsDatabase
from sportsbet.data.storage import save_games, save_team_stats

logger = logging.getLogger(__name__)

Sport = Literal["nba", "mlb"]

FINISHED_STATUS = {"FT", "AOT", "Finished", "AFTER_OT", "POST", "closed"}


def infer_season(sport: Sport, on_date: date | None = None) -> int:
    """API-Sports 賽季參數為賽季「起始年」（如 2024-25 → 2024）。"""
    d = on_date or date.today()
    if sport == "nba":
        return d.year if d.month >= 10 else d.year - 1
    return d.year if d.month >= 3 else d.year - 1


def _league_id(sport: Sport) -> int:
    return config.API_SPORTS_LEAGUE_NBA if sport == "nba" else config.API_SPORTS_LEAGUE_MLB


class ApiSportsClient:
    def __init__(self, api_key: str | None = None):
        self.api_key = (api_key or config.resolve_api_sports_key()).strip()
        if not self.api_key:
            logger.warning("未設定 API_SPORTS_KEY，API 請求將失敗。請在 .env 或 Streamlit Secrets 填入金鑰。")

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    def _headers(self) -> dict[str, str]:
        return {"x-apisports-key": self.api_key}

    def _base_url(self, sport: Sport) -> str:
        return config.API_SPORTS_BASE if sport == "nba" else config.API_SPORTS_MLB_BASE

    def _get(self, sport: Sport, endpoint: str, params: dict | None = None) -> dict[str, Any]:
        url = f"{self._base_url(sport)}/{endpoint.lstrip('/')}"
        try:
            resp = requests.get(url, headers=self._headers(), params=params or {}, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as exc:
            raise RuntimeError(f"API-Sports 請求失敗：{exc}") from exc
        except ValueError as exc:
            raise RuntimeError("API-Sports 回傳非 JSON 格式，請稍後再試。") from exc

        errors = data.get("errors")
        if errors:
            logger.error("API-Sports errors: %s", errors)
            if isinstance(errors, dict):
                detail = "; ".join(f"{k}: {v}" for k, v in errors.items())
            elif isinstance(errors, list):
                detail = "; ".join(str(e) for e in errors)
            else:
                detail = str(errors)
            raise RuntimeError(f"API-Sports 回傳錯誤：{detail}")
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
        lid = league_id or _league_id(sport)
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
                    "match_datetime": item.get("date") or item.get("timestamp"),
                    "home_logo_url": home.get("logo") or None,
                    "away_logo_url": away.get("logo") or None,
                }
            )
        df = pd.DataFrame(rows)
        if not df.empty:
            path = save_games(df, sport, season)
            logger.info("已儲存 %d 場比賽至 %s", len(df), path)
        return df

    def fetch_games_by_date(
        self,
        sport: Sport,
        match_date: str,
        *,
        season: int | None = None,
        league_id: int | None = None,
    ) -> pd.DataFrame:
        """抓取指定日期賽程（含已結束與未開賽）。"""
        d = date.fromisoformat(match_date)
        season = season or infer_season(sport, d)
        lid = league_id or _league_id(sport)
        data = self._get(
            sport,
            "games",
            {"league": lid, "season": season, "date": match_date},
        )
        rows = []
        for item in data.get("response", []):
            teams = item.get("teams", {})
            scores = item.get("scores", {})
            home = teams.get("home", {})
            away = teams.get("away", {})
            status = item.get("status", {}).get("short") or item.get("status", {}).get("long")
            rows.append(
                {
                    "game_id": item.get("id"),
                    "date": (item.get("date") or match_date)[:10],
                    "season": season,
                    "home_team": home.get("name"),
                    "away_team": away.get("name"),
                    "home_score": _extract_total(scores.get("home", {})),
                    "away_score": _extract_total(scores.get("away", {})),
                    "status": status,
                    "match_datetime": item.get("date") or item.get("timestamp"),
                    "home_logo_url": home.get("logo") or None,
                    "away_logo_url": away.get("logo") or None,
                }
            )
        return pd.DataFrame(rows)

    def fetch_teams(self, sport: Sport, season: int | None = None) -> pd.DataFrame:
        """抓取聯盟球隊清單（含 logo）。"""
        season = season or infer_season(sport)
        lid = _league_id(sport)
        data = self._get(sport, "teams", {"league": lid, "season": season})
        rows = []
        for item in data.get("response", []):
            rows.append(
                {
                    "team": item.get("name"),
                    "logo_url": item.get("logo"),
                    "api_team_id": item.get("id"),
                }
            )
        return pd.DataFrame(rows)

    def sync_team_logos(self, db: SportsDatabase, sport: Sport, season: int | None = None) -> int:
        """將球隊 logo 寫入 teams 表。"""
        if not self.is_configured:
            return 0
        teams = self.fetch_teams(sport, season)
        n = 0
        for _, row in teams.iterrows():
            if row.get("team") and row.get("logo_url"):
                db.upsert_team_logo(
                    sport,
                    str(row["team"]),
                    str(row["logo_url"]),
                    int(row["api_team_id"]) if pd.notna(row.get("api_team_id")) else None,
                )
                n += 1
        return n

    def build_team_stats(self, games_df: pd.DataFrame, sport: Sport) -> pd.DataFrame:
        """由比賽結果彙總各隊得分/失分（賽季累計）。"""
        if games_df.empty:
            return pd.DataFrame()

        finished = games_df[games_df["status"].astype(str).isin(FINISHED_STATUS)].copy()
        finished = finished.dropna(subset=["home_score", "away_score"])
        recent = _recent_win_pct(finished, config.BAYES_RECENT_GAMES)

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
                    "recent_win_pct": recent.get(team, s["wins"] / g),
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

    def sync_to_database(
        self,
        db: SportsDatabase,
        sport: Sport,
        season: int | None = None,
    ) -> pd.DataFrame:
        """將賽季賽果與球隊統計寫入 SQLite。"""
        season = season or infer_season(sport)
        games = self.fetch_games(sport, season)
        stats = self.build_team_stats(games, sport)
        for _, row in stats.iterrows():
            db.upsert_team_stats(
                sport,
                str(row["team"]),
                float(row["rs_per_game"]),
                float(row["ra_per_game"]),
                season=str(season),
                games=int(row["games"]),
                win_pct=float(row["win_pct"]),
                recent_win_pct=float(row.get("recent_win_pct", row["win_pct"])),
            )
        for _, g in games.iterrows():
            status = "final" if str(g.get("status")) in FINISHED_STATUS else "scheduled"
            db.upsert_game(
                sport,
                str(g["date"])[:10],
                str(g["home_team"]),
                str(g["away_team"]),
                match_datetime=str(g.get("match_datetime") or ""),
                home_score=int(g["home_score"]) if pd.notna(g.get("home_score")) else None,
                away_score=int(g["away_score"]) if pd.notna(g.get("away_score")) else None,
                status=status,
                home_logo_url=g.get("home_logo_url") if "home_logo_url" in g else None,
                away_logo_url=g.get("away_logo_url") if "away_logo_url" in g else None,
            )
        return stats

    def sync_daily_to_database(
        self,
        db: SportsDatabase,
        sport: Sport,
        match_date: str | None = None,
    ) -> pd.DataFrame:
        """將指定日期賽程寫入 SQLite。"""
        d = match_date or date.today().isoformat()
        games = self.fetch_games_by_date(sport, d)
        rows = []
        for _, g in games.iterrows():
            status = "final" if str(g.get("status")) in FINISHED_STATUS else "scheduled"
            gid = db.upsert_game(
                sport,
                d,
                str(g["home_team"]),
                str(g["away_team"]),
                match_datetime=str(g.get("match_datetime") or ""),
                home_score=int(g["home_score"]) if pd.notna(g.get("home_score")) else None,
                away_score=int(g["away_score"]) if pd.notna(g.get("away_score")) else None,
                status=status,
                home_logo_url=g.get("home_logo_url") if pd.notna(g.get("home_logo_url")) else None,
                away_logo_url=g.get("away_logo_url") if pd.notna(g.get("away_logo_url")) else None,
            )
            rows.append({"game_id": gid, **g.to_dict()})
        return pd.DataFrame(rows)


def _recent_win_pct(finished: pd.DataFrame, n_games: int) -> dict[str, float]:
    """各隊近 N 場勝率。"""
    if finished.empty:
        return {}
    df = finished.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.sort_values("date")
    results: dict[str, list[int]] = {}

    def _push(team: str, won: int) -> None:
        results.setdefault(team, []).append(won)

    for _, row in df.iterrows():
        hs, aws = float(row["home_score"]), float(row["away_score"])
        _push(row["home_team"], int(hs > aws))
        _push(row["away_team"], int(aws > hs))

    return {team: sum(wins[-n_games:]) / len(wins[-n_games:]) for team, wins in results.items() if wins}


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
