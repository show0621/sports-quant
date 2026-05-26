"""現在 / 未來賽事預測專頁（與回測覆盤分離）。"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from sportsbet.models.forecast import team_detail_dataframe
from sportsbet.services.prediction_service import PredictionService
from sportsbet.ui.matchup_display import format_match_datetime, render_matchup_header


def _render_injury_impact(fc, side: str) -> None:
    missing = fc.home_missing if side == "home" else fc.away_missing
    penalty = fc.home_injury_penalty if side == "home" else fc.away_injury_penalty
    adj = fc.home_adjusted_rating if side == "home" else fc.away_adjusted_rating
    if not missing and not penalty:
        return
    st.markdown(f"**{side.upper()} 傷兵調整**")
    if penalty is not None:
        st.caption(f"陣容戰力扣分：{penalty:.2f} · 調整後評分：{adj:.2f}" if adj else f"扣分：{penalty:.2f}")
    if missing:
        for m in missing:
            st.warning(f"缺陣/疑慮：{m.get('name')} ({m.get('status')}) — 勝率影響約 {m.get('penalty', 0)*100:.1f}%")


def _pct(v: float | None) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    return f"{float(v) * 100:.1f}%"


def _render_forecast_card(fc, sport: str, *, expanded: bool = False) -> None:
    d_str, t_str = format_match_datetime(fc.match_datetime, fc.match_date)
    with st.expander(
        f"{d_str} {t_str} · {fc.home_team} vs {fc.away_team} · 預測：{fc.predicted_winner}",
        expanded=expanded,
    ):
        render_matchup_header(
            fc,
            sport=sport,
            home_logo_db=fc.home_logo_url,
            away_logo_db=fc.away_logo_url,
        )
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("主隊勝率", _pct(fc.home_win_prob))
        c2.metric("客隊勝率", _pct(fc.away_win_prob))
        c3.metric("預估總分", f"{fc.predicted_total:.1f}")
        c4.metric("預估分差", f"{fc.predicted_margin:+.1f}")

        c5, c6, c7 = st.columns(3)
        c5.metric("大小分線", fc.total_line or "—")
        c6.metric("大分機率", _pct(fc.prob_over))
        c7.metric("小分機率", _pct(fc.prob_under))
        st.caption(fc.margin_note)

        ic1, ic2 = st.columns(2)
        with ic1:
            _render_injury_impact(fc, "home")
        with ic2:
            _render_injury_impact(fc, "away")

        detail = team_detail_dataframe(fc).copy()
        for col in ["畢達哥拉斯勝率", "賽季勝率", "近況勝率", "Log5單場勝率", "貝氏修正勝率", "最終預測勝率"]:
            detail[col] = detail[col].map(_pct)
        st.dataframe(detail, use_container_width=True, hide_index=True)


def page_current_future_predictions(sport: str, svc: PredictionService) -> None:
    st.header("賽事預測（現在 / 未來）")
    st.caption("僅顯示尚未開打或進行中的賽事；歷史覆盤請至「回測覆盤」分頁。")

    col_a, col_b, col_c = st.columns([1, 1, 2])
    with col_a:
        days_ahead = st.selectbox("未來天數", [3, 7, 14], index=1)
    with col_b:
        if st.button("重新計算並儲存預測", type="primary"):
            with st.spinner("計算中…"):
                svc.run_upcoming(sport, days_ahead=days_ahead)
            st.success("已更新預測紀錄")
            st.rerun()

    forecasts = svc.run_upcoming(sport, days_ahead=days_ahead)
    if not forecasts:
        st.warning(
            "尚無現在或未來賽程。請在側欄按「同步 API-Sports」或「重新載入 MOCK」，"
            "系統會自動抓取今日起算的多日賽程。"
        )
        return

    today = date.today().isoformat()
    today_fc = [f for f in forecasts if f.match_date == today]
    future_fc = [f for f in forecasts if f.match_date > today]

    m1, m2, m3 = st.columns(3)
    m1.metric("今日場次", len(today_fc))
    m2.metric("未來場次", len(future_fc))
    m3.metric("預測紀錄總數", len(forecasts))

    summary = svc.upcoming_summary_table(forecasts)
    if not summary.empty:
        show = summary.copy()
        for col in ["主隊勝率", "客隊勝率", "大分機率"]:
            show[col] = show[col].map(_pct)
        st.subheader("預測總覽")
        st.dataframe(show, use_container_width=True, hide_index=True)

    sub_today, sub_future, sub_pick = st.tabs(["今日賽事", "未來賽程", "指定日期"])

    with sub_today:
        if not today_fc:
            st.info("今日無賽事。")
        else:
            for i, fc in enumerate(today_fc):
                _render_forecast_card(fc, sport, expanded=i == 0 and len(today_fc) <= 3)

    with sub_future:
        if not future_fc:
            st.info("未來區間無賽事。")
        else:
            by_date: dict[str, list] = {}
            for fc in future_fc:
                by_date.setdefault(fc.match_date, []).append(fc)
            for d in sorted(by_date):
                st.markdown(f"#### {d}")
                for fc in by_date[d]:
                    _render_forecast_card(fc, sport, expanded=False)

    with sub_pick:
        pick = st.date_input(
            "選擇日期",
            value=date.today(),
            min_value=date.today(),
            max_value=date.today() + timedelta(days=days_ahead),
        ).isoformat()
        picked = [f for f in forecasts if f.match_date == pick]
        if not picked:
            st.info(f"{pick} 無賽事。")
        else:
            for i, fc in enumerate(picked):
                _render_forecast_card(fc, sport, expanded=i == 0)

    with st.expander("已儲存的預測紀錄（資料庫）"):
        log = svc.db.get_upcoming_forecast_review(sport)
        if log.empty:
            st.write("尚無紀錄")
        else:
            st.dataframe(log, use_container_width=True)
