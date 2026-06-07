"""
荷蘭式（Dutching）與對沖注碼精算。

台灣運彩單注含本金賠率 O：淨利 = stake × (O - 1)，回收 = stake × O。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StakeAllocation:
    """單一結果的注碼分配。"""

    label: str
    odds: float
    stake: float
    profit_if_hit: float

    @property
    def payout_if_hit(self) -> float:
        return self.stake * self.odds


def dutch_stakes_equal_profit(
    legs: list[tuple[str, float]],
    total_stake: float,
) -> list[StakeAllocation]:
    """
    互斥結果荷蘭式下注：任一中獎時，淨利完全相同。

    stake_i = total × (1/O_i) / Σ(1/O_j)
    """
    if total_stake <= 0 or not legs:
        return []
    valid = [(lbl, o) for lbl, o in legs if o > 1.0]
    if not valid:
        return []

    inv_sum = sum(1.0 / o for _, o in valid)
    stakes = [total_stake * (1.0 / o) / inv_sum for _, o in valid]
    profits = [s * o - total_stake for s, (_, o) in zip(stakes, valid, strict=True)]
    target = profits[0] if profits else 0.0

    return [
        StakeAllocation(label=lbl, odds=o, stake=round(s, 2), profit_if_hit=round(target, 2))
        for (lbl, o), s in zip(valid, stakes, strict=True)
    ]


def hedge_stakes_two_outcome(
    label_a: str,
    odds_a: float,
    label_b: str,
    odds_b: float,
    total_stake: float,
    *,
    target_profit: float | None = None,
) -> tuple[StakeAllocation, StakeAllocation]:
    """
    雙結果對沖：A 中則賺 target_profit；B 中則亦賺 target_profit（互斥）。

    若未指定 target_profit，使用荷蘭式均利。
    """
    allocs = dutch_stakes_equal_profit([(label_a, odds_a), (label_b, odds_b)], total_stake)
    if len(allocs) != 2:
        return (
            StakeAllocation(label_a, odds_a, 0.0, 0.0),
            StakeAllocation(label_b, odds_b, 0.0, 0.0),
        )
    if target_profit is None:
        return allocs[0], allocs[1]

    # 指定目標淨利 P：s_a*(O_a-1) - s_b = P 且 s_b*(O_b-1) - s_a = P，s_a+s_b = total
    oa, ob = odds_a, odds_b
    if oa <= 1 or ob <= 1:
        return allocs[0], allocs[1]
    p = target_profit
    # s_a = (P + total) / O_a 近似求解（互斥二元）
    sa = (total_stake + p) / oa
    sb = total_stake - sa
    if sb < 0:
        return allocs[0], allocs[1]
    return (
        StakeAllocation(label_a, oa, round(sa, 2), round(p, 2)),
        StakeAllocation(label_b, ob, round(sb, 2), round(p, 2)),
    )


def synthetic_parlay_odds(leg_odds: list[float]) -> float:
    """串關合成賠率（台灣運彩：各腿賠率相乘）。"""
    prod = 1.0
    for o in leg_odds:
        if o <= 1.0:
            return 0.0
        prod *= o
    return prod


def dutch_parlay_grid(
    match_legs: list[list[tuple[str, float]]],
    total_stake: float,
) -> list[tuple[tuple[str, ...], float, float]]:
    """
    多場包牌笛卡爾積荷蘭式串關。

    回傳 [(各場選項標籤 tuple, 串關賠率, 建議注碼), ...]
    假設各組合互斥（同一場僅一選項可中）。
    """
    from itertools import product

    combos: list[tuple[tuple[str, ...], float]] = []
    for picks in product(*match_legs):
        labels = tuple(lbl for lbl, _ in picks)
        odds = synthetic_parlay_odds([o for _, o in picks])
        if odds > 1.0:
            combos.append((labels, odds))

    if not combos:
        return []

    inv_sum = sum(1.0 / o for _, o in combos)
    out: list[tuple[tuple[str, ...], float, float]] = []
    for labels, odds in combos:
        stake = total_stake * (1.0 / odds) / inv_sum
        out.append((labels, odds, round(stake, 2)))
    return out
