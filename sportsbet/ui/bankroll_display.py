"""資金回測交易明細格式化。"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from sportsbet.data.team_names import team_bilingual

_MARKET_ZH = {
    "moneyline": "勝負",
    "total": "大小分",
    "spread": "讓分",
}


def inject_bankroll_compact_style() -> None:
    """縮小資金回測摘要數字，避免 metric 滿版。"""
    st.markdown(
        """
        <style>
        div.bankroll-metrics [data-testid="stMetric"] {
            background: #f8fafc;
            border: 1px solid #e2e8f0;
            border-radius: 8px;
            padding: 0.35rem 0.5rem;
        }
        div.bankroll-metrics [data-testid="stMetricLabel"] {
            font-size: 0.72rem !important;
        }
        div.bankroll-metrics [data-testid="stMetricValue"] {
            font-size: 0.95rem !important;
            font-weight: 600 !important;
        }
        div.bankroll-metrics [data-testid="stMetricDelta"] {
            font-size: 0.68rem !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def format_compact_twd(value: float, *, signed: bool = False) -> str:
    """緊湊台幣顯示（萬 / M）。"""
    v = float(value)
    prefix = "+" if signed and v > 0 else ("-" if signed and v < 0 else "")
    av = abs(v)
    if av >= 1_000_000:
        return f"{prefix}NT$ {av / 1_000_000:.2f}M"
    if av >= 10_000:
        return f"{prefix}NT$ {av / 10_000:.1f}萬"
    if av >= 1_000:
        return f"{prefix}NT$ {av:,.0f}"
    return f"{prefix}NT$ {av:.0f}"


def format_compact_pct(value: float, *, signed: bool = False) -> str:
    v = float(value) * 100
    if signed:
        return f"{v:+.1f}%"
    return f"{v:.1f}%"


def format_bet_selection(
    market: str,
    selection: str | None,
    *,
    home_team: str,
    away_team: str,
    handicap: float | None,
    sport: str,
) -> str:
    sel = str(selection or "")
    m = str(market or "")
    _, h_zh = team_bilingual(home_team, sport)
    _, a_zh = team_bilingual(away_team, sport)
    h = h_zh or home_team
    a = a_zh or away_team
    if m == "moneyline":
        if sel == "home":
            return f"主勝 · {h}"
        if sel == "away":
            return f"客勝 · {a}"
    if m == "total":
        line = f"{float(handicap):g}" if handicap is not None and pd.notna(handicap) else "—"
        if sel == "over":
            return f"大分 {line}"
        if sel == "under":
            return f"小分 {line}"
    if m == "spread":
        line = f"{float(handicap):+g}" if handicap is not None and pd.notna(handicap) else "—"
        if sel == "home":
            return f"主讓 {line} · {h}"
        if sel == "away":
            return f"客讓 {line} · {a}"
    return f"{m}/{sel}"


def format_matchup_label(home_team: str, away_team: str, sport: str) -> str:
    _, h_zh = team_bilingual(home_team, sport)
    _, a_zh = team_bilingual(away_team, sport)
    h = f"{home_team} / {h_zh}" if h_zh else home_team
    a = f"{away_team} / {a_zh}" if a_zh else away_team
    return f"{a} @ {h}"


def format_bankroll_trades(trades: pd.DataFrame, sport: str) -> pd.DataFrame:
    """將回測引擎輸出轉為可讀交易明細（台幣）。"""
    if trades.empty:
        return pd.DataFrame()

    out = trades.copy()
    out["序號"] = range(1, len(out) + 1)
    out["日期"] = out.get("match_date", out.get("date", "")).astype(str).str[:10]

    if "home_team" in out.columns and "away_team" in out.columns:
        out["對戰"] = out.apply(
            lambda r: format_matchup_label(str(r["home_team"]), str(r["away_team"]), sport),
            axis=1,
        )
    else:
        out["對戰"] = "—"

    if "market" in out.columns:
        out["盤口"] = out["market"].map(lambda m: _MARKET_ZH.get(str(m), str(m)))
        out["投注項目"] = out.apply(
            lambda r: format_bet_selection(
                str(r.get("market", "")),
                str(r.get("selection", "")) if pd.notna(r.get("selection")) else None,
                home_team=str(r.get("home_team", "")),
                away_team=str(r.get("away_team", "")),
                handicap=float(r["handicap"]) if pd.notna(r.get("handicap")) else None,
                sport=sport,
            ),
            axis=1,
        )
    else:
        out["盤口"] = "勝負"
        out["投注項目"] = "—"

    if "model_prob" in out.columns:
        out["模型勝率"] = (out["model_prob"].astype(float) * 100).round(1).astype(str) + "%"
    elif "prob" in out.columns:
        out["模型勝率"] = (out["prob"].astype(float) * 100).round(1).astype(str) + "%"
    else:
        out["模型勝率"] = "—"

    if "odds" in out.columns:
        out["賠率"] = out["odds"].astype(float).round(3)
    if "ev" in out.columns:
        out["EV"] = (out["ev"].astype(float) * 100).round(2).astype(str) + "%"
    if "stake_frac" in out.columns:
        out["倉位比例"] = (out["stake_frac"].astype(float) * 100).round(2).astype(str) + "%"
    if "stake" in out.columns:
        out["投注金額(台幣)"] = out["stake"].astype(float).map(lambda x: format_compact_twd(x))
    if "bankroll_before" in out.columns:
        out["投注前資金"] = out["bankroll_before"].astype(float).map(lambda x: format_compact_twd(x))
    if "bankroll" in out.columns:
        out["投注後資金"] = out["bankroll"].astype(float).map(lambda x: format_compact_twd(x))
    if "pnl" in out.columns:
        out["損益(台幣)"] = out["pnl"].astype(float).map(lambda x: format_compact_twd(x, signed=True))
    if "won" in out.columns:
        out["結果"] = out["won"].map({1: "✓ 贏", 0: "✗ 輸"})

    if "home_score" in out.columns and "away_score" in out.columns:
        out["實際比分"] = out.apply(
            lambda r: (
                f"{int(r['away_score'])}–{int(r['home_score'])}"
                if pd.notna(r.get("away_score")) and pd.notna(r.get("home_score"))
                else "—"
            ),
            axis=1,
        )

    cols = [
        c
        for c in [
            "序號", "日期", "對戰", "盤口", "投注項目", "模型勝率", "賠率", "EV",
            "倉位比例", "投注前資金", "投注金額(台幣)", "結果", "實際比分", "損益(台幣)", "投注後資金",
        ]
        if c in out.columns
    ]
    return out[cols]
