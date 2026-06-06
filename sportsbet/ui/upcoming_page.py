"""賽事預測（現在 / 未來）專頁。"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from sportsbet.data.team_names import team_bilingual
from sportsbet.models.forecast import GameForecast, forecast_event_label, team_detail_dataframe
from sportsbet.services.prediction_service import PredictionService
from sportsbet.ui.matchup_display import format_match_datetime, render_matchup_header, taipei_match_date
from sportsbet.ui.odds_display import render_odds_panel


def _render_injury_impact(fc, side: str) -> None:
    missing = getattr(fc, f"{side}_missing", None) or []
    penalty = getattr(fc, f"{side}_injury_penalty", None)
    adj = getattr(fc, f"{side}_adjusted_rating", None)
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


def _status_sort_key(fc) -> tuple[int, str]:
    order = {"in_progress": 0, "scheduled": 1, "final": 2}
    st_val = str(getattr(fc, "status", "") or "scheduled").lower()
    md = getattr(fc, "match_datetime", None) or getattr(fc, "match_date", "")
    return order.get(st_val, 3), str(md)


def _card_title(fc, sport: str) -> str:
    d_str, t_str = format_match_datetime(
        getattr(fc, "match_datetime", None),
        str(getattr(fc, "match_date", "")),
    )
    home = getattr(fc, "home_team", "?")
    away = getattr(fc, "away_team", "?")
    h_en, h_zh = team_bilingual(home, sport)
    a_en, a_zh = team_bilingual(away, sport)
    h_show = f"{h_en} / {h_zh}" if h_zh else h_en
    a_show = f"{a_en} / {a_zh}" if a_zh else a_en
    label = forecast_event_label(fc)
    title_extra = f" · {label}" if label else ""
    status = str(getattr(fc, "status", "") or "").lower()
    status_tag = ""
    if status == "final":
        status_tag = " · 已完賽"
    elif status == "in_progress":
        status_tag = " · LIVE"
    winner = getattr(fc, "predicted_winner", "—")
    return (
        f"{d_str} {t_str} · {h_show} vs {a_show}{title_extra}{status_tag} · "
        f"預測：{winner}"
    )


def _render_forecast_card(
    fc,
    sport: str,
    svc: PredictionService,
    *,
    expanded: bool = False,
) -> None:
    if not isinstance(fc, GameForecast):
        st.warning(f"略過無效預測物件：{type(fc).__name__}")
        return
    with st.expander(_card_title(fc, sport), expanded=expanded):
        render_matchup_header(
            fc,
            sport=sport,
            home_logo_db=getattr(fc, "home_logo_url", None),
            away_logo_db=getattr(fc, "away_logo_url", None),
        )
        render_odds_panel(svc.db, fc, sport)

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("主隊勝率（最終）", _pct(fc.home_win_prob))
        c2.metric("客隊勝率（最終）", _pct(fc.away_win_prob))
        c3.metric("預估總分", f"{fc.predicted_total:.1f}")
        c4.metric("預估分差", f"{fc.predicted_margin:+.1f}")

        if fc.home_win_prob_base is not None and fc.away_win_prob_base is not None:
            adj_h = fc.home_injury_adj or 0.0
            adj_a = fc.away_injury_adj or 0.0
            st.caption(
                f"傷兵修正：主隊 {_pct(fc.home_win_prob_base)} → {_pct(fc.home_win_prob)} "
                f"({adj_h:+.1%})　｜　客隊 {_pct(fc.away_win_prob_base)} → {_pct(fc.away_win_prob)} "
                f"({adj_a:+.1%})"
            )

        c5, c6, c7 = st.columns(3)
        c5.metric("大小盤口線" if sport == "mlb" else "大小分線", fc.total_line or "無開盤")
        c6.metric("大分機率" if sport == "nba" else "大機率", _pct(fc.prob_over))
        c7.metric("小分機率" if sport == "nba" else "小機率", _pct(fc.prob_under))
        st.caption(fc.margin_note)

        ic1, ic2 = st.columns(2)
        with ic1:
            _render_injury_impact(fc, "home")
        with ic2:
            _render_injury_impact(fc, "away")

        detail = team_detail_dataframe(fc).copy()
        pct_cols = [
            "畢達哥拉斯勝率", "賽季勝率", "近況勝率", "Log5單場勝率", "貝氏修正勝率",
            "傷兵前勝率", "傷兵修正", "最終預測勝率",
        ]
        for col in pct_cols:
            if col == "傷兵修正":
                detail[col] = detail[col].map(
                    lambda x: f"{float(x) * 100:+.1f}%" if pd.notna(x) and x is not None else "—"
                )
            else:
                detail[col] = detail[col].map(_pct)
        st.dataframe(detail, use_container_width=True, hide_index=True)


def page_current_future_predictions(sport: str, svc: PredictionService) -> None:
    from sportsbet import config

    st.header("賽事預測（現在 / 未來）")
    st.caption(
        "以台灣時間顯示 · 今日儀表板含進行中、未開賽與已完賽 · "
        "中英文隊名並列 · 盤口：大小分、讓分、勝負賠率 · "
        "預測納入每場開賽前已完賽結果、近況勝率、傷兵與陣容評估"
    )

    max_days = config.SCHEDULE_SYNC_DAYS_AHEAD
    col_a, col_b, col_c = st.columns([1, 1, 2])
    with col_a:
        days_ahead = st.selectbox("未來天數", [7, 14, 21], index=2)
    with col_b:
        sync_btn = st.button("同步賽程並重算", type="secondary")
        recalc_btn = st.button("重新計算並儲存預測", type="primary")
    if sync_btn:
        with st.spinner("向 ESPN 補抓賽程…"):
            n = svc.ensure_schedule_sync(sport, days_ahead=max(days_ahead, max_days))
        st.caption(f"新增 {n} 場賽程")
    if recalc_btn or sync_btn:
        with st.spinner("計算中…"):
            svc.run_upcoming(sport, days_ahead=days_ahead)
        st.success("已更新預測紀錄")
        st.rerun()

    forecasts = [f for f in svc.run_upcoming(sport, days_ahead=days_ahead) if isinstance(f, GameForecast)]
    today = date.today().isoformat()

    if not forecasts:
        db = svc.db
        raw = db.get_games_in_range(
            sport,
            (date.today() - timedelta(days=1)).isoformat(),
            (date.today() + timedelta(days=days_ahead)).isoformat(),
        )
        live_today = db.get_live_games(sport)  # type: ignore[arg-type]
        st.warning("尚無模型預測輸出。")
        if not raw.empty or not live_today.empty:
            show = live_today if not live_today.empty else raw
            st.info(f"資料庫有 {len(show)} 場賽程，但缺少球隊統計或隊名對應。請按側欄「完整同步」。")
            cols = [c for c in ["match_date", "home_team", "away_team", "status", "season_type", "competition_note"] if c in show.columns]
            st.dataframe(show[cols], use_container_width=True, hide_index=True)
        else:
            st.caption("請在側欄按「完整同步」或「即時監控 → 立即刷新」。")
        return

    today_fc = sorted(
        [
            f for f in forecasts
            if taipei_match_date(getattr(f, "match_datetime", None), str(getattr(f, "match_date", ""))) == today
        ],
        key=_status_sort_key,
    )
    future_fc = [
        f for f in forecasts
        if taipei_match_date(getattr(f, "match_datetime", None), str(getattr(f, "match_date", ""))) > today
    ]

    finals_n = sum(1 for f in today_fc if str(getattr(f, "status", "")).lower() == "final")
    live_n = sum(1 for f in today_fc if str(getattr(f, "status", "")).lower() == "in_progress")

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("今日場次（台灣）", len(today_fc))
    m2.metric("進行中", live_n)
    m3.metric("今日已完賽", finals_n)
    m4.metric("未來場次", len(future_fc))

    summary = svc.upcoming_summary_table(forecasts)
    if not summary.empty:
        show = summary.copy()
        for col in ["主隊勝率", "客隊勝率", "大分機率"]:
            if col in show.columns:
                show[col] = show[col].map(_pct)
        st.subheader("預測總覽")
        st.dataframe(show, use_container_width=True, hide_index=True)

    sub_today, sub_future, sub_pick = st.tabs(["今日賽事", "未來賽程", "指定日期"])

    with sub_today:
        if not today_fc:
            st.info("依台灣時間，今日無賽事。請執行「完整同步」或「即時刷新」。")
        else:
            if finals_n:
                st.caption(
                    f"今日共 {len(today_fc)} 場（含 {finals_n} 場已完賽）— "
                    "完賽場次仍保留於此頁追蹤，詳細覆盤請至「回測覆盤」。"
                )
            for i, fc in enumerate(today_fc):
                _render_forecast_card(fc, sport, svc, expanded=i == 0 and len(today_fc) <= 4)

    with sub_future:
        if not future_fc:
            st.info("未來區間無賽事。請按「同步賽程並重算」或側欄「完整同步」。")
        else:
            st.caption(
                "若 [Bing 賽程](https://www.bing.com/sportsdetails?q=nba%20%E8%B3%BD%E4%BA%8B&sport=Basketball&league=Basketball_NBA&intent=Schedule) "
                "有 TBA 場次（如 G6/G7）但此處未顯示，代表 ESPN 尚未公布該日 scoreboard，公布後再同步即可。"
            )
            by_date: dict[str, list] = {}
            for fc in future_fc:
                d = taipei_match_date(fc.match_datetime, fc.match_date)
                by_date.setdefault(d, []).append(fc)
            for d in sorted(by_date):
                st.markdown(f"#### {d}")
                for fc in by_date[d]:
                    _render_forecast_card(fc, sport, svc, expanded=False)

    with sub_pick:
        pick = st.date_input(
            "選擇日期",
            value=date.today(),
            min_value=date.today() - timedelta(days=1),
            max_value=date.today() + timedelta(days=days_ahead),
        ).isoformat()
        picked = sorted(
            [
                f for f in forecasts
                if taipei_match_date(f.match_datetime, f.match_date) == pick
            ],
            key=_status_sort_key,
        )
        if not picked:
            st.info(f"{pick} 無賽事。")
        else:
            for i, fc in enumerate(picked):
                _render_forecast_card(fc, sport, svc, expanded=i == 0)

    with st.expander("已儲存的預測紀錄（資料庫）"):
        log = svc.db.get_upcoming_forecast_review(sport)
        if log.empty:
            st.write("尚無紀錄")
        else:
            st.dataframe(log, use_container_width=True)
