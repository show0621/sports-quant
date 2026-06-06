"""
ESPN 公開 API：聯盟傷兵名單與球隊 roster。

端點（無需 API Key）：
  NBA: https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries
  MLB: https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/injuries
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any, Literal

import pandas as pd
import requests

from sportsbet.data.database import SportsDatabase
from sportsbet.data.team_logos import canonical_team_name, resolve_team_in_database

logger = logging.getLogger(__name__)

Sport = Literal["nba", "mlb"]

ESPN_SITE = "https://site.api.espn.com/apis/site/v2/sports"
USER_AGENT = "sports-quant/1.0 (+https://github.com/show0621/sports-quant)"

# ESPN displayName → 專案標準全名（與 team_logos 一致）
ESPN_TEAM_ALIASES: dict[str, dict[str, str]] = {
    "nba": {
        "LA Clippers": "LA Clippers",
        "Los Angeles Clippers": "LA Clippers",
    },
    "mlb": {},
}

# 僅同步影響出賽的狀態至 DB（其餘略過）
_STATUS_OUT = frozenset({"out", "60-day-il", "15-day-il", "10-day-il", "7-day il", "suspension"})
_STATUS_DOUBTFUL = frozenset({"doubtful"})
_STATUS_QUESTIONABLE = frozenset({"questionable", "day-to-day", "day to day"})
_STATUS_PROBABLE = frozenset({"probable"})


def _sport_path(sport: Sport) -> str:
    return "basketball/nba" if sport == "nba" else "baseball/mlb"


def normalize_espn_status(raw: str | None) -> str | None:
    """將 ESPN 狀態對應至 Out / Doubtful / Questionable / Probable / Available。"""
    if not raw:
        return None
    key = raw.strip().lower().replace("_", "-")
    if key in _STATUS_OUT:
        return "Out"
    if key in _STATUS_DOUBTFUL:
        return "Doubtful"
    if key in _STATUS_QUESTIONABLE:
        return "Questionable"
    if key in _STATUS_PROBABLE:
        return "Probable"
    if key == "available":
        return "Available"
    # 未知狀態：保守視為 Out（IL 類）
    if "il" in key or "injured" in key:
        return "Out"
    return None


def normalize_espn_team(display_name: str, sport: Sport) -> str:
    aliases = ESPN_TEAM_ALIASES.get(sport, {})
    name = aliases.get(display_name, display_name)
    return canonical_team_name(name, sport)  # type: ignore[arg-type]


def _injury_type_label(details: dict[str, Any] | None) -> str | None:
    if not details:
        return None
    parts = []
    for key in ("type", "detail", "side"):
        val = details.get(key)
        if val and str(val).lower() not in ("not specified", "unknown"):
            parts.append(str(val))
    return " · ".join(parts) if parts else None


def _parse_return_date(details: dict[str, Any] | None) -> str | None:
    if not details:
        return None
    rd = details.get("returnDate")
    if not rd:
        return None
    return str(rd)[:10]


def _athlete_id(athlete: dict[str, Any]) -> str | None:
    aid = athlete.get("id")
    if aid is not None:
        return f"espn-{aid}"
    return None


def _flatten_roster_athletes(payload: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for entry in payload.get("athletes", []):
        if isinstance(entry, dict) and entry.get("items"):
            out.extend(entry["items"])
        elif isinstance(entry, dict) and entry.get("id"):
            out.append(entry)
    return out


class EspnInjuryClient:
    def __init__(self, timeout: float = 25.0):
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": USER_AGENT})

    def _get(self, url: str) -> dict[str, Any]:
        resp = self._session.get(url, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def fetch_league_injuries(self, sport: Sport) -> list[dict[str, Any]]:
        url = f"{ESPN_SITE}/{_sport_path(sport)}/injuries"
        data = self._get(url)
        rows: list[dict[str, Any]] = []
        for team_block in data.get("injuries", []):
            team_name = team_block.get("displayName") or ""
            team_id = team_block.get("id")
            for inj in team_block.get("injuries", []):
                athlete = inj.get("athlete") or {}
                rows.append(
                    {
                        "espn_team_id": team_id,
                        "espn_team_name": team_name,
                        "injury": inj,
                        "athlete": athlete,
                    }
                )
        return rows

    def fetch_team_roster(self, sport: Sport, espn_team_id: str | int) -> list[dict[str, Any]]:
        url = f"{ESPN_SITE}/{_sport_path(sport)}/teams/{espn_team_id}/roster"
        data = self._get(url)
        return _flatten_roster_athletes(data)

    def fetch_all_teams(self, sport: Sport) -> list[dict[str, Any]]:
        url = f"{ESPN_SITE}/{_sport_path(sport)}/teams"
        data = self._get(url)
        teams: list[dict[str, Any]] = []
        for league in data.get("sports", [{}])[0].get("leagues", []):
            for wrapper in league.get("teams", []):
                tm = wrapper.get("team") or wrapper
                if tm.get("id"):
                    teams.append(tm)
        return teams


def sync_espn_injuries(
    db: SportsDatabase,
    sport: Sport,
    *,
    report_date: str | None = None,
    client: EspnInjuryClient | None = None,
) -> int:
    """
    從 ESPN 同步今日傷兵；先清除舊的 espn 來源紀錄再寫入。
    回傳寫入筆數（不含 Available）。
    """
    d = report_date or date.today().isoformat()
    client = client or EspnInjuryClient()
    db.clear_injuries(sport, source="espn")

    try:
        raw_rows = client.fetch_league_injuries(sport)
    except requests.RequestException as exc:
        logger.error("ESPN 傷兵抓取失敗: %s", exc)
        raise

    n = 0
    for row in raw_rows:
        inj = row["injury"]
        athlete = row["athlete"]
        pid = _athlete_id(athlete)
        if not pid:
            continue

        status = normalize_espn_status(inj.get("status"))
        if not status or status == "Available":
            continue

        espn_team = row["espn_team_name"]
        team = resolve_team_in_database(db, sport, normalize_espn_team(espn_team, sport))

        name = athlete.get("displayName") or f"{athlete.get('firstName', '')} {athlete.get('lastName', '')}".strip()
        pos = (athlete.get("position") or {}).get("abbreviation") or ""

        db.upsert_player(sport, pid, name, team, pos)
        db.upsert_injury(
            sport,
            pid,
            team,
            d,
            status,
            injury_type=_injury_type_label(inj.get("details")),
            expected_return=_parse_return_date(inj.get("details")),
            source="espn",
        )
        n += 1

    logger.info("ESPN 傷兵同步完成 sport=%s count=%d", sport, n)
    return n


def sync_espn_rosters_for_teams(
    db: SportsDatabase,
    sport: Sport,
    team_espn_ids: set[str | int],
    *,
    client: EspnInjuryClient | None = None,
) -> int:
    """同步指定球隊 roster 至 players（不含統計；統計由 nba_api/ESPN stats 模組負責）。"""
    client = client or EspnInjuryClient()
    n = 0

    for tid in team_espn_ids:
        try:
            athletes = client.fetch_team_roster(sport, tid)
        except requests.RequestException as exc:
            logger.warning("ESPN roster 失敗 team_id=%s: %s", tid, exc)
            continue

        team_name = _team_name_from_id(client, sport, tid)

        for ath in athletes:
            pid = _athlete_id(ath)
            if not pid:
                continue
            name = ath.get("displayName") or ""
            pos = (ath.get("position") or {}).get("abbreviation") or ""
            team = resolve_team_in_database(db, sport, normalize_espn_team(team_name, sport))
            db.upsert_player(sport, pid, name, team, pos)
            n += 1

    return n


def _team_name_from_id(client: EspnInjuryClient, sport: Sport, team_id: str | int) -> str:
    for tm in client.fetch_all_teams(sport):
        if str(tm.get("id")) == str(team_id):
            return str(tm.get("displayName") or tm.get("name") or "")
    return ""


def sync_espn_injuries_and_rosters(
    db: SportsDatabase,
    sport: Sport,
    *,
    report_date: str | None = None,
) -> dict[str, int]:
    """
    同步傷兵 + 受傷球隊與今日有賽事球隊的 roster。
    """
    client = EspnInjuryClient()
    d = report_date or date.today().isoformat()

    inj_count = sync_espn_injuries(db, sport, report_date=d, client=client)

    team_ids: set[str | int] = set()
    try:
        for row in client.fetch_league_injuries(sport):
            tid = row.get("espn_team_id")
            if tid is not None:
                team_ids.add(tid)
    except requests.RequestException:
        pass

    games = db.get_games(sport, d)
    if not games.empty:
        for _, g in games.iterrows():
            for col in ("home_team", "away_team"):
                resolved = resolve_team_in_database(db, sport, str(g[col]))
                tid = _espn_team_id_for_name(client, sport, resolved)
                if tid is not None:
                    team_ids.add(tid)

    roster_n = sync_espn_rosters_for_teams(db, sport, team_ids, client=client) if team_ids else 0
    return {"injuries": inj_count, "roster_players": roster_n}


def _espn_team_id_for_name(client: EspnInjuryClient, sport: Sport, team_name: str) -> str | int | None:
    target = team_name.lower()
    for tm in client.fetch_all_teams(sport):
        disp = str(tm.get("displayName") or "").lower()
        short = str(tm.get("shortDisplayName") or "").lower()
        if disp == target or short == target:
            return tm.get("id")
        if team_name.split()[-1].lower() in disp:
            return tm.get("id")
    return None


def sync_espn_projected_lineups(
    db: SportsDatabase,
    sport: Sport,
    *,
    match_dates: list[str],
    client: EspnInjuryClient | None = None,
) -> int:
    """
    依 ESPN roster + DB 真實上場時間/評分建立 projected_lineups。
    - NBA：依 vorp/上場時間取前 8 人
    - MLB：依 war 取前 9 人（先發投手優先）
    """
    client = client or EspnInjuryClient()

    games_by_date: dict[str, Any] = {}
    participating_teams: set[str] = set()
    for d in match_dates:
        games = db.get_games(sport, d)
        if games.empty:
            continue
        games_by_date[d] = games
        participating_teams |= set(games["home_team"]) | set(games["away_team"])

    if not participating_teams:
        return 0

    roster_cache: dict[str, list[dict[str, Any]]] = {}
    for team_name in participating_teams:
        espn_team_id = _espn_team_id_for_name(client, sport, team_name)
        if espn_team_id is None:
            continue
        try:
            roster_cache[team_name] = client.fetch_team_roster(sport, espn_team_id)
        except requests.RequestException:
            continue

    if not roster_cache:
        return 0

    n = 0
    for d, games in games_by_date.items():
        teams_today = set(games["home_team"]) | set(games["away_team"])
        for team_name in teams_today:
            athletes = roster_cache.get(team_name)
            if not athletes:
                continue

            team_players = db.get_players_by_team(sport, team_name)
            metric_col = "vorp" if sport == "nba" else "war"

            ranked: list[tuple[str, dict[str, Any], float, float]] = []
            for ath in athletes:
                pid = _athlete_id(ath)
                if not pid:
                    continue
                row = team_players[team_players["player_id"] == pid]
                metric = float(row.iloc[0][metric_col]) if not row.empty and pd.notna(row.iloc[0].get(metric_col)) else None
                if metric is None:
                    continue
                if sport == "nba":
                    minutes = float(row.iloc[0].get("usg_pct") or 0.2) * 240.0 if not row.empty else 20.0
                    if not row.empty and pd.notna(row.iloc[0].get("rolling_off_rating")):
                        minutes = max(minutes, 15.0)
                else:
                    pos = (ath.get("position") or {}).get("abbreviation") or ""
                    minutes = 6.0 if pos == "SP" else 1.0
                ranked.append((pid, ath, metric, minutes))

            if not ranked:
                continue

            ranked.sort(key=lambda x: x[2], reverse=True)
            limit = 8 if sport == "nba" else 9
            ranked = ranked[:limit]

            for i, (pid, ath, _metric, minutes) in enumerate(ranked):
                name = ath.get("displayName") or ""
                pos = (ath.get("position") or {}).get("abbreviation") or ""
                db.upsert_player(sport, pid, name, team_name, pos)
                db.upsert_projected_lineup(
                    sport,
                    team_name,
                    d,
                    pid,
                    expected_minutes=float(minutes) if sport == "nba" else None,
                    expected_innings=float(minutes) if sport == "mlb" else None,
                    is_starter=i < (5 if sport == "nba" else 1),
                )
                n += 1

    return n
