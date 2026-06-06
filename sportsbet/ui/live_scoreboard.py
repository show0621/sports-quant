"""即時比分看板（ESPN 同步 + 模型預測）。"""
from __future__ import annotations

from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

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
from sportsbet.ui.odds_display import (
    actual_result_line,
    build_game_market_picks,
    format_market_pick_html,
    summarize_game_odds,
)

if TYPE_CHECKING:
    from sportsbet.services.prediction_service import PredictionService


def _sport_emoji(sport: str) -> str:
    return "🏀" if sport == "nba" else "⚾"


def _pct(v: float | None) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    return f"{float(v) * 100:.1f}%"


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


def _get_game_forecast_row(
    db: SportsDatabase,
    sport: str,
    gid: int,
    match_date: str,
) -> pd.Series | None:
    """讀取單場 forecast；相容舊版 DB / 快取中的 SportsDatabase 實例。"""
    if hasattr(db, "get_game_forecast_row"):
        return db.get_game_forecast_row(gid)  # type: ignore[attr-defined]

    if hasattr(db, "get_forecasts_by_date"):
        df = db.get_forecasts_by_date(sport, str(match_date)[:10])  # type: ignore[arg-type]
        if not df.empty and "game_id" in df.columns:
            hit = df[df["game_id"] == gid]
            if not hit.empty:
                return hit.iloc[0]

    try:
        with db.connection() as conn:
            df = pd.read_sql_query(
                "SELECT * FROM game_forecasts WHERE game_id = ?",
                conn,
                params=(gid,),
            )
        if not df.empty:
            return df.iloc[0]
    except Exception:
        pass
    return None


def _get_total_line(db: SportsDatabase, gid: int) -> float | None:
    if hasattr(db, "get_market_line"):
        return db.get_market_line(gid, "total")  # type: ignore[attr-defined]
    line = summarize_game_odds(db, gid).get("total_line")
    if line is None or (isinstance(line, float) and pd.isna(line)):
        return None
    return float(line)


def _load_forecast(
    db: SportsDatabase,
    sport: str,
    g: pd.Series,
    svc: PredictionService | None,
) -> dict[str, Any] | None:
    gid = int(g["id"])
    match_date = str(g.get("match_date", ""))[:10]
    row = _get_game_forecast_row(db, sport, gid, match_date)
    if row is not None and pd.notna(row.get("predicted_winner")):
        return row.to_dict()

    if svc is None:
        return None
    stats = svc.db.get_team_stats(sport).set_index("team")
    ht, at = g["home_team"], g["away_team"]
    if ht not in stats.index or at not in stats.index:
        return None
    line = _get_total_line(db, gid)
    fc = svc.forecast_game_row(sport, g, stats, total_line=line)
    if not fc:
        return None
    return {
        "predicted_winner": fc.predicted_winner,
        "home_win_prob": fc.home_win_prob,
        "away_win_prob": fc.away_win_prob,
        "predicted_margin": fc.predicted_margin,
        "predicted_total": fc.predicted_total,
        "total_line": fc.total_line,
        "prob_over": fc.prob_over,
        "prob_under": fc.prob_under,
        "predicted_home_score": fc.predicted_home_score,
        "predicted_away_score": fc.predicted_away_score,
        "pick_correct": fc.pick_correct,
        "home_team": fc.home_team,
        "away_team": fc.away_team,
    }


def _render_prediction_strip(
    db: SportsDatabase,
    sport: str,
    g: pd.Series,
    fc: dict[str, Any] | None,
    *,
    status: str,
) -> None:
    if not fc:
        st.markdown(
            "<div class='sq-pred-strip sq-pred-empty'>"
            "尚無模型預測 · 請執行「完整同步」或 watch 更新</div>",
            unsafe_allow_html=True,
        )
        return

    home = str(g["home_team"])
    away = str(g["away_team"])
    is_final = status == "final"
    hs = int(g["home_score"]) if is_final and pd.notna(g.get("home_score")) else None
    aws = int(g["away_score"]) if is_final and pd.notna(g.get("away_score")) else None

    odds = summarize_game_odds(db, int(g["id"]))
    picks = build_game_market_picks(
        fc,
        odds,
        sport,
        home_team=home,
        away_team=away,
        home_score=hs,
        away_score=aws,
        is_final=is_final,
    )

    ph, pa = fc.get("predicted_home_score"), fc.get("predicted_away_score")
    score_sub = ""
    if ph is not None and pa is not None and not pd.isna(ph) and not pd.isna(pa):
        score_sub = f"預估比分 {int(pa)}–{int(ph)}"

    margin = fc.get("predicted_margin")
    margin_hint = ""
    if margin is not None and not pd.isna(margin):
        margin_hint = f"模型淨勝 {float(margin):+.1f}"

    actual_txt = ""
    if is_final and hs is not None and aws is not None:
        actual_txt = actual_result_line(hs, aws, home_team=home, away_team=away, sport=sport)

    ml_body = format_market_pick_html(
        picks.get("moneyline"),
        extra_sub=score_sub,
        actual_line=actual_txt,
    )
    spread_body = format_market_pick_html(picks.get("spread"), extra_sub=margin_hint)
    total_label = "大小分" if sport == "nba" else "大小分（總得分）"

    summary_tags = ""
    if is_final:
        parts: list[str] = []
        for key, label in [("moneyline", "勝負"), ("spread", "讓分"), ("total", "大小")]:
            p = picks.get(key)
            if p is None or p.settled is None:
                continue
            mark = "✓" if p.settled else "✗"
            cls = "sq-pred-ok" if p.settled else "sq-pred-miss"
            if key == "moneyline":
                tag = f"{mark} {label}{'正確' if p.settled else '錯誤'}"
            else:
                tag = f"{mark} {label}"
            parts.append(f"<span class='sq-pred-hit {cls}'>{tag}</span>")
        if parts:
            summary_tags = f"<div class='sq-pred-summary'>{''.join(parts)}</div>"

    st.markdown(
        f"""
        <div class="sq-pred-strip">
            <div class="sq-pred-grid">
                <div class="sq-pred-cell">
                    <div class="sq-pred-label">勝負預測</div>
                    {ml_body}
                    <div class="sq-pred-sub">主 {_pct(fc.get('home_win_prob'))} · 客 {_pct(fc.get('away_win_prob'))}</div>
                </div>
                <div class="sq-pred-cell">
                    <div class="sq-pred-label">勝分差（讓分）</div>
                    {spread_body}
                </div>
                <div class="sq-pred-cell">
                    <div class="sq-pred-label">{total_label}</div>
                    {format_market_pick_html(picks.get("total"))}
                </div>
            </div>
            {summary_tags}
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_live_scoreboard(
    db: SportsDatabase,
    sport: str,
    svc: PredictionService | None = None,
) -> None:
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
        f" · 含模型預測 · 盤口賠率 · EV · 完賽覆盤</p></div>",
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
        # 版面左客右主，比分依慣例為客–主
        score_txt = f"{int(as_)} – {int(hs)}" if pd.notna(hs) and pd.notna(as_) else "VS"

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
        fc = _load_forecast(db, sport, g, svc)

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

        _render_prediction_strip(db, sport, g, fc, status=status)
        st.markdown("</div>", unsafe_allow_html=True)
