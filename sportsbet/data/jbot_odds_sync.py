"""將 JBot 歷史賠率寫入 SQLite（含 moneyline）。"""
from __future__ import annotations

import logging
from datetime import date, timedelta

import pandas as pd

from sportsbet import config
from sportsbet.data.database import SportsDatabase
from sportsbet.data.jbot import JBotClient
from sportsbet.data.team_logos import resolve_team_in_database

logger = logging.getLogger(__name__)

Sport = str


def _match_game_id(
    db: SportsDatabase,
    sport: Sport,
    games: pd.DataFrame,
    home_team: str,
    away_team: str,
) -> int | None:
    """JBot 中文/英文隊名 → DB game_id（含主客對調）。"""
    if games.empty:
        return None
    h = resolve_team_in_database(db, sport, str(home_team))  # type: ignore[arg-type]
    a = resolve_team_in_database(db, sport, str(away_team))  # type: ignore[arg-type]

    for gh, ga in ((h, a), (a, h)):
        match = games[(games["home_team"] == gh) & (games["away_team"] == ga)]
        if not match.empty:
            return int(match.iloc[0]["id"])

    h_last = h.split()[-1].lower() if h else ""
    a_last = a.split()[-1].lower() if a else ""
    if h_last and a_last:
        for _, row in games.iterrows():
            if (
                row["home_team"].split()[-1].lower() == h_last
                and row["away_team"].split()[-1].lower() == a_last
            ) or (
                row["home_team"].split()[-1].lower() == a_last
                and row["away_team"].split()[-1].lower() == h_last
            ):
                return int(row["id"])
    return None


def sync_jbot_odds_to_db(
    db: SportsDatabase,
    sport: Sport,
    *,
    start: str | None = None,
    end: str | None = None,
    mode: str = "close",
    incremental: bool = True,
) -> int:
    """抓取 JBot 區間賠率並寫入 odds 表（moneyline / spread / total）。需 JBOT_TOKEN。"""
    if not config.jbot_configured():
        logger.info("未設定 JBOT_TOKEN，略過 JBot 歷史賠率")
        return 0

    end_d = date.fromisoformat(end) if end else date.today() - timedelta(days=1)
    if start:
        start_d = date.fromisoformat(start)
    elif incremental:
        meta = db.get_backtest_sync_meta(sport, "jbot_odds_synced_to")  # type: ignore[arg-type]
        if meta:
            try:
                start_d = date.fromisoformat(meta[:10]) - timedelta(days=3)
            except ValueError:
                start_d = end_d - timedelta(days=min(config.BACKTEST_DAYS, 120))
        else:
            start_d = end_d - timedelta(days=min(config.BACKTEST_DAYS, 120))
    else:
        start_d = end_d - timedelta(days=min(config.BACKTEST_DAYS, 365))

    max_days = config.JBOT_MAX_DAYS_PER_RUN
    if (end_d - start_d).days > max_days:
        start_d = end_d - timedelta(days=max_days)
        logger.info("JBot 抓取區間限制為 %d 天（JBOT_MAX_DAYS_PER_RUN）", max_days)

    client = JBotClient()
    try:
        odds_df = client.fetch_date_range(sport, start_d, end_d, mode)  # type: ignore[arg-type]
    except Exception as exc:
        logger.warning("JBot 同步失敗 sport=%s: %s", sport, exc)
        return 0

    if odds_df.empty:
        logger.info("JBot 無資料 sport=%s %s~%s", sport, start_d, end_d)
        return 0

    phase_pref = "close" if mode in ("close", "both", "all") else "open"
    if "odds_phase" in odds_df.columns:
        phased = odds_df[odds_df["odds_phase"] == phase_pref]
        if not phased.empty:
            odds_df = phased

    n = 0
    for match_date, grp in odds_df.groupby(odds_df["match_date"].astype(str).str[:10]):
        games = db.get_games(sport, str(match_date))
        if games.empty:
            continue
        db.clear_odds_for_date(sport, str(match_date), bookmaker="jbot")
        for _, o in grp.iterrows():
            gid = _match_game_id(db, sport, games, o["home_team"], o["away_team"])
            if gid is None:
                continue
            db.upsert_odds(
                gid,
                str(o["market"]),
                str(o["selection"]),
                float(o["odds"]),
                handicap=float(o["handicap"]) if pd.notna(o.get("handicap")) else None,
                bookmaker="jbot",
                odds_phase=str(o.get("odds_phase", phase_pref)),
            )
            n += 1

    db.set_backtest_sync_meta(sport, "jbot_odds_synced_to", end_d.isoformat())  # type: ignore[arg-type]
    logger.info("JBot 寫入 sport=%s rows=%d (%s~%s)", sport, n, start_d, end_d)
    return n


def sync_jbot_upcoming_odds(
    db: SportsDatabase,
    sport: Sport,
    *,
    days_ahead: int = 14,
    mode: str = "close",
) -> int:
    """同步今日～未來 N 天 JBot 盤口（不讓分/讓分/大小），供賽事預測頁使用。"""
    if not config.jbot_configured():
        return 0

    today = date.today()
    end_d = today + timedelta(days=days_ahead)
    client = JBotClient()
    try:
        odds_df = client.fetch_date_range(sport, today, end_d, mode)  # type: ignore[arg-type]
    except Exception as exc:
        logger.warning("JBot upcoming 失敗 sport=%s: %s", sport, exc)
        return 0

    if odds_df.empty:
        return 0

    phase_pref = "close" if mode in ("close", "both", "all") else "open"
    if "odds_phase" in odds_df.columns:
        phased = odds_df[odds_df["odds_phase"] == phase_pref]
        if not phased.empty:
            odds_df = phased

    n = 0
    for match_date, grp in odds_df.groupby(odds_df["match_date"].astype(str).str[:10]):
        games = db.get_games(sport, str(match_date))
        if games.empty:
            continue
        for _, o in grp.iterrows():
            gid = _match_game_id(db, sport, games, o["home_team"], o["away_team"])
            if gid is None:
                continue
            db.upsert_odds(
                gid,
                str(o["market"]),
                str(o["selection"]),
                float(o["odds"]),
                handicap=float(o["handicap"]) if pd.notna(o.get("handicap")) else None,
                bookmaker="jbot",
                odds_phase=str(o.get("odds_phase", phase_pref)),
            )
            n += 1
    logger.info("JBot upcoming sport=%s rows=%d (%s~%s)", sport, n, today, end_d)
    return n
