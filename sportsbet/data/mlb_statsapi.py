"""MLB 官方 Stats API（statsapi.mlb.com）— 免費、穩定。"""
from __future__ import annotations

import logging
import time
from datetime import date
from typing import Any

import pandas as pd
import requests

from sportsbet.data.database import SportsDatabase
from sportsbet.data.team_logos import canonical_team_name, resolve_team_in_database

logger = logging.getLogger(__name__)

MLB_API = "https://statsapi.mlb.com/api/v1"
USER_AGENT = "sports-quant/1.0"
PAUSE = 0.4

# MLB API team name → canonical
_MLB_NAME_MAP = {
    "Athletics": "Oakland Athletics",
    "Oakland Athletics": "Oakland Athletics",
    "Arizona Diamondbacks": "Arizona Diamondbacks",
    "Atlanta Braves": "Atlanta Braves",
    "Baltimore Orioles": "Baltimore Orioles",
    "Boston Red Sox": "Boston Red Sox",
    "Chicago Cubs": "Chicago Cubs",
    "Chicago White Sox": "Chicago White Sox",
    "Cincinnati Reds": "Cincinnati Reds",
    "Cleveland Guardians": "Cleveland Guardians",
    "Colorado Rockies": "Colorado Rockies",
    "Detroit Tigers": "Detroit Tigers",
    "Houston Astros": "Houston Astros",
    "Kansas City Royals": "Kansas City Royals",
    "Los Angeles Angels": "Los Angeles Angels",
    "Los Angeles Dodgers": "Los Angeles Dodgers",
    "Miami Marlins": "Miami Marlins",
    "Milwaukee Brewers": "Milwaukee Brewers",
    "Minnesota Twins": "Minnesota Twins",
    "New York Mets": "New York Mets",
    "New York Yankees": "New York Yankees",
    "Philadelphia Phillies": "Philadelphia Phillies",
    "Pittsburgh Pirates": "Pittsburgh Pirates",
    "San Diego Padres": "San Diego Padres",
    "San Francisco Giants": "San Francisco Giants",
    "Seattle Mariners": "Seattle Mariners",
    "St. Louis Cardinals": "St. Louis Cardinals",
    "Tampa Bay Rays": "Tampa Bay Rays",
    "Texas Rangers": "Texas Rangers",
    "Toronto Blue Jays": "Toronto Blue Jays",
    "Washington Nationals": "Washington Nationals",
}


def _canonical(name: str) -> str:
    mapped = _MLB_NAME_MAP.get(name, name)
    return canonical_team_name(mapped, "mlb")


class MlbStatsApiClient:
    def __init__(self, timeout: float = 25.0):
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": USER_AGENT})

    def _get(self, path: str, params: dict | None = None) -> dict[str, Any]:
        url = f"{MLB_API}/{path.lstrip('/')}"
        resp = self._session.get(url, params=params or {}, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def fetch_teams(self, season: int | None = None) -> list[dict[str, Any]]:
        season = season or date.today().year
        data = self._get("teams", {"season": season, "sportId": 1})
        return data.get("teams", [])


def sync_mlb_statsapi_team_stats(
    db: SportsDatabase,
    *,
    season: int | None = None,
    client: MlbStatsApiClient | None = None,
) -> int:
    """從 MLB Stats API 同步球隊 RS/RA 至 team_stats（補強 ESPN）。"""
    season = season or date.today().year
    client = client or MlbStatsApiClient()
    n = 0

    try:
        teams = client.fetch_teams(season)
    except requests.RequestException as exc:
        logger.error("MLB Stats API teams 失敗: %s", exc)
        raise

    for tm in teams:
        tid = tm.get("id")
        if not tid:
            continue
        name = _canonical(str(tm.get("name") or ""))
        team = resolve_team_in_database(db, "mlb", name)
        time.sleep(PAUSE)
        try:
            stats = client._get(
                f"teams/{tid}/stats",
                {"season": season, "group": "hitting,pitching", "stats": "season"},
            )
        except requests.RequestException as exc:
            logger.warning("MLB stats 失敗 team=%s: %s", team, exc)
            continue

        runs_scored = runs_allowed = games = 0
        for split in stats.get("stats", []):
            grp = str(split.get("group", {}).get("displayName", "")).lower()
            splits = split.get("splits", [])
            if not splits:
                continue
            stat = splits[0].get("stat", {})
            if grp == "hitting":
                runs_scored = int(stat.get("runs", 0) or 0)
                games = int(stat.get("gamesPlayed", 0) or games)
            elif grp == "pitching":
                runs_allowed = int(stat.get("runs", 0) or 0)

        if games <= 0 or runs_scored <= 0:
            continue
        rs_pg = runs_scored / games
        ra_pg = runs_allowed / games if runs_allowed > 0 else rs_pg
        win_pct = None
        record = tm.get("record", {}) or {}
        if record.get("wins") is not None and record.get("losses") is not None:
            w, l = int(record["wins"]), int(record["losses"])
            win_pct = w / (w + l) if (w + l) > 0 else None

        db.upsert_team_stats(
            "mlb", team, rs_pg, ra_pg,
            season=str(season), games=games, win_pct=win_pct,
        )
        n += 1

    logger.info("MLB Stats API 同步 %d 隊 season=%s", n, season)
    return n
