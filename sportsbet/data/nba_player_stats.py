"""NBA 球員真實高階數據：nba_api + ESPN roster 對齊。"""
from __future__ import annotations

import logging
import re
import time
from datetime import date
from typing import Any

import pandas as pd

from sportsbet.data.api_sports import calendar_season
from sportsbet.data.database import SportsDatabase
from sportsbet.data.espn_injuries import EspnInjuryClient, _athlete_id
from sportsbet.data.nba_api_stats import nba_season_param
from sportsbet.data.team_logos import canonical_team_name, resolve_team_in_database

logger = logging.getLogger(__name__)

ROLLING_WINDOW = 10
MIN_MINUTES = 12.0
GAMELOG_TOP_N = 150
PAUSE_SEC = 0.65


def _norm_name(name: str) -> str:
    s = re.sub(r"[^a-z0-9 ]", "", str(name).lower())
    s = re.sub(r"\b(jr|sr|ii|iii|iv)\b", "", s)
    return " ".join(s.split())


def _build_espn_name_index(client: EspnInjuryClient) -> dict[str, tuple[str, str, str]]:
    """norm_name -> (espn_player_id, display_name, team)."""
    index: dict[str, tuple[str, str, str]] = {}
    for tm in client.fetch_all_teams("nba"):
        tid = tm.get("id")
        if not tid:
            continue
        team = canonical_team_name(str(tm.get("displayName") or ""), "nba")
        try:
            roster = client.fetch_team_roster("nba", tid)
        except Exception as exc:
            logger.warning("ESPN roster 失敗 team=%s: %s", team, exc)
            continue
        for ath in roster:
            pid = _athlete_id(ath)
            if not pid:
                continue
            name = str(ath.get("displayName") or "")
            key = _norm_name(name)
            if key:
                index[key] = (pid, name, team)
    return index


def _off_rating_from_gamelog(player_id: int, season_param: str) -> tuple[float | None, float | None]:
    """回傳 (season_off_proxy, rolling_off_proxy) 以每 48 分鐘得分率估算。"""
    try:
        from nba_api.stats.endpoints import playergamelog
    except ImportError:
        return None, None

    time.sleep(PAUSE_SEC)
    try:
        log = playergamelog.PlayerGameLog(
            player_id=player_id,
            season=season_param,
            season_type_all_star="Regular Season",
        ).get_data_frames()[0]
    except Exception as exc:
        logger.debug("PlayerGameLog 失敗 id=%s: %s", player_id, exc)
        return None, None

    if log.empty:
        return None, None

    def _rate(row: pd.Series) -> float | None:
        mins = float(row.get("MIN") or 0)
        if mins <= 0:
            return None
        pts = float(row.get("PTS") or 0)
        return pts / mins * 48.0

    rates = log.apply(_rate, axis=1).dropna()
    if rates.empty:
        return None, None
    season_avg = float(rates.mean())
    rolling = float(rates.head(ROLLING_WINDOW).mean())
    return season_avg, rolling


def sync_nba_player_stats(
    db: SportsDatabase,
    *,
    season_start_year: int | None = None,
    client: EspnInjuryClient | None = None,
) -> int:
    """
    同步 NBA 球員進階數據至 player_advanced_stats（espn-{id} 鍵）。
    指標來源：nba_api LeagueDashPlayerStats（OFF/DEF/NET/USG）+ 近 10 場 game log。
    """
    try:
        from nba_api.stats.endpoints import leaguedashplayerstats
    except ImportError as exc:
        raise RuntimeError("請安裝 nba_api：pip install nba_api") from exc

    season_start_year = season_start_year or calendar_season("nba")
    season_param = nba_season_param(season_start_year)
    today = date.today().isoformat()
    client = client or EspnInjuryClient()
    espn_index = _build_espn_name_index(client)

    time.sleep(PAUSE_SEC)
    advanced = leaguedashplayerstats.LeagueDashPlayerStats(
        season=season_param,
        season_type_all_star="Regular Season",
        measure_type_detailed_defense="Advanced",
        per_mode_detailed="PerGame",
    ).get_data_frames()[0]

    time.sleep(PAUSE_SEC)
    base = leaguedashplayerstats.LeagueDashPlayerStats(
        season=season_param,
        season_type_all_star="Regular Season",
        measure_type_detailed_defense="Base",
        per_mode_detailed="PerGame",
    ).get_data_frames()[0]

    if advanced.empty or base.empty:
        logger.warning("nba_api 球員統計為空 season=%s", season_param)
        return 0

    merged = advanced.merge(
        base[["PLAYER_ID", "PLAYER_NAME", "TEAM_ID", "TEAM_ABBREVIATION", "MIN", "GP"]],
        on="PLAYER_ID",
        how="inner",
        suffixes=("", "_base"),
    )
    merged = merged[merged["MIN"] >= MIN_MINUTES].sort_values("MIN", ascending=False)

    gamelog_targets = merged.head(GAMELOG_TOP_N)
    rolling_cache: dict[int, tuple[float | None, float | None]] = {}
    for _, row in gamelog_targets.iterrows():
        pid = int(row["PLAYER_ID"])
        rolling_cache[pid] = _off_rating_from_gamelog(pid, season_param)

    n = 0
    for _, row in merged.iterrows():
        nba_name = str(row["PLAYER_NAME"])
        key = _norm_name(nba_name)
        match = espn_index.get(key)
        if not match:
            continue
        espn_pid, display_name, espn_team = match
        team_abbr = str(row.get("TEAM_ABBREVIATION") or "")
        if team_abbr:
            team = canonical_team_name(team_abbr, "nba")
        else:
            team = resolve_team_in_database(db, "nba", espn_team)

        off_rating = float(row["OFF_RATING"]) if pd.notna(row.get("OFF_RATING")) else None
        def_rating = float(row["DEF_RATING"]) if pd.notna(row.get("DEF_RATING")) else None
        net_rating = float(row["NET_RATING"]) if pd.notna(row.get("NET_RATING")) else None
        usg = float(row["USG_PCT"]) if pd.notna(row.get("USG_PCT")) else None
        pace = float(row["PACE"]) if pd.notna(row.get("PACE")) else None
        pie = float(row["PIE"]) if pd.notna(row.get("PIE")) else None

        bpm_proxy = (net_rating / 5.0) if net_rating is not None else None
        vorp_proxy = (net_rating / 3.5) if net_rating is not None else None

        nba_pid = int(row["PLAYER_ID"])
        season_off, rolling_off = rolling_cache.get(nba_pid, (None, None))
        rolling_val = rolling_off if rolling_off is not None else off_rating
        hot_cold = None
        if rolling_off is not None and off_rating is not None and off_rating > 0:
            hot_cold = (rolling_off - off_rating) / off_rating

        pos = ""
        db.upsert_player("nba", espn_pid, display_name or nba_name, team, pos)
        db.upsert_player_stats(
            "nba",
            espn_pid,
            today,
            season=str(season_start_year),
            window_games=ROLLING_WINDOW,
            bpm=bpm_proxy,
            vorp=vorp_proxy,
            usg_pct=usg,
            pace=pace,
            rolling_off_rating=rolling_val,
            hot_cold_index=hot_cold,
        )
        n += 1

    logger.info("NBA 球員真實統計同步完成 count=%d season=%s", n, season_param)
    return n
