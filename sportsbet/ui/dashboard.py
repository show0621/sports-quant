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
from sportsbet.data.player_ingestion import sync_v2_player_data  # noqa: E402
from sportsbet.data.ingestion import MockDataProvider  # noqa: E402
from sportsbet.data.provider import api_key_configured, get_data_provider  # noqa: E402
from sportsbet.evaluation.evaluator import EvaluationModule  # noqa: E402
from sportsbet.models.analytics_engine import AnalyticsEngine  # noqa: E402
from sportsbet.models.forecast import team_detail_dataframe  # noqa: E402
from sportsbet.risk.ev import RiskManager  # noqa: E402
from sportsbet.services.prediction_service import PredictionService  # noqa: E402
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


def ensure_data(sport: str, *, seed_history: bool, use_mock_only: bool = False) -> None:
    db = get_db()
    provider = MockDataProvider(db) if use_mock_only else get_data_provider(db)
    season = None
    if api_key_configured() and not use_mock_only:
        from sportsbet.data.api_sports import infer_season

        season = infer_season(sport)  # type: ignore[arg-type]

    if db.get_team_stats(sport).empty:
        provider.fetch_historical_stats(sport, season)
    from datetime import timedelta

    today = date.today().isoformat()
    for offset in range(7):
        d = (date.today() + timedelta(days=offset)).isoformat()
        if db.get_games(sport, d).empty:
            provider.fetch_daily_schedule(sport, d)
            if offset == 0:
                provider.fetch_odds(sport, d)
    if seed_history and db.get_backtest_frame(sport).empty and (use_mock_only or not api_key_configured()):
        provider.seed_historical_backtest(sport, days=60)

    svc = get_prediction_service()
    svc.run_upcoming(sport, days_ahead=7)
    if db.get_injuries(sport).empty and not api_key_configured():
        sync_v2_player_data(db, sport)

    if db.get_forecast_review(sport, final_only=True).empty:
        svc.run_backtest_reconcile(sport)


def build_daily_predictions(sport: str) -> pd.DataFrame:
    db = get_db()
    engine = AnalyticsEngine(sport)  # type: ignore[arg-type]
    risk = RiskManager()
    stats = db.get_team_stats(sport).set_index("team")
    board = db.get_daily_board(sport, date.today().isoformat())
    if board.empty or stats.empty:
        return pd.DataFrame()

    rows = []
    for _, g in board.drop_duplicates(subset=["game_id", "market", "selection"]).iterrows():
        ht, at = g["home_team"], g["away_team"]
        if ht not in stats.index or at not in stats.index:
            continue
        h, a = stats.loc[ht], stats.loc[at]
        pred = engine.predict_matchup(
            h["rs_per_game"], h["ra_per_game"], a["rs_per_game"], a["ra_per_game"],
            home_recent_win_pct=h.get("recent_win_pct"),
            away_recent_win_pct=a.get("recent_win_pct"),
        )
        market = g.get("market", "moneyline")
        sel = g.get("selection", "home")
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
        "現在/未來預測請至「賽事預測」分頁。"
    )

    svc = get_prediction_service()
    if st.button("重新產生全部覆盤紀錄", type="primary"):
        with st.spinner("計算中…"):
            svc.run_backtest_reconcile(sport)
        st.success("覆盤紀錄已更新")
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
            "home_win_prob": "主隊預測勝率",
            "away_win_prob": "客隊預測勝率",
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
    pct_cols = ["主隊預測勝率", "客隊預測勝率", "大分機率"]
    for col in pct_cols:
        if col in display.columns:
            display[col] = display[col].map(_pct)

    show_cols = [
        c
        for c in [
            "日期", "主隊", "客隊", "預測勝者", "實際勝者", "預測正確",
            "主隊預測勝率", "客隊預測勝率",
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
        st.warning("尚無今日賽程或球隊統計，請按側欄「重新載入 MOCK 資料」。")
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
    db = get_db()
    df = db.get_backtest_frame(sport)
    if df.empty:
        st.warning("尚無歷史預測與賽果，請先載入 MOCK 歷史資料。")
        return

    evaluator = EvaluationModule()
    report = evaluator.run_full_evaluation(df)

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

    if "ev" not in df.columns:
        risk = RiskManager()
        df = df.copy()
        df["ev"] = df.apply(
            lambda r: risk.expected_value(float(r["model_prob"]), float(r["odds"])), axis=1
        )

    evaluator = EvaluationModule()
    report = evaluator.run_full_evaluation(df)
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

    if api_key_configured():
        st.sidebar.success("API-Sports 已設定")
    else:
        st.sidebar.warning("未設定 API_SPORTS_KEY（使用 MOCK）")

    seed = st.sidebar.checkbox(
        "載入 MOCK 歷史（僅無 API 時）",
        value=not api_key_configured(),
        disabled=api_key_configured(),
    )

    if st.sidebar.button("同步 API-Sports + 運彩賠率"):
        if not api_key_configured():
            st.sidebar.error("請先在 Secrets 或 .env 設定 API_SPORTS_KEY")
        else:
            db = get_db()
            provider = get_data_provider(db)
            with st.spinner("同步中…"):
                from sportsbet.data.api_sports import ApiSportsClient, infer_season

                season = infer_season(sport)  # type: ignore[arg-type]
                client = ApiSportsClient()
                if client.is_configured:
                    client.sync_team_logos(get_db(), sport, season)
                provider.fetch_historical_stats(sport, season)
                provider.fetch_daily_schedule(sport)
                provider.fetch_odds(sport)
            svc_pred = get_prediction_service()
            for offset in range(7):
                d = (date.today() + timedelta(days=offset)).isoformat()
                provider.fetch_daily_schedule(sport, d)
            provider.fetch_odds(sport)
            svc_pred.run_upcoming(sport, days_ahead=7)
            svc_pred.run_backtest_reconcile(sport)
            st.sidebar.success("同步完成")
            st.cache_resource.clear()
            st.rerun()

    if st.sidebar.button("重新載入 MOCK 資料"):
        db = get_db()
        provider = MockDataProvider(db)
        provider.fetch_historical_stats(sport)
        from datetime import timedelta as _td

        for _off in range(7):
            _d = (date.today() + _td(days=_off)).isoformat()
            provider.fetch_daily_schedule(sport, _d)
        provider.fetch_odds(sport)
        if seed or not api_key_configured():
            provider.seed_historical_backtest(sport, days=60)
        sync_v2_player_data(db, sport)
        st.sidebar.success("MOCK 資料已更新")
        st.cache_resource.clear()
        st.rerun()

    with st.sidebar.expander("傷兵示範 (MOCK)", expanded=False):
        st.caption("API-Sports 尚無傷兵端點；僅供介面示範。")
        db_inj = get_db()
        if st.button("載入示範傷兵", key="load_mock_inj"):
            sync_v2_player_data(db_inj, sport)
            st.success("已載入示範傷兵")
            st.rerun()
        if st.button("清除示範傷兵", key="clear_mock_inj"):
            n = db_inj.clear_injuries(sport, source="mock")
            st.success(f"已清除 {n} 筆")
            st.rerun()

    ensure_data(sport, seed_history=seed)

    render_injury_ticker(get_db(), sport)

    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(
        ["賽事預測", "回測覆盤", "球員熱區", "投注訊號", "模型健康度", "資金回測"]
    )
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
