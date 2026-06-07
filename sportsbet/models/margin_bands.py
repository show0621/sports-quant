"""台灣運彩勝分差（margin）區間與模型機率。"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.stats import norm

from sportsbet.models.totals import margin_std_for_sport

# 台灣運彩 NBA 常見勝分差區間（selection 鍵 → 主/客與分差範圍）
NBA_MARGIN_BANDS: list[tuple[str, str, int, int]] = [
    ("home_1_5", "home", 1, 5),
    ("home_6_10", "home", 6, 10),
    ("home_11_15", "home", 11, 15),
    ("home_16_20", "home", 16, 20),
    ("home_21_25", "home", 21, 25),
    ("home_26_plus", "home", 26, 99),
    ("away_1_5", "away", 1, 5),
    ("away_6_10", "away", 6, 10),
    ("away_11_15", "away", 11, 15),
    ("away_16_20", "away", 16, 20),
    ("away_21_25", "away", 21, 25),
    ("away_26_plus", "away", 26, 99),
]

MLB_MARGIN_BANDS: list[tuple[str, str, int, int]] = [
    ("home_1_2", "home", 1, 2),
    ("home_3_5", "home", 3, 5),
    ("home_6_plus", "home", 6, 99),
    ("away_1_2", "away", 1, 2),
    ("away_3_5", "away", 3, 5),
    ("away_6_plus", "away", 6, 99),
]


@dataclass(frozen=True)
class MarginBand:
    key: str
    side: str
    lo: int
    hi: int

    @property
    def label_zh(self) -> str:
        side = "主" if self.side == "home" else "客"
        if self.hi >= 99:
            return f"{side}勝 {self.lo}+"
        if self.lo == self.hi:
            return f"{side}勝 {self.lo}"
        return f"{side}勝 {self.lo}–{self.hi}"


def bands_for_sport(sport: str) -> list[MarginBand]:
    raw = NBA_MARGIN_BANDS if sport == "nba" else MLB_MARGIN_BANDS
    return [MarginBand(k, s, lo, hi) for k, s, lo, hi in raw]


def margin_band_hit(side: str, lo: int, hi: int, home_score: int, away_score: int) -> bool:
    diff = int(home_score) - int(away_score)
    if side == "home":
        if diff <= 0:
            return False
        m = diff
    else:
        if diff >= 0:
            return False
        m = -diff
    if hi >= 99:
        return m >= lo
    return lo <= m <= hi


def prob_margin_band(
    side: str,
    lo: int,
    hi: int,
    pred_margin: float,
    *,
    sport: str = "nba",
    pred_total: float | None = None,
) -> float:
    """常態近似：預估淨勝分差落在某勝分差區間的機率。"""
    std = margin_std_for_sport(sport, pred_total=pred_total)
    if side == "home":
        if lo <= 0:
            return 0.0
        a = (lo - 0.5 - pred_margin) / std
        b = (hi + 0.5 - pred_margin) / std if hi < 99 else 10.0
        p_win = 1.0 - norm.cdf(-pred_margin / std)
        p_band = norm.cdf(b) - norm.cdf(a)
        return float(max(0.0, min(p_win, p_band)))
    if hi >= 99:
        a = (-lo + 0.5 + pred_margin) / std
        p_win = norm.cdf(-pred_margin / std)
        p_band = 1.0 - norm.cdf(a)
        return float(max(0.0, min(p_win, p_band)))
    a = (-hi - 0.5 + pred_margin) / std
    b = (-lo + 0.5 + pred_margin) / std
    p_win = norm.cdf(-pred_margin / std)
    p_band = norm.cdf(b) - norm.cdf(a)
    return float(max(0.0, min(p_win, p_band)))


def prob_margin_selection(
    selection: str,
    pred_margin: float,
    *,
    sport: str = "nba",
    pred_total: float | None = None,
) -> float | None:
    for band in bands_for_sport(sport):
        if band.key == selection or selection.endswith(band.key):
            return prob_margin_band(
                band.side, band.lo, band.hi, pred_margin, sport=sport, pred_total=pred_total,
            )
    return None


def mc_margin_band_probs(
    home_scores: np.ndarray,
    away_scores: np.ndarray,
    *,
    sport: str = "nba",
) -> dict[str, float]:
    """由 MC 抽樣結果計算各勝分差區間機率。"""
    out: dict[str, float] = {}
    n = max(len(home_scores), 1)
    for band in bands_for_sport(sport):
        hits = [
            margin_band_hit(band.side, band.lo, band.hi, int(h), int(a))
            for h, a in zip(home_scores, away_scores, strict=False)
        ]
        out[band.key] = float(np.mean(hits))
    return out


def best_margin_pick(
    band_probs: dict[str, float],
    odds_by_selection: dict[str, float],
    *,
    sport: str = "nba",
    min_ev: float = 0.0,
) -> tuple[str | None, float | None, float | None]:
    """回傳 (selection, prob, ev) 最佳勝分差選項。"""
    from sportsbet import analytics

    best_key, best_ev, best_p = None, float("-inf"), None
    for band in bands_for_sport(sport):
        p = band_probs.get(band.key)
        o = odds_by_selection.get(band.key)
        if p is None or o is None or o <= 1.0:
            continue
        ev = analytics.expected_value(float(p), float(o))
        if ev > best_ev and ev >= min_ev:
            best_ev, best_key, best_p = ev, band.key, float(p)
    if best_key is None:
        return None, None, None
    return best_key, best_p, best_ev
