"""MLB 球員真實數據：ESPN athlete statistics API。"""
from __future__ import annotations

import logging
import time
from datetime import date
from typing import Any

import requests

from sportsbet.data.database import SportsDatabase
from sportsbet.data.espn_injuries import EspnInjuryClient, _athlete_id, normalize_espn_team
from sportsbet.data.team_logos import resolve_team_in_database

logger = logging.getLogger(__name__)

ESPN_SITE = "https://site.api.espn.com/apis/site/v2/sports"
USER_AGENT = "sports-quant/1.0 (+https://github.com/show0621/sports-quant)"
PAUSE_SEC = 0.35


def _parse_stat_value(stats_block: dict[str, Any], *names: str) -> float | None:
    for cat in stats_block.get("splits", {}).get("categories", []):
        for st in cat.get("stats", []):
            if st.get("name") in names or st.get("abbreviation") in names:
                try:
                    return float(st.get("value"))
                except (TypeError, ValueError):
                    return None
    return None


def _fetch_athlete_statistics(athlete_id: str | int, session: requests.Session) -> dict[str, Any] | None:
    url = f"{ESPN_SITE}/baseball/mlb/athletes/{athlete_id}/statistics"
    try:
        resp = session.get(url, timeout=25)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as exc:
        logger.debug("ESPN MLB stats 失敗 id=%s: %s", athlete_id, exc)
        return None


def _extract_mlb_metrics(payload: dict[str, Any]) -> dict[str, float | None]:
    """從 ESPN statistics 解析打者/投手指標。"""
    season_off = season_war = wrc = fip = hot_cold = rolling_off = None

    for split in payload.get("splits", []):
        label = str(split.get("displayName") or split.get("type") or "").lower()
        stats = split
        if "last" in label or "7" in label or "14" in label:
            rolling_ops = _parse_stat_value(stats, "OPS", "ops")
            if rolling_ops is not None:
                rolling_off = rolling_ops * 100.0
        else:
            ops = _parse_stat_value(stats, "OPS", "ops")
            avg = _parse_stat_value(stats, "AVG", "avg")
            era = _parse_stat_value(stats, "ERA", "era")
            whip = _parse_stat_value(stats, "WHIP", "whip")
            if ops is not None:
                season_off = ops * 100.0
                wrc = ops * 100.0
                season_war = max(0.0, (ops - 0.720) * 8.0)
            elif era is not None:
                season_off = max(0.0, (5.0 - era) * 20.0)
                fip = era
                season_war = max(0.0, (4.5 - era) * 1.2)
            elif avg is not None:
                season_off = avg * 300.0
                wrc = avg * 300.0

    if rolling_off is not None and season_off is not None and season_off > 0:
        hot_cold = (rolling_off - season_off) / season_off

    return {
        "rolling_off_rating": rolling_off if rolling_off is not None else season_off,
        "hot_cold_index": hot_cold,
        "war": season_war,
        "wrc_plus": wrc,
        "fip": fip,
        "off_proxy": season_off,
    }


def sync_mlb_player_stats(
    db: SportsDatabase,
    *,
    client: EspnInjuryClient | None = None,
    season: str | None = None,
) -> int:
    """同步 MLB 全聯盟 roster 球員 ESPN 真實統計。"""
    client = client or EspnInjuryClient()
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    today = date.today().isoformat()
    season = season or str(date.today().year)
    n = 0

    for tm in client.fetch_all_teams("mlb"):
        tid = tm.get("id")
        if not tid:
            continue
        team_name = normalize_espn_team(str(tm.get("displayName") or ""), "mlb")
        team = resolve_team_in_database(db, "mlb", team_name)
        try:
            roster = client.fetch_team_roster("mlb", tid)
        except Exception as exc:
            logger.warning("ESPN MLB roster 失敗 team=%s: %s", team, exc)
            continue

        for ath in roster:
            pid = _athlete_id(ath)
            if not pid:
                continue
            name = str(ath.get("displayName") or "")
            pos = (ath.get("position") or {}).get("abbreviation") or ""
            db.upsert_player("mlb", pid, name, team, pos)

            time.sleep(PAUSE_SEC)
            payload = _fetch_athlete_statistics(str(ath.get("id")), session)
            if not payload:
                continue
            metrics = _extract_mlb_metrics(payload)
            if metrics["off_proxy"] is None and metrics["war"] is None:
                continue

            db.upsert_player_stats(
                "mlb",
                pid,
                today,
                season=season,
                window_games=10,
                war=metrics["war"],
                wrc_plus=metrics["wrc_plus"],
                fip=metrics["fip"],
                rolling_off_rating=metrics["rolling_off_rating"],
                hot_cold_index=metrics["hot_cold_index"],
            )
            n += 1

    logger.info("MLB 球員真實統計同步完成 count=%d", n)
    return n
