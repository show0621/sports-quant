"""Monte Carlo 對戰模擬：勝負、大小分、讓分（基於 Poisson 得分 + 集成勝率校準）。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np

from sportsbet.models.totals import prob_home_covers_spread

Sport = Literal["nba", "mlb"]


@dataclass
class MonteCarloResult:
    home_win_prob: float
    prob_over: float | None
    prob_under: float | None
    prob_home_cover: float | None
    prob_away_cover: float | None
    median_home_score: float
    median_away_score: float
    median_total: float
    median_margin: float
    p10_total: float
    p90_total: float
    n_sims: int

    def summary_line(self, *, sport: str = "nba") -> str:
        parts = [f"MC 模擬 {self.n_sims} 次 · 主勝 {self.home_win_prob:.1%}"]
        if self.prob_over is not None:
            label = "大分" if sport == "nba" else "大"
            parts.append(f"{label} {self.prob_over:.1%}")
        if self.prob_home_cover is not None:
            parts.append(f"主讓分過盤 {self.prob_home_cover:.1%}")
        parts.append(
            f"中位比分 {self.median_away_score:.0f}–{self.median_home_score:.0f}"
        )
        return " · ".join(parts)


def _calibrate_lambdas(
    lam_home: float,
    lam_away: float,
    target_home_win: float,
    *,
    max_iter: int = 12,
) -> tuple[float, float]:
    """微調 λ 使 Poisson 模擬主勝率接近集成模型勝率。"""
    target = min(max(float(target_home_win), 0.08), 0.92)
    lh, la = max(lam_home, 0.1), max(lam_away, 0.1)
    rng = np.random.default_rng(42)
    for _ in range(max_iter):
        hs = rng.poisson(lh, 2000)
        aws = rng.poisson(la, 2000)
        sim_p = float(np.mean(hs > aws) + 0.5 * np.mean(hs == aws))
        err = target - sim_p
        if abs(err) < 0.015:
            break
        scale = 1.0 + err * 0.35
        lh = max(0.1, lh * scale)
        la = max(0.1, la / scale)
    return lh, la


def simulate_matchup(
    lambda_home: float,
    lambda_away: float,
    *,
    sport: Sport = "nba",
    total_line: float | None = None,
    spread_home: float | None = None,
    home_win_anchor: float | None = None,
    n_sims: int = 8000,
    seed: int | None = None,
) -> MonteCarloResult:
    """
    以 Poisson 抽樣模擬 n 場，估計勝負 / 大小 / 讓分機率。

    home_win_anchor：集成模型主勝率，用於校準得分率（動態 PK）。
    """
    lh, la = max(float(lambda_home), 0.1), max(float(lambda_away), 0.1)
    if home_win_anchor is not None:
        lh, la = _calibrate_lambdas(lh, la, home_win_anchor)

    rng = np.random.default_rng(seed)
    home_scores = rng.poisson(lh, n_sims).astype(np.int32)
    away_scores = rng.poisson(la, n_sims).astype(np.int32)
    margins = home_scores - away_scores
    totals = home_scores + away_scores

    home_wins = margins > 0
    home_win_prob = float(np.mean(home_wins) + 0.5 * np.mean(margins == 0))

    prob_over = prob_under = None
    if total_line is not None:
        line = float(total_line)
        prob_over = float(np.mean(totals > line))
        prob_under = float(np.mean(totals < line))

    prob_home_cover = prob_away_cover = None
    if spread_home is not None:
        handicap = float(spread_home)
        prob_home_cover = float(np.mean(home_scores + handicap > away_scores))
        prob_away_cover = 1.0 - prob_home_cover

    return MonteCarloResult(
        home_win_prob=home_win_prob,
        prob_over=prob_over,
        prob_under=prob_under,
        prob_home_cover=prob_home_cover,
        prob_away_cover=prob_away_cover,
        median_home_score=float(np.median(home_scores)),
        median_away_score=float(np.median(away_scores)),
        median_total=float(np.median(totals)),
        median_margin=float(np.median(margins)),
        p10_total=float(np.percentile(totals, 10)),
        p90_total=float(np.percentile(totals, 90)),
        n_sims=n_sims,
    )


def adjust_lambdas_from_roster(
    lam_home: float,
    lam_away: float,
    *,
    home_adjusted: float | None,
    away_adjusted: float | None,
    home_baseline: float | None,
    away_baseline: float | None,
    max_shift: float = 0.12,
) -> tuple[float, float]:
    """依 Bottom-Up 陣容評分微調得分率 λ。"""
    lh, la = lam_home, lam_away
    if home_baseline and home_adjusted and home_baseline > 0:
        ratio = home_adjusted / home_baseline
        lh *= max(1.0 - max_shift, min(1.0 + max_shift, ratio))
    if away_baseline and away_adjusted and away_baseline > 0:
        ratio = away_adjusted / away_baseline
        la *= max(1.0 - max_shift, min(1.0 + max_shift, ratio))
    return max(lh, 0.1), max(la, 0.1)


def blend_lambdas_with_h2h(
    db,
    sport: Sport,
    home_team: str,
    away_team: str,
    match_date: str,
    lam_home: float,
    lam_away: float,
    *,
    blend: float = 0.25,
    limit: int = 8,
    playoff_series: bool = False,
) -> tuple[float, float]:
    """混入近期對戰場均得分（季後賽同對手 ≥1 場即混入 G1 比分）。"""
    from sportsbet import config

    with db.connection() as conn:
        rows = conn.execute(
            """
            SELECT home_team, away_team, home_score, away_score
            FROM games
            WHERE sport = ?
              AND match_date < ?
              AND home_score IS NOT NULL
              AND away_score IS NOT NULL
              AND status IN ('final', 'FT', 'AOT', 'Finished', 'POST')
              AND (
                    (home_team = ? AND away_team = ?)
                 OR (home_team = ? AND away_team = ?)
              )
            ORDER BY match_date DESC
            LIMIT ?
            """,
            (sport, str(match_date)[:10], home_team, away_team, away_team, home_team, limit),
        ).fetchall()
    min_games = (
        config.MC_H2H_PLAYOFF_MIN_GAMES if playoff_series else config.MC_H2H_REGULAR_MIN_GAMES
    )
    if len(rows) < min_games:
        return lam_home, lam_away

    h_pts: list[float] = []
    a_pts: list[float] = []
    for r in rows:
        ht, at = r["home_team"], r["away_team"]
        hs, aws = float(r["home_score"]), float(r["away_score"])
        if ht == home_team:
            h_pts.append(hs)
            a_pts.append(aws)
        else:
            h_pts.append(aws)
            a_pts.append(hs)

    avg_h = sum(h_pts) / len(h_pts)
    avg_a = sum(a_pts) / len(a_pts)
    if playoff_series and len(rows) == 1:
        w = min(max(config.MC_H2H_PLAYOFF_SINGLE_BLEND, 0.0), 0.55)
    else:
        w = min(max(blend, 0.0), 0.5)
    return (1 - w) * lam_home + w * avg_h, (1 - w) * lam_away + w * avg_a
