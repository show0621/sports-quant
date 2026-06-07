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
from sportsbet.data.db_github_sync import DbPushResult, persist_database_after_sync  # noqa: E402
from sportsbet.data.data_quality import data_quality_detail  # noqa: E402
from sportsbet.data.orchestrator import DataOrchestrator  # noqa: E402
from sportsbet.data.provider import api_key_configured, describe_data_source  # noqa: E402
from sportsbet.evaluation.evaluator import EvaluationModule  # noqa: E402
from sportsbet.models.analytics_engine import AnalyticsEngine  # noqa: E402
from sportsbet.risk.ev import RiskManager  # noqa: E402
from sportsbet.services.data_refresh import run_full_backtest_refresh, run_incremental_backtest_refresh  # noqa: E402
from sportsbet.services.prediction_service import PredictionService, load_stored_for_date_compat  # noqa: E402
from sportsbet.ui.live_monitor_page import page_live_monitor  # noqa: E402
from sportsbet.ui.live_scoreboard import render_live_scoreboard  # noqa: E402
from sportsbet.ui.theme import inject_dashboard_theme, render_masthead  # noqa: E402
from sportsbet.ui.hot_cold_page import page_player_hot_cold  # noqa: E402
from sportsbet.ui.injury_ticker import render_injury_ticker  # noqa: E402
from sportsbet.ui.upcoming_page import page_current_future_predictions  # noqa: E402
from sportsbet.data.team_names import team_bilingual  # noqa: E402
from sportsbet.ui.odds_display import _fmt_odds  # noqa: E402

st.set_page_config(page_title="韻彩 · 賽事分析", layout="wide", page_icon="📊", initial_sidebar_state="expanded")


def _pct(v: float | None) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    return f"{float(v) * 100:.1f}%"


# 遞增以在 Streamlit Cloud 部署後清掉舊版 SportsDatabase 快取
_DB_CACHE_VERSION = 9


def _schedule_coverage(db: SportsDatabase, sport: str) -> dict[str, object]:
    """賽程涵蓋範圍；相容舊版快取中的 SportsDatabase 實例。"""
    if hasattr(db, "get_schedule_coverage"):
        return db.get_schedule_coverage(sport)  # type: ignore[attr-defined]
    today = date.today().isoformat()
    empty: dict[str, object] = {
        "first_date": "",
        "last_date": "",
        "total_games": 0,
        "today_games": 0,
        "future_games": 0,
        "covers_today": False,
    }
    try:
        with db.connection() as conn:
            row = conn.execute(
                """
                SELECT MAX(match_date) AS last_date,
                       MIN(match_date) AS first_date,
                       COUNT(*) AS total_games,
                       SUM(CASE WHEN match_date = ? THEN 1 ELSE 0 END) AS today_games,
                       SUM(CASE WHEN match_date >= ? THEN 1 ELSE 0 END) AS future_games
                FROM games WHERE sport = ?
                """,
                (today, today, sport),
            ).fetchone()
    except Exception:
        return empty
    if not row:
        return empty
    last = str(row["last_date"] or "")[:10]
    first = str(row["first_date"] or "")[:10]
    return {
        "first_date": first,
        "last_date": last,
        "total_games": int(row["total_games"] or 0),
        "today_games": int(row["today_games"] or 0),
        "future_games": int(row["future_games"] or 0),
        "covers_today": last >= today if last else False,
    }


def _market_data_fingerprint(db: SportsDatabase, sport: str) -> str:
    if hasattr(db, "get_market_data_fingerprint"):
        return db.get_market_data_fingerprint(sport)  # type: ignore[attr-defined]
    return f"{sport}:legacy"


def _sync_meta(db: SportsDatabase, sport: str, meta_key: str) -> str | None:
    """讀取 backtest_sync_meta；相容舊版 DB 包裝。"""
    if hasattr(db, "get_backtest_sync_meta"):
        return db.get_backtest_sync_meta(sport, meta_key)  # type: ignore[attr-defined]
    try:
        with db.connection() as conn:
            row = conn.execute(
                "SELECT meta_value FROM backtest_sync_meta WHERE sport = ? AND meta_key = ?",
                (sport, meta_key),
            ).fetchone()
        return str(row["meta_value"]) if row and row["meta_value"] is not None else None
    except Exception:
        return None


@st.cache_resource
def get_db(_cache_version: int = _DB_CACHE_VERSION) -> SportsDatabase:
    return SportsDatabase()


@st.cache_resource
def get_prediction_service(_cache_version: int = _DB_CACHE_VERSION) -> PredictionService:
    return PredictionService(get_db(_cache_version))


@st.cache_data(show_spinner=False)
def _cached_bankroll_simulation(
    fingerprint: str,
    sport: str,
    market_key: str,
    allowed_markets: tuple[str, ...],
    min_ev: float,
) -> tuple[dict, pd.Series, pd.DataFrame, int]:
    """從 DB 讀 predictions + 跑 Kelly 模擬；fingerprint 變才重算。"""
    db = SportsDatabase()
    df = db.get_backtest_frame(sport)
    if df.empty:
        return {"error": "無資料"}, pd.Series([config.INITIAL_BANKROLL]), pd.DataFrame(), 0
    df = df.dropna(subset=["model_prob", "won", "odds"]).copy()
    if market_key == "all":
        df = df[df["market"].isin(allowed_markets)].copy()
    else:
        df = df[df["market"] == market_key].copy()
    if df.empty:
        return {"error": "無資料"}, pd.Series([config.INITIAL_BANKROLL]), pd.DataFrame(), len(df)
    df["model_prob"] = df["model_prob"].astype(float).clip(0.0, 1.0)
    if "ev" not in df.columns or df["ev"].isna().all():
        risk = RiskManager()
        df["ev"] = df.apply(
            lambda r: risk.expected_value(float(r["model_prob"]), float(r["odds"])), axis=1
        )
    summary, equity, trades = EvaluationModule(min_ev=min_ev).run_bankroll_simulation(df)
    return summary, equity, trades, len(df)


def _persist_database(message: str | None = None, *, db: SportsDatabase | None = None) -> DbPushResult:
    """資料變更後推送 SQLite 至 GitHub（供 Cloud / 其他使用者讀取 repo DB）。"""
    try:
        return persist_database_after_sync(message, db=db or get_db())
    except Exception as exc:
        return DbPushResult(False, "failed", str(exc))


def _show_db_push_result(result: DbPushResult) -> None:
    if result.status == "pushed":
        st.sidebar.success(f"GitHub DB · {result.detail}")
    elif result.status == "unchanged":
        st.sidebar.info(f"GitHub DB · {result.detail}")
    elif result.status == "skipped":
        st.sidebar.warning(f"GitHub DB 未推送 · {result.detail}")
    else:
        st.sidebar.error(f"GitHub DB 推送失敗 · {result.detail}")


def _render_db_coverage(db: SportsDatabase, sport: str) -> None:
    cov = _schedule_coverage(db, sport)
    last = str(cov.get("last_date") or "—")
    today_ok = "含今日" if cov.get("covers_today") else "尚無今日"
    pushed = _sync_meta(db, sport, "db_pushed_at")
    push_note = f" · GitHub {str(pushed)[:16]}" if pushed else ""
    st.sidebar.caption(
        f"📦 DB 賽程 {cov.get('first_date', '—')} → {last} · {today_ok} · "
        f"{cov.get('total_games', 0)} 場{push_note}"
    )
    st.sidebar.caption("看板優先讀取 repo 內 data/sportsbet.db；同步後自動推送 GitHub。")


def ensure_data(sport: str) -> None:
    """看板載入：優先讀 repo DB；僅在資料空或缺今日賽程時提示同步。"""
    db = get_db()
    cov = _schedule_coverage(db, sport)
    if cov.get("covers_today") or cov.get("total_games", 0) > 0:
        return
    if db.get_team_stats(sport).empty and db.get_games(sport, date.today().isoformat()).empty:
        st.sidebar.warning(
            "資料庫為空。請先執行：`python main.py watch --sport all` 或 `python main.py sync --mode daily --sport all`"
        )


def build_daily_predictions(sport: str) -> pd.DataFrame:
    from sportsbet.ui.matchup_display import taipei_match_date

    db = get_db()
    svc = get_prediction_service()
    risk = RiskManager()
    today = date.today().isoformat()
    board = db.get_daily_board(sport, today)
    if board.empty:
        for offset in (-1, 1):
            alt = (date.today() + timedelta(days=offset)).isoformat()
            board = db.get_daily_board(sport, alt)
            if not board.empty:
                break
    if board.empty:
        return pd.DataFrame()

    forecasts = {fc.game_id: fc for fc in load_stored_for_date_compat(svc, sport, today) if fc.game_id}
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
            if pd.isna(g.get("odds")):
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
            elif pd.notna(g.get("handicap")):
                line = float(g["handicap"])
                prob = engine.prob_total_over(line, pred.lambda_home, pred.lambda_away)
                if sel == "under":
                    prob = 1.0 - prob
            else:
                continue
        odds = float(g["odds"])
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


def _team_label(name: str, sport: str) -> str:
    en, zh = team_bilingual(name, sport)
    return f"{en} / {zh}" if zh else en


def _fmt_spread_line(v: float | None) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    return f"{float(v):+.1f}"


def page_backtest_review(sport: str) -> None:
    st.header("回測覆盤（歷史賽事）")
    st.caption(
        f"僅顯示 **{sport.upper()}** 賽事（已過濾跨球種污染）· "
        f"預設回測區間：過去 {config.BACKTEST_YEARS} 年（{config.BACKTEST_DAYS} 天）。"
        f"已結束賽事覆盤會寫入資料庫；之後只補最近 {config.BACKTEST_INCREMENTAL_LOOKBACK_DAYS} 天與缺漏日期。"
        "現在/未來預測請至「賽事預測」分頁。"
    )

    svc = get_prediction_service()
    db = get_db()
    bc1, bc2 = st.columns(2)
    with bc1:
        full_refresh = st.button("重新產生全部覆盤紀錄", type="primary")
    with bc2:
        bayes_recalc = st.button("僅重算預測（今日+歷史，貝氏模型）", type="secondary")
    if bayes_recalc:
        with st.spinner("重算今日/未來與全部歷史覆盤（貝氏集成管線）…"):
            stats = svc.recompute_all_forecasts(sport)
            _persist_database(f"chore(model): bayesian recompute {sport}", db=db)
        st.success(
            f"預測已更新：今日/未來 {stats.get('upcoming', 0)} 場 · "
            f"歷史覆盤 {stats.get('history', 0)} 場"
        )
        st.cache_resource.clear()
        st.cache_data.clear()
        st.rerun()
    if full_refresh:
        with st.spinner("同步歷史賽果、傷兵並重算全部覆盤…"):
            stats = run_full_backtest_refresh(db, sport, sync_api=True, sync_injuries=True)
            _persist_database(f"chore(data): full backtest refresh {sport}", db=db)
        st.success(
            f"覆盤已更新：{stats.get('forecasts', 0)} 場預測、"
            f"{stats.get('games_with_scores', 0)} 場有比分、"
            f"{stats.get('predictions', 0)} 筆投注紀錄"
        )
        st.cache_resource.clear()
        st.cache_data.clear()
        st.rerun()

    review = svc.get_review_table(sport, final_only=True)
    if review.empty:
        st.warning("尚無已結束賽事的覆盤資料，請先載入歷史賽果或按上方按鈕產生。")
        return

    unit = "分" if sport == "nba" else "分"
    total_label = "大小分" if sport == "nba" else "大小分（總得分）"
    if "has_total_odds" in review.columns:
        with_total = int((review["has_total_odds"] > 0).sum())
        with_ml = int((review["has_ml_odds"] > 0).sum()) if "has_ml_odds" in review.columns else 0
        with_sp = int((review["has_spread_odds"] > 0).sum()) if "has_spread_odds" in review.columns else 0
        full_odds = 0
        if {"has_total_odds", "has_ml_odds", "has_spread_odds"}.issubset(review.columns):
            full_odds = int(
                ((review["has_total_odds"] > 0) & (review["has_ml_odds"] > 0) & (review["has_spread_odds"] > 0)).sum()
            )
        st.caption(
            f"運動：**{sport.upper()}** · 共 {len(review)} 場 · "
            f"勝負盤 {with_ml} · 讓分（勝分差）{with_sp} · {total_label} {with_total} · "
            f"三項齊全 {full_odds} 場"
        )
        if with_total == 0 or with_ml == 0 or with_sp == 0:
            missing = []
            if with_ml == 0:
                missing.append("勝負")
            if with_sp == 0:
                missing.append("讓分（勝分差）")
            if with_total == 0:
                missing.append(total_label)
            st.warning(
                f"部分場次缺少 {' / '.join(missing)} 賠率。"
                "請執行 `python scripts/repair_data.py --sport "
                f"{sport}` 或側欄「完整同步」以還原玩運彩 / 台灣運彩盤口。"
            )

    hits = review["pick_correct"].sum()
    total = len(review)
    c1, c2, c3 = st.columns(3)
    c1.metric("勝負預測命中", f"{hits}/{total}", f"{hits/total:.1%}" if total else "—")
    if "margin_error" in review.columns:
        c2.metric("平均分差誤差", f"{review['margin_error'].abs().mean():.1f} {unit}")
    if "total_error" in review.columns:
        c3.metric("平均總分誤差", f"{review['total_error'].abs().mean():.1f} {unit}")

    display = review.copy()
    display["主隊"] = display["home_team"].map(lambda x: _team_label(x, sport))
    display["客隊"] = display["away_team"].map(lambda x: _team_label(x, sport))
    if "odds_total_line" in display.columns:
        display["大小分線(盤口)"] = display["odds_total_line"].combine_first(display.get("total_line"))
    display = display.rename(
        columns={
            "match_date": "日期",
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
            "prob_over": "大" + ("分" if sport == "nba" else "") + "機率",
            "total_line": total_label + "線(模型)",
            "ml_home_odds": "主勝賠率",
            "ml_away_odds": "客勝賠率",
            "spread_home_line": "主讓分線",
            "spread_home_odds": "主讓分賠率",
            "spread_away_line": "客讓分線",
            "spread_away_odds": "客讓分賠率",
            "over_odds": "大分賠率",
            "under_odds": "小分賠率",
        }
    )
    pct_cols = [
        "主隊勝率(最終)", "客隊勝率(最終)", "主隊勝率(傷兵前)", "客隊勝率(傷兵前)",
        "大分機率" if sport == "nba" else "大機率",
    ]
    adj_cols = ["主隊傷兵修正", "客隊傷兵修正"]
    for col in pct_cols:
        if col in display.columns:
            display[col] = display[col].map(_pct)
    for col in adj_cols:
        if col in display.columns:
            display[col] = display[col].map(lambda x: f"{float(x)*100:+.1f}%" if pd.notna(x) else "—")

    odds_cols = ["主勝賠率", "客勝賠率", "主讓分賠率", "客讓分賠率", "大分賠率", "小分賠率"]
    for col in odds_cols:
        if col in display.columns:
            display[col] = display[col].map(_fmt_odds)
    for col in ["主讓分線", "客讓分線"]:
        if col in display.columns:
            display[col] = display[col].map(_fmt_spread_line)
    if "大小分線(盤口)" in display.columns:
        display["大小分線(盤口)"] = display["大小分線(盤口)"].map(
            lambda x: f"{float(x):.1f}" if pd.notna(x) and x is not None else "—"
        )

    show_cols = [
        c
        for c in [
            "日期", "主隊", "客隊", "預測勝者", "實際勝者", "預測正確",
            "主勝賠率", "客勝賠率",
            "主讓分線", "主讓分賠率", "客讓分線", "客讓分賠率",
            "大小分線(盤口)", "大分賠率", "小分賠率",
            "主隊勝率(傷兵前)", "主隊傷兵修正", "主隊勝率(最終)",
            "客隊勝率(傷兵前)", "客隊傷兵修正", "客隊勝率(最終)",
            "預測主隊分", "預測客隊分", "實際主隊分", "實際客隊分",
            "預測總分", "預測分差", "分差誤差", "總分誤差",
            total_label + "線(模型)", "大分機率" if sport == "nba" else "大機率",
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
    from sportsbet.ui.model_methodology import render_methodology_overview

    with st.expander("貝氏集成 PK 模型方法論", expanded=True):
        render_methodology_overview()
    st.caption("集成模型：Log5 + 貝氏 + Beta-Binomial + 馬可夫近況 + H2H + 傷兵 + MC")
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

    from sportsbet.evaluation.market_backtest import build_market_backtest_table

    st.subheader("分玩法回測（勝率 / EV / ROI）")
    mkt_table = build_market_backtest_table(df)
    if not mkt_table.empty:
        show_mkt = mkt_table.copy()
        for col in ("準確率", "正EV勝率", "ROI(正EV)"):
            if col in show_mkt.columns:
                show_mkt[col] = show_mkt[col].map(
                    lambda x: f"{x:.1%}" if pd.notna(x) else "—"
                )
        for col in ("Brier",):
            if col in show_mkt.columns:
                show_mkt[col] = show_mkt[col].map(
                    lambda x: f"{x:.4f}" if pd.notna(x) else "—"
                )
        for col in ("平均EV",):
            if col in show_mkt.columns:
                show_mkt[col] = show_mkt[col].map(
                    lambda x: f"{x:+.2%}" if pd.notna(x) else "—"
                )
        st.dataframe(
            show_mkt.drop(columns=["market"], errors="ignore"),
            use_container_width=True,
            hide_index=True,
        )

    mkt_tabs = st.tabs(["不讓分", "讓分", "大小分", "勝分差"])
    for tab, market in zip(mkt_tabs, ["moneyline", "spread", "total", "margin"], strict=True):
        with tab:
            sub = df[df["market"] == market].copy()
            if sub.empty:
                st.info(f"尚無 {market} 回測資料（需歷史賠率 + predictions）。")
                continue
            sub["model_prob"] = sub["model_prob"].astype(float).clip(0.0, 1.0)
            rep = build_ev_backtest_report(sub)
            st.write(rep.summary_text)
            c1, c2, c3 = st.columns(3)
            c1.metric("樣本數", len(sub))
            c2.metric("正 EV ROI", f"{rep.roi_taken:+.2%}" if rep.n_positive_ev else "—")
            c3.metric("正 EV 筆數", rep.n_positive_ev)

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
    from sportsbet.ui.bankroll_display import (
        format_bankroll_trades,
        format_compact_pct,
        format_compact_twd,
        inject_bankroll_compact_style,
    )

    inject_bankroll_compact_style()
    st.header("資金回測模擬 (Bankroll Simulation)")
    st.caption(
        f"起始 NT$ {config.INITIAL_BANKROLL/10000:.0f}萬 · "
        f"每場僅下注 EV 最高且 > {config.MIN_EV_THRESHOLD:.0%} 的單一玩法 · "
        f"凱利 f*×{config.KELLY_FRACTION:g}（上限 {config.MAX_BET_FRACTION:.0%}）· 依日期序 · "
        f"**預測/賠率已存 DB，重整僅讀庫 + 快取模擬**"
    )

    db = get_db()
    fp = _market_data_fingerprint(db, sport)

    allowed = config.BANKROLL_MARKETS.get(sport, ("moneyline", "total", "spread"))
    market_opts = {"全部": "all", "勝負": "moneyline", "大小分": "total", "讓分": "spread", "勝分差": "margin"}
    if sport == "mlb" and "moneyline" not in allowed:
        st.info("MLB 勝率模型校準不足，回測預設僅含大小盤；勝負盤可手動篩選檢視。")
    market_label = st.selectbox("盤口篩選", list(market_opts.keys()), index=0)
    market_key = market_opts[market_label]

    summary, equity, trades, raw_n = _cached_bankroll_simulation(
        fp,
        sport,
        market_key,
        tuple(allowed),
        config.MIN_EV_THRESHOLD,
    )
    if summary.get("error") == "無資料" and raw_n == 0:
        with db.connection() as conn:
            pred_n = conn.execute(
                "SELECT COUNT(*) FROM predictions p JOIN games g ON g.id=p.game_id WHERE g.sport=?",
                (sport,),
            ).fetchone()[0]
        if pred_n == 0:
            st.warning("尚無回測資料。請先執行 watch 或側欄「完整同步」。")
        else:
            st.warning(f"「{market_label}」尚無可回測資料（predictions 共 {pred_n} 筆）。")
        return

    st.markdown('<div class="bankroll-metrics">', unsafe_allow_html=True)
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("ROI", format_compact_pct(summary.get("roi", 0), signed=True))
    c2.metric("最終淨值", format_compact_twd(summary.get("final_bankroll", config.INITIAL_BANKROLL)))
    c3.metric("最大回撤", format_compact_pct(summary.get("max_drawdown", 0)))
    c4.metric("下注場次", summary.get("total_trades", 0))
    c5.metric("總損益", format_compact_twd(summary.get("total_pnl", 0), signed=True))
    st.markdown("</div>", unsafe_allow_html=True)

    roi = float(summary.get("roi", 0))
    if roi < 0 and not trades.empty:
        t = trades
        st.warning(
            f"回測虧損（ROI {format_compact_pct(roi, signed=True)}）。"
            f"模型勝率 {t['prob'].mean():.0%} vs 實際 {t['won'].mean():.0%}；"
            f"常見原因：大小分 Poisson 過度自信、或勝率與賽果相關性不足。"
        )

    eq = equity.reset_index(drop=True)
    eq_df = pd.DataFrame({"step": eq.index, "equity": eq.values})
    fig = px.line(eq_df, x="step", y="equity", title="淨值成長曲線 (Equity Curve)")
    fig.add_hline(y=config.INITIAL_BANKROLL, line_dash="dot", annotation_text="起始")
    fig.update_layout(
        height=320,
        margin=dict(l=40, r=20, t=40, b=40),
        yaxis_tickformat=",.0f",
        yaxis_title="台幣",
    )
    st.plotly_chart(fig, use_container_width=True)

    if not trades.empty:
        st.subheader("交易明細")
        st.caption(
            "每場一筆：該場 EV 最高且為正的唯一玩法 · 倉位依凱利公式 · "
            "含日期、對戰、盤口、賠率、投注與損益。"
        )
        detail = format_bankroll_trades(trades, sport)
        st.dataframe(detail, use_container_width=True, hide_index=True)
        wins = int(trades["won"].sum()) if "won" in trades.columns else 0
        total = len(trades)
        st.caption(f"命中 {wins}/{total}（{wins/total:.1%}）" if total else "")


def main() -> None:
    inject_dashboard_theme()
    st.sidebar.title("韻彩分析")
    sport = st.sidebar.selectbox("運動項目", ["nba", "mlb"], format_func=lambda x: "NBA 籃球" if x == "nba" else "MLB 棒球")
    st.session_state.setdefault("last_api_error", "")

    def _show_sidebar_api_error(exc: Exception, *, prefix: str = "同步失敗") -> None:
        msg = str(exc).strip() or exc.__class__.__name__
        full = f"{prefix}：{msg}"
        st.session_state["last_api_error"] = full
        st.sidebar.error(full)

    st.sidebar.caption(describe_data_source(sport))
    quality = data_quality_detail(get_db(), sport)  # type: ignore[arg-type]
    q_labels = {
        "team_stats": "球隊統計",
        "historical_games": "歷史賽果",
        "tw_odds": "台灣盤口",
        "moneyline_odds": "Moneyline",
        "injuries": "傷兵",
        "player_rolling": "球員滾動",
    }
    for key, label in q_labels.items():
        info = quality.get(key) or {}
        mark = "✅" if info.get("ok") else "⬜"
        detail = str(info.get("detail") or "")
        st.sidebar.caption(f"{mark} {label} · {detail}")
    if config.SPORTSLOTTERY_PLAYWRIGHT_ENABLED:
        st.sidebar.success("台灣運彩官網 SPA 爬蟲已啟用")
    elif config.PLAYSPORT_ENABLED:
        st.sidebar.warning(
            "賽前盤口：請啟用 SPORTSLOTTERY_PLAYWRIGHT（官網 event 頁）。"
            "玩運彩僅補官網缺漏之歷史場次。"
        )
    else:
        st.sidebar.warning("未啟用官網 / 玩運彩盤口來源")
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
            svc = get_prediction_service()
            with st.spinner("完整同步中…（完成後推送 GitHub DB）"):
                orch.sync_daily(sport, force_players=True)  # type: ignore[arg-type]
                run_incremental_backtest_refresh(
                    db, sport, sync_api=False, sync_injuries=False,
                    days_lineup=config.SCHEDULE_SYNC_DAYS_AHEAD,
                )
                svc.sync_upcoming_odds(
                    sport, days_ahead=config.SCHEDULE_SYNC_DAYS_AHEAD,
                )
                svc.run_upcoming(sport, days_ahead=config.SCHEDULE_SYNC_DAYS_AHEAD)
            push = _persist_database(f"chore(data): full sync {sport}", db=db)
            _show_db_push_result(push)
            st.session_state["last_api_error"] = ""
            st.sidebar.success("完整同步完成")
            st.cache_resource.clear()
            st.cache_data.clear()
            st.rerun()
        except Exception as exc:
            _show_sidebar_api_error(exc)

    _render_db_coverage(get_db(), sport)

    last_live = _sync_meta(get_db(), sport, "live_synced_at")
    if last_live:
        st.sidebar.caption(f"🟢 Live · {last_live[:16]}")
    else:
        st.sidebar.caption("⚪ 尚未 live 同步 · 請執行 watch")

    try:
        ensure_data(sport)
    except Exception as exc:
        _show_sidebar_api_error(exc, prefix="資料載入失敗")

    render_masthead(sport)
    render_injury_ticker(get_db(), sport)

    tab0, tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(
        ["即時賽況", "賽事預測", "歷史覆盤", "球員熱區", "投注訊號", "模型健康", "資金回測"]
    )
    with tab0:
        detail_id = st.session_state.get("game_detail_id")
        if detail_id:
            from sportsbet.ui.game_center_page import render_game_center

            render_game_center(get_db(), sport, int(detail_id), on_close="game_detail_id")
            st.divider()
        render_live_scoreboard(get_db(), sport, get_prediction_service())
        st.divider()
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
