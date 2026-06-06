"""NBA box score 同步：優先總冠軍賽，再例行賽回補。"""
from __future__ import annotations

import logging
import time
from datetime import date, timedelta
from typing import Literal

from sportsbet import config
from sportsbet.data.database import SportsDatabase
from sportsbet.data.espn_boxscore import EspnBoxScoreClient

logger = logging.getLogger(__name__)

Sport = Literal["nba"]


def sync_box_scores_for_games(
    db: SportsDatabase,
    games: pd.DataFrame,
    *,
    pause_sec: float = 0.15,
) -> dict[str, int]:
    """同步指定完賽場次的 box score（G1 完賽後立即拉球員數據）。"""
    if games.empty:
        return {"boxscore_games": 0, "boxscore_players": 0}
    client = EspnBoxScoreClient()
    synced_games = 0
    player_rows = 0
    for _, g in games.iterrows():
        n = client.sync_game_box_score(db, "nba", g)
        if n > 0:
            synced_games += 1
            player_rows += n
        time.sleep(pause_sec)
    return {"boxscore_games": synced_games, "boxscore_players": player_rows}


def sync_nba_box_scores(
    db: SportsDatabase,
    *,
    regular_days_back: int | None = None,
    max_finals: int = 50,
    max_regular: int = 150,
    pause_sec: float = 0.2,
) -> dict[str, int]:
    """
    1. 優先：總冠軍賽 / 季後賽缺 box score 的完賽場次
    2. 其次：例行賽近 N 天完賽場次
    """
    client = EspnBoxScoreClient()
    regular_days = regular_days_back or config.BOXSCORE_REGULAR_DAYS_BACK
    since_regular = (date.today() - timedelta(days=regular_days)).isoformat()

    finals = db.get_games_missing_box_scores("nba", finals_only=True, limit=max_finals)
    regular = db.get_games_missing_box_scores(
        "nba", since_date=since_regular, finals_only=False, limit=max_regular,
    )
    if not regular.empty and not finals.empty:
        fin_ids = set(finals["id"].tolist())
        regular = regular[~regular["id"].isin(fin_ids)]

    synced_games = 0
    player_rows = 0

    for label, df in (("finals", finals), ("regular", regular)):
        if df.empty:
            continue
        for _, g in df.iterrows():
            n = client.sync_game_box_score(db, "nba", g)
            if n > 0:
                synced_games += 1
                player_rows += n
            time.sleep(pause_sec)
        logger.info("boxscore sync %s games=%d rows=%d", label, synced_games, player_rows)

    db.set_backtest_sync_meta("nba", "boxscores_synced_at", date.today().isoformat())
    return {
        "boxscore_games": synced_games,
        "boxscore_players": player_rows,
        "boxscore_finals_queued": len(finals),
        "boxscore_regular_queued": len(regular),
    }
