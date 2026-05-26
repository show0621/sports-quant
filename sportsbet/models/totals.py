"""大小分預測：卜瓦松分配計算總分超越盤口機率。"""
from __future__ import annotations

import numpy as np
from scipy.stats import poisson


def expected_lambdas(
    home_rs: float,
    home_ra: float,
    away_rs: float,
    away_ra: float,
    *,
    home_advantage_pts: float = 1.5,
) -> tuple[float, float]:
    """
    由進攻/防守效率估算兩隊得分率 λ。

    λ_home ≈ (主隊得分 + 客隊失分) / 2 + 主場加成
    λ_away ≈ (客隊得分 + 主隊失分) / 2
    """
    lam_home = (home_rs + away_ra) / 2.0 + home_advantage_pts / 2.0
    lam_away = (away_rs + home_ra) / 2.0
    return max(lam_home, 0.1), max(lam_away, 0.1)


def prob_total_over(
    line: float,
    lambda_home: float,
    lambda_away: float,
    *,
    max_points: int = 350,
) -> float:
    """
    P(主隊得分 + 客隊得分 > line)

    假設兩隊得分獨立 Poisson，以卷積求總分分布。
    """
    lam_home = max(lambda_home, 0.1)
    lam_away = max(lambda_away, 0.1)
    k_max = min(max_points, int(line) + 80)
    pmf_h = poisson.pmf(np.arange(k_max), lam_home)
    pmf_a = poisson.pmf(np.arange(k_max), lam_away)
    pmf_total = np.convolve(pmf_h, pmf_a)
    threshold = int(np.floor(line))
    if threshold >= len(pmf_total):
        return 0.0
    return float(1.0 - pmf_total[: threshold + 1].sum())


def prob_total_under(line: float, lambda_home: float, lambda_away: float, **kwargs) -> float:
    """P(總分 < line)。"""
    return 1.0 - prob_total_over(line - 0.001, lambda_home, lambda_away, **kwargs)
