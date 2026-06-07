"""賽事預測（現在 / 未來）專頁。"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from sportsbet.data.team_names import team_bilingual
from sportsbet.models.forecast import GameForecast, forecast_event_label, team_detail_dataframe
from sportsbet.services.prediction_service import PredictionService
from sportsbet.ui.matchup_display import format_match_datetime, render_matchup_header, taipei_match_date
from sportsbet.ui.model_methodology import render_forecast_pipeline, render_methodology_overview
from sportsbet.ui.odds_display import render_odds_panel
from sportsbet.ui.statshub_panel import render_statshub_panel


def _load_upcoming_forecasts(svc: PredictionService, sport: str, days_ahead: int) -> list[GameForecast]:
    loader = getattr(svc, "load_stored_upcoming", None)
    if callable(loader):
        try:
            stored = loader(sport, days_ahead=days_ahead)
            if stored:
                return stored
        except Exception:
            pass
    return [
        f for f in svc.run_upcoming(sport, days_ahead=days_ahead)
        if isinstance(f, GameForecast)
    ]


def _recompute_all_forecasts(svc: PredictionService, sport: str, days_ahead: int) -> dict[str, int]:
    fn = getattr(svc, "recompute_all_forecasts", None)
    if callable(fn):
        return fn(sport, days_ahead=days_ahead)
    upcoming = svc.run_upcoming(sport, days_ahead=days_ahead)
    review = svc.run_backtest_reconcile(sport, only_missing=False)
    return {"upcoming": len(upcoming), "history": len(review)}


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


def _box_score_columns(stats: pd.DataFrame) -> list[str]:
    cols = ["player_name", "team", "points", "rebounds", "assists", "minutes"]
    return [c for c in cols if c in stats.columns]


def _render_h2h_box_context(fc, sport: str, svc: PredictionService) -> None:
    """顯示近期對戰 box score（逐節 + 得分王）。"""
    try:
        _render_h2h_box_context_inner(fc, sport, svc)
    except Exception as exc:
        import logging

        logging.getLogger(__name__).warning("H2H box score 顯示略過: %s", exc)


def _render_h2h_box_context_inner(fc, sport: str, svc: PredictionService) -> None:
    db = svc.db
    md = str(getattr(fc, "match_date", ""))[:10]
    home = getattr(fc, "home_team", "")
    away = getattr(fc, "away_team", "")
    h2h = db.get_h2h_games_with_box_scores(sport, home, away, md, limit=1)
    if h2h.empty:
        gid = getattr(fc, "game_id", None)
        if gid and str(getattr(fc, "status", "")).lower() == "final":
            stats = db.get_player_game_stats(int(gid))
            q = db.get_game_quarter_scores(int(gid))
            if stats.empty:
                return
            st.markdown("**本場 Box Score（得分王）**")
            if q is not None:
                st.caption(
                    f"逐節 客 Q1–Q4: {q.get('away_q1','—')}-{q.get('away_q2','—')}-"
                    f"{q.get('away_q3','—')}-{q.get('away_q4','—')} · "
                    f"主 Q1–Q4: {q.get('home_q1','—')}-{q.get('home_q2','—')}-"
                    f"{q.get('home_q3','—')}-{q.get('home_q4','—')}"
                )
            cols = _box_score_columns(stats)
            if cols:
                st.dataframe(stats.head(6)[cols], use_container_width=True, hide_index=True)
        return

    g = h2h.iloc[0]
    gid = int(g["id"])
    stats = db.get_player_game_stats(gid)
    q = db.get_game_quarter_scores(gid)
    st.markdown(f"**前次交鋒 Box Score（{g['match_date']}）**")
    st.caption(f"比分 客 {int(g['away_score'])} – 主 {int(g['home_score'])}")
    if q is not None:
        st.caption(
            f"逐節 客: {q.get('away_q1','—')}-{q.get('away_q2','—')}-"
            f"{q.get('away_q3','—')}-{q.get('away_q4','—')} · "
            f"主: {q.get('home_q1','—')}-{q.get('home_q2','—')}-"
            f"{q.get('home_q3','—')}-{q.get('home_q4','—')}"
        )
    if not stats.empty:
        cols = _box_score_columns(stats)
        if cols:
            st.dataframe(stats.head(8)[cols], use_container_width=True, hide_index=True)


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
            adj_h = fc.home_injury_adj
            adj_a = fc.away_injury_adj
            h_adj_txt = f"{adj_h:+.1%}" if adj_h is not None else "—"
            a_adj_txt = f"{adj_a:+.1%}" if adj_a is not None else "—"
            st.caption(
                f"傷兵修正（僅真實資料）：主 {h_adj_txt} · 客 {a_adj_txt} · "
                f"最終勝率（含 MC）主 {_pct(fc.home_win_prob)} · 客 {_pct(fc.away_win_prob)}"
            )
            if adj_h is None and adj_a is None:
                st.caption("尚未同步傷兵/球員 VORP，不顯示虛構修正值。")

        c5, c6, c7 = st.columns(3)
        c5.metric("大小盤口線" if sport == "mlb" else "大小分線", fc.total_line or "無開盤")
        c6.metric("大分機率" if sport == "nba" else "大機率", _pct(fc.prob_over))
        c7.metric("小分機率" if sport == "nba" else "小機率", _pct(fc.prob_under))
        st.caption(fc.margin_note)

        sim = getattr(fc, "sim_result", None)
        if sim is not None:
            st.markdown("**動態 MC 模擬（PK / 大小 / 讓分）**")
            sc1, sc2, sc3, sc4 = st.columns(4)
            sc1.metric("MC 主勝", _pct(sim.home_win_prob))
            sc2.metric("MC 大分" if sport == "nba" else "MC 大", _pct(sim.prob_over))
            sc3.metric("MC 主讓分過盤", _pct(sim.prob_home_cover))
            sc4.metric("MC 中位總分", f"{sim.median_total:.0f}")
            st.caption(
                f"總分 P10–P90：{sim.p10_total:.0f}–{sim.p90_total:.0f} · "
                f"中位比分 {sim.median_away_score:.0f}–{sim.median_home_score:.0f} · "
                f"{sim.n_sims} 次模擬"
            )


        render_forecast_pipeline(fc)

        ic1, ic2 = st.columns(2)
        with ic1:
            _render_injury_impact(fc, "home")
        with ic2:
            _render_injury_impact(fc, "away")

        if sport == "nba":
            _render_h2h_box_context(fc, sport, svc)
            render_statshub_panel(
                svc.db,
                sport,
                getattr(fc, "game_id", None),
                home_team=getattr(fc, "home_team", ""),
                away_team=getattr(fc, "away_team", ""),
                match_date=str(getattr(fc, "match_date", ""))[:10],
            )

        detail = team_detail_dataframe(fc).copy()
        pct_cols = [
            "畢達哥拉斯勝率", "賽季勝率", "近況勝率", "Log5單場勝率",
            "Beta-Binomial", "貝氏近況修正", "馬可夫鏈 Hot/Cold", "前次交鋒 H2H PK",
            "集成後驗（傷兵前）", "傷兵修正", "傷兵後勝率", "球員數據 PK",
            "MC 模擬後驗", "最終 PK 修正勝率",
        ]
        for col in pct_cols:
            if col == "傷兵修正":
                detail[col] = detail[col].map(
                    lambda x: f"{float(x) * 100:+.1f}%" if pd.notna(x) and x is not None else "—"
                )
            else:
                detail[col] = detail[col].map(_pct)
        st.dataframe(detail, use_container_width=True, hide_index=True)


def _forecasts_missing_odds(svc: PredictionService, forecasts: list) -> bool:
    from sportsbet.ui.odds_display import summarize_game_odds

    for f in forecasts:
        if not getattr(f, "game_id", None):
            continue
        odds = summarize_game_odds(svc.db, f.game_id)
        if odds.get("ml_home") is None and odds.get("spread_home_line") is None:
            if odds.get("total_line") is None and not odds.get("margin_odds"):
                return True
    return False


def page_current_future_predictions(sport: str, svc: PredictionService) -> None:
    from sportsbet import config

    st.header("賽事預測（現在 / 未來）")
    st.caption(
        "以台灣時間顯示 · 賽程與預測自 DB 讀取（重整不重算）· "
        "按「重新計算」或「同步賽程」才更新 · "
        "中英文隊名 · 盤口：不讓分、讓分、勝分差、大小分 · 推薦下注（EV）· 貝氏集成 PK 勝率"
    )
    with st.expander("貝氏集成 PK 模型方法論", expanded=False):
        render_methodology_overview()

    max_days = config.SCHEDULE_SYNC_DAYS_AHEAD
    col_a, col_b, col_c = st.columns([1, 1, 2])
    with col_a:
        days_ahead = st.selectbox("未來天數", [7, 14, 21], index=2)
    with col_b:
        sync_btn = st.button("同步賽程並重算", type="secondary")
        recalc_btn = st.button("重新計算並儲存預測", type="primary")
        full_recalc_btn = st.button("重算今日+歷史（貝氏）", type="secondary")
        if sport == "nba" and st.button("同步 Box Score", type="secondary"):
            with st.spinner("拉取 ESPN 逐場 box score（優先總冠軍賽）…"):
                from sportsbet.data.boxscore_sync import sync_nba_box_scores

                bs = sync_nba_box_scores(svc.db, regular_days_back=max_days)
            st.success(
                f"已同步 {bs.get('boxscore_games', 0)} 場 · "
                f"{bs.get('boxscore_players', 0)} 筆球員數據"
            )
            st.rerun()
    if sync_btn:
        with st.spinner("向 ESPN 補抓賽程並同步台灣盤口…"):
            n = svc.ensure_schedule_sync(sport, days_ahead=max(days_ahead, max_days))
            odds_stats = svc.sync_upcoming_odds(sport, days_ahead=max(days_ahead, max_days))
        st.caption(
            f"新增 {n} 場賽程 · 運彩 {odds_stats.get('sportslottery_rows', 0)} 列 · "
            f"玩運彩補 {odds_stats.get('playsport_fallback', 0)} 列"
        )
    if full_recalc_btn:
        with st.spinner("重算今日/未來與全部歷史覆盤（貝氏集成管線）…"):
            stats = _recompute_all_forecasts(svc, sport, days_ahead)
        st.success(
            f"已更新：今日/未來 {stats.get('upcoming', 0)} 場 · "
            f"歷史覆盤 {stats.get('history', 0)} 場"
        )
        st.rerun()
    if recalc_btn or sync_btn:
        with st.spinner("計算中…"):
            if recalc_btn and not sync_btn:
                svc.sync_upcoming_odds(sport, days_ahead=days_ahead)
            svc.run_upcoming(sport, days_ahead=days_ahead)
        st.success("已更新預測紀錄")
        st.rerun()

    forecasts = _load_upcoming_forecasts(svc, sport, days_ahead)
    today = date.today().isoformat()

    sync_key = f"odds_auto_{sport}_{today}"
    if forecasts and _forecasts_missing_odds(svc, forecasts) and not st.session_state.get(sync_key):
        with st.spinner("偵測到缺漏盤口，正在同步台灣運彩 / JBot…"):
            stats = svc.sync_upcoming_odds(sport, days_ahead=days_ahead)
        st.session_state[sync_key] = True
        if stats.get("sportslottery_rows") or stats.get("jbot_upcoming"):
            st.rerun()

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
            st.info(
                f"資料庫有 {len(show)} 場賽程，但尚無已儲存預測。"
                "請按「重新計算並儲存預測」或側欄「完整同步」。"
            )
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
