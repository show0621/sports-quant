"""對戰卡片：日期時間 + 隊徽。"""
from __future__ import annotations

from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from sportsbet.data.team_logos import resolve_logo_url
from sportsbet.models.forecast import GameForecast


def format_match_datetime(match_datetime: str | None, match_date: str) -> tuple[str, str]:
    """回傳 (日期, 時間) 台灣時區字串。"""
    if not match_datetime or (isinstance(match_datetime, float) and pd.isna(match_datetime)):
        return match_date, "時間待定"

    try:
        dt = pd.to_datetime(match_datetime, utc=True, errors="coerce")
        if pd.isna(dt):
            return match_date, "時間待定"
        local = dt.tz_convert(ZoneInfo("Asia/Taipei"))
        return local.strftime("%Y-%m-%d"), local.strftime("%H:%M") + " (台灣)"
    except Exception:
        return match_date, str(match_datetime)[:16]


def render_matchup_header(
    fc: GameForecast,
    *,
    sport: str,
    home_logo_db: str | None = None,
    away_logo_db: str | None = None,
) -> None:
    """渲染隊徽 + 隊名 + 日期時間。"""
    date_str, time_str = format_match_datetime(fc.match_datetime, fc.match_date)
    home_logo = resolve_logo_url(fc.home_team, sport, db_url=home_logo_db)  # type: ignore[arg-type]
    away_logo = resolve_logo_url(fc.away_team, sport, db_url=away_logo_db)  # type: ignore[arg-type]

    left, center, right = st.columns([1, 2.2, 1])

    with left:
        if home_logo:
            st.image(home_logo, width=72)
        st.markdown(f"**{fc.home_team}**")
        st.caption("主場")

    with center:
        st.markdown(f"##### {date_str}")
        st.markdown(f"**{time_str}**")
        st.markdown("##### VS")
        st.markdown(f"預測勝者：**{fc.predicted_winner}**")
        st.caption(f"預估比分 {fc.predicted_home_score:.0f} – {fc.predicted_away_score:.0f}")

    with right:
        if away_logo:
            st.image(away_logo, width=72)
        st.markdown(f"**{fc.away_team}**")
        st.caption("客場")

    st.divider()
