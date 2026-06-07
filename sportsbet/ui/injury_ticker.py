"""傷兵警報跑馬燈。"""
from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from sportsbet.data.database import SportsDatabase
from sportsbet.data.provider import api_key_configured
from sportsbet.data.team_logos import canonical_team_name

_STATUS_RANK = {"Out": 0, "Doubtful": 1, "Questionable": 2, "Probable": 3}


def _teams_playing_today(db: SportsDatabase, sport: str) -> set[str]:
    games = db.get_games(sport, date.today().isoformat())
    if games.empty:
        return set()
    return set(games["home_team"]) | set(games["away_team"])


def _dedupe_injuries(inj: pd.DataFrame) -> pd.DataFrame:
    """每位球員只保留一筆，優先顯示較嚴重狀態。"""
    if inj.empty:
        return inj
    df = inj.copy()
    df["_rank"] = df["status"].map(lambda s: _STATUS_RANK.get(str(s), 99))
    df = df.sort_values(["player_id", "_rank"]).drop_duplicates(subset=["player_id"], keep="first")
    return df.drop(columns=["_rank"], errors="ignore")


def _statshub_injuries_for_teams(db: SportsDatabase, sport: str, teams: set[str]) -> pd.DataFrame:
    """從 StatsHub 快照讀取傷兵（ESPN 無資料時的備援）。"""
    if sport != "nba" or not teams:
        return pd.DataFrame()

    rows: list[dict[str, object]] = []
    with db.connection() as conn:
        games = conn.execute(
            """
            SELECT g.id, g.home_team, g.away_team
            FROM games g
            WHERE g.sport = ?
              AND g.match_date = date('now')
              AND g.sportradar_match_id IS NOT NULL
              AND TRIM(g.sportradar_match_id) != ''
            """,
            (sport,),
        ).fetchall()

    for g in games:
        home = str(g["home_team"])
        away = str(g["away_team"])
        if home not in teams and away not in teams:
            continue
        try:
            getter = getattr(db, "get_statshub_snapshot", None)
            if callable(getter):
                snap = getter(int(g["id"]))
            else:
                from sportsbet.ui.statshub_panel import _compat_get_statshub_snapshot

                snap = _compat_get_statshub_snapshot(db, int(g["id"]))
        except Exception:
            snap = None
        if not snap or not isinstance(snap.get("payload"), dict):
            continue
        merged = snap["payload"].get("merged") or {}
        side_team = {"home": home, "away": away}
        for inj in merged.get("injuries") or []:
            team = side_team.get(str(inj.get("side")), home)
            if team not in teams:
                continue
            rows.append(
                {
                    "team": team,
                    "player_name": inj.get("name"),
                    "status": inj.get("status") or "Out",
                    "injury_type": inj.get("injury_type"),
                    "source": "statshub",
                    "player_id": inj.get("player_id") or f"sr-{inj.get('name')}",
                }
            )
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def render_injury_ticker(db: SportsDatabase, sport: str) -> None:
    inj = db.get_injuries(sport)
    playing = _teams_playing_today(db, sport)

    if inj.empty and playing:
        inj = _statshub_injuries_for_teams(db, sport, playing)

    if inj.empty:
        if api_key_configured():
            st.caption("尚未取得 ESPN / StatsHub 即時傷兵資料。")
        return

    major = inj[inj["status"].isin(["Out", "Doubtful", "Questionable"])]
    if major.empty:
        return

    if playing:
        major = major[major["team"].isin(playing)]
    if major.empty and playing:
        sh = _statshub_injuries_for_teams(db, sport, playing)
        if not sh.empty:
            major = sh[sh["status"].isin(["Out", "Doubtful", "Questionable"])]
    if major.empty:
        return

    major = _dedupe_injuries(major)

    lines = []
    for _, row in major.head(12).iterrows():
        team = canonical_team_name(row["team"], sport)  # type: ignore[arg-type]
        itype = row.get("injury_type") or ""
        src = row.get("source") or "espn"
        src_tag = " · StatsHub" if src == "statshub" else ""
        suffix = f" ({itype})" if itype else ""
        lines.append(f"⚠️ [{team}] {row['player_name']} — {row['status']}{suffix}{src_tag}")

    ticker = "　｜　".join(lines)
    st.markdown(f"<div class='sq-injury-ticker'>{ticker}</div>", unsafe_allow_html=True)
