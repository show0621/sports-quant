"""對同對手近況（系列賽 G1→G2 等）。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sportsbet import config
from sportsbet.data.database import SportsDatabase

Sport = Literal["nba", "mlb"]

_FINISHED = ("final", "FT", "AOT", "Finished", "POST")


@dataclass(frozen=True)
class H2HRecentSide:
    wins: int
    games: int
    win_pct: float


def is_playoff_series(
    season_type: str | None,
    competition_note: str | None,
) -> bool:
    st = str(season_type or "")
    note = str(competition_note or "")
    return ("季後" in st) or ("總冠軍" in note) or ("季後" in note)


def get_h2h_recent_for_matchup(
    db: SportsDatabase,
    sport: Sport,
    home_team: str,
    away_team: str,
    before_date: str,
    *,
    limit: int | None = None,
) -> tuple[H2HRecentSide, H2HRecentSide]:
    """對同對手最近 N 場，回傳 (主隊視角, 客隊視角) 勝率。"""
    n_limit = limit or config.BAYES_H2H_RECENT_GAMES
    ph = ",".join("?" for _ in _FINISHED)
    with db.connection() as conn:
        rows = conn.execute(
            f"""
            SELECT home_team, away_team, home_score, away_score
            FROM games
            WHERE sport = ?
              AND match_date < ?
              AND home_score IS NOT NULL
              AND away_score IS NOT NULL
              AND status IN ({ph})
              AND (
                    (home_team = ? AND away_team = ?)
                 OR (home_team = ? AND away_team = ?)
              )
            ORDER BY match_date DESC
            LIMIT ?
            """,
            (
                sport,
                str(before_date)[:10],
                *_FINISHED,
                home_team,
                away_team,
                away_team,
                home_team,
                n_limit,
            ),
        ).fetchall()

    home_wins = 0
    away_wins = 0
    games = 0
    for r in rows:
        ht, at = str(r["home_team"]), str(r["away_team"])
        hs, aws = int(r["home_score"]), int(r["away_score"])
        if hs == aws:
            continue
        games += 1
        if ht == home_team:
            home_won = hs > aws
        elif at == home_team:
            home_won = aws > hs
        else:
            continue
        home_wins += int(home_won)
        away_wins += int(not home_won)

    if games <= 0:
        empty = H2HRecentSide(0, 0, 0.5)
        return empty, empty

    return (
        H2HRecentSide(home_wins, games, home_wins / games),
        H2HRecentSide(away_wins, games, away_wins / games),
    )


def resolve_matchup_recent_form(
    db: SportsDatabase,
    sport: Sport,
    home_team: str,
    away_team: str,
    match_date: str,
    home_team_recent: float,
    away_team_recent: float,
    *,
    playoff: bool,
) -> tuple[float, float, float, float, int]:
    """
    回傳 (模型用主近況, 模型用客近況, 顯示用主, 顯示用客, H2H 場數)。
    季後賽且已有對手交鋒 → 改用 H2H 近況。
    """
    if not playoff or not config.PLAYOFF_USE_H2H_RECENT:
        return home_team_recent, away_team_recent, home_team_recent, away_team_recent, 0

    h2h_h, h2h_a = get_h2h_recent_for_matchup(
        db, sport, home_team, away_team, match_date,
    )
    if h2h_h.games < config.MC_H2H_PLAYOFF_MIN_GAMES:
        return home_team_recent, away_team_recent, home_team_recent, away_team_recent, 0

    return h2h_h.win_pct, h2h_a.win_pct, h2h_h.win_pct, h2h_a.win_pct, h2h_h.games


def playoff_ensemble_weights(h2h_games: int) -> tuple[float, float, float, float]:
    """季後賽有 H2H 時提高 Beta/Bayes、降低 Log5。"""
    w_log5 = config.WEIGHT_LOG5
    w_bayes = config.WEIGHT_BAYESIAN
    w_beta = config.WEIGHT_BETA
    w_markov = config.WEIGHT_MARKOV if config.USE_MARKOV_FORM else 0.0

    if h2h_games >= 1 and config.PLAYOFF_H2H_ENSEMBLE_BOOST:
        w_log5 *= config.PLAYOFF_WEIGHT_LOG5_SCALE
        w_bayes *= config.PLAYOFF_WEIGHT_BAYES_SCALE
        w_beta *= config.PLAYOFF_WEIGHT_BETA_SCALE
        w_markov *= config.PLAYOFF_WEIGHT_MARKOV_SCALE

    w_sum = w_log5 + w_bayes + w_beta + w_markov
    if w_sum <= 0:
        return config.WEIGHT_LOG5, config.WEIGHT_BAYESIAN, config.WEIGHT_BETA, w_markov
    return w_log5, w_bayes, w_beta, w_markov
