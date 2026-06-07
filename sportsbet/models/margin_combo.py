"""勝分差雙包（包組）策略：強弱懸殊型 / 強強對決型。"""
from __future__ import annotations

from dataclasses import dataclass

from sportsbet import analytics
from sportsbet.models.margin_bands import MarginBand, bands_for_sport, prob_margin_band


@dataclass(frozen=True)
class ComboLeg:
    label: str
    selection: str
    prob: float
    odds: float


@dataclass(frozen=True)
class ComboBetRecommendation:
    strategy_id: str
    title: str
    rationale: str
    legs: tuple[ComboLeg, ComboLeg]
    hit_prob: float
    ev_total: float
    ev_per_unit: float


def _dual_independent_ev(prob_a: float, odds_a: float, prob_b: float, odds_b: float) -> tuple[float, float]:
    """
    各押 1 單位、兩區間互斥時的總 EV 與每單位 EV。
    命中 A：odds_a - 2；命中 B：odds_b - 2；皆未中：-2。
    """
    p_a = max(0.0, min(1.0, prob_a))
    p_b = max(0.0, min(1.0, prob_b))
    p_none = max(0.0, 1.0 - p_a - p_b)
    ev = p_a * (odds_a - 2.0) + p_b * (odds_b - 2.0) + p_none * (-2.0)
    return ev, ev / 2.0


def _band_prob(
    band_probs: dict[str, float],
    band: MarginBand,
    *,
    pred_margin: float,
    sport: str,
    pred_total: float | None,
) -> float:
    if band.key in band_probs:
        return float(band_probs[band.key])
    return prob_margin_band(
        band.side, band.lo, band.hi, pred_margin, sport=sport, pred_total=pred_total,
    )


def _leg(
    band: MarginBand,
    odds_by_selection: dict[str, float],
    band_probs: dict[str, float],
    *,
    pred_margin: float,
    sport: str,
    pred_total: float | None,
) -> ComboLeg | None:
    odds = odds_by_selection.get(band.key)
    if odds is None or odds <= 1.0:
        return None
    prob = _band_prob(band_probs, band, pred_margin=pred_margin, sport=sport, pred_total=pred_total)
    return ComboLeg(band.label_zh, band.key, prob, float(odds))


def strategy_a_blowout(
    *,
    sport: str,
    pred_margin: float,
    pred_total: float | None,
    margin_odds: dict[str, float],
    band_probs: dict[str, float],
    home_team: str,
    away_team: str,
    min_pred_margin: float = 4.0,
) -> ComboBetRecommendation | None:
    """策略 A：強隊 6–10 + 11–15 雙包（預測強隊明顯過盤）。"""
    if abs(pred_margin) < min_pred_margin:
        return None
    strong_side = "home" if pred_margin > 0 else "away"
    team = home_team if strong_side == "home" else away_team
    bands = {b.key: b for b in bands_for_sport(sport)}
    k6, k11 = f"{strong_side}_6_10", f"{strong_side}_11_15"
    if k6 not in bands or k11 not in bands:
        return None
    leg_a = _leg(bands[k6], margin_odds, band_probs, pred_margin=pred_margin, sport=sport, pred_total=pred_total)
    leg_b = _leg(bands[k11], margin_odds, band_probs, pred_margin=pred_margin, sport=sport, pred_total=pred_total)
    if not leg_a or not leg_b:
        return None
    ev_total, ev_per = _dual_independent_ev(leg_a.prob, leg_a.odds, leg_b.prob, leg_b.odds)
    hit = leg_a.prob + leg_b.prob
    return ComboBetRecommendation(
        strategy_id="blowout_dual",
        title="策略 A · 強弱懸殊型（6–10 + 11–15 雙包）",
        rationale=(
            f"模型預估 {team} 淨勝 {abs(pred_margin):.1f}，適合覆蓋強隊拉開比分的常見區間。"
            "各押 1 單位，命中任一區間即可覆蓋另一張本金並有獲利空間。"
        ),
        legs=(leg_a, leg_b),
        hit_prob=hit,
        ev_total=ev_total,
        ev_per_unit=ev_per,
    )


def strategy_b_clutch(
    *,
    sport: str,
    pred_margin: float,
    pred_total: float | None,
    margin_odds: dict[str, float],
    band_probs: dict[str, float],
    max_pred_margin: float = 3.5,
) -> ComboBetRecommendation | None:
    """策略 B：主 1–5 + 客 1–5 雙包（肉搏戰、勝負難拉開）。"""
    if abs(pred_margin) > max_pred_margin:
        return None
    bands = {b.key: b for b in bands_for_sport(sport)}
    leg_h = _leg(bands["home_1_5"], margin_odds, band_probs, pred_margin=pred_margin, sport=sport, pred_total=pred_total)
    leg_a = _leg(bands["away_1_5"], margin_odds, band_probs, pred_margin=pred_margin, sport=sport, pred_total=pred_total)
    if not leg_h or not leg_a:
        return None
    ev_total, ev_per = _dual_independent_ev(leg_h.prob, leg_h.odds, leg_a.prob, leg_a.odds)
    hit = leg_h.prob + leg_a.prob
    return ComboBetRecommendation(
        strategy_id="clutch_dual",
        title="策略 B · 強強對決型（主 1–5 + 客 1–5 雙包）",
        rationale=(
            "預估分差接近，適合賭「撕到最後一刻」：不論誰贏，只要分差在 5 分內即命中其一，"
            "繞開必須猜中勝方的限制。"
        ),
        legs=(leg_h, leg_a),
        hit_prob=hit,
        ev_total=ev_total,
        ev_per_unit=ev_per,
    )


def build_combo_recommendations(
    *,
    sport: str,
    pred_margin: float | None,
    pred_total: float | None,
    margin_odds: dict[str, float],
    band_probs: dict[str, float],
    home_team: str,
    away_team: str,
) -> list[ComboBetRecommendation]:
    if pred_margin is None or not margin_odds:
        return []
    pm = float(pred_margin)
    out: list[ComboBetRecommendation] = []
    a = strategy_a_blowout(
        sport=sport,
        pred_margin=pm,
        pred_total=pred_total,
        margin_odds=margin_odds,
        band_probs=band_probs,
        home_team=home_team,
        away_team=away_team,
    )
    if a:
        out.append(a)
    b = strategy_b_clutch(
        sport=sport,
        pred_margin=pm,
        pred_total=pred_total,
        margin_odds=margin_odds,
        band_probs=band_probs,
    )
    if b:
        out.append(b)
    out.sort(key=lambda x: x.ev_total, reverse=True)
    return out


def recommend_best_play(
    picks: dict[str, object | None],
    combos: list[ComboBetRecommendation],
    *,
    min_ev: float,
) -> tuple[str, str, float | None]:
    """
    回傳 (類型, 描述, EV)。
    類型：moneyline / spread / total / margin / combo
    """
    labels = {
        "moneyline": "不讓分",
        "spread": "讓分",
        "total": "大小分",
        "margin": "勝分差",
    }
    best_type, best_desc, best_ev = "", "", float("-inf")

    for key, pick in picks.items():
        if pick is None:
            continue
        ev = getattr(pick, "ev", None)
        if ev is None or ev < min_ev:
            continue
        if float(ev) > best_ev:
            best_ev = float(ev)
            best_type = key
            best_desc = f"{labels.get(key, key)} · {getattr(pick, 'selection_label', '')}"

    for combo in combos:
        if combo.ev_total >= min_ev and combo.ev_total > best_ev:
            best_ev = combo.ev_total
            best_type = "combo"
            legs = " + ".join(leg.label for leg in combo.legs)
            best_desc = f"{combo.title}（{legs}）"

    if best_type:
        return best_type, best_desc, best_ev
    return "", "觀望（無達門檻 EV）", None


def single_leg_ev(prob: float, odds: float) -> float:
    return analytics.expected_value(prob, odds)
