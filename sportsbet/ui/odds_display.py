"""賽事預測卡片：盤口（大小分、讓分、勝負賠率）呈現。"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from sportsbet.data.database import SportsDatabase
from sportsbet.models.forecast import GameForecast


def _latest_odds_by_key(odds_df: pd.DataFrame) -> dict[tuple[str, str], pd.Series]:
    if odds_df.empty:
        return {}
    df = odds_df.sort_values("id")
    out: dict[tuple[str, str], pd.Series] = {}
    for _, row in df.iterrows():
        out[(str(row["market"]), str(row["selection"]))] = row
    return out


def _fmt_odds(v: float | None) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    return f"{float(v):.2f}"


def summarize_game_odds(db: SportsDatabase, game_id: int | None) -> dict[str, object]:
    """取該場最新盤口摘要。"""
    empty: dict[str, object] = {
        "ml_home": None,
        "ml_away": None,
        "spread_home_line": None,
        "spread_away_line": None,
        "spread_home_odds": None,
        "spread_away_odds": None,
        "total_line": None,
        "over_odds": None,
        "under_odds": None,
    }
    if not game_id:
        return empty

    raw = db.get_game_odds(int(game_id))
    if raw.empty:
        return empty

    by = _latest_odds_by_key(raw)

    ml_h = by.get(("moneyline", "home"))
    ml_a = by.get(("moneyline", "away"))
    sp_h = by.get(("spread", "home"))
    sp_a = by.get(("spread", "away"))
    ov = by.get(("total", "over"))
    un = by.get(("total", "under"))

    total_line = None
    if ov is not None and pd.notna(ov.get("handicap")):
        total_line = float(ov["handicap"])
    elif un is not None and pd.notna(un.get("handicap")):
        total_line = float(un["handicap"])

    spread_home_line = float(sp_h["handicap"]) if sp_h is not None and pd.notna(sp_h.get("handicap")) else None
    spread_away_line = float(sp_a["handicap"]) if sp_a is not None and pd.notna(sp_a.get("handicap")) else None

    return {
        "ml_home": float(ml_h["odds"]) if ml_h is not None else None,
        "ml_away": float(ml_a["odds"]) if ml_a is not None else None,
        "spread_home_line": spread_home_line,
        "spread_away_line": spread_away_line,
        "spread_home_odds": float(sp_h["odds"]) if sp_h is not None else None,
        "spread_away_odds": float(sp_a["odds"]) if sp_a is not None else None,
        "total_line": total_line,
        "over_odds": float(ov["odds"]) if ov is not None else None,
        "under_odds": float(un["odds"]) if un is not None else None,
    }


def render_odds_panel(
    db: SportsDatabase,
    fc: GameForecast,
    sport: str,
) -> None:
    """清楚呈現大小分、讓分（勝分差）、主客勝負賠率。"""
    odds = summarize_game_odds(db, fc.game_id)
    total_label = "大小分" if sport == "nba" else "大小分（總得分）"
    spread_label = "讓分（勝分差）"

    st.markdown("#### 盤口資訊")
    c1, c2, c3 = st.columns(3)

    with c1:
        st.markdown("**勝負（不讓分）**")
        st.markdown(f"主隊 **{_fmt_odds(odds['ml_home'])}**")
        st.markdown(f"客隊 **{_fmt_odds(odds['ml_away'])}**")
        if odds["ml_home"] is None and odds["ml_away"] is None:
            st.caption("尚無勝負賠率")

    with c2:
        st.markdown(f"**{spread_label}**")
        if odds["spread_home_line"] is not None:
            sign_h = f"{odds['spread_home_line']:+.1f}"
            st.markdown(f"主隊 {sign_h} · {_fmt_odds(odds['spread_home_odds'])}")
        if odds["spread_away_line"] is not None:
            sign_a = f"{odds['spread_away_line']:+.1f}"
            st.markdown(f"客隊 {sign_a} · {_fmt_odds(odds['spread_away_odds'])}")
        if odds["spread_home_line"] is None and odds["spread_away_line"] is None:
            st.caption("尚無讓分盤")
        elif fc.predicted_margin is not None:
            st.caption(f"模型預估分差 {fc.predicted_margin:+.1f}")

    with c3:
        st.markdown(f"**{total_label}**")
        line = odds["total_line"] if odds["total_line"] is not None else fc.total_line
        if line is not None:
            st.markdown(f"盤口線 **{float(line):.1f}**")
            st.markdown(f"大 {_fmt_odds(odds['over_odds'])}　｜　小 {_fmt_odds(odds['under_odds'])}")
            if fc.prob_over is not None:
                under = fc.prob_under if fc.prob_under is not None else (1.0 - fc.prob_over)
                st.caption(f"模型：大 {fc.prob_over * 100:.1f}% · 小 {under * 100:.1f}%")
        else:
            st.caption("尚無大小分盤")
            if fc.predicted_total is not None:
                st.caption(f"模型預估總分 {fc.predicted_total:.1f}")
