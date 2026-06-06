"""ESPN 單場 summary / box score（球員得分、逐節比分）。"""
from __future__ import annotations

import logging
import re
import time
from datetime import date, timedelta
from typing import Any, Literal

import requests

from sportsbet.data.database import SportsDatabase
from sportsbet.data.espn_injuries import USER_AGENT, _athlete_id, normalize_espn_team
from sportsbet.data.espn_schedule import EspnScheduleClient, ESPN_SITE, _sport_path

logger = logging.getLogger(__name__)

Sport = Literal["nba", "mlb"]


def _parse_minutes(raw: str | None) -> float | None:
    if raw is None or raw == "" or raw == "--":
        return None
    s = str(raw).strip()
    if ":" in s:
        parts = s.split(":")
        try:
            return float(parts[0]) + float(parts[1]) / 60.0
        except (ValueError, IndexError):
            return None
    try:
        return float(s)
    except ValueError:
        return None


def _stat_index(labels: list[str], name: str) -> int | None:
    for i, lab in enumerate(labels):
        if lab.upper() == name.upper():
            return i
    return None


def _safe_int(vals: list[str], idx: int | None) -> int | None:
    if idx is None or idx >= len(vals):
        return None
    raw = str(vals[idx]).strip()
    if not raw or raw == "--":
        return None
    try:
        return int(float(raw))
    except ValueError:
        m = re.search(r"\d+", raw)
        return int(m.group()) if m else None


class EspnBoxScoreClient:
    def __init__(self, timeout: float = 25.0):
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": USER_AGENT})
        self._schedule = EspnScheduleClient(timeout=timeout)

    def fetch_summary(self, sport: Sport, espn_event_id: str) -> dict[str, Any]:
        url = f"{ESPN_SITE}/{_sport_path(sport)}/summary?event={espn_event_id}"
        resp = self._session.get(url, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def parse_box_score(
        self,
        payload: dict[str, Any],
        *,
        home_team: str,
        away_team: str,
    ) -> tuple[list[dict[str, Any]], dict[str, list[int | None]]]:
        """回傳 (player_rows, {home: [q1..q4], away: [q1..q4]})."""
        players_out: list[dict[str, Any]] = []
        quarters: dict[str, list[int | None]] = {"home": [], "away": []}

        header = payload.get("header") or {}
        comp = (header.get("competitions") or [{}])[0]
        for c in comp.get("competitors") or []:
            side = "home" if c.get("homeAway") == "home" else "away"
            lines = c.get("linescores") or []
            quarters[side] = [
                int(float(x.get("displayValue", 0))) if x.get("displayValue") not in (None, "") else None
                for x in lines[:4]
            ]
            while len(quarters[side]) < 4:
                quarters[side].append(None)

        box = payload.get("boxscore") or {}
        for side_block in box.get("players") or []:
            team_name = normalize_espn_team(
                str((side_block.get("team") or {}).get("displayName", "")),
                "nba",
            )
            is_home = team_name == home_team
            stats_blocks = side_block.get("statistics") or []
            if not stats_blocks:
                continue
            block = stats_blocks[0]
            labels = [str(x) for x in block.get("labels") or []]
            idx_min = _stat_index(labels, "MIN")
            idx_pts = _stat_index(labels, "PTS")
            idx_reb = _stat_index(labels, "REB")
            idx_ast = _stat_index(labels, "AST")
            idx_3pt = _stat_index(labels, "3PT")
            idx_stl = _stat_index(labels, "STL")
            idx_blk = _stat_index(labels, "BLK")
            idx_to = _stat_index(labels, "TO")

            for row in block.get("athletes") or []:
                ath = row.get("athlete") or {}
                if ath.get("didNotPlay") or row.get("didNotPlay"):
                    continue
                vals = [str(v) for v in row.get("stats") or []]
                if not vals:
                    continue
                pid = _athlete_id(ath)
                if not pid:
                    continue
                players_out.append(
                    {
                        "player_id": pid,
                        "player_name": str(ath.get("displayName") or ath.get("shortName") or pid),
                        "team": team_name,
                        "is_home": is_home,
                        "minutes": _parse_minutes(vals[idx_min] if idx_min is not None else None),
                        "points": _safe_int(vals, idx_pts),
                        "rebounds": _safe_int(vals, idx_reb),
                        "assists": _safe_int(vals, idx_ast),
                        "threes": _safe_int(vals, idx_3pt),
                        "steals": _safe_int(vals, idx_stl),
                        "blocks": _safe_int(vals, idx_blk),
                        "turnovers": _safe_int(vals, idx_to),
                    }
                )
        return players_out, quarters

    def resolve_espn_event_id(
        self,
        sport: Sport,
        match_date: str,
        home_team: str,
        away_team: str,
    ) -> str | None:
        """依日期 scoreboard 比對隊名取得 ESPN event id。"""
        d = str(match_date)[:10]
        for offset in (0, -1, 1):
            probe = (date.fromisoformat(d) + timedelta(days=offset)).isoformat()
            for row in self._schedule.fetch_scoreboard(sport, probe):
                if row.get("home_team") == home_team and row.get("away_team") == away_team:
                    eid = row.get("espn_event_id")
                    if eid:
                        return str(eid)
        return None

    def sync_game_box_score(
        self,
        db: SportsDatabase,
        sport: Sport,
        game_row: dict[str, Any] | Any,
        *,
        client: EspnBoxScoreClient | None = None,
    ) -> int:
        """拉取並寫入單場 box score；回傳寫入球員筆數。"""
        client = client or self
        gid = int(game_row["id"] if hasattr(game_row, "__getitem__") else game_row.id)
        home = str(game_row["home_team"])
        away = str(game_row["away_team"])
        match_date = str(game_row["match_date"])[:10]
        eid = game_row.get("espn_event_id") if hasattr(game_row, "get") else getattr(game_row, "espn_event_id", None)
        if not eid or (isinstance(eid, float) and str(eid) == "nan"):
            eid = client.resolve_espn_event_id(sport, match_date, home, away)
            if eid:
                db.set_game_espn_event_id(gid, eid)
        if not eid:
            logger.debug("no espn event id for game_id=%s %s vs %s", gid, away, home)
            return 0

        try:
            payload = client.fetch_summary(sport, str(eid))
        except Exception as exc:
            logger.warning("boxscore fetch failed game_id=%s event=%s: %s", gid, eid, exc)
            return 0

        players, quarters = client.parse_box_score(payload, home_team=home, away_team=away)
        if not players:
            return 0

        for p in players:
            db.upsert_player_game_stat(
                gid,
                sport,
                p["player_id"],
                p["team"],
                player_name=p.get("player_name"),
                is_home=bool(p.get("is_home")),
                minutes=p.get("minutes"),
                points=p.get("points"),
                rebounds=p.get("rebounds"),
                assists=p.get("assists"),
                threes=p.get("threes"),
                steals=p.get("steals"),
                blocks=p.get("blocks"),
                turnovers=p.get("turnovers"),
            )
        db.upsert_game_quarter_scores(
            gid,
            sport,
            home_quarters=quarters.get("home", []),
            away_quarters=quarters.get("away", []),
        )
        return len(players)
