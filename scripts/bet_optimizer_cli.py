#!/usr/bin/env python3
"""
台灣運彩全玩法 EV 優化 CLI。

用法：
  python scripts/bet_optimizer_cli.py
  python main.py optimize
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sportsbet.models.margin_bands import bands_for_sport
from sportsbet.optimization.parlay_engine import MatchParlayOptions, ParlayLeg, ParlaySystemOptimizer
from sportsbet.optimization.universal_sport_optimizer import GameInput, UniversalSportOptimizer

SPORT_CHOICES = {
    "1": ("nba", "NBA 籃球"),
    "2": ("mlb", "MLB 棒球"),
    "3": ("soccer", "足球"),
    "4": ("tennis", "網球"),
    "5": ("generic", "通用"),
}


def _prompt_float(label: str, default: float | None = None) -> float:
    raw = input(f"{label}" + (f" [{default}]" if default is not None else "") + ": ").strip()
    if not raw and default is not None:
        return default
    return float(raw)


def _prompt_side(label: str = "看好主隊還是客隊") -> str:
    while True:
        raw = input(f"{label} (h=主 / a=客): ").strip().lower()
        if raw in ("h", "home", "主"):
            return "home"
        if raw in ("a", "away", "客"):
            return "away"


def _prompt_margin_odds(sport: str) -> dict[str, float]:
    """選填：逐項輸入勝分差賠率；直接 Enter 跳過。"""
    sport_key = "nba" if sport in ("tennis", "generic", "soccer") else sport
    bands = bands_for_sport(sport_key)
    print(f"\n--- 勝分差賠率（共 {len(bands)} 項，Enter 跳過未開盤）---")
    out: dict[str, float] = {}
    for band in bands:
        raw = input(f"  {band.label_zh} ({band.key}): ").strip()
        if raw:
            out[band.key] = float(raw)
    return out


def _input_game(index: int) -> GameInput:
    print(f"\n{'='*50}\n第 {index} 場賽事\n{'='*50}")
    label = input("賽事名稱（例：馬刺 @ 尼克）: ").strip() or f"比賽{index}"

    print("球種：")
    for k, (_, name) in SPORT_CHOICES.items():
        print(f"  {k}. {name}")
    sport_key = input("選擇 [1]: ").strip() or "1"
    sport = SPORT_CHOICES.get(sport_key, SPORT_CHOICES["1"])[0]

    fav = _prompt_side("您看好的隊伍")
    win_prob = _prompt_float("該隊獨贏勝率 (0~1，例 0.60)", 0.60)

    print("\n--- 不讓分 ---")
    ml_h = _prompt_float("主隊賠率")
    ml_a = _prompt_float("客隊賠率")

    print("\n--- 讓分（主隊讓分值，負=主讓）---")
    spread = _prompt_float("主隊 handicap")
    sp_h = _prompt_float("主隊讓分賠率")
    sp_a = _prompt_float("客隊讓分賠率")

    print("\n--- 大小分 ---")
    total_line = _prompt_float("大小分界線")
    ov = _prompt_float("大分賠率")
    un = _prompt_float("小分賠率")

    margin_odds = _prompt_margin_odds(sport)

    pred_total = input("\n預測總分（Enter 用預設）: ").strip()
    pred_margin = input("預測淨勝分差（Enter 自動推算）: ").strip()

    return GameInput(
        label=label,
        sport=sport,  # type: ignore[arg-type]
        favorite_side=fav,  # type: ignore[arg-type]
        win_prob_favorite=win_prob,
        moneyline_home=ml_h,
        moneyline_away=ml_a,
        spread_line=spread,
        spread_home_odds=sp_h,
        spread_away_odds=sp_a,
        total_line=total_line,
        total_over_odds=ov,
        total_under_odds=un,
        margin_odds=margin_odds,
        pred_total=float(pred_total) if pred_total else None,
        pred_margin=float(pred_margin) if pred_margin else None,
    )


def _build_parlay_options(
    game: GameInput,
    matrix,
    optimizer: UniversalSportOptimizer,
) -> MatchParlayOptions:
    """從單場最佳建議建立串關選項（含包牌）。"""
    best, hedges = optimizer.find_best_single_bet(matrix, game)
    legs: list[ParlayLeg] = []

    if best:
        legs.append(
            ParlayLeg(
                match_label=game.label,
                market=best.market,
                selection_label=f"{best.title}:{best.selection}",
                prob=best.prob,
                odds=best.odds,
            )
        )

    for h in hedges[:1]:
        for lbl, stake, odds in h.stake_allocations[:2]:
            legs.append(
                ParlayLeg(
                    match_label=game.label,
                    market="hedge",
                    selection_label=lbl,
                    prob=h.combined_hit_prob / max(len(h.stake_allocations), 1),
                    odds=odds,
                )
            )

    if not legs and best is None:
        # 降級：用讓分或大小
        from sportsbet import analytics

        for market, prob, odds, sel in (
            ("spread", matrix.spread_cover_home, game.spread_home_odds, "主讓分"),
            ("total", matrix.total_over, game.total_over_odds, "大分"),
        ):
            if analytics.expected_value(prob, odds) > 0:
                legs.append(
                    ParlayLeg(game.label, market, sel, prob, odds)
                )
                break

    return MatchParlayOptions(match_label=game.label, legs=legs)


def run_cli() -> None:
    print("=" * 60)
    print("  台灣運彩 · 全玩法 EV 優化 / 對沖 / 串關系統")
    print("  UniversalSportOptimizer v1.0")
    print("=" * 60)

    n_raw = input("\n要分析幾場比賽？(1~5) [1]: ").strip() or "1"
    n_games = max(1, min(5, int(n_raw)))
    total_stake = _prompt_float("單場/串關總注碼（元）", 100.0)
    min_ev_raw = input("最低 EV 門檻 (例 0.05 = 5%) [0.05]: ").strip()
    min_ev = float(min_ev_raw) if min_ev_raw else 0.05

    optimizer = UniversalSportOptimizer(min_ev=min_ev)
    parlay_opt = ParlaySystemOptimizer(min_ev=min_ev)

    games: list[GameInput] = []
    matrices = []
    match_options: list[MatchParlayOptions] = []

    for i in range(1, n_games + 1):
        g = _input_game(i)
        games.append(g)
        matrix = optimizer.build_probability_matrix(g)
        matrices.append(matrix)
        best, hedges = optimizer.find_best_single_bet(matrix, g, total_stake=total_stake)
        print("\n" + optimizer.format_single_game_report(g, matrix, best, hedges, total_stake=total_stake))
        match_options.append(_build_parlay_options(g, matrix, optimizer))

    if n_games >= 2:
        parlays, systems, dutch = parlay_opt.optimize_parlay_system(
            match_options,
            total_stake=total_stake,
            parlay_size=2,
        )
        print("\n" + parlay_opt.format_parlay_report(parlays, systems, dutch, total_stake=total_stake))

    print("\n" + "=" * 60)
    print("分析完成。請依上方劃單指引至台灣運彩投注。")
    print("提醒：過去績效不代表未來；請量力而為。")
    print("=" * 60)


if __name__ == "__main__":
    run_cli()
