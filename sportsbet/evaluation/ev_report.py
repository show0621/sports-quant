"""投注期望值與回測專業報告：校準、ROI、邊際顯著性。"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from sportsbet import analytics, config


@dataclass
class EVBacktestReport:
    n_bets: int
    n_positive_ev: int
    avg_model_prob: float
    avg_implied_prob: float
    avg_ev: float
    avg_ev_taken: float
    actual_win_rate: float
    win_rate_taken: float
    roi: float
    roi_taken: float
    edge_over_breakeven: float
    brier_score: float
    profit_factor: float
    sharpe_like: float
    p_value_edge: float
    pass_ev_threshold: bool
    pass_calibration: bool
    pass_roi: bool
    by_odds_bucket: pd.DataFrame
    by_prob_bucket: pd.DataFrame
    summary_text: str


def _binomial_p_value(successes: int, n: int, p0: float) -> float:
    """H0: true win rate = p0，雙尾近似。"""
    if n <= 0:
        return 1.0
    obs = successes / n
    se = math.sqrt(p0 * (1 - p0) / n) if n else 1.0
    if se <= 0:
        return 1.0
    z = abs(obs - p0) / se
    return 2.0 * (1.0 - 0.5 * (1 + math.erf(z / math.sqrt(2))))


def build_ev_backtest_report(
    df: pd.DataFrame,
    *,
    prob_col: str = "model_prob",
    odds_col: str = "odds",
    won_col: str = "won",
    ev_col: str | None = "ev",
    min_ev: float | None = None,
) -> EVBacktestReport:
    """從回測 frame 產生專業 EV 報告。"""
    min_ev = min_ev if min_ev is not None else config.MIN_EV_THRESHOLD
    d = df.dropna(subset=[prob_col, odds_col, won_col]).copy()
    if d.empty:
        return EVBacktestReport(
            n_bets=0, n_positive_ev=0,
            avg_model_prob=0, avg_implied_prob=0, avg_ev=0, avg_ev_taken=0,
            actual_win_rate=0, win_rate_taken=0, roi=0, roi_taken=0,
            edge_over_breakeven=0, brier_score=float("nan"),
            profit_factor=0, sharpe_like=0, p_value_edge=1.0,
            pass_ev_threshold=False, pass_calibration=False, pass_roi=False,
            by_odds_bucket=pd.DataFrame(), by_prob_bucket=pd.DataFrame(),
            summary_text="資料不足",
        )

    if ev_col is None or ev_col not in d.columns:
        d["ev"] = d.apply(
            lambda r: analytics.expected_value(float(r[prob_col]), float(r[odds_col])),
            axis=1,
        )
        ev_col = "ev"

    d["implied_prob"] = d[odds_col].apply(analytics.breakeven_win_rate)
    d["won_int"] = d[won_col].astype(int)
    d["pnl_unit"] = d.apply(
        lambda r: (float(r[odds_col]) - 1) if r["won_int"] else -1.0,
        axis=1,
    )

    taken = d[d[ev_col] > min_ev].copy()
    n = len(d)
    n_taken = len(taken)

    avg_prob = float(d[prob_col].mean())
    avg_impl = float(d["implied_prob"].mean())
    avg_ev = float(d[ev_col].mean())
    avg_ev_taken = float(taken[ev_col].mean()) if n_taken else 0.0
    actual_wr = float(d["won_int"].mean())
    wr_taken = float(taken["won_int"].mean()) if n_taken else 0.0
    roi = float(d["pnl_unit"].sum() / n) if n else 0.0
    roi_taken = float(taken["pnl_unit"].sum() / n_taken) if n_taken else 0.0

    y_true = d["won_int"].values
    y_prob = d[prob_col].astype(float).values
    brier = float(np.mean((y_prob - y_true) ** 2))

    gross_win = taken.loc[taken["pnl_unit"] > 0, "pnl_unit"].sum() if n_taken else 0
    gross_loss = abs(taken.loc[taken["pnl_unit"] < 0, "pnl_unit"].sum()) if n_taken else 0
    profit_factor = float(gross_win / gross_loss) if gross_loss > 0 else float("inf")

    pnl_std = taken["pnl_unit"].std() if n_taken > 1 else 1.0
    sharpe = float(taken["pnl_unit"].mean() / pnl_std) if pnl_std and n_taken else 0.0

    be_avg = avg_impl
    edge = wr_taken - be_avg if n_taken else actual_wr - be_avg
    p_val = _binomial_p_value(
        int(taken["won_int"].sum()) if n_taken else int(d["won_int"].sum()),
        n_taken or n,
        be_avg,
    )

    d["odds_bucket"] = pd.cut(d[odds_col], bins=[1.0, 1.6, 1.8, 2.0, 2.5, 10], labels=["≤1.6", "1.6-1.8", "1.8-2.0", "2.0-2.5", ">2.5"])
    by_odds = (
        d.groupby("odds_bucket", observed=True)
        .agg(
            count=("won_int", "count"),
            win_rate=("won_int", "mean"),
            avg_prob=(prob_col, "mean"),
            avg_ev=(ev_col, "mean"),
            roi=("pnl_unit", "mean"),
        )
        .reset_index()
    )

    d["prob_bucket"] = pd.cut(d[prob_col], bins=[0, 0.45, 0.5, 0.55, 0.6, 1.0], labels=["<45%", "45-50%", "50-55%", "55-60%", ">60%"])
    by_prob = (
        d.groupby("prob_bucket", observed=True)
        .agg(
            count=("won_int", "count"),
            win_rate=("won_int", "mean"),
            predicted=(prob_col, "mean"),
            avg_ev=(ev_col, "mean"),
        )
        .reset_index()
    )

    cal_gap = abs(avg_prob - actual_wr)
    pass_cal = cal_gap < 0.08 and n >= 30
    pass_ev = avg_ev_taken > min_ev and n_taken >= 10
    pass_roi = roi_taken > 0 and n_taken >= 20

    summary = (
        f"樣本 {n} 筆，正 EV 下注 {n_taken} 筆。"
        f" 實際勝率 {actual_wr:.1%} vs 模型 {avg_prob:.1%}（Brier {brier:.4f}）。"
        f" 正 EV 子集 ROI {roi_taken:+.2%}、平均 EV {avg_ev_taken:+.2%}。"
        f" 邊際 p-value={p_val:.3f}。"
    )

    return EVBacktestReport(
        n_bets=n,
        n_positive_ev=n_taken,
        avg_model_prob=avg_prob,
        avg_implied_prob=avg_impl,
        avg_ev=avg_ev,
        avg_ev_taken=avg_ev_taken,
        actual_win_rate=actual_wr,
        win_rate_taken=wr_taken,
        roi=roi,
        roi_taken=roi_taken,
        edge_over_breakeven=edge,
        brier_score=brier,
        profit_factor=profit_factor,
        sharpe_like=sharpe,
        p_value_edge=p_val,
        pass_ev_threshold=pass_ev,
        pass_calibration=pass_cal,
        pass_roi=pass_roi,
        by_odds_bucket=by_odds,
        by_prob_bucket=by_prob,
        summary_text=summary,
    )
