"""將 JBot 歷史賠率寫入 SQLite（含 moneyline）。"""
from __future__ import annotations

import logging
from datetime import date, timedelta

import pandas as pd

from sportsbet import config
from sportsbet.data.database import SportsDatabase
from sportsbet.data.jbot import JBotClient

logger = logging.getLogger(__name__)

Sport = str


def sync_jbot_odds_to_db(
    db: SportsDatabase,
    sport: Sport,
    *,
    start: str | None = None,
    end: str | None = None,
    mode: str = "close",
    incremental: bool = True,
) -> int:
    """抓取 JBot 區間賠率並寫入 odds 表。需 JBOT_TOKEN。"""
    if not config.JBOT_TOKEN:
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

    client = JBotClient()
    try:
        odds_df = client.fetch_date_range(sport, start_d, end_d, mode)  # type: ignore[arg-type]
    except Exception as exc:
        logger.warning("JBot 同步失敗 sport=%s: %s", sport, exc)
        return 0

    if odds_df.empty:
        return 0

    if mode in ("close", "both", "all"):
        phase_pref = "close"
    else:
        phase_pref = "open"
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
            match = games[
                (games["home_team"] == o["home_team"]) & (games["away_team"] == o["away_team"])
            ]
            if match.empty:
                continue
            gid = int(match.iloc[0]["id"])
            db.insert_odds(
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
