"""
串關、荷蘭式拆單、立柱（Banker）與過關組合優化引擎。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from itertools import combinations, product

from sportsbet import analytics
from sportsbet.optimization.stake_solver import dutch_parlay_grid, synthetic_parlay_odds


@dataclass
class ParlayLeg:
    """單場串關腿。"""

    match_label: str
    market: str
    selection_label: str
    prob: float
    odds: float
    is_banker: bool = False


@dataclass
class MatchParlayOptions:
    """單場可包牌的多个選項（笛卡爾積用）。"""

    match_label: str
    legs: list[ParlayLeg]


@dataclass
class ParlayPlan:
    """一張實體串關注單。"""

    legs: tuple[ParlayLeg, ...]
    parlay_odds: float
    combined_prob: float
    ev: float
    stake: float
    expected_profit: float


@dataclass
class SystemBetPlan:
    """過關組合（例如 3串4）。"""

    name: str
    parlays: list[ParlayPlan]
    total_stake: float
    compound_ev: float
    description: str


class ParlaySystemOptimizer:
    """多場次串關 + 立柱 + 荷蘭式拆單。"""

    def __init__(self, *, min_ev: float = 0.05, banker_prob_min: float = 0.58, banker_odds_max: float = 1.45):
        self.min_ev = min_ev
        self.banker_prob_min = banker_prob_min
        self.banker_odds_max = banker_odds_max

    def mark_bankers(self, all_legs: list[ParlayLeg]) -> list[ParlayLeg]:
        """自動標記主柱：高勝率 + 低賠率 + EV 穩定。"""
        out: list[ParlayLeg] = []
        for leg in all_legs:
            ev = analytics.expected_value(leg.prob, leg.odds)
            is_banker = (
                leg.prob >= self.banker_prob_min
                and leg.odds <= self.banker_odds_max
                and ev >= self.min_ev
            )
            out.append(
                ParlayLeg(
                    match_label=leg.match_label,
                    market=leg.market,
                    selection_label=leg.selection_label,
                    prob=leg.prob,
                    odds=leg.odds,
                    is_banker=is_banker,
                )
            )
        return out

    def optimize_parlay_system(
        self,
        matches: list[MatchParlayOptions],
        *,
        total_stake: float = 100.0,
        parlay_size: int = 2,
    ) -> tuple[list[ParlayPlan], list[SystemBetPlan], list[tuple[tuple[str, ...], float, float]]]:
        """
        多場串關優化。

        回傳：
        1. 單一最佳 2串1 / N串1 列表
        2. 過關組合（3串3、4串11 等）
        3. 荷蘭式拆單網格（若各場有多選項）
        """
        dutch_grid: list[tuple[tuple[str, ...], float, float]] = []
        multi = [m for m in matches if len(m.legs) > 1]
        if multi:
            leg_groups = [[(f"{leg.selection_label}", leg.odds) for leg in m.legs] for m in multi]
            dutch_grid = dutch_parlay_grid(leg_groups, total_stake)

        # 每場取 EV 最高腿作為預設串關
        best_per_match: list[ParlayLeg] = []
        for m in matches:
            if not m.legs:
                continue
            best = max(m.legs, key=lambda x: analytics.expected_value(x.prob, x.odds))
            best_per_match.append(best)

        best_per_match = self.mark_bankers(best_per_match)
        n = len(best_per_match)
        if n < 2:
            return [], [], dutch_grid

        parlay_plans: list[ParlayPlan] = []
        for combo in combinations(best_per_match, parlay_size):
            probs = [l.prob for l in combo]
            odds_list = [l.odds for l in combo]
            p = math.prod(probs)
            o = synthetic_parlay_odds(odds_list)
            ev = analytics.parlay_ev(probs, o)
            if ev >= self.min_ev:
                stake = total_stake / max(len(list(combinations(best_per_match, parlay_size))), 1)
                parlay_plans.append(
                    ParlayPlan(
                        legs=tuple(combo),
                        parlay_odds=o,
                        combined_prob=p,
                        ev=ev,
                        stake=round(stake, 2),
                        expected_profit=round(stake * ev, 2),
                    )
                )

        parlay_plans.sort(key=lambda x: x.ev, reverse=True)
        systems = self._build_system_bets(best_per_match, total_stake)
        return parlay_plans, systems, dutch_grid

    def _build_system_bets(self, legs: list[ParlayLeg], total_stake: float) -> list[SystemBetPlan]:
        """3串3、3串4、4串11 等過關組合。"""
        n = len(legs)
        if n < 3:
            return []

        bankers = [l for l in legs if l.is_banker]
        branches = [l for l in legs if not l.is_banker]
        systems: list[SystemBetPlan] = []

        # 3 場：3串3（全 2串1）+ 3串4（3個2串1 + 1個3串1）
        if n == 3:
            pairs = list(combinations(legs, 2))
            treble_legs = legs
            p2_plans: list[ParlayPlan] = []
            for combo in pairs:
                p2_plans.append(self._make_plan(combo, total_stake / 4))

            p3 = self._make_plan(tuple(treble_legs), total_stake / 4)
            all_plans = p2_plans + [p3]
            compound = sum(pl.ev * pl.stake for pl in all_plans) / total_stake
            systems.append(
                SystemBetPlan(
                    name="3串4",
                    parlays=all_plans,
                    total_stake=total_stake,
                    compound_ev=compound,
                    description="3 個 2串1 + 1 個 3串1；任一場可錯仍可能獲利。",
                )
            )

        # 4 場：4串11（6×2串1 + 4×3串1 + 1×4串1）
        if n == 4:
            plans: list[ParlayPlan] = []
            unit = total_stake / 11
            for combo in combinations(legs, 2):
                plans.append(self._make_plan(combo, unit))
            for combo in combinations(legs, 3):
                plans.append(self._make_plan(combo, unit))
            plans.append(self._make_plan(tuple(legs), unit))
            compound = sum(pl.ev * pl.stake for pl in plans) / total_stake
            banker_note = f"主柱：{', '.join(b.match_label for b in bankers)}" if bankers else ""
            branch_note = f"副柱：{', '.join(b.match_label for b in branches)}" if branches else ""
            systems.append(
                SystemBetPlan(
                    name="4串11",
                    parlays=plans,
                    total_stake=total_stake,
                    compound_ev=compound,
                    description=f"6×2串1 + 4×3串1 + 1×4串1。{banker_note} {branch_note}".strip(),
                )
            )

        return systems

    def _make_plan(self, combo: tuple[ParlayLeg, ...], stake: float) -> ParlayPlan:
        probs = [l.prob for l in combo]
        odds_list = [l.odds for l in combo]
        p = math.prod(probs)
        o = synthetic_parlay_odds(odds_list)
        ev = analytics.parlay_ev(probs, o)
        return ParlayPlan(
            legs=combo,
            parlay_odds=o,
            combined_prob=p,
            ev=ev,
            stake=round(stake, 2),
            expected_profit=round(stake * ev, 2),
        )

    def format_parlay_report(
        self,
        parlays: list[ParlayPlan],
        systems: list[SystemBetPlan],
        dutch_grid: list[tuple[tuple[str, ...], float, float]],
        *,
        total_stake: float,
    ) -> str:
        lines = ["=== 串關 / 過關組合優化 ===", ""]

        if dutch_grid:
            lines.append("【荷蘭式拆單 · 跨場包牌笛卡爾積】")
            for labels, odds, stake in dutch_grid:
                lines.append(f"  · {' × '.join(labels)} @ {odds:.2f} → 注 {stake:.0f} 元")
            lines.append("")

        if parlays:
            lines.append("【推薦 2串1 / N串1】")
            for i, pl in enumerate(parlays[:5], 1):
                leg_txt = " × ".join(f"{l.match_label}:{l.selection_label}" for l in pl.legs)
                lines.append(
                    f"  {i}. {leg_txt} | 合成 {pl.parlay_odds:.2f} | "
                    f"P {pl.combined_prob:.1%} | EV {pl.ev:+.1%} | 注 {pl.stake:.0f} 元"
                )
            lines.append("")

        if systems:
            lines.append("【過關組合 · 立柱策略】")
            for sys in systems:
                lines.append(f"  ★ {sys.name} | 複合 EV {sys.compound_ev:+.1%} | 總注 {sys.total_stake:.0f} 元")
                lines.append(f"    {sys.description}")
                for j, pl in enumerate(sys.parlays[:6], 1):
                    leg_txt = " × ".join(l.selection_label for l in pl.legs)
                    lines.append(f"    單{j}: {leg_txt} @ {pl.parlay_odds:.2f} → {pl.stake:.0f} 元")
                if len(sys.parlays) > 6:
                    lines.append(f"    … 共 {len(sys.parlays)} 張")
                lines.append("")

        if not parlays and not systems and not dutch_grid:
            lines.append("無達 EV 門檻的串關組合。")

        return "\n".join(lines)
