"""ESPN 公開 API：賽程、比分與歷史回補。"""
from __future__ import annotations

import logging
import time
from datetime import date, timedelta
from typing import Any, Literal

import pandas as pd
import requests

from sportsbet import config
from sportsbet.data.database import SportsDatabase
from sportsbet.data.espn_injuries import ESPN_SITE, USER_AGENT, normalize_espn_team
from sportsbet.data.team_logos import espn_logo_url
from sportsbet.data.team_stats import build_team_stats_from_games, persist_team_stats

logger = logging.getLogger(__name__)

Sport = Literal["nba", "mlb"]

_ESPN_FINAL = frozenset(
    {"status_final", "final", "status_full_time", "full_time", "completed"}
)


def _sport_path(sport: Sport) -> str:
    return "basketball/nba" if sport == "nba" else "baseball/mlb"


def _parse_status(comp: dict[str, Any]) -> str:
    st = comp.get("status", {}) or {}
    name = str(st.get("type", {}).get("name", "")).lower()
    state = str(st.get("type", {}).get("state", "")).lower()
    if name in _ESPN_FINAL or state == "post":
        return "final"
    if state in ("pre",) or "scheduled" in name:
        return "scheduled"
    if state in ("in",) or "progress" in name:
        return "in_progress"
    return "scheduled"


def _score_value(competitor: dict[str, Any]) -> int | None:
    for key in ("score",):
        val = competitor.get(key)
        if val is None or val == "":
            return None
        try:
            return int(float(val))
        except (TypeError, ValueError):
            return None
    return None


class EspnScheduleClient:
    def __init__(self, timeout: float = 25.0):
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": USER_AGENT})

    def fetch_scoreboard(self, sport: Sport, match_date: str) -> list[dict[str, Any]]:
        ymd = match_date.replace("-", "")
        url = f"{ESPN_SITE}/{_sport_path(sport)}/scoreboard?dates={ymd}"
        resp = self._session.get(url, timeout=self.timeout)
        resp.raise_for_status()
        payload = resp.json()
        rows: list[dict[str, Any]] = []
        for event in payload.get("events", []):
            comps = event.get("competitions") or []
            if not comps:
                continue
            comp = comps[0]
            home = away = None
            home_score = away_score = None
            for c in comp.get("competitors", []):
                team_info = c.get("team", {}) or {}
                name = normalize_espn_team(str(team_info.get("displayName", "")), sport)
                if c.get("homeAway") == "home":
                    home = name
                    home_score = _score_value(c)
                else:
                    away = name
                    away_score = _score_value(c)
            if not home or not away:
                continue
            match_dt = event.get("date") or comp.get("date")
            d_str = str(match_dt)[:10] if match_dt else match_date
            rows.append(
                {
                    "match_date": d_str,
                    "home_team": home,
                    "away_team": away,
                    "home_score": home_score,
                    "away_score": away_score,
                    "status": _parse_status(comp),
                    "match_datetime": str(match_dt) if match_dt else None,
                    "home_logo_url": espn_logo_url(home, sport),
                    "away_logo_url": espn_logo_url(away, sport),
                }
            )
        return rows

    def sync_date_to_database(self, db: SportsDatabase, sport: Sport, match_date: str) -> pd.DataFrame:
        games = self.fetch_scoreboard(sport, match_date)
        out = []
        for g in games:
            gid = db.upsert_game(
                sport,
                g["match_date"],
                g["home_team"],
                g["away_team"],
                match_datetime=g.get("match_datetime"),
                home_score=g.get("home_score"),
                away_score=g.get("away_score"),
                status=g.get("status", "scheduled"),
                home_logo_url=g.get("home_logo_url"),
                away_logo_url=g.get("away_logo_url"),
            )
            out.append({**g, "game_id": gid})
        db.mark_schedule_date_checked(sport, match_date)
        return pd.DataFrame(out)

    def backfill_dates(
        self,
        db: SportsDatabase,
        sport: Sport,
        *,
        days_back: int,
        pause_sec: float = 0.25,
        only_missing: bool = False,
    ) -> int:
        """依日迴圈抓取 ESPN 賽程（MLB 歷史 / API 備援用）。"""
        n = 0
        for offset in range(days_back):
            d = (date.today() - timedelta(days=offset)).isoformat()
            if only_missing and db.is_schedule_date_checked(sport, d):
                games = db.get_games(sport, d)
                if not games.empty and games["home_score"].notna().all():
                    continue
            df = self.sync_date_to_database(db, sport, d)
            db.mark_schedule_date_checked(sport, d)
            n += len(df)
            time.sleep(pause_sec)
        return n

    def rebuild_team_stats_from_db(
        self,
        db: SportsDatabase,
        sport: Sport,
        *,
        season: str | int,
        days_back: int | None = None,
    ) -> pd.DataFrame:
        days_back = days_back or min(config.BACKTEST_DAYS, 365)
        start = (date.today() - timedelta(days=days_back)).isoformat()
        end = date.today().isoformat()
        games = db.get_games_in_range(sport, start, end)
        if games.empty:
            games = db.get_games(sport, with_scores_only=True)
        stats = build_team_stats_from_games(games, sport)
        if not stats.empty:
            persist_team_stats(db, sport, stats, season=season)
        return stats
