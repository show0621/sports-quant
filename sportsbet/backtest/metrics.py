"""預測準確率與校準指標。"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import brier_score_loss, confusion_matrix


def brier_score(y_true: np.ndarray, y_prob: np.ndarray) -> float:
    """Brier Score，越低越好（完美校準 = 0）。"""
    return float(brier_score_loss(y_true, y_prob))


def accuracy_report(df: pd.DataFrame, prob_col: str = "model_prob", outcome_col: str = "won") -> dict:
    """
    產生準確率報告。

    df 需含 model_prob（預測勝率）與 won（0/1 實際結果）。
    """
    if df.empty or outcome_col not in df.columns:
        return {"error": "資料不足"}

    y_true = df[outcome_col].astype(int).values
    y_prob = df[prob_col].astype(float).values
    y_pred = (y_prob >= 0.5).astype(int)

    cm = confusion_matrix(y_true, y_pred, labels=[0, 1])
    tn, fp, fn, tp = cm.ravel() if cm.size == 4 else (0, 0, 0, 0)

    return {
        "n_games": len(df),
        "accuracy": float((y_pred == y_true).mean()),
        "brier_score": brier_score(y_true, y_prob),
        "avg_predicted_prob": float(y_prob.mean()),
        "actual_win_rate": float(y_true.mean()),
        "confusion_matrix": {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)},
    }


def calibration_bins(df: pd.DataFrame, prob_col: str = "model_prob", outcome_col: str = "won", n_bins: int = 10) -> pd.DataFrame:
    """分箱校準：預測機率 vs 實際勝率。"""
    d = df[[prob_col, outcome_col]].dropna().copy()
    d["bin"] = pd.cut(d[prob_col], bins=n_bins, labels=False)
    return (
        d.groupby("bin", observed=True)
        .agg(
            predicted=(prob_col, "mean"),
            actual=(outcome_col, "mean"),
            count=(outcome_col, "count"),
        )
        .reset_index()
    )
