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


def render_injury_ticker(db: SportsDatabase, sport: str) -> None:
    inj = db.get_injuries(sport)
    if inj.empty:
        if api_key_configured():
            st.caption("即時傷兵名單尚未接入（API-Sports 僅提供賽程／賽果）。可於側欄載入示範傷兵。")
        return

    major = inj[inj["status"].isin(["Out", "Doubtful", "Questionable"])]
    if major.empty:
        return

    playing = _teams_playing_today(db, sport)
    if playing:
        major = major[major["team"].isin(playing)]
    if major.empty:
        return

    major = _dedupe_injuries(major)
    is_mock = (major.get("source") == "mock").all() if "source" in major.columns else True

    lines = []
    for _, row in major.head(12).iterrows():
        team = canonical_team_name(row["team"], sport)  # type: ignore[arg-type]
        itype = row.get("injury_type") or ""
        suffix = f" ({itype})" if itype else ""
        lines.append(f"⚠️ [{team}] {row['player_name']} — {row['status']}{suffix}")

    ticker = "　｜　".join(lines)
    mock_note = (
        '<div style="font-size:0.75rem;color:#aaa;margin-bottom:4px;">'
        "示範傷兵資料（MOCK）· 非真實球員"
        "</div>"
        if is_mock
        else ""
    )
    st.markdown(
        f"""
        {mock_note}
        <div style="
            background: linear-gradient(90deg, #3d1a1a 0%, #1a1a2e 100%);
            color: #ffcccc;
            padding: 10px 14px;
            border-radius: 8px;
            border-left: 4px solid #e74c3c;
            font-size: 0.92rem;
            margin-bottom: 12px;
            overflow-x: auto;
            white-space: nowrap;
        ">{ticker}</div>
        """,
        unsafe_allow_html=True,
    )
