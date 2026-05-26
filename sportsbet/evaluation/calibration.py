"""校準度曲線資料準備。"""
from __future__ import annotations

import pandas as pd


def calibration_curve_df(
    df: pd.DataFrame,
    prob_col: str = "model_prob",
    outcome_col: str = "won",
    n_bins: int = 10,
) -> pd.DataFrame:
    """
    將預測機率分箱（如 50–60%、60–70%），比對各組實際勝率。
    """
    d = df[[prob_col, outcome_col]].dropna().copy()
    if d.empty:
        return pd.DataFrame(columns=["bin_label", "bin_mid", "predicted", "actual", "count"])

    d["bin"] = pd.cut(d[prob_col], bins=n_bins, labels=False)
    grouped = (
        d.groupby("bin", observed=True)
        .agg(
            predicted=(prob_col, "mean"),
            actual=(outcome_col, "mean"),
            count=(outcome_col, "count"),
            bin_low=(prob_col, "min"),
            bin_high=(prob_col, "max"),
        )
        .reset_index()
    )
    grouped["bin_mid"] = (grouped["bin_low"] + grouped["bin_high"]) / 2
    grouped["bin_label"] = grouped.apply(
        lambda r: f"{r['bin_low']:.0%}–{r['bin_high']:.0%}", axis=1
    )
    return grouped
