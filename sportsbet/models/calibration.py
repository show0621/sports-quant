"""機率校準：修正大小分過度自信、勝率極端值。"""
from __future__ import annotations

from typing import Literal

import pandas as pd
from scipy.stats import norm

from sportsbet import config

Sport = Literal["nba", "mlb"]


def shrink_prob(prob: float, factor: float) -> float:
    """線性收縮 toward 0.5，factor∈(0,1] 越小越保守。"""
    p = max(0.001, min(0.999, float(prob)))
    f = max(0.0, min(1.0, float(factor)))
    return 0.5 + (p - 0.5) * f


def market_implied_over_prob(odds_df: pd.DataFrame) -> float | None:
    """由大小盤 over/under 賠率去水後估算大分機率。"""
    if odds_df is None or odds_df.empty:
        return None
    d = odds_df[odds_df["market"] == "total"]
    if d.empty:
        return None
    over = d[d["selection"] == "over"]["odds"]
    under = d[d["selection"] == "under"]["odds"]
    if over.empty or under.empty:
        return None
    o_odds = float(over.iloc[0])
    u_odds = float(under.iloc[0])
    if o_odds <= 1.0 or u_odds <= 1.0:
        return None
    inv_o, inv_u = 1.0 / o_odds, 1.0 / u_odds
    return inv_o / (inv_o + inv_u)


def calibrate_total_prob(
    line: float,
    pred_total: float,
    sport: Sport,
    *,
    poisson_prob: float | None = None,
    mc_prob: float | None = None,
    market_implied: float | None = None,
) -> float:
    """
    大小分機率校準：
    - 預測總分向盤口線收斂（市場更有效）
    - 以歷史誤差 σ 做常態 CDF，取代 Poisson 的過窄分布
    - 可混入 MC / 盤口隱含機率，最後線性收縮
    """
    sigma = config.TOTAL_EDGE_SIGMA.get(sport, 12.0)
    line_blend = config.TOTAL_LINE_BLEND.get(sport, 0.55)
    pred_eff = (1.0 - line_blend) * float(pred_total) + line_blend * float(line)
    edge = pred_eff - float(line)
    normal_p = float(norm.cdf(edge / max(sigma, 0.5)))

    parts: list[tuple[float, float]] = [(normal_p, 0.55)]
    if poisson_prob is not None:
        parts.append((float(poisson_prob), 0.20))
    if mc_prob is not None:
        parts.append((float(mc_prob), 0.25))

    wsum = sum(w for _, w in parts)
    p = sum(v * w for v, w in parts) / wsum

    mkt_blend = config.TOTAL_MARKET_BLEND
    if market_implied is not None:
        mi = max(0.05, min(0.95, float(market_implied)))
        p = (1.0 - mkt_blend) * p + mkt_blend * mi

    shrink = config.TOTAL_PROB_SHRINK.get(sport, 0.45)
    return max(0.05, min(0.95, shrink_prob(p, shrink)))


def calibrate_win_prob(prob: float, sport: Sport) -> float:
    """勝負機率收縮，降低集成模型在極端區間的過度自信。"""
    shrink = config.ML_PROB_SHRINK.get(sport, 0.80)
    return max(0.05, min(0.95, shrink_prob(prob, shrink)))
