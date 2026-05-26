"""傷兵警報跑馬燈。"""
from __future__ import annotations

import streamlit as st

from sportsbet.data.database import SportsDatabase
from sportsbet.data.team_logos import canonical_team_name


def render_injury_ticker(db: SportsDatabase, sport: str) -> None:
    inj = db.get_injuries(sport)
    if inj.empty:
        return
    major = inj[inj["status"].isin(["Out", "Doubtful", "Questionable"])]
    if major.empty:
        return
    lines = []
    for _, row in major.head(12).iterrows():
        team = canonical_team_name(row["team"], sport)  # type: ignore[arg-type]
        itype = row.get("injury_type") or ""
        lines.append(
            f"⚠️ [{team}] {row['player_name']} — {row['status']} ({itype})"
        )
    ticker = "　｜　".join(lines)
    st.markdown(
        f"""
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
