"""
Streamlit 多頁面看板：每日預測、模型健康度、資金回測。

啟動：streamlit run dashboard.py
"""
from __future__ import annotations

import sys
from datetime import date
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
from sportsbet.data.ingestion import MockDataProvider  # noqa: E402
from sportsbet.evaluation.evaluator import EvaluationModule  # noqa: E402
from sportsbet.models.analytics_engine import AnalyticsEngine  # noqa: E402
from sportsbet.risk.ev import RiskManager  # noqa: E402

st.set_page_config(page_title="運彩量化看板", layout="wide", page_icon="📊")


@st.cache_resource
def get_db() -> SportsDatabase:
    return SportsDatabase()


def ensure_data(sport: str, *, seed_history: bool) -> None:
    db = get_db()
    provider = MockDataProvider(db)
    if db.get_team_stats(sport).empty:
        provider.fetch_historical_stats(sport)
    today = date.today().isoformat()
    if db.get_games(sport, today).empty:
        provider.fetch_daily_schedule(sport, today)
        provider.fetch_odds(sport, today)
    if seed_history and db.get_backtest_frame(sport).empty:
        provider.seed_historical_backtest(sport, days=60)


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


def page_daily_picks(sport: str) -> None:
    st.header("每日預測 (Daily Picks)")
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
    seed = st.sidebar.checkbox("載入 60 天 MOCK 歷史（回測用）", value=True)
    if st.sidebar.button("重新載入 MOCK 資料"):
        db = get_db()
        provider = MockDataProvider(db)
        provider.fetch_historical_stats(sport)
        provider.fetch_daily_schedule(sport)
        provider.fetch_odds(sport)
        if seed:
            provider.seed_historical_backtest(sport, days=60)
        st.sidebar.success("資料已更新")
        st.cache_resource.clear()
        st.rerun()

    ensure_data(sport, seed_history=seed)

    tab1, tab2, tab3 = st.tabs(["每日預測", "模型健康度", "資金回測"])
    with tab1:
        page_daily_picks(sport)
    with tab2:
        page_model_health(sport)
    with tab3:
        page_bankroll(sport)


if __name__ == "__main__":
    main()
