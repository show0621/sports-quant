"""
量化模型核心：畢達哥拉斯期望值、貝氏修正、期望值與凱利公式。

輸入：球隊得分/失分、近況、威剛賠率
輸出：勝率、EV、建議下注比例
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from sportsbet import config


@dataclass
class BetSignal:
    """單筆投注訊號。"""

    win_prob: float
    odds: float  # 含本金，如 1.75
    ev: float
    kelly_fraction: float
    recommended_stake_fraction: float
    is_positive_ev: bool
    breakeven_prob: float


@dataclass
class ParlaySignal:
    """串關投注訊號。"""

    combined_prob: float
    parlay_odds: float
    ev: float
    kelly_fraction: float
    recommended_stake_fraction: float
    is_positive_ev: bool
    leg_probs: tuple[float, ...]


# ---------------------------------------------------------------------------
# 1. 畢達哥拉斯定理 (Pythagorean Expectation)
# ---------------------------------------------------------------------------


def pythagorean_win_pct(
    runs_scored: float,
    runs_allowed: float,
    exponent: float,
) -> float:
    """
    Win% = RS^x / (RS^x + RA^x)

    runs_scored / runs_allowed 可為賽季累計或 per-game 平均。
    """
    if runs_scored <= 0 or runs_allowed <= 0:
        return 0.5
    rs_x = runs_scored**exponent
    ra_x = runs_allowed**exponent
    return rs_x / (rs_x + ra_x)


def mlb_dynamic_exponent(runs_scored: float, runs_allowed: float, games: int) -> float:
    """MLB 動態指數：1.5 * log10((RS+RA)/G) + 0.45"""
    if games <= 0:
        return config.PYTH_EXPONENT_MLB
    total = runs_scored + runs_allowed
    if total <= 0:
        return config.PYTH_EXPONENT_MLB
    return 1.5 * math.log10(total / games) + 0.45


def team_win_pct(
    sport: Literal["nba", "mlb"],
    runs_scored: float,
    runs_allowed: float,
    games: int = 0,
) -> float:
    """依運動類型計算畢達哥拉斯預期勝率。"""
    if sport == "nba":
        exp = config.PYTH_EXPONENT_NBA
    else:
        exp = (
            mlb_dynamic_exponent(runs_scored, runs_allowed, games)
            if config.USE_DYNAMIC_MLB_EXPONENT and games > 0
            else config.PYTH_EXPONENT_MLB
        )
    return pythagorean_win_pct(runs_scored, runs_allowed, exp)


def matchup_win_prob(home_pct: float, away_pct: float, home_advantage: float | None = None) -> tuple[float, float]:
    """
    兩隊畢達哥拉斯勝率轉為單場勝率（Log5 法）。

    P(home wins) = (home - home*away) / (home + away - 2*home*away)
    """
    h = home_pct + (home_advantage or config.BAYES_HOME_ADVANTAGE)
    a = away_pct
    h = min(max(h, 0.01), 0.99)
    a = min(max(a, 0.01), 0.99)
    denom = h + a - 2 * h * a
    if denom <= 0:
        return 0.5, 0.5
    p_home = (h - h * a) / denom
    p_home = min(max(p_home, 0.01), 0.99)
    return p_home, 1.0 - p_home


# ---------------------------------------------------------------------------
# 2. 貝氏定理動態修正
# ---------------------------------------------------------------------------


def bayesian_update(
    prior: float,
    likelihood_ratio: float,
) -> float:
    """
    簡化貝氏更新：以似然比調整先驗。

    posterior_odds = prior_odds * LR
    其中 prior_odds = prior / (1-prior)
    """
    prior = min(max(prior, 0.001), 0.999)
    prior_odds = prior / (1.0 - prior)
    posterior_odds = prior_odds * likelihood_ratio
    posterior = posterior_odds / (1.0 + posterior_odds)
    return min(max(posterior, 0.001), 0.999)


def recent_form_likelihood(recent_win_pct: float, season_win_pct: float) -> float:
    """
    近況 vs 賽季平均 → 似然比。
    近 5 場勝率明顯高於賽季 → LR > 1。
    """
    if season_win_pct <= 0:
        return 1.0
    return max(0.5, min(2.0, recent_win_pct / season_win_pct))


def apply_bayesian_adjustments(
    prior_win_prob: float,
    *,
    is_home: bool = False,
    recent_win_pct: float | None = None,
    season_win_pct: float | None = None,
    key_player_out: bool = False,
    custom_likelihood: float = 1.0,
    recent_weight: float | None = None,
) -> float:
    """
    將畢達哥拉斯先驗更新為後驗勝率。

    - 主場：似然比略 > 1（已含在 matchup 時可關閉）
    - 近況：recent_form_likelihood
    - 傷兵：LR *= (1 - injury_penalty)
    """
    lr = custom_likelihood

    if is_home:
        lr *= 1.0 + config.BAYES_HOME_ADVANTAGE

    if recent_win_pct is not None and season_win_pct is not None:
        form_lr = recent_form_likelihood(recent_win_pct, season_win_pct)
        w = recent_weight if recent_weight is not None else config.BAYES_RECENT_WEIGHT
        lr *= (1.0 - w) + w * form_lr

    if key_player_out:
        lr *= 1.0 - config.BAYES_INJURY_PENALTY

    return bayesian_update(prior_win_prob, lr)


# ---------------------------------------------------------------------------
# 3. 期望值 (EV) 與凱利公式 (Kelly)
# ---------------------------------------------------------------------------


def breakeven_win_rate(odds: float) -> float:
    """含本金賠率下的盈虧平衡勝率。"""
    if odds <= 1.0:
        return 1.0
    return 1.0 / odds


def expected_value(win_prob: float, odds: float) -> float:
    """
    EV = P * O - 1

    odds 為含本金賠率（台灣運彩常見 1.75）。
    """
    return win_prob * odds - 1.0


def kelly_fraction(win_prob: float, odds: float) -> float:
    """
    f* = (P*O - 1) / (O - 1) = EV / (O - 1)

    賠率 <= 1 時回傳 0。
    """
    if odds <= 1.0:
        return 0.0
    ev = expected_value(win_prob, odds)
    if ev <= 0:
        return 0.0
    return ev / (odds - 1.0)


def adjusted_kelly(
    win_prob: float,
    odds: float,
    kelly_fraction_multiplier: float | None = None,
    max_bet: float | None = None,
) -> float:
    """半凱利 / 四分之一凱利 + 單注上限。"""
    raw = kelly_fraction(win_prob, odds)
    mult = kelly_fraction_multiplier if kelly_fraction_multiplier is not None else config.KELLY_FRACTION
    cap = max_bet if max_bet is not None else config.MAX_BET_FRACTION
    return min(raw * mult, cap)


def evaluate_bet(
    win_prob: float,
    odds: float,
    min_ev: float | None = None,
) -> BetSignal:
    """完整評估單注訊號。"""
    threshold = min_ev if min_ev is not None else config.MIN_EV_THRESHOLD
    ev = expected_value(win_prob, odds)
    kelly = kelly_fraction(win_prob, odds)
    stake = adjusted_kelly(win_prob, odds)
    return BetSignal(
        win_prob=win_prob,
        odds=odds,
        ev=ev,
        kelly_fraction=kelly,
        recommended_stake_fraction=stake,
        is_positive_ev=ev > threshold,
        breakeven_prob=breakeven_win_rate(odds),
    )


def parlay_ev(probs: list[float], parlay_odds: float) -> float:
    """
    串關 EV = P1 * P2 * ... * On - 1

    威剛強制 2/3 關時使用。
    """
    if not probs or parlay_odds <= 1.0:
        return -1.0
    combined = 1.0
    for p in probs:
        combined *= p
    return combined * parlay_odds - 1.0


def evaluate_parlay(probs: list[float], parlay_odds: float, min_ev: float | None = None) -> ParlaySignal:
    """評估串關訊號。"""
    threshold = min_ev if min_ev is not None else config.MIN_EV_THRESHOLD
    combined = 1.0
    for p in probs:
        combined *= p
    ev = parlay_ev(probs, parlay_odds)
    # 串關凱利：將組合視為單一事件
    kelly = kelly_fraction(combined, parlay_odds) if parlay_odds > 1 else 0.0
    stake = adjusted_kelly(combined, parlay_odds)
    return ParlaySignal(
        combined_prob=combined,
        parlay_odds=parlay_odds,
        ev=ev,
        kelly_fraction=kelly,
        recommended_stake_fraction=stake,
        is_positive_ev=ev > threshold,
        leg_probs=tuple(probs),
    )


def implied_vig(odds_a: float, odds_b: float) -> float:
    """
    從雙邊賠率估算抽水（overround）。

    vig = (1/Oa + 1/Ob) - 1；返還率 ≈ 1 - vig（簡化）。
    """
    return (1.0 / odds_a + 1.0 / odds_b) - 1.0


def taiwan_break_even_note(odds: float = 1.75) -> dict[str, float]:
    """台灣運彩高抽水下的盈虧平衡說明。"""
    be = breakeven_win_rate(odds)
    return {
        "odds": odds,
        "breakeven_win_rate": be,
        "breakeven_pct": be * 100,
        "config_return_rate": config.TAIWAN_VIG_RETURN_RATE,
        "min_edge_over_break_even": be - (1.0 - config.TAIWAN_VIG_RETURN_RATE) / 2,
    }
