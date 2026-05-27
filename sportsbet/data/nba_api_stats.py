"""NBA 賽程/賽果：nba_api（免費、當季可用）。"""
from __future__ import annotations

import logging
import time
from typing import Literal

import pandas as pd

from sportsbet.data.api_sports import calendar_season
from sportsbet.data.database import SportsDatabase
from sportsbet.data.team_logos import canonical_team_name, espn_logo_url
from sportsbet.data.team_stats import build_team_stats_from_games, persist_team_stats

logger = logging.getLogger(__name__)

Sport = Literal["nba"]


def nba_season_param(season_start_year: int) -> str:
    """2024 → 2024-25"""
    y2 = str(season_start_year + 1)[-2:]
    return f"{season_start_year}-{y2}"


def sync_nba_season_to_database(
    db: SportsDatabase,
    season_start_year: int | None = None,
    *,
    pause_sec: float = 0.6,
) -> pd.DataFrame:
    """以 LeagueGameFinder 同步整季賽果至 SQLite。"""
    season_start_year = season_start_year or calendar_season("nba")
    season_param = nba_season_param(season_start_year)

    try:
        from nba_api.stats.endpoints import leaguegamefinder
    except ImportError as exc:
        raise RuntimeError("請安裝 nba_api：pip install nba_api") from exc

    logger.info("nba_api 同步賽季 %s", season_param)
    time.sleep(pause_sec)
    finder = leaguegamefinder.LeagueGameFinder(
        season_nullable=season_param,
        season_type_nullable="Regular Season",
        league_id_nullable="00",
    )
    raw = finder.get_data_frames()[0]
    if raw.empty:
        logger.warning("nba_api 未回傳賽季 %s 資料", season_param)
        return pd.DataFrame()

    games: dict[str, dict] = {}
    for _, row in raw.iterrows():
        gid = str(row["GAME_ID"])
        team = canonical_team_name(str(row["TEAM_NAME"]), "nba")
        matchup = str(row.get("MATCHUP", ""))
        pts = int(row["PTS"]) if pd.notna(row.get("PTS")) else None
        gdate = str(row["GAME_DATE"])[:10]

        entry = games.setdefault(
            gid,
            {
                "match_date": gdate,
                "home_team": None,
                "away_team": None,
                "home_score": None,
                "away_score": None,
                "status": "final",
            },
        )
        if "@" in matchup:
            entry["away_team"] = team
            entry["away_score"] = pts
        elif "vs." in matchup.lower():
            entry["home_team"] = team
            entry["home_score"] = pts

    rows = []
    for _gid, g in games.items():
        if not g["home_team"] or not g["away_team"]:
            continue
        if g["home_score"] is None or g["away_score"] is None:
            continue
        db.upsert_game(
            "nba",
            g["match_date"],
            g["home_team"],
            g["away_team"],
            home_score=int(g["home_score"]),
            away_score=int(g["away_score"]),
            status="final",
            home_logo_url=espn_logo_url(g["home_team"], "nba"),
            away_logo_url=espn_logo_url(g["away_team"], "nba"),
        )
        rows.append(g)

    games_df = pd.DataFrame(rows)
    stats = build_team_stats_from_games(games_df, "nba")
    if not stats.empty:
        persist_team_stats(db, "nba", stats, season=season_start_year)
    logger.info("nba_api 寫入 %d 場、%d 隊統計", len(rows), len(stats))
    return stats
