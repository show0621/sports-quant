"""由 box score + 預計上場估算球隊得分 λ。"""
from __future__ import annotations

from typing import Literal

from sportsbet import config
from sportsbet.data.database import SportsDatabase

Sport = Literal["nba", "mlb"]


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

    total_min = float(lineup["expected_minutes"].fillna(0).sum()) or 240.0
    pts_sum = 0.0
    weight_sum = 0.0
    for _, row in lineup.iterrows():
        pid = row.get("player_id")
        if not pid:
            continue
        recent = db.get_player_recent_box_scores(
            sport, str(pid), match_date, limit=recent_games,
        )
        if recent.empty or recent["points"].isna().all():
            continue
        avg_pts = float(recent["points"].dropna().mean())
        share = float(row.get("expected_minutes") or 0) / total_min
        if share <= 0:
            continue
        pts_sum += avg_pts * share
        weight_sum += share
    if weight_sum < 0.25:
        return None
    return pts_sum / weight_sum


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
