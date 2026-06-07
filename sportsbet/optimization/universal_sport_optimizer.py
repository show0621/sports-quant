"""
全玩法聯合機率分佈 + 跨玩法 EV 優化 + 對沖策略。

支援 NBA / MLB（偏態正態 + MC）、足球（雙變數 Poisson）、網球／通用（偏態正態）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import numpy as np
from scipy.stats import norm, poisson, skewnorm

from sportsbet import analytics
from sportsbet.models.margin_bands import bands_for_sport, mc_margin_band_probs
from sportsbet.models.totals import margin_std_for_sport
from sportsbet.optimization.stake_solver import dutch_stakes_equal_profit

SportKind = Literal["nba", "mlb", "soccer", "tennis", "generic"]
MIN_EV_THRESHOLD = 0.05
DEFAULT_SIMULATIONS = 20_000


@dataclass
class GameInput:
    """單場比賽輸入：模型勝率 + 官方即時賠率。"""

    label: str
    sport: SportKind
    favorite_side: Literal["home", "away"]
    win_prob_favorite: float
    moneyline_home: float
    moneyline_away: float
    spread_line: float
    spread_home_odds: float
    spread_away_odds: float
    total_line: float
    total_over_odds: float
    total_under_odds: float
    margin_odds: dict[str, float] = field(default_factory=dict)
    pred_total: float | None = None
    pred_margin: float | None = None


@dataclass
class ProbabilityMatrix:
    """MC 後的全玩法機率矩陣。"""

    sport: SportKind
    n_simulations: int
    moneyline_home: float
    moneyline_away: float
    spread_cover_home: float
    spread_cover_away: float
    total_over: float
    total_under: float
    margin_probs: dict[str, float]
    p_over_given_strong_blowout: float
    p_strong_blowout_given_over: float
    home_scores: np.ndarray
    away_scores: np.ndarray


@dataclass
class BetRecommendation:
    """單注 / 包牌建議。"""

    market: str
    title: str
    selection: str
    prob: float
    odds: float
    ev: float
    stake_allocations: list[tuple[str, float, float]]
    synthetic_odds: float | None = None
    rationale: str = ""


@dataclass
class HedgePackage:
    """跨玩法對沖包牌。"""

    strategy_id: str
    title: str
    legs: list[BetRecommendation]
    combined_hit_prob: float
    ev_total: float
    stake_allocations: list[tuple[str, float, float]]
    rationale: str


class UniversalSportOptimizer:
    """台灣運彩全玩法量化優化器。"""

    def __init__(
        self,
        *,
        n_simulations: int = DEFAULT_SIMULATIONS,
        min_ev: float = MIN_EV_THRESHOLD,
        random_seed: int | None = 42,
    ):
        self.n_simulations = n_simulations
        self.min_ev = min_ev
        self.rng = np.random.default_rng(random_seed)

    def build_probability_matrix(self, game: GameInput) -> ProbabilityMatrix:
        if game.sport == "soccer":
            return self._simulate_soccer(game)
        return self._simulate_skew_normal(game)

    def _resolve_pred_margin(self, game: GameInput, std: float) -> float:
        if game.pred_margin is not None:
            return float(game.pred_margin)
        p = max(0.01, min(0.99, game.win_prob_favorite))
        z = float(norm.ppf(p))
        mag = z * std
        return mag if game.favorite_side == "home" else -mag

    def _resolve_pred_total(self, game: GameInput) -> float:
        if game.pred_total is not None:
            return float(game.pred_total)
        defaults = {"nba": 225.0, "mlb": 8.5, "tennis": 24.5, "generic": 220.0, "soccer": 2.6}
        return defaults.get(game.sport, 220.0)

    def _simulate_skew_normal(self, game: GameInput) -> ProbabilityMatrix:
        n = self.n_simulations
        sport_key = "nba" if game.sport in ("tennis", "generic") else game.sport
        std = margin_std_for_sport(sport_key, pred_total=self._resolve_pred_total(game))
        pred_margin = self._resolve_pred_margin(game, std)
        pred_total = self._resolve_pred_total(game)
        total_std = 12.0 if sport_key == "nba" else 2.2

        skew = 2.0 if abs(pred_margin) >= 6 else 0.5
        if game.favorite_side == "away" and pred_margin < 0:
            skew = -skew

        margins = skewnorm.rvs(skew, loc=pred_margin, scale=std, size=n, random_state=self.rng)
        totals = pred_total + self.rng.normal(0, total_std, n)
        home = np.maximum((totals + margins) / 2.0, 0)
        away = np.maximum((totals - margins) / 2.0, 0)

        if sport_key == "mlb":
            home = np.round(home).astype(int)
            away = np.round(away).astype(int)

        return self._matrix_from_samples(game, home, away, sport_key)

    def _simulate_soccer(self, game: GameInput) -> ProbabilityMatrix:
        n = self.n_simulations
        p_home = game.win_prob_favorite if game.favorite_side == "home" else (1.0 - game.win_prob_favorite)
        total_exp = self._resolve_pred_total(game)
        lam_home = total_exp * (0.5 + (p_home - 0.5) * 0.35)
        lam_away = max(0.3, total_exp - lam_home)
        home = poisson.rvs(lam_home, size=n, random_state=self.rng).astype(float)
        away = poisson.rvs(lam_away, size=n, random_state=self.rng).astype(float)
        return self._matrix_from_samples(game, home, away, "nba")

    def _matrix_from_samples(
        self,
        game: GameInput,
        home: np.ndarray,
        away: np.ndarray,
        sport_key: str,
    ) -> ProbabilityMatrix:
        diff = home - away
        totals = home + away

        ml_home = float(np.mean(diff > 0))
        ml_away = float(np.mean(diff < 0))
        sp_home = float(np.mean(diff + game.spread_line > 0))
        sp_away = float(np.mean(diff + game.spread_line < 0))
        over = float(np.mean(totals > game.total_line))
        under = 1.0 - over
        margin_probs = mc_margin_band_probs(home, away, sport=sport_key)

        if sport_key == "mlb":
            blowout = (diff >= 3) if game.favorite_side == "home" else (diff <= -3)
        else:
            blowout = (diff >= 11) if game.favorite_side == "home" else (diff <= -11)
        over_mask = totals > game.total_line
        p_b_given_o = float(np.mean(blowout[over_mask])) if over_mask.any() else 0.0
        p_o_given_b = float(np.mean(over_mask[blowout])) if blowout.any() else 0.0

        return ProbabilityMatrix(
            sport=game.sport,
            n_simulations=len(home),
            moneyline_home=ml_home,
            moneyline_away=ml_away,
            spread_cover_home=sp_home,
            spread_cover_away=sp_away,
            total_over=over,
            total_under=under,
            margin_probs=margin_probs,
            p_over_given_strong_blowout=p_b_given_o,
            p_strong_blowout_given_over=p_o_given_b,
            home_scores=home,
            away_scores=away,
        )

    def find_best_single_bet(
        self,
        matrix: ProbabilityMatrix,
        game: GameInput,
        *,
        total_stake: float = 100.0,
    ) -> tuple[BetRecommendation | None, list[HedgePackage]]:
        candidates: list[BetRecommendation] = []

        for side, prob, odds in (
            ("home", matrix.moneyline_home, game.moneyline_home),
            ("away", matrix.moneyline_away, game.moneyline_away),
        ):
            ev = analytics.expected_value(prob, odds)
            if ev >= self.min_ev:
                candidates.append(
                    BetRecommendation(
                        market="moneyline",
                        title="不讓分",
                        selection=side,
                        prob=prob,
                        odds=odds,
                        ev=ev,
                        stake_allocations=[("不讓分·" + ("主" if side == "home" else "客"), total_stake, odds)],
                        rationale=f"模型勝率 {prob:.1%}，EV {ev:+.1%}",
                    )
                )

        for side, prob, odds in (
            ("home", matrix.spread_cover_home, game.spread_home_odds),
            ("away", matrix.spread_cover_away, game.spread_away_odds),
        ):
            ev = analytics.expected_value(prob, odds)
            if ev >= self.min_ev:
                candidates.append(
                    BetRecommendation(
                        market="spread",
                        title="讓分盤",
                        selection=side,
                        prob=prob,
                        odds=odds,
                        ev=ev,
                        stake_allocations=[(
                            f"讓分·{'主' if side == 'home' else '客'} ({game.spread_line:+.1f})",
                            total_stake,
                            odds,
                        )],
                        rationale=f"過盤機率 {prob:.1%}，EV {ev:+.1%}",
                    )
                )

        for side, prob, odds in (
            ("over", matrix.total_over, game.total_over_odds),
            ("under", matrix.total_under, game.total_under_odds),
        ):
            ev = analytics.expected_value(prob, odds)
            if ev >= self.min_ev:
                candidates.append(
                    BetRecommendation(
                        market="total",
                        title="大小分",
                        selection=side,
                        prob=prob,
                        odds=odds,
                        ev=ev,
                        stake_allocations=[(
                            f"{'大' if side == 'over' else '小'} {game.total_line}",
                            total_stake,
                            odds,
                        )],
                        rationale=f"過{'大' if side == 'over' else '小'}機率 {prob:.1%}，EV {ev:+.1%}",
                    )
                )

        sport_key = "nba" if game.sport in ("tennis", "generic", "soccer") else game.sport
        for band in bands_for_sport(sport_key):
            prob = matrix.margin_probs.get(band.key, 0.0)
            odds = game.margin_odds.get(band.key)
            if odds is None or odds <= 1.0:
                continue
            ev = analytics.expected_value(prob, odds)
            if ev >= self.min_ev:
                candidates.append(
                    BetRecommendation(
                        market="margin",
                        title="勝分差",
                        selection=band.key,
                        prob=prob,
                        odds=odds,
                        ev=ev,
                        stake_allocations=[(band.label_zh, total_stake, odds)],
                        rationale=f"{band.label_zh} 機率 {prob:.1%}，EV {ev:+.1%}",
                    )
                )

        candidates.sort(key=lambda x: x.ev, reverse=True)
        best = candidates[0] if candidates else None
        hedges = [
            h
            for h in (
                self._strategy_a_over_margin_cross(game, matrix, total_stake),
                self._strategy_b_ml_margin_hedge(game, matrix, total_stake),
            )
            if h is not None
        ]
        hedges.sort(key=lambda x: x.ev_total, reverse=True)
        return best, hedges

    def _strategy_a_over_margin_cross(
        self,
        game: GameInput,
        matrix: ProbabilityMatrix,
        total_stake: float,
    ) -> HedgePackage | None:
        if matrix.total_over < 0.52 or matrix.p_strong_blowout_given_over < 0.55:
            return None

        sport_key = "nba" if game.sport in ("tennis", "generic", "soccer") else game.sport
        weak = "away" if game.favorite_side == "home" else "home"
        hedge_keys = ["away_1_2", "away_1_5"] if sport_key == "mlb" else [f"{weak}_1_5", f"{weak}_6_10"]
        legs: list[tuple[str, float, float]] = [("大分", game.total_over_odds, matrix.total_over)]

        for key in hedge_keys:
            o = game.margin_odds.get(key)
            p = matrix.margin_probs.get(key, 0.0)
            if o and o > 1.0 and p > 0.02:
                band = next((b for b in bands_for_sport(sport_key) if b.key == key), None)
                legs.append((f"對沖·{band.label_zh if band else key}", o, p))

        if len(legs) < 2:
            return None

        dutch = dutch_stakes_equal_profit([(l[0], l[1]) for l in legs], total_stake)
        stakes = [a.stake for a in dutch]
        probs = [l[2] for l in legs]
        odds = [l[1] for l in legs]
        ev_total = sum(s / total_stake * (p * o - 1) for s, p, o in zip(stakes, probs, odds, strict=True))
        if ev_total < self.min_ev:
            return None

        return HedgePackage(
            strategy_id="A_over_margin_cross",
            title="策略 A · 大分 + 勝分差交叉對沖",
            legs=[],
            combined_hit_prob=min(sum(probs), 0.99),
            ev_total=ev_total,
            stake_allocations=[(a.label, a.stake, a.odds) for a in dutch],
            rationale=(
                f"開大且強隊大勝條件機率 {matrix.p_strong_blowout_given_over:.0%}；"
                "荷蘭式分配 Over 與弱隊小勝區間。"
            ),
        )

    def _strategy_b_ml_margin_hedge(
        self,
        game: GameInput,
        matrix: ProbabilityMatrix,
        total_stake: float,
    ) -> HedgePackage | None:
        fav = game.favorite_side
        ml_odds = game.moneyline_home if fav == "home" else game.moneyline_away
        ml_prob = matrix.moneyline_home if fav == "home" else matrix.moneyline_away

        if ml_odds > 1.35 or ml_prob < 0.55:
            return None
        if abs(game.spread_line) < 8 and game.sport == "nba":
            return None

        sport_key = "nba" if game.sport in ("tennis", "generic", "soccer") else game.sport
        weak = "away" if fav == "home" else "home"
        keys = [f"{weak}_1_5", f"{weak}_6_10"] if sport_key == "nba" else [f"{weak}_1_2", f"{weak}_3_5"]

        legs: list[tuple[str, float, float]] = [
            (f"不讓分·{'主' if fav == 'home' else '客'}", ml_odds, ml_prob),
        ]
        for key in keys:
            o = game.margin_odds.get(key)
            p = matrix.margin_probs.get(key, 0.0)
            if o and o > 1.0:
                band = next((b for b in bands_for_sport(sport_key) if b.key == key), None)
                legs.append((band.label_zh if band else key, o, p))

        if len(legs) < 2:
            return None

        dutch = dutch_stakes_equal_profit([(l[0], l[1]) for l in legs], total_stake)
        stakes = [a.stake for a in dutch]
        probs = [l[2] for l in legs]
        odds = [l[1] for l in legs]
        ev_total = sum(s / total_stake * (p * o - 1) for s, p, o in zip(stakes, probs, odds, strict=True))
        if ev_total < self.min_ev:
            return None

        return HedgePackage(
            strategy_id="B_ml_margin_hedge",
            title="策略 B · 低賠獨贏 + 弱隊勝分差荷蘭式對沖",
            legs=[],
            combined_hit_prob=min(sum(probs), 0.99),
            ev_total=ev_total,
            stake_allocations=[(a.label, a.stake, a.odds) for a in dutch],
            rationale="強隊低賠獨贏搭配弱隊小勝區間，覆蓋贏球但沒大勝的路徑。",
        )

    def format_single_game_report(
        self,
        game: GameInput,
        matrix: ProbabilityMatrix,
        best: BetRecommendation | None,
        hedges: list[HedgePackage],
        *,
        total_stake: float = 100.0,
    ) -> str:
        lines = [
            f"=== {game.label} ({game.sport.upper()}) ===",
            f"MC {matrix.n_simulations:,} 次 · 看好 {'主' if game.favorite_side == 'home' else '客'} "
            f"{game.win_prob_favorite:.0%}",
            "",
            "【全玩法模型機率】",
            f"  不讓分  主 {matrix.moneyline_home:.1%} / 客 {matrix.moneyline_away:.1%}",
            f"  讓分({game.spread_line:+.1f})  主過 {matrix.spread_cover_home:.1%} / 客過 {matrix.spread_cover_away:.1%}",
            f"  大小({game.total_line})  大 {matrix.total_over:.1%} / 小 {matrix.total_under:.1%}",
        ]
        top_margin = sorted(matrix.margin_probs.items(), key=lambda x: -x[1])[:4]
        if top_margin:
            lines.append("  勝分差 Top4: " + ", ".join(f"{k} {v:.1%}" for k, v in top_margin))

        lines.extend(["", "【單注 EV 最佳】"])
        if best:
            lines.append(
                f"  ★ {best.title} · {best.selection} | 機率 {best.prob:.1%} | "
                f"賠率 {best.odds:.2f} | EV {best.ev:+.1%} | 注 {total_stake:.0f} 元"
            )
        else:
            lines.append(f"  無單注達 EV ≥ {self.min_ev:.0%}")

        if hedges:
            lines.extend(["", "【對沖包牌】"])
            for h in hedges:
                lines.append(f"  ★ {h.title} | EV {h.ev_total:+.1%} | 覆蓋 {h.combined_hit_prob:.1%}")
                lines.append(f"    {h.rationale}")
                for lbl, stake, odds in h.stake_allocations:
                    lines.append(f"    · {lbl}: {stake:.0f} 元 @ {odds:.2f}")

        return "\n".join(lines)

    def optimize_parlay_system(
        self,
        matches: list,
        *,
        total_stake: float = 100.0,
        parlay_size: int = 2,
    ):
        """第三部分：多場串關 / 立柱 / 荷蘭式拆單（委派 ParlaySystemOptimizer）。"""
        from sportsbet.optimization.parlay_engine import ParlaySystemOptimizer

        return ParlaySystemOptimizer(min_ev=self.min_ev).optimize_parlay_system(
            matches,
            total_stake=total_stake,
            parlay_size=parlay_size,
        )
