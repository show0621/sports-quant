"""期望值與資金控管：EV、凱利公式、四分之一凱利。"""
from __future__ import annotations

from dataclasses import dataclass

from sportsbet import analytics, config


@dataclass
class RiskSignal:
    win_prob: float
    odds: float
    ev: float
    kelly_fraction: float
    recommended_stake_fraction: float
    is_positive_ev: bool


class RiskManager:
    """期望值與凱利資金控管。"""

    def __init__(
        self,
        *,
        kelly_multiplier: float | None = None,
        max_bet_fraction: float | None = None,
        min_ev: float | None = None,
    ):
        self.kelly_multiplier = kelly_multiplier if kelly_multiplier is not None else config.KELLY_FRACTION
        self.max_bet_fraction = max_bet_fraction if max_bet_fraction is not None else config.MAX_BET_FRACTION
        self.min_ev = min_ev if min_ev is not None else config.MIN_EV_THRESHOLD

    def expected_value(self, win_prob: float, odds: float) -> float:
        return analytics.expected_value(win_prob, odds)

    def kelly(self, win_prob: float, odds: float) -> float:
        return analytics.kelly_fraction(win_prob, odds)

    def quarter_kelly(self, win_prob: float, odds: float) -> float:
        """四分之一凱利建議倉位。"""
        return analytics.adjusted_kelly(
            win_prob, odds,
            kelly_fraction_multiplier=self.kelly_multiplier,
            max_bet=self.max_bet_fraction,
        )

    def evaluate(self, win_prob: float, odds: float) -> RiskSignal:
        sig = analytics.evaluate_bet(win_prob, odds, self.min_ev)
        return RiskSignal(
            win_prob=sig.win_prob,
            odds=sig.odds,
            ev=sig.ev,
            kelly_fraction=sig.kelly_fraction,
            recommended_stake_fraction=sig.recommended_stake_fraction,
            is_positive_ev=sig.is_positive_ev,
        )
