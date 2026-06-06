"""即時比分看板（ESPN 同步 + 動態賽況）。"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from sportsbet.data.database import SportsDatabase
from sportsbet.data.team_logos import resolve_logo_url
from sportsbet.ui.matchup_display import (
    format_match_datetime,
    render_season_badges_html,
    taipei_match_date,
    team_bilingual_html,
)


def _sport_emoji(sport: str) -> str:
    return "🏀" if sport == "nba" else "⚾"


def _fetch_today_games(db: SportsDatabase, sport: str) -> pd.DataFrame:
    """今日賽事；相容舊版 DB 無 get_live_games。"""
    today = date.today().isoformat()
    if hasattr(db, "get_live_games"):
        games = db.get_live_games(sport)  # type: ignore[arg-type]
        if not games.empty:
            return games
    games = db.get_games(sport, today)  # type: ignore[arg-type]
    if not games.empty:
        return games
    start = (date.today() - timedelta(days=1)).isoformat()
    end = (date.today() + timedelta(days=1)).isoformat()
    window = db.get_games_in_range(sport, start, end)  # type: ignore[arg-type]
    if window.empty:
        return window
    return window[
        window.apply(
            lambda r: taipei_match_date(
                str(r["match_datetime"]) if pd.notna(r.get("match_datetime")) else None,
                str(r["match_date"])[:10],
            )
            == today,
            axis=1,
        )
    ]


def render_live_scoreboard(db: SportsDatabase, sport: str) -> None:
    today = date.today().isoformat()
    games = _fetch_today_games(db, sport)
    if games.empty:
        st.info("今日尚無賽程。請按「立即刷新」或執行 `python main.py watch --sport all`。")
        return

    live_n = int((games["status"] == "in_progress").sum()) if "status" in games.columns else 0
    final_n = int((games["status"] == "final").sum()) if "status" in games.columns else 0

    st.markdown(
        f"<div class='sq-hero'><h1>{_sport_emoji(sport)} 今日賽事速報</h1>"
        f"<p>{today}（台灣）· 共 {len(games)} 場 · 進行中 {live_n} · 已完賽 {final_n}"
        f" · 資料 ESPN / 玩運彩</p></div>",
        unsafe_allow_html=True,
    )

    order = {"in_progress": 0, "scheduled": 1, "final": 2}
    games = games.copy()
    games["_ord"] = games["status"].map(lambda s: order.get(str(s), 9))
    games = games.sort_values(["_ord", "match_datetime"], na_position="last")

    for _, g in games.iterrows():
        status = str(g.get("status") or "scheduled")
        is_live = status == "in_progress"
        card_cls = "sq-live-card live" if is_live else "sq-live-card"
        d_str, t_str = format_match_datetime(g.get("match_datetime"), str(g["match_date"]))
        badges = render_season_badges_html(
            g.get("season_type"), g.get("competition_note"), is_live=is_live, status=status,
        )
        hs = g.get("home_score")
        as_ = g.get("away_score")
        score_txt = f"{int(hs)} – {int(as_)}" if pd.notna(hs) and pd.notna(as_) else "VS"

        if is_live:
            period = g.get("period")
            clk = g.get("clock") or g.get("status_detail") or "進行中"
            if pd.notna(period):
                unit = "局" if sport == "mlb" else "節"
                clock = f"{unit} {period} · {clk}"
            else:
                clock = str(clk)
        elif status == "final":
            clock = str(g.get("status_detail") or "已結束")
        else:
            clock = t_str

        home_logo = resolve_logo_url(g["home_team"], sport, db_url=g.get("home_logo_url"))
        away_logo = resolve_logo_url(g["away_team"], sport, db_url=g.get("away_logo_url"))

        st.markdown(f"<div class='{card_cls}'>", unsafe_allow_html=True)
        col_a, col_mid, col_b = st.columns([2, 1.2, 2])
        with col_a:
            st.markdown(
                team_bilingual_html(g["away_team"], sport, away_logo, align="left", logo_size=40),
                unsafe_allow_html=True,
            )
            st.caption("客場")
        with col_mid:
            st.markdown(
                f"<div style='text-align:center'>"
                f"{badges}"
                f"<div class='sq-score'>{score_txt}</div>"
                f"<div class='sq-clock'>{clock}</div>"
                f"<div class='sq-clock'>{d_str}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )
        with col_b:
            st.markdown(
                team_bilingual_html(g["home_team"], sport, home_logo, align="right", logo_size=40),
                unsafe_allow_html=True,
            )
            st.caption("主場")
        st.markdown("</div>", unsafe_allow_html=True)
