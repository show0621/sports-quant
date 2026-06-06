"""
回測引擎：歷史賠率 + 模型機率 → 資金曲線、ROI。

支援：
- 單場投注（min_parlay == 1）
- 強制串關（EV 相乘，僅在可組合時下注）
- 四分之一凱利資金控管
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from sportsbet import analytics, config
from sportsbet.backtest.metrics import accuracy_report

logger = logging.getLogger(__name__)


def prepare_bet_signals(
    df: pd.DataFrame,
    *,
    prob_col: str = "model_prob",
    odds_col: str = "odds",
    ev_col: str = "ev",
    date_col: str = "match_date",
    min_ev: float = 0.0,
    kelly_fraction: float | None = None,
    one_bet_per_game: bool = True,
) -> pd.DataFrame:
    """
    篩選可下注列：EV > 0、Kelly 倉位 > 0，每場僅保留 EV 最高的一個玩法。
    """
    if df.empty:
        return df

    d = df.copy()
    if ev_col not in d.columns:
        d[ev_col] = d.apply(
            lambda r: analytics.expected_value(float(r[prob_col]), float(r[odds_col])),
            axis=1,
        )

    d[ev_col] = d[ev_col].astype(float)
    d = d[d[ev_col] > max(0.0, min_ev)]

    if "game_id" in d.columns and "market" in d.columns and "selection" in d.columns:
        d = d.drop_duplicates(subset=["game_id", "market", "selection"], keep="first")

    k_frac = kelly_fraction if kelly_fraction is not None else config.KELLY_FRACTION
    d["_kelly_stake"] = d.apply(
        lambda r: analytics.adjusted_kelly(float(r[prob_col]), float(r[odds_col]), k_frac),
        axis=1,
    )
    d = d[d["_kelly_stake"] > 0]
    if d.empty:
        return d.iloc[0:0]

    if one_bet_per_game:
        if "game_id" in d.columns:
            d = d.loc[d.groupby("game_id", sort=False)[ev_col].idxmax()]
        else:
            grp = ["match_date", "home_team", "away_team"]
            grp = [c for c in grp if c in d.columns]
            if grp:
                d = d.loc[d.groupby(grp, sort=False)[ev_col].idxmax()]

    sort_cols = [c for c in (date_col, "game_id") if c in d.columns]
    if sort_cols:
        d = d.sort_values(sort_cols)
    return d.drop(columns=["_kelly_stake"], errors="ignore")


@dataclass
class BacktestResult:
    equity_curve: pd.Series
    trades: pd.DataFrame
    summary: dict
    accuracy: dict = field(default_factory=dict)


class BacktestEngine:
    def __init__(
        self,
        initial_bankroll: float | None = None,
        kelly_fraction: float | None = None,
        min_ev: float | None = None,
    ):
        self.bankroll0 = initial_bankroll or config.INITIAL_BANKROLL
        self.kelly_fraction = kelly_fraction or config.KELLY_FRACTION
        self.min_ev = min_ev if min_ev is not None else config.MIN_EV_THRESHOLD

    def run(
        self,
        signals_df: pd.DataFrame,
        *,
        date_col: str = "match_date",
        prob_col: str = "model_prob",
        odds_col: str = "odds",
        won_col: str = "won",
        parlay_col: str = "min_parlay",
        ev_col: str | None = "ev",
    ) -> BacktestResult:
        """
        signals_df 每列為一筆可下注選項，需含：
        - model_prob, odds, won (事後結果 0/1)
        - min_parlay: 1 單場 / 2+ 需串關（同場次分組由呼叫端處理）
        """
        df = signals_df.copy()
        if df.empty:
            return BacktestResult(
                equity_curve=pd.Series([self.bankroll0]),
                trades=pd.DataFrame(),
                summary={"error": "無資料"},
            )

        if ev_col is None or ev_col not in df.columns:
            df["ev"] = df.apply(
                lambda r: analytics.expected_value(float(r[prob_col]), float(r[odds_col])),
                axis=1,
            )
            ev_col = "ev"

        singles = df[df.get(parlay_col, 1) == 1] if parlay_col in df.columns else df
        singles = prepare_bet_signals(
            singles,
            prob_col=prob_col,
            odds_col=odds_col,
            ev_col=ev_col,
            date_col=date_col,
            min_ev=self.min_ev,
            kelly_fraction=self.kelly_fraction,
            one_bet_per_game=True,
        )

        bankroll = self.bankroll0
        equity = [bankroll]
        trade_rows = []
        trade_no = 0

        pass_cols = [
            c for c in (
                "game_id", "match_date", "home_team", "away_team",
                "home_score", "away_score", "market", "selection",
                "handicap", "model_prob", "ev", "stake_fraction",
            )
            if c in singles.columns
        ]

        for idx, row in singles.iterrows():
            prob = float(row[prob_col])
            odds = float(row[odds_col])
            ev = float(row[ev_col])
            won = int(row.get(won_col, 0))

            stake_frac = analytics.adjusted_kelly(prob, odds, self.kelly_fraction)
            stake = bankroll * stake_frac
            if stake <= 0:
                continue

            bankroll_before = bankroll
            pnl = stake * (odds - 1) if won else -stake
            bankroll += pnl
            equity.append(bankroll)
            trade_no += 1
            trade_row: dict = {
                "trade_no": trade_no,
                "idx": idx,
                "date": row.get(date_col),
                "prob": prob,
                "odds": odds,
                "ev": ev,
                "stake_frac": stake_frac,
                "stake": stake,
                "won": won,
                "pnl": pnl,
                "bankroll_before": bankroll_before,
                "bankroll": bankroll,
                "type": "single",
            }
            for col in pass_cols:
                trade_row[col] = row.get(col)
            trade_rows.append(trade_row)

        trades = pd.DataFrame(trade_rows)
        summary = self._summarize(trades, equity)

        acc = {}
        if won_col in df.columns:
            acc = accuracy_report(df, prob_col, won_col)

        return BacktestResult(
            equity_curve=pd.Series(equity),
            trades=trades,
            summary=summary,
            accuracy=acc,
        )

    def run_parlay_groups(
        self,
        df: pd.DataFrame,
        group_cols: list[str],
        prob_col: str = "model_prob",
        odds_col: str = "parlay_odds",
        won_col: str = "parlay_won",
    ) -> BacktestResult:
        """串關回測：每組為一張 parlay ticket。"""
        bankroll = self.bankroll0
        equity = [bankroll]
        trade_rows = []

        for _, grp in df.groupby(group_cols):
            probs = grp[prob_col].astype(float).tolist()
            odds = float(grp[odds_col].iloc[0])
            ev = analytics.parlay_ev(probs, odds)
            won = int(grp[won_col].iloc[0]) if won_col in grp.columns else 0

            if ev <= self.min_ev:
                equity.append(bankroll)
                continue

            combined = float(np.prod(probs))
            stake_frac = analytics.adjusted_kelly(combined, odds, self.kelly_fraction)
            stake = bankroll * stake_frac
            pnl = stake * (odds - 1) if won else -stake
            bankroll += pnl
            equity.append(bankroll)
            trade_rows.append({"ev": ev, "stake": stake, "won": won, "pnl": pnl, "bankroll": bankroll, "type": "parlay"})

        trades = pd.DataFrame(trade_rows)
        return BacktestResult(
            equity_curve=pd.Series(equity),
            trades=trades,
            summary=self._summarize(trades, equity),
        )

    @staticmethod
    def _summarize(trades: pd.DataFrame, equity: list[float]) -> dict:
        if trades.empty:
            return {
                "total_trades": 0,
                "final_bankroll": equity[-1] if equity else 0,
                "roi": 0.0,
                "win_rate": 0.0,
                "max_drawdown": 0.0,
            }
        start = equity[0]
        end = equity[-1]
        wins = trades["won"].sum() if "won" in trades.columns else 0
        eq = np.array(equity)
        peak = np.maximum.accumulate(eq)
        dd = (eq - peak) / np.where(peak > 0, peak, 1)
        return {
            "total_trades": len(trades),
            "final_bankroll": float(end),
            "roi": float((end - start) / start) if start else 0.0,
            "win_rate": float(wins / len(trades)),
            "total_pnl": float(trades["pnl"].sum()) if "pnl" in trades.columns else 0.0,
            "max_drawdown": float(dd.min()),
            "avg_ev": float(trades["ev"].mean()) if "ev" in trades.columns else 0.0,
        }
