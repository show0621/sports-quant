"""由 box score + 預計上場估算球隊得分 λ。"""
from __future__ import annotations

from typing import Literal

from sportsbet import config
from sportsbet.data.database import SportsDatabase

Sport = Literal["nba", "mlb"]

_NBA_REGULATION_MIN = 48.0


def _team_lineup_expected_points(
    db: SportsDatabase,
    sport: Sport,
    team: str,
    match_date: str,
    *,
    recent_games: int = 5,
) -> float | None:
    lineup = db.get_projected_lineup(sport, team, match_date)
    if lineup.empty:
        players = db.get_players_by_team(sport, team)
        if players.empty:
            return None
        lineup = players.head(8)
        lineup = lineup.assign(expected_minutes=28.0)

    pts_sum = 0.0
    covered_min = 0.0
    for _, row in lineup.iterrows():
        pid = row.get("player_id")
        if not pid:
            continue
        exp_min = float(row.get("expected_minutes") or 0)
        if exp_min <= 0:
            continue
        recent = db.get_player_recent_box_scores(
            sport, str(pid), match_date, limit=recent_games,
        )
        if recent.empty or recent["points"].isna().all():
            continue
        avg_pts = float(recent["points"].dropna().mean())
        pts_sum += avg_pts * (exp_min / _NBA_REGULATION_MIN)
        covered_min += exp_min
    if covered_min < 60:
        return None
    est = pts_sum
    if est < 55 or est > 150:
        return None
    return est


def player_matchup_win_prob(
    home_pts: float | None,
    away_pts: float | None,
) -> tuple[float, float] | None:
    """由兩隊球員近況估分推算 PK 勝率（需合理得分區間）。"""
    if home_pts is None or away_pts is None:
        return None
    if home_pts < 55 or away_pts < 55:
        return None
    total = home_pts + away_pts
    if total <= 0:
        return None
    return home_pts / total, away_pts / total


def blend_lambdas_with_lineup_scoring(
    db: SportsDatabase,
    sport: Sport,
    home_team: str,
    away_team: str,
    match_date: str,
    lam_home: float,
    lam_away: float,
    *,
    blend: float | None = None,
) -> tuple[float, float]:
    """將預計上場球員近況得分 blended 進 team λ。"""
    if sport != "nba":
        return lam_home, lam_away
    w = blend if blend is not None else config.LINEUP_SCORING_BLEND
    h_pts = _team_lineup_expected_points(db, sport, home_team, match_date)
    a_pts = _team_lineup_expected_points(db, sport, away_team, match_date)
    lh, la = lam_home, lam_away
    if h_pts is not None and h_pts > 0:
        lh = (1 - w) * lh + w * h_pts
    if a_pts is not None and a_pts > 0:
        la = (1 - w) * la + w * a_pts
    return max(lh, 0.1), max(la, 0.1)
