"""依玩法（moneyline / spread / total / margin）分開統計回測。"""
from __future__ import annotations

import pandas as pd

from sportsbet import analytics, config
from sportsbet.backtest.metrics import brier_score
from sportsbet.evaluation.ev_report import build_ev_backtest_report


MARKET_LABELS = {
    "moneyline": "不讓分（勝負）",
    "spread": "讓分",
    "total": "大小分",
    "margin": "勝分差",
}


def build_market_backtest_table(df: pd.DataFrame) -> pd.DataFrame:
    """各玩法勝率、Brier、ROI、正 EV 筆數。"""
    if df.empty or "market" not in df.columns:
        return pd.DataFrame()

    rows = []
    for market, label in MARKET_LABELS.items():
        sub = df[df["market"] == market].dropna(subset=["model_prob", "won", "odds"])
        if sub.empty:
            rows.append(
                {
                    "玩法": label,
                    "market": market,
                    "筆數": 0,
                    "準確率": None,
                    "Brier": None,
                    "平均EV": None,
                    "正EV筆數": 0,
                    "正EV勝率": None,
                    "ROI(正EV)": None,
                }
            )
            continue

        y_true = sub["won"].astype(int).values
        y_prob = sub["model_prob"].astype(float).clip(0, 1).values
        y_pred = (y_prob >= 0.5).astype(int)
        acc = float((y_pred == y_true).mean())

        if "ev" not in sub.columns:
            sub = sub.copy()
            sub["ev"] = sub.apply(
                lambda r: analytics.expected_value(float(r["model_prob"]), float(r["odds"])),
                axis=1,
            )
        pos = sub[sub["ev"] >= config.MIN_EV_THRESHOLD]
        rep = build_ev_backtest_report(sub, min_ev=config.MIN_EV_THRESHOLD)

        rows.append(
            {
                "玩法": label,
                "market": market,
                "筆數": len(sub),
                "準確率": acc,
                "Brier": brier_score(y_true, y_prob),
                "平均EV": float(sub["ev"].mean()),
                "正EV筆數": len(pos),
                "正EV勝率": rep.win_rate_taken if len(pos) else None,
                "ROI(正EV)": rep.roi_taken if len(pos) else None,
            }
        )

    out = pd.DataFrame(rows)
    return out.sort_values("筆數", ascending=False)


def format_market_backtest_markdown(table: pd.DataFrame) -> str:
    if table.empty:
        return "尚無分玩法回測資料。"
    lines = ["| 玩法 | 筆數 | 準確率 | Brier | 平均EV | 正EV筆數 | 正EV ROI |", "|---|---:|---:|---:|---:|---:|---:|"]
    for _, r in table.iterrows():
        acc = f"{r['準確率']:.1%}" if pd.notna(r["準確率"]) else "—"
        bs = f"{r['Brier']:.4f}" if pd.notna(r["Brier"]) else "—"
        ev = f"{r['平均EV']:+.2%}" if pd.notna(r["平均EV"]) else "—"
        roi = f"{r['ROI(正EV)']:+.2%}" if pd.notna(r["ROI(正EV)"]) else "—"
        lines.append(
            f"| {r['玩法']} | {int(r['筆數'])} | {acc} | {bs} | {ev} | {int(r['正EV筆數'])} | {roi} |"
        )
    return "\n".join(lines)
