"""預測驗證：Brier Score、校準度、資金曲線回測。"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from sportsbet import config
from sportsbet.backtest.engine import BacktestEngine
from sportsbet.backtest.metrics import accuracy_report, brier_score, calibration_bins
from sportsbet.evaluation.calibration import calibration_curve_df


@dataclass
class EvaluationReport:
    brier_score: float
    accuracy: dict
    calibration: pd.DataFrame
    calibration_curve: pd.DataFrame
    backtest_summary: dict
    equity_curve: pd.Series
    trades: pd.DataFrame


class EvaluationModule:
    """模型健康度與資金回測評估。"""

    def __init__(
        self,
        initial_bankroll: float | None = None,
        kelly_fraction: float | None = None,
        min_ev: float | None = None,
    ):
        self.backtest = BacktestEngine(initial_bankroll, kelly_fraction, min_ev)

    def brier(self, y_true: np.ndarray, y_prob: np.ndarray) -> float:
        return brier_score(y_true, y_prob)

    def calibration_bins(
        self,
        df: pd.DataFrame,
        prob_col: str = "model_prob",
        outcome_col: str = "won",
        n_bins: int = 10,
    ) -> pd.DataFrame:
        return calibration_bins(df, prob_col, outcome_col, n_bins)

    def run_full_evaluation(
        self,
        df: pd.DataFrame,
        *,
        prob_col: str = "model_prob",
        outcome_col: str = "won",
        odds_col: str = "odds",
        date_col: str = "match_date",
        ev_col: str | None = "ev",
    ) -> EvaluationReport:
        d = df.dropna(subset=[prob_col, outcome_col, odds_col]).copy()
        if d.empty:
            empty_eq = pd.Series([config.INITIAL_BANKROLL])
            return EvaluationReport(
                brier_score=float("nan"),
                accuracy={"error": "資料不足"},
                calibration=pd.DataFrame(),
                calibration_curve=pd.DataFrame(),
                backtest_summary={"error": "資料不足"},
                equity_curve=empty_eq,
                trades=pd.DataFrame(),
            )

        y_true = d[outcome_col].astype(int).values
        y_prob = np.clip(d[prob_col].astype(float).values, 0.0, 1.0)
        bs = self.brier(y_true, y_prob)
        acc = accuracy_report(d, prob_col, outcome_col)
        cal = self.calibration_bins(d, prob_col, outcome_col, n_bins=10)
        curve = calibration_curve_df(d, prob_col, outcome_col)

        bt = self.backtest.run(
            d,
            date_col=date_col if date_col in d.columns else "match_date",
            prob_col=prob_col,
            odds_col=odds_col,
            won_col=outcome_col,
            ev_col=ev_col,
        )

        return EvaluationReport(
            brier_score=bs,
            accuracy=acc,
            calibration=cal,
            calibration_curve=curve,
            backtest_summary=bt.summary,
            equity_curve=bt.equity_curve,
            trades=bt.trades,
        )
