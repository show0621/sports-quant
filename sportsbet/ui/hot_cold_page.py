"""球員狀態熱區圖分頁。"""
from __future__ import annotations

import plotly.express as px
import streamlit as st

from sportsbet.data.data_quality import has_real_player_stats
from sportsbet.data.database import SportsDatabase


def page_player_hot_cold(db: SportsDatabase, sport: str) -> None:
    st.header("球員狀態熱區 (Hot / Cold)")
    st.caption("近 10 場滾動表現 vs 賽季平均（nba_api / ESPN 真實數據）")

    if not has_real_player_stats(db, sport):  # type: ignore[arg-type]
        st.warning("尚無球員滾動統計。請執行 `python main.py sync --mode players --sport " + sport + "`。")
        return

    df = db.get_player_hot_cold(sport, limit=80)
    if df.empty:
        st.warning("資料庫中尚無 hot/cold 指標。")
        return

    hot = df[df["hot_cold_index"] > 0.08].head(15)
    cold = df[df["hot_cold_index"] < -0.08].head(15)

    c1, c2 = st.columns(2)
    with c1:
        st.subheader("🔥 Hot（優於平均）")
        st.dataframe(hot[["name", "team", "hot_cold_index", "rolling_off_rating"]], hide_index=True)
    with c2:
        st.subheader("🧊 Cold（劣於平均）")
        st.dataframe(cold[["name", "team", "hot_cold_index", "rolling_off_rating"]], hide_index=True)

    pivot = df.pivot_table(
        index="team", columns="name", values="hot_cold_index", aggfunc="first",
    ).fillna(0)
    if pivot.shape[0] > 1 and pivot.shape[1] > 1:
        fig = px.imshow(
            pivot.values,
            x=list(pivot.columns),
            y=list(pivot.index),
            color_continuous_scale="RdYlGn",
            aspect="auto",
            labels=dict(color="Hot/Cold"),
            title="球隊 × 球員 狀態熱力圖",
        )
        fig.update_layout(height=500)
        st.plotly_chart(fig, use_container_width=True)
