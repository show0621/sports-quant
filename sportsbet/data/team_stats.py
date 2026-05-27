"""由賽果 DataFrame 彙總球隊場均得分/失分。"""
from __future__ import annotations

import pandas as pd

from sportsbet import config

FINISHED_STATUS = {"FT", "AOT", "Finished", "AFTER_OT", "POST", "closed", "final"}


def _recent_win_pct(finished: pd.DataFrame, n_games: int) -> dict[str, float]:
    if finished.empty:
        return {}
    date_col = "match_date" if "match_date" in finished.columns else "date"
    if date_col not in finished.columns:
        return {}
    df = finished.copy()
    df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
    df = df.sort_values(date_col)
    results: dict[str, list[int]] = {}

    def _push(team: str, won: int) -> None:
        results.setdefault(team, []).append(won)

    for _, row in df.iterrows():
        hs, aws = float(row["home_score"]), float(row["away_score"])
        _push(row["home_team"], int(hs > aws))
        _push(row["away_team"], int(aws > hs))

    return {team: sum(wins[-n_games:]) / len(wins[-n_games:]) for team, wins in results.items() if wins}


def build_team_stats_from_games(games_df: pd.DataFrame, sport: str) -> pd.DataFrame:
    """由比賽結果彙總各隊 rs/ra、勝率、近況。"""
    if games_df.empty:
        return pd.DataFrame()

    finished = games_df[games_df["status"].astype(str).str.lower().isin(
        {s.lower() for s in FINISHED_STATUS}
    )].copy()
    finished = finished.dropna(subset=["home_score", "away_score"])
    if "match_date" not in finished.columns and "date" in finished.columns:
        finished = finished.rename(columns={"date": "match_date"})
    recent = _recent_win_pct(finished, config.BAYES_RECENT_GAMES)

    stats: dict[str, dict[str, float]] = {}

    def _add(team: str, scored: float, allowed: float, won: bool) -> None:
        if team not in stats:
            stats[team] = {"games": 0, "wins": 0, "runs_scored": 0.0, "runs_allowed": 0.0}
        s = stats[team]
        s["games"] += 1
        s["wins"] += int(won)
        s["runs_scored"] += scored
        s["runs_allowed"] += allowed

    for _, row in finished.iterrows():
        hs, aws = float(row["home_score"]), float(row["away_score"])
        _add(str(row["home_team"]), hs, aws, hs > aws)
        _add(str(row["away_team"]), aws, hs, aws > hs)

    records = []
    for team, s in stats.items():
        g = s["games"] or 1
        records.append(
            {
                "team": team,
                "sport": sport,
                "games": int(s["games"]),
                "wins": int(s["wins"]),
                "losses": int(s["games"] - s["wins"]),
                "win_pct": s["wins"] / g,
                "recent_win_pct": recent.get(team, s["wins"] / g),
                "runs_scored": s["runs_scored"],
                "runs_allowed": s["runs_allowed"],
                "rs_per_game": s["runs_scored"] / g,
                "ra_per_game": s["runs_allowed"] / g,
            }
        )
    return pd.DataFrame(records)


def persist_team_stats(
    db,
    sport: str,
    stats_df: pd.DataFrame,
    *,
    season: str | int | None,
) -> None:
    season_s = str(season) if season is not None else ""
    for _, row in stats_df.iterrows():
        db.upsert_team_stats(
            sport,
            str(row["team"]),
            float(row["rs_per_game"]),
            float(row["ra_per_game"]),
            season=season_s,
            games=int(row["games"]),
            win_pct=float(row["win_pct"]),
            recent_win_pct=float(row.get("recent_win_pct", row["win_pct"])),
        )
