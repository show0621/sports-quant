"""從 DB 賽程計算情境特徵：休息、背靠背、連勝/連敗、主客場、對戰歷史。"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

import pandas as pd

from sportsbet.data.database import SportsDatabase

Sport = Literal["nba", "mlb"]


@dataclass
class MatchContext:
    home_team: str
    away_team: str
    match_date: str
    home_rest_days: int
    away_rest_days: int
    home_back_to_back: bool
    away_back_to_back: bool
    home_streak: int  # 正=連勝，負=連敗
    away_streak: int
    home_last5_win_pct: float
    away_last5_win_pct: float
    home_home_win_pct: float  # 本季主場
    away_away_win_pct: float  # 本季客場
    h2h_home_win_pct: float | None  # 近 3 年對戰主場勝率
    home_markov_state: str
    away_markov_state: str


def _team_game_results(
    db: SportsDatabase,
    sport: Sport,
    team: str,
    before_date: str,
    *,
    limit: int = 30,
) -> list[dict]:
    """該隊 before_date 之前的完賽，由近到遠。"""
    with db.connection() as conn:
        rows = conn.execute(
            """
            SELECT match_date, home_team, away_team, home_score, away_score
            FROM games
            WHERE sport = ?
              AND match_date < ?
              AND home_score IS NOT NULL
              AND away_score IS NOT NULL
              AND (home_team = ? OR away_team = ?)
            ORDER BY match_date DESC
            LIMIT ?
            """,
            (sport, before_date, team, team, limit),
        ).fetchall()
    out: list[dict] = []
    for r in rows:
        ht, at = r["home_team"], r["away_team"]
        hs, aws = int(r["home_score"]), int(r["away_score"])
        if ht == team:
            won = hs > aws
            loc = "home"
        else:
            won = aws > hs
            loc = "away"
        out.append({"date": str(r["match_date"])[:10], "won": won, "location": loc})
    return out


def _rest_days(results: list[dict], match_date: str) -> tuple[int, bool]:
    if not results:
        return 3, False
    last = date.fromisoformat(results[0]["date"])
    cur = date.fromisoformat(match_date)
    rest = max(0, (cur - last).days - 1)
    b2b = rest == 0
    return rest, b2b


def _streak(results: list[dict]) -> int:
    if not results:
        return 0
    streak = 0
    first_won = results[0]["won"]
    for g in results:
        if g["won"] == first_won:
            streak += 1 if first_won else -1
        else:
            break
    return streak


def _win_pct(results: list[dict], n: int = 5) -> float:
    subset = results[:n]
    if not subset:
        return 0.5
    return sum(1 for g in subset if g["won"]) / len(subset)


def _split_win_pct(results: list[dict], location: str) -> float:
    subset = [g for g in results if g["location"] == location]
    if not subset:
        return 0.5
    return sum(1 for g in subset if g["won"]) / len(subset)


def _markov_state(win_pct5: float, streak: int) -> str:
    if streak >= 3 or win_pct5 >= 0.7:
        return "hot"
    if streak <= -3 or win_pct5 <= 0.3:
        return "cold"
    return "neutral"


def _h2h_home_win_pct(
    db: SportsDatabase,
    sport: Sport,
    home: str,
    away: str,
    before_date: str,
    *,
    years: int = 3,
) -> float | None:
    start = (date.fromisoformat(before_date) - timedelta(days=365 * years)).isoformat()
    with db.connection() as conn:
        rows = conn.execute(
            """
            SELECT home_score, away_score FROM games
            WHERE sport = ? AND match_date >= ? AND match_date < ?
              AND home_team = ? AND away_team = ?
              AND home_score IS NOT NULL
            ORDER BY match_date DESC
            LIMIT 10
            """,
            (sport, start, before_date, home, away),
        ).fetchall()
    if not rows:
        return None
    wins = sum(1 for r in rows if int(r["home_score"]) > int(r["away_score"]))
    return wins / len(rows)


def build_match_context(
    db: SportsDatabase,
    sport: Sport,
    home_team: str,
    away_team: str,
    match_date: str,
) -> MatchContext:
    home_res = _team_game_results(db, sport, home_team, match_date)
    away_res = _team_game_results(db, sport, away_team, match_date)
    h_rest, h_b2b = _rest_days(home_res, match_date)
    a_rest, a_b2b = _rest_days(away_res, match_date)
    h5 = _win_pct(home_res, 5)
    a5 = _win_pct(away_res, 5)
    hs = _streak(home_res)
    ast = _streak(away_res)
    return MatchContext(
        home_team=home_team,
        away_team=away_team,
        match_date=match_date,
        home_rest_days=h_rest,
        away_rest_days=a_rest,
        home_back_to_back=h_b2b,
        away_back_to_back=a_b2b,
        home_streak=hs,
        away_streak=ast,
        home_last5_win_pct=h5,
        away_last5_win_pct=a5,
        home_home_win_pct=_split_win_pct(home_res, "home"),
        away_away_win_pct=_split_win_pct(away_res, "away"),
        h2h_home_win_pct=_h2h_home_win_pct(db, sport, home_team, away_team, match_date),
        home_markov_state=_markov_state(h5, hs),
        away_markov_state=_markov_state(a5, ast),
    )
