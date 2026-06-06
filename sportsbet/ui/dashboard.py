"""
Streamlit 多頁面看板：每日預測、模型健康度、資金回測。

啟動：streamlit run dashboard.py
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sportsbet import config  # noqa: E402
from sportsbet.data.database import SportsDatabase  # noqa: E402
from sportsbet.data.db_github_sync import push_database_to_github  # noqa: E402
from sportsbet.data.data_quality import data_quality_summary  # noqa: E402
from sportsbet.data.orchestrator import DataOrchestrator  # noqa: E402
from sportsbet.data.provider import api_key_configured, describe_data_source  # noqa: E402
from sportsbet.evaluation.evaluator import EvaluationModule  # noqa: E402
from sportsbet.models.analytics_engine import AnalyticsEngine  # noqa: E402
from sportsbet.risk.ev import RiskManager  # noqa: E402
from sportsbet.services.data_refresh import run_full_backtest_refresh, run_incremental_backtest_refresh  # noqa: E402
from sportsbet.services.prediction_service import PredictionService  # noqa: E402
from sportsbet.ui.live_monitor_page import page_live_monitor  # noqa: E402
from sportsbet.ui.hot_cold_page import page_player_hot_cold  # noqa: E402
from sportsbet.ui.injury_ticker import render_injury_ticker  # noqa: E402
from sportsbet.ui.upcoming_page import page_current_future_predictions  # noqa: E402

st.set_page_config(page_title="運彩量化看板", layout="wide", page_icon="📊")


def _pct(v: float | None) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    return f"{float(v) * 100:.1f}%"


@st.cache_resource
def get_db() -> SportsDatabase:
    return SportsDatabase()


@st.cache_resource
def get_prediction_service() -> PredictionService:
    return PredictionService(get_db())


def _persist_database(message: str | None = None) -> None:
    """資料變更後嘗試推送 SQLite 至 GitHub。"""
    try:
        push_database_to_github(message=message)
    except Exception as exc:
        st.sidebar.caption(f"GitHub 資料庫同步略過：{exc}")


def ensure_data(sport: str) -> None:
    """看板載入：只讀 DB，不在此觸發重型同步（由 watch / CLI 負責）。"""
    db = get_db()
    if db.get_team_stats(sport).empty and db.get_games(sport, date.today().isoformat()).empty:
        st.sidebar.warning(
            "資料庫為空。請先執行：`python main.py watch --sport all` 或 `python main.py sync --mode daily --sport all`"
        )


def build_daily_predictions(sport: str) -> pd.DataFrame:
    db = get_db()
    svc = get_prediction_service()
    risk = RiskManager()
    today = date.today().isoformat()
    board = db.get_daily_board(sport, today)
    if board.empty:
        return pd.DataFrame()

    forecasts = {fc.game_id: fc for fc in svc.run_for_date(sport, today) if fc.game_id}
    rows = []
    for _, g in board.drop_duplicates(subset=["game_id", "market", "selection"]).iterrows():
        gid = int(g["game_id"])
        fc = forecasts.get(gid)
        ht, at = g["home_team"], g["away_team"]
        market = g.get("market", "moneyline")
        sel = g.get("selection", "home")
        if fc:
            if market == "moneyline":
                prob = fc.home_win_prob if sel == "home" else fc.away_win_prob
            elif fc.prob_over is not None:
                prob = fc.prob_over if sel == "over" else (fc.prob_under if fc.prob_under is not None else (1.0 - fc.prob_over))
            else:
                continue
        else:
            stats = db.get_team_stats(sport).set_index("team")
            if ht not in stats.index or at not in stats.index:
                continue
            h, a = stats.loc[ht], stats.loc[at]
            engine = AnalyticsEngine(sport)  # type: ignore[arg-type]
            pred = engine.predict_matchup(
                h["rs_per_game"], h["ra_per_game"], a["rs_per_game"], a["ra_per_game"],
                home_recent_win_pct=h.get("recent_win_pct"),
                away_recent_win_pct=a.get("recent_win_pct"),
            )
            if market == "moneyline":
                prob = pred.home_win_prob if sel == "home" else pred.away_win_prob
            else:
                line = float(g["handicap"]) if pd.notna(g.get("handicap")) else 220.0
                prob = engine.prob_total_over(line, pred.lambda_home, pred.lambda_away)
                if sel == "under":
                    prob = 1.0 - prob
        odds = float(g["odds"]) if pd.notna(g.get("odds")) else 1.75
        sig = risk.evaluate(prob, odds)
        rows.append(
            {
                "對戰": f"{ht} vs {at}",
                "盤口": market,
                "選項": sel,
                "盤口線": g.get("handicap"),
                "莊家賠率": odds,
                "模型勝率": prob,
                "EV": sig.ev,
                "建議倉位": sig.recommended_stake_fraction,
                "正EV": sig.is_positive_ev,
            }
        )
    return pd.DataFrame(rows)


def page_backtest_review(sport: str) -> None:
    st.header("回測覆盤（歷史賽事）")
    st.caption(
        f"預設回測區間：過去 {config.BACKTEST_YEARS} 年（{config.BACKTEST_DAYS} 天）。"
        f"已結束賽事覆盤會寫入資料庫；之後只補最近 {config.BACKTEST_INCREMENTAL_LOOKBACK_DAYS} 天與缺漏日期。"
        "現在/未來預測請至「賽事預測」分頁。"
    )

    svc = get_prediction_service()
    db = get_db()
    if st.button("重新產生全部覆盤紀錄", type="primary"):
        with st.spinner("同步歷史賽果、傷兵並重算全部覆盤…"):
            stats = run_full_backtest_refresh(db, sport, sync_api=True, sync_injuries=True)
            _persist_database(f"chore(data): full backtest refresh {sport}")
        st.success(
            f"覆盤已更新：{stats.get('forecasts', 0)} 場預測、"
            f"{stats.get('games_with_scores', 0)} 場有比分、"
            f"{stats.get('predictions', 0)} 筆投注紀錄"
        )
        st.cache_resource.clear()
        st.rerun()

    review = svc.get_review_table(sport, final_only=True)
    if review.empty:
        st.warning("尚無已結束賽事的覆盤資料，請先載入歷史賽果或按上方按鈕產生。")
        return

    hits = review["pick_correct"].sum()
    total = len(review)
    c1, c2, c3 = st.columns(3)
    c1.metric("勝負預測命中", f"{hits}/{total}", f"{hits/total:.1%}" if total else "—")
    if "margin_error" in review.columns:
        c2.metric("平均分差誤差", f"{review['margin_error'].abs().mean():.1f} 分")
    if "total_error" in review.columns:
        c3.metric("平均總分誤差", f"{review['total_error'].abs().mean():.1f} 分")

    display = review.rename(
        columns={
            "match_date": "日期",
            "home_team": "主隊",
            "away_team": "客隊",
            "predicted_winner": "預測勝者",
            "actual_winner": "實際勝者",
            "home_win_prob": "主隊勝率(最終)",
            "away_win_prob": "客隊勝率(最終)",
            "home_win_prob_base": "主隊勝率(傷兵前)",
            "away_win_prob_base": "客隊勝率(傷兵前)",
            "home_injury_adj": "主隊傷兵修正",
            "away_injury_adj": "客隊傷兵修正",
            "predicted_home_score": "預測主隊分",
            "predicted_away_score": "預測客隊分",
            "actual_home_score": "實際主隊分",
            "actual_away_score": "實際客隊分",
            "predicted_total": "預測總分",
            "predicted_margin": "預測分差",
            "margin_error": "分差誤差",
            "total_error": "總分誤差",
            "prob_over": "大分機率",
            "total_line": "大小分線",
        }
    )
    pct_cols = [
        "主隊勝率(最終)", "客隊勝率(最終)", "主隊勝率(傷兵前)", "客隊勝率(傷兵前)", "大分機率",
    ]
    adj_cols = ["主隊傷兵修正", "客隊傷兵修正"]
    for col in pct_cols:
        if col in display.columns:
            display[col] = display[col].map(_pct)
    for col in adj_cols:
        if col in display.columns:
            display[col] = display[col].map(lambda x: f"{float(x)*100:+.1f}%" if pd.notna(x) else "—")

    show_cols = [
        c
        for c in [
            "日期", "主隊", "客隊", "預測勝者", "實際勝者", "預測正確",
            "主隊勝率(傷兵前)", "主隊傷兵修正", "主隊勝率(最終)",
            "客隊勝率(傷兵前)", "客隊傷兵修正", "客隊勝率(最終)",
            "預測主隊分", "預測客隊分", "實際主隊分", "實際客隊分",
            "預測總分", "預測分差", "分差誤差", "總分誤差", "大小分線", "大分機率",
        ]
        if c in display.columns
    ]
    st.dataframe(display[show_cols], use_container_width=True, hide_index=True)

    st.subheader("各隊數據明細（最近一場）")
    if not review.empty:
        last = review.iloc[0]
        st.write(f"**{last['home_team']} vs {last['away_team']}** ({last['match_date']})")
        team_rows = pd.DataFrame(
            [
                {
                    "隊伍": last["home_team"],
                    "畢達哥拉斯": _pct(last.get("home_pyth")),
                    "賽季勝率": _pct(last.get("home_season_win_pct")),
                    "近況": _pct(last.get("home_recent_win_pct")),
                    "貝氏修正": _pct(last.get("home_bayesian_win_pct")),
                },
                {
                    "隊伍": last["away_team"],
                    "畢達哥拉斯": _pct(last.get("away_pyth")),
                    "賽季勝率": _pct(last.get("away_season_win_pct")),
                    "近況": _pct(last.get("away_recent_win_pct")),
                    "貝氏修正": _pct(last.get("away_bayesian_win_pct")),
                },
            ]
        )
        st.dataframe(team_rows, use_container_width=True, hide_index=True)


def page_daily_picks(sport: str) -> None:
    st.header("投注訊號 (EV)")
    st.caption("僅顯示 EV > 0 的場次 · 四分之一凱利建議倉位")
    df = build_daily_predictions(sport)
    if df.empty:
        st.warning("尚無今日賽程或球隊統計，請先在側欄同步 API 資料。")
        return
    positive = df[df["正EV"] == True].copy()  # noqa: E712
    st.metric("今日正 EV 場次", len(positive))
    if positive.empty:
        st.info("目前無正 EV 訊號。")
        st.dataframe(df.sort_values("EV", ascending=False), use_container_width=True)
    else:
        display = positive.assign(
            模型勝率=lambda x: (x["模型勝率"] * 100).round(1).astype(str) + "%",
            EV=lambda x: (x["EV"] * 100).round(2).astype(str) + "%",
            建議倉位=lambda x: (x["建議倉位"] * 100).round(2).astype(str) + "%",
        )
        st.dataframe(
            display[
                ["對戰", "盤口", "選項", "盤口線", "莊家賠率", "模型勝率", "EV", "建議倉位"]
            ],
            use_container_width=True,
            hide_index=True,
        )


def page_model_health(sport: str) -> None:
    st.header("模型健康度 (Model Health)")
    st.caption("集成模型：Log5 + 貝氏 + Beta-Binomial + 馬可夫近況 + 休息/B2B/H2H 情境")
    db = get_db()
    df = db.get_backtest_frame(sport)
    if df.empty:
        st.warning("尚無歷史預測與賽果，請先執行 `python main.py sync --mode backtest --sport nba`。")
        return

    from sportsbet.evaluation.ev_report import build_ev_backtest_report

    df_ml = df[df["market"] == "moneyline"] if "market" in df.columns else df
    if df_ml.empty:
        st.warning(
            "尚無 moneyline 賠率。請執行 `python main.py sync --mode backtest --sport "
            + sport
            + "`（玩運彩爬蟲）或設定 JBOT_TOKEN。"
        )
        return

    df_ml = df_ml.copy()
    df_ml["model_prob"] = df_ml["model_prob"].astype(float).clip(0.0, 1.0)

    ev_rep = build_ev_backtest_report(df_ml)
    st.subheader("期望值回測（EV Validation）")
    st.write(ev_rep.summary_text)

    e1, e2, e3, e4, e5 = st.columns(5)
    e1.metric("正 EV 筆數", ev_rep.n_positive_ev)
    e2.metric("正 EV ROI", f"{ev_rep.roi_taken:+.2%}")
    e3.metric("平均 EV（正EV）", f"{ev_rep.avg_ev_taken:+.2%}")
    e4.metric("邊際 p-value", f"{ev_rep.p_value_edge:.3f}")
    e5.metric("Profit Factor", f"{ev_rep.profit_factor:.2f}" if ev_rep.profit_factor < 100 else "∞")

    verdict_cols = st.columns(3)
    verdict_cols[0].success("EV 門檻 ✓" if ev_rep.pass_ev_threshold else "EV 門檻 ✗")
    verdict_cols[1].success("校準 ✓" if ev_rep.pass_calibration else "校準 ✗")
    verdict_cols[2].success("ROI ✓" if ev_rep.pass_roi else "ROI ✗")

    if not ev_rep.by_odds_bucket.empty:
        st.subheader("依賠率區間")
        st.dataframe(
            ev_rep.by_odds_bucket.assign(
                win_rate=lambda x: (x["win_rate"] * 100).round(1).astype(str) + "%",
                avg_prob=lambda x: (x["avg_prob"] * 100).round(1).astype(str) + "%",
                avg_ev=lambda x: (x["avg_ev"] * 100).round(2).astype(str) + "%",
                roi=lambda x: (x["roi"] * 100).round(2).astype(str) + "%",
            ),
            use_container_width=True,
            hide_index=True,
        )

    evaluator = EvaluationModule()
    report = evaluator.run_full_evaluation(df_ml)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Brier Score", f"{report.brier_score:.4f}", help="越低越好，0 為完美校準")
    acc = report.accuracy
    c2.metric("預測準確率", f"{acc.get('accuracy', 0):.1%}")
    c3.metric("樣本數", acc.get("n_games", 0))
    c4.metric("實際勝率", f"{acc.get('actual_win_rate', 0):.1%}")

    st.subheader("校準度曲線 (Calibration Curve)")
    curve = report.calibration_curve
    if not curve.empty:
        fig = go.Figure()
        fig.add_trace(
            go.Scatter(
                x=curve["predicted"],
                y=curve["actual"],
                mode="markers+lines",
                name="各分箱實際勝率",
                text=curve["bin_label"],
                marker=dict(size=curve["count"] / curve["count"].max() * 30 + 8),
            )
        )
        fig.add_trace(
            go.Scatter(
                x=[0, 1], y=[0, 1], mode="lines",
                name="完美校準", line=dict(dash="dash", color="gray"),
            )
        )
        fig.update_layout(
            xaxis_title="模型預測勝率（分箱平均）",
            yaxis_title="實際勝率",
            xaxis=dict(range=[0, 1]),
            yaxis=dict(range=[0, 1]),
            height=450,
        )
        st.plotly_chart(fig, use_container_width=True)

    st.subheader("各機率區間勝率比較")
    cal = report.calibration
    if not cal.empty:
        cal_plot = cal.copy()
        cal_plot["區間"] = cal_plot.index.astype(str)
        fig2 = px.bar(
            cal_plot, x="區間", y=["predicted", "actual"],
            barmode="group", labels={"value": "勝率", "variable": "類型"},
            title="預測 vs 實際（分箱）",
        )
        st.plotly_chart(fig2, use_container_width=True)
        st.dataframe(
            cal.rename(columns={"predicted": "預測勝率", "actual": "實際勝率", "count": "場次"}),
            use_container_width=True,
        )


def page_bankroll(sport: str) -> None:
    st.header("資金回測模擬 (Bankroll Simulation)")
    st.caption(f"起始資金 ${config.INITIAL_BANKROLL:,.0f} · 四分之一凱利 · 僅下注 EV > 門檻")

    db = get_db()
    df = db.get_backtest_frame(sport)
    if df.empty:
        st.warning("尚無回測資料。")
        return

    df_ml = df[df["market"] == "moneyline"].copy() if "market" in df.columns else df.copy()
    if df_ml.empty:
        st.warning(
            "尚無 moneyline 賠率。請執行 `python scripts/backfill_playsport_moneyline.py --rebuild` "
            "或 backtest sync。"
        )
        return

    df_ml["model_prob"] = df_ml["model_prob"].astype(float).clip(0.0, 1.0)

    if "ev" not in df_ml.columns:
        risk = RiskManager()
        df_ml["ev"] = df_ml.apply(
            lambda r: risk.expected_value(float(r["model_prob"]), float(r["odds"])), axis=1
        )

    evaluator = EvaluationModule()
    report = evaluator.run_full_evaluation(df_ml)
    summary = report.backtest_summary

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("ROI", f"{summary.get('roi', 0):.2%}")
    c2.metric("最終淨值", f"${summary.get('final_bankroll', config.INITIAL_BANKROLL):,.0f}")
    c3.metric("最大回撤", f"{summary.get('max_drawdown', 0):.2%}")
    c4.metric("下注筆數", summary.get("total_trades", 0))

    eq = report.equity_curve.reset_index(drop=True)
    eq_df = pd.DataFrame({"step": eq.index, "equity": eq.values})
    fig = px.line(eq_df, x="step", y="equity", title="淨值成長曲線 (Equity Curve)")
    fig.add_hline(y=config.INITIAL_BANKROLL, line_dash="dot", annotation_text="起始資金")
    st.plotly_chart(fig, use_container_width=True)

    if not report.trades.empty:
        st.subheader("交易明細")
        st.dataframe(report.trades, use_container_width=True)


def main() -> None:
    st.sidebar.title("運彩量化看板")
    sport = st.sidebar.selectbox("運動", ["nba", "mlb"])
    st.session_state.setdefault("last_api_error", "")

    def _show_sidebar_api_error(exc: Exception, *, prefix: str = "同步失敗") -> None:
        msg = str(exc).strip() or exc.__class__.__name__
        full = f"{prefix}：{msg}"
        st.session_state["last_api_error"] = full
        st.sidebar.error(full)

    st.sidebar.caption(describe_data_source(sport))
    quality = data_quality_summary(get_db(), sport)  # type: ignore[arg-type]
    q_labels = {
        "team_stats": "球隊統計",
        "historical_games": "歷史賽果",
        "tw_odds": "台灣盤口",
        "moneyline_odds": "Moneyline",
        "injuries": "傷兵",
        "player_rolling": "球員滾動",
    }
    for key, label in q_labels.items():
        st.sidebar.caption(f"{'✅' if quality.get(key) else '⬜'} {label}")
    if config.jbot_configured():
        st.sidebar.success("JBot 歷史盤口已設定")
    elif config.PLAYSPORT_MONEYLINE_ENABLED:
        st.sidebar.info("Moneyline：玩運彩固定賠率（無 JBot）")
    else:
        st.sidebar.info("未設定盤口來源")
    if api_key_configured():
        st.sidebar.success("API-Sports 金鑰已設定（作為備援）")
    else:
        st.sidebar.info("未設定 API-Sports：使用 nba_api + ESPN + 運彩 Blob（免費混合模式）")

    from sportsbet import config as app_config
    from sportsbet.data.api_sports import calendar_season, infer_season, season_clamped

    if api_key_configured() and season_clamped(sport):  # type: ignore[arg-type]
        st.sidebar.warning(
            f"API 免費方案僅 {app_config.API_SPORTS_SEASON_MIN}–{app_config.API_SPORTS_SEASON_MAX}；"
            f"當季 {calendar_season(sport)} 改由 nba_api/ESPN。"
        )

    if st.sidebar.button("完整同步（賽程+覆盤）", type="secondary"):
        try:
            db = get_db()
            orch = DataOrchestrator(db)
            with st.spinner("完整同步中…"):
                orch.sync_daily(sport, days_ahead=7, force_players=True)  # type: ignore[arg-type]
                run_incremental_backtest_refresh(db, sport, sync_api=False, sync_injuries=False)
            _persist_database(f"chore(data): full sync {sport}")
            st.session_state["last_api_error"] = ""
            st.sidebar.success("完整同步完成")
            st.cache_resource.clear()
            st.rerun()
        except Exception as exc:
            _show_sidebar_api_error(exc)

    last_live = get_db().get_backtest_sync_meta(sport, "live_synced_at")
    if last_live:
        st.sidebar.caption(f"🟢 Live · {last_live[:16]}")
    else:
        st.sidebar.caption("⚪ 尚未 live 同步 · 請執行 watch")

    try:
        ensure_data(sport)
    except Exception as exc:
        _show_sidebar_api_error(exc, prefix="資料載入失敗")

    render_injury_ticker(get_db(), sport)

    tab0, tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(
        ["即時監控", "賽事預測", "回測覆盤", "球員熱區", "投注訊號", "模型健康度", "資金回測"]
    )
    with tab0:
        page_live_monitor(get_db(), sport, get_prediction_service())
    with tab1:
        page_current_future_predictions(sport, get_prediction_service())
    with tab2:
        page_backtest_review(sport)
    with tab3:
        page_player_hot_cold(get_db(), sport)
    with tab4:
        page_daily_picks(sport)
    with tab5:
        page_model_health(sport)
    with tab6:
        page_bankroll(sport)


if __name__ == "__main__":
    main()
