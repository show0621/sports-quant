"""ESPN 公開 API：賽程、比分與歷史回補。"""
from __future__ import annotations

import logging
import time
from datetime import date, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

import pandas as pd
import requests

from sportsbet import config
from sportsbet.data.database import SportsDatabase
from sportsbet.data.espn_injuries import ESPN_SITE, USER_AGENT, normalize_espn_team
from sportsbet.data.team_logos import espn_logo_url
from sportsbet.data.team_stats import build_team_stats_from_games, persist_team_stats

logger = logging.getLogger(__name__)

Sport = Literal["nba", "mlb"]
_TZ = ZoneInfo("Asia/Taipei")

_ESPN_FINAL = frozenset(
    {"status_final", "final", "status_full_time", "full_time", "completed"}
)

_SEASON_TYPE_ZH = {
    "preseason": "熱身賽",
    "regular": "例行賽",
    "regular season": "例行賽",
    "postseason": "季後賽",
    "playoffs": "季後賽",
    "play in": "附加賽",
    "play-in": "附加賽",
    "off season": "休賽季",
}


def _sport_path(sport: Sport) -> str:
    return "basketball/nba" if sport == "nba" else "baseball/mlb"


def _taipei_date(iso_dt: str | None, fallback: str) -> str:
    if not iso_dt:
        return fallback
    try:
        dt = pd.to_datetime(iso_dt, utc=True, errors="coerce")
        if pd.isna(dt):
            return fallback
        return dt.tz_convert(_TZ).strftime("%Y-%m-%d")
    except Exception:
        return fallback


def _parse_status(comp: dict[str, Any]) -> str:
    st = comp.get("status", {}) or {}
    name = str(st.get("type", {}).get("name", "")).lower()
    state = str(st.get("type", {}).get("state", "")).lower()
    if name in _ESPN_FINAL or state == "post":
        return "final"
    if state in ("in",) or "progress" in name:
        return "in_progress"
    if state in ("pre",) or "scheduled" in name:
        return "scheduled"
    return "scheduled"


def _parse_season_meta(event: dict[str, Any]) -> tuple[str | None, str | None]:
    season = event.get("season") or {}
    stype_raw = season.get("type")
    if isinstance(stype_raw, dict):
        stype = stype_raw
        code = stype.get("type")
        raw_name = str(stype.get("name") or stype.get("abbreviation") or "").strip()
    else:
        code = stype_raw
        raw_name = ""
    base = _SEASON_TYPE_ZH.get(raw_name.lower(), raw_name or None)
    if code == 1 and not base:
        base = "熱身賽"
    elif code == 2 and not base:
        base = "例行賽"
    elif code == 3 and not base:
        base = "季後賽"

    note = None
    for key in ("name", "shortName"):
        title = str(event.get(key) or "")
        low = title.lower()
        if "final" in low and "finals" in low or "總冠軍" in title or "NBA Finals" in title:
            note = "總冠軍賽"
            break
        if "conference" in low or "分區" in title:
            note = "分區賽"
            break
        if "play-in" in low or "play in" in low:
            note = "附加賽"
            base = base or "附加賽"
            break
        if "semifinal" in low or "conf finals" in low:
            note = "分區決賽"
            break
    return base, note


def _score_value(competitor: dict[str, Any]) -> int | None:
    val = competitor.get("score")
    if val is None or val == "":
        return None
    try:
        return int(float(val))
    except (TypeError, ValueError):
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
            d_str = _taipei_date(str(match_dt) if match_dt else None, match_date)
            st = comp.get("status", {}) or {}
            stype = st.get("type", {}) or {}
            season_type, comp_note = _parse_season_meta(event)
            rows.append(
                {
                    "espn_event_id": str(event.get("id", "")),
                    "match_date": d_str,
                    "home_team": home,
                    "away_team": away,
                    "home_score": home_score,
                    "away_score": away_score,
                    "status": _parse_status(comp),
                    "match_datetime": str(match_dt) if match_dt else None,
                    "home_logo_url": espn_logo_url(home, sport),
                    "away_logo_url": espn_logo_url(away, sport),
                    "season_type": season_type,
                    "competition_note": comp_note,
                    "period": st.get("period"),
                    "clock": st.get("displayClock"),
                    "status_detail": stype.get("shortDetail") or stype.get("detail"),
                }
            )
        return rows

    def sync_date_to_database(self, db: SportsDatabase, sport: Sport, match_date: str) -> pd.DataFrame:
        games = self.fetch_scoreboard(sport, match_date)
        out = []
        for g in games:
            try:
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
                    season_type=g.get("season_type"),
                    competition_note=g.get("competition_note"),
                    period=g.get("period"),
                    clock=g.get("clock"),
                    status_detail=g.get("status_detail"),
                    espn_event_id=g.get("espn_event_id"),
                )
            except ValueError as exc:
                logger.debug("skip game %s vs %s: %s", g.get("away_team"), g.get("home_team"), exc)
                continue
            out.append({**g, "game_id": gid})
        db.mark_schedule_date_checked(sport, match_date)
        return pd.DataFrame(out)

    def sync_window_to_database(
        self,
        db: SportsDatabase,
        sport: Sport,
        *,
        center: date | None = None,
        days_before: int = 1,
        days_after: int = 1,
    ) -> pd.DataFrame:
        """同步中心日 ±N 天（涵蓋跨時區賽事）。"""
        center = center or date.today()
        frames = []
        for offset in range(-days_before, days_after + 1):
            d = (center + timedelta(days=offset)).isoformat()
            frames.append(self.sync_date_to_database(db, sport, d))
            time.sleep(0.15)
        if not frames:
            return pd.DataFrame()
        return pd.concat([f for f in frames if not f.empty], ignore_index=True)

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
