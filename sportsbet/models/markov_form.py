"""馬可夫鏈近況模型：Hot / Neutral / Cold 狀態轉移與對戰勝率。"""
from __future__ import annotations

from typing import Literal

import numpy as np
import pandas as pd

from sportsbet import config
from sportsbet.data.context_features import MatchContext

Sport = Literal["nba", "mlb"]

STATES = ("cold", "neutral", "hot")
_STATE_IDX = {s: i for i, s in enumerate(STATES)}


def _default_transition() -> np.ndarray:
    """3x3 轉移矩陣 P(next | current)，列和=1。"""
    # cold→neutral 較易，hot 延續性較高
    return np.array([
        [0.35, 0.45, 0.20],  # from cold
        [0.25, 0.50, 0.25],  # from neutral
        [0.20, 0.40, 0.40],  # from hot
    ])


def _default_matchup_table(sport: Sport) -> np.ndarray:
    """matchup[home_state, away_state] = P(home wins)."""
    base = 0.54 if sport == "nba" else 0.535
    t = np.full((3, 3), base)
    for hi, hs in enumerate(STATES):
        for ai, aws in enumerate(STATES):
            adj = (hi - ai) * 0.06  # home hot vs away cold
            t[hi, ai] = min(max(base + adj, 0.25), 0.75)
    return t


def estimate_transition_from_games(
    games_df: pd.DataFrame,
    sport: Sport,
    db: SportsDatabase | None = None,
) -> np.ndarray:
    """
    從歷史完賽估計狀態轉移（每隊依時間序列）。
    games_df 需含 home_team, away_team, home_score, away_score, match_date。
    """
    if games_df.empty or len(games_df) < 50:
        return _default_transition()

    from sportsbet.data.context_features import _markov_state, _team_game_results
    from sportsbet.data.database import SportsDatabase

    # 簡化：用全聯盟聚合的 streak→next game win rate 近似
    counts = np.zeros((3, 3))
    db_conn = db or SportsDatabase()
    teams = set(games_df["home_team"]) | set(games_df["away_team"])
    for team in list(teams)[:40]:
        dates = sorted(games_df["match_date"].unique())
        if len(dates) < 10:
            continue
        for i in range(5, min(len(dates), 80)):
            d = str(dates[i])[:10]
            res = _team_game_results(db_conn, sport, team, d, limit=8)
            if len(res) < 3:
                continue
            w5 = sum(1 for g in res[:5] if g["won"]) / min(5, len(res))
            streak = 0
            for g in res:
                if g["won"] == res[0]["won"]:
                    streak += 1 if g["won"] else -1
                else:
                    break
            s_from = _STATE_IDX[_markov_state(w5, streak)]
            # next game outcome
            s_to = _STATE_IDX["neutral"]
            if res[0]["won"]:
                s_to = _STATE_IDX["hot"] if w5 >= 0.6 else _STATE_IDX["neutral"]
            else:
                s_to = _STATE_IDX["cold"] if w5 <= 0.4 else _STATE_IDX["neutral"]
            counts[s_from, s_to] += 1

    row_sums = counts.sum(axis=1, keepdims=True)
    row_sums[row_sums == 0] = 1
    trans = counts / row_sums
    if trans.sum() < 0.5:
        return _default_transition()
    return trans


def markov_matchup_win_prob(
    ctx: MatchContext,
    sport: Sport,
    *,
    transition: np.ndarray | None = None,
    matchup_table: np.ndarray | None = None,
) -> tuple[float, float]:
    """
    依主客當前馬可夫狀態查表得 P(home wins)，再正規化。
    """
    trans = transition if transition is not None else _default_transition()
    table = matchup_table if matchup_table is not None else _default_matchup_table(sport)

    hi = _STATE_IDX.get(ctx.home_markov_state, 1)
    ai = _STATE_IDX.get(ctx.away_markov_state, 1)

    p_home = float(table[hi, ai])

    # 背靠背：客隊 B2B 略利主隊
    if ctx.away_back_to_back and not ctx.home_back_to_back:
        p_home += config.MARKOV_B2B_EDGE
    elif ctx.home_back_to_back and not ctx.away_back_to_back:
        p_home -= config.MARKOV_B2B_EDGE

    # 休息差
    rest_diff = ctx.home_rest_days - ctx.away_rest_days
    p_home += rest_diff * config.MARKOV_REST_EDGE_PER_DAY

    p_home = min(max(p_home, 0.05), 0.95)
    return p_home, 1.0 - p_home
