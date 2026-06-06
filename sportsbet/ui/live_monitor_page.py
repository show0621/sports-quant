"""即時監控分頁：盤口、EV、同步心跳。"""
from __future__ import annotations

from datetime import date, datetime

import pandas as pd
import streamlit as st

from sportsbet import config
from sportsbet.data.data_quality import data_quality_detail
from sportsbet.data.database import SportsDatabase
from sportsbet.risk.ev import RiskManager
from sportsbet.services.live_sync import LiveSyncService
from sportsbet.services.prediction_service import PredictionService, load_stored_for_date_compat


def _trigger_live_sync(
    sport: str,
    db: SportsDatabase,
    *,
    push_github: bool = False,
) -> dict[str, int | str] | None:
    try:
        return LiveSyncService(db).sync_live(sport, push_github=push_github)  # type: ignore[arg-type]
    except Exception as exc:
        st.error(f"即時同步失敗：{exc}")
        return None


@st.fragment(run_every=config.DASHBOARD_AUTOREFRESH_SEC)
def _live_autorefresh_block(sport: str, db: SportsDatabase, *, enabled: bool) -> None:
    if not enabled:
        return
    stats = _trigger_live_sync(sport, db, push_github=False)
    if stats:
        st.session_state["last_live_sync"] = datetime.now().isoformat(timespec="seconds")
        st.session_state["last_live_stats"] = stats


def page_live_monitor(
    db: SportsDatabase,
    sport: str,
    prediction_svc: PredictionService,
) -> None:
    st.header("即時監控")
    st.caption(
        f"背景 `python main.py watch` 每 {config.LIVE_SYNC_INTERVAL_SEC}s 同步 · "
        f"看板每 {config.DASHBOARD_AUTOREFRESH_SEC}s 可選刷新"
    )

    auto = st.toggle("啟用看板自動刷新（即時同步）", value=False, key="live_autorefresh")
    if st.button("立即刷新", type="primary"):
        stats = _trigger_live_sync(sport, db, push_github=True)
        if stats:
            st.session_state["last_live_sync"] = datetime.now().isoformat(timespec="seconds")
            st.session_state["last_live_stats"] = stats
            detail = stats.get("github_detail")
            if detail:
                st.caption(f"GitHub DB · {detail}")
            st.success(f"同步完成：{stats}")

    if auto:
        _live_autorefresh_block(sport, db, enabled=True)

    last = st.session_state.get("last_live_sync") or db.get_backtest_sync_meta(
        sport, "live_synced_at"  # type: ignore[arg-type]
    )
    if last:
        st.metric("最後即時同步", str(last)[:19])

    sync_summary = db.get_sync_status_summary(sport)  # type: ignore[arg-type]
    if sync_summary:
        cols = st.columns(min(len(sync_summary), 4))
        for i, (kind, ts) in enumerate(sync_summary.items()):
            cols[i % len(cols)].caption(f"**{kind}** · {str(ts)[:16] if ts else '—'}")

    health = db.get_last_sync_health(sport, "live")  # type: ignore[arg-type]
    if not health.empty:
        latest = health.iloc[0]
        status = latest.get("status", "—")
        if status == "error":
            st.error(f"上次 live 失敗：{latest.get('message', '')}")
        else:
            st.success(f"Live 狀態正常 · {latest.get('duration_ms', 0)} ms")

    quality = data_quality_detail(db, sport)  # type: ignore[arg-type]
    qcols = st.columns(5)
    labels = [
        ("team_stats", "球隊統計"),
        ("tw_odds", "台灣盤口"),
        ("injuries", "傷兵"),
        ("player_rolling", "球員滾動"),
        ("historical_games", "歷史賽果"),
    ]
    for col, (key, label) in zip(qcols, labels):
        info = quality.get(key) or {}
        col.metric(label, "✅" if info.get("ok") else "⬜", str(info.get("detail") or ""))

    today = date.today().isoformat()
    board = db.get_daily_board(sport, today)
    if board.empty:
        st.warning("今日尚無賽程或盤口。請確認 watch 程序正在執行。")
        st.code("python main.py watch --sport all", language="bash")
        return

    risk = RiskManager()
    forecasts = {
        fc.game_id: fc
        for fc in load_stored_for_date_compat(prediction_svc, sport, today)
        if fc.game_id
    }

    rows = []
    for _, g in board.drop_duplicates(subset=["game_id", "market", "selection"]).iterrows():
        gid = int(g["game_id"])
        fc = forecasts.get(gid)
        market = g.get("market", "moneyline")
        sel = g.get("selection", "home")
        if not fc or pd.isna(g.get("odds")):
            continue
        if market == "moneyline":
            prob = fc.home_win_prob if sel == "home" else fc.away_win_prob
        elif fc.prob_over is not None:
            prob = fc.prob_over if sel == "over" else (1.0 - fc.prob_over)
        else:
            continue
        odds = float(g["odds"])
        sig = risk.evaluate(prob, odds)
        rows.append(
            {
                "對戰": f"{g['home_team']} vs {g['away_team']}",
                "盤口": market,
                "選項": sel,
                "賠率": odds,
                "模型勝率": f"{prob * 100:.1f}%",
                "EV": f"{sig.ev * 100:+.2f}%",
                "正EV": sig.is_positive_ev,
                "盤口更新": str(g.get("odds_updated_at", ""))[:19],
            }
        )

    df = pd.DataFrame(rows)
    if df.empty:
        st.info("有賽程但尚無完整預測/賠率配對。")
        return

    positive = df[df["正EV"] == True]  # noqa: E712
    st.metric("今日正 EV", len(positive), f"共 {len(df)} 筆盤口")
    show = positive if not positive.empty else df
    st.dataframe(show.drop(columns=["正EV"]), use_container_width=True, hide_index=True)
