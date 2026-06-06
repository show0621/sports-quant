"""G1 等完賽後：box score 同步 + 同系列下一場（G2）預測重算。"""
from __future__ import annotations

import logging
from typing import Literal

import pandas as pd

from sportsbet.data.database import SportsDatabase

logger = logging.getLogger(__name__)

Sport = Literal["nba", "mlb"]


def refresh_after_finals(
    db: SportsDatabase,
    sport: Sport,
    finalized_game_ids: list[int],
) -> dict[str, int]:
    """
    新完賽場次觸發：
    1. 優先同步該場 box score（NBA）
    2. 重算同對手下一場 scheduled 預測（如 6/4 G1 → 6/6 G2）
    """
    out: dict[str, int] = {
        "post_final_box_games": 0,
        "post_final_box_players": 0,
        "post_final_reforecast": 0,
    }
    if not finalized_game_ids:
        return out

    finals = db.get_games_by_ids(finalized_game_ids)
    if finals.empty:
        return out

    if sport == "nba":
        from sportsbet.data.boxscore_sync import (
            sync_box_scores_for_games,
            sync_nba_box_scores,
        )

        direct = sync_box_scores_for_games(db, finals)
        out["post_final_box_games"] += int(direct.get("boxscore_games", 0))
        out["post_final_box_players"] += int(direct.get("boxscore_players", 0))
        # 順便補齊其他季後賽缺 box 的場次
        bs = sync_nba_box_scores(db, max_finals=20, max_regular=0)
        out["post_final_box_games"] += int(bs.get("boxscore_games", 0))
        out["post_final_box_players"] += int(bs.get("boxscore_players", 0))

    rematch = db.get_rematch_games_after_finals(sport, finalized_game_ids)
    if not rematch.empty:
        from sportsbet.services.prediction_service import PredictionService

        n = PredictionService(db).recompute_scheduled_games(sport, rematch)
        out["post_final_reforecast"] = n
        logger.info(
            "post-final refresh sport=%s finals=%s rematch=%d reforecast=%d",
            sport, finalized_game_ids, len(rematch), n,
        )

    return out
