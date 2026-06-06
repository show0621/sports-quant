"""
集成勝率引擎：Log5 + Beta-Bayesian + 馬可夫近況 + 情境修正。

專業量化流程：
1. 畢達哥拉斯/Log5 先驗（實力基線）
2. Beta-Binomial 後驗（近 N 場勝率，共軛貝氏）
3. 馬可夫狀態對戰（Hot/Cold 轉移）
4. 休息/背靠背/H2H/主客場 split 似然比
5. 加權集成 → 最終 home_win_prob
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from sportsbet import analytics, config
from sportsbet.data.context_features import MatchContext, build_match_context
from sportsbet.data.database import SportsDatabase
from sportsbet.models.analytics_engine import AnalyticsEngine
from sportsbet.models.markov_form import markov_matchup_win_prob

Sport = Literal["nba", "mlb"]


@dataclass
class ProbabilityBreakdown:
    log5_home: float
    log5_away: float
    bayesian_home: float
    bayesian_away: float
    beta_home: float
    beta_away: float
    markov_home: float
    markov_away: float
    context_lr_home: float
    context_lr_away: float
    final_home: float
    final_away: float
    context: MatchContext | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "log5_home": self.log5_home,
            "bayesian_home": self.bayesian_home,
            "beta_home": self.beta_home,
            "markov_home": self.markov_home,
            "final_home": self.final_home,
            "home_markov_state": self.context.home_markov_state if self.context else None,
            "away_markov_state": self.context.away_markov_state if self.context else None,
            "home_rest_days": self.context.home_rest_days if self.context else None,
            "away_rest_days": self.context.away_rest_days if self.context else None,
        }


def beta_binomial_win_pct(
    wins: float,
    n: int,
    prior_mean: float,
    *,
    prior_strength: float | None = None,
) -> float:
    """Beta-Binomial 共軛：先驗 Beta(α,β) 由 prior_mean 與 prior_strength 決定。"""
    strength = prior_strength or config.BETA_PRIOR_STRENGTH
    prior_mean = min(max(prior_mean, 0.05), 0.95)
    alpha0 = prior_mean * strength
    beta0 = (1.0 - prior_mean) * strength
    alpha = alpha0 + wins
    beta = beta0 + max(0, n - wins)
    return alpha / (alpha + beta)


def _context_likelihood_ratio(ctx: MatchContext, *, is_home: bool) -> float:
    lr = 1.0
    if is_home:
        if ctx.home_back_to_back:
            lr *= 1.0 - config.CONTEXT_B2B_PENALTY
        if ctx.away_back_to_back:
            lr *= 1.0 + config.CONTEXT_B2B_PENALTY * 0.5
        if ctx.home_rest_days >= 3:
            lr *= 1.0 + config.CONTEXT_REST_BONUS
        lr *= 1.0 + (ctx.home_home_win_pct - 0.5) * config.CONTEXT_SPLIT_WEIGHT
        if ctx.h2h_home_win_pct is not None:
            lr *= 1.0 + (ctx.h2h_home_win_pct - 0.5) * config.CONTEXT_H2H_WEIGHT
    else:
        if ctx.away_back_to_back:
            lr *= 1.0 - config.CONTEXT_B2B_PENALTY
        if ctx.home_back_to_back:
            lr *= 1.0 + config.CONTEXT_B2B_PENALTY * 0.5
        if ctx.away_rest_days >= 3:
            lr *= 1.0 + config.CONTEXT_REST_BONUS
        lr *= 1.0 + (ctx.away_away_win_pct - 0.5) * config.CONTEXT_SPLIT_WEIGHT
    return max(0.7, min(1.35, lr))


def ensemble_matchup_probability(
    engine: AnalyticsEngine,
    sport: Sport,
    home_team: str,
    away_team: str,
    home_rs: float,
    home_ra: float,
    away_rs: float,
    away_ra: float,
    match_date: str,
    *,
    home_games: int = 0,
    away_games: int = 0,
    home_season_win_pct: float | None = None,
    away_season_win_pct: float | None = None,
    home_recent_win_pct: float | None = None,
    away_recent_win_pct: float | None = None,
    db: SportsDatabase | None = None,
    season_type: str | None = None,
    competition_note: str | None = None,
) -> ProbabilityBreakdown:
    """計算集成勝率及分解。"""
    from sportsbet.data.h2h_recent import (
        get_h2h_recent_for_matchup,
        is_playoff_series,
        playoff_ensemble_weights,
        resolve_matchup_recent_form,
    )

    home_pyth = engine.team_win_pct(home_rs, home_ra, home_games)
    away_pyth = engine.team_win_pct(away_rs, away_ra, away_games)
    h_season = home_season_win_pct if home_season_win_pct is not None else home_pyth
    a_season = away_season_win_pct if away_season_win_pct is not None else away_pyth
    team_h_recent = home_recent_win_pct if home_recent_win_pct is not None else h_season
    team_a_recent = away_recent_win_pct if away_recent_win_pct is not None else a_season

    playoff = is_playoff_series(season_type, competition_note)
    h2h_n = 0
    h2h_h = h2h_a = None
    if db is not None and playoff:
        h_recent, a_recent, _, _, h2h_n = resolve_matchup_recent_form(
            db,
            sport,
            home_team,
            away_team,
            match_date,
            team_h_recent,
            team_a_recent,
            playoff=True,
        )
        if h2h_n >= 1:
            h2h_h, h2h_a = get_h2h_recent_for_matchup(
                db, sport, home_team, away_team, match_date,
            )
    else:
        h_recent, a_recent = team_h_recent, team_a_recent

    recent_w = (
        config.PLAYOFF_H2H_BAYES_RECENT_WEIGHT
        if h2h_n >= 1 and config.PLAYOFF_USE_H2H_RECENT
        else None
    )

    log5_h, log5_a = analytics.matchup_win_prob(home_pyth, away_pyth, engine.home_advantage)

    bayes_h = engine.bayesian_posterior(
        log5_h,
        is_home=True,
        recent_win_pct=h_recent,
        season_win_pct=home_pyth,
        recent_weight=recent_w,
    )
    bayes_a = engine.bayesian_posterior(
        log5_a,
        recent_win_pct=a_recent,
        season_win_pct=away_pyth,
        recent_weight=recent_w,
    )

    if h2h_h is not None and h2h_h.games >= 1:
        beta_h = beta_binomial_win_pct(float(h2h_h.wins), h2h_h.games, home_pyth)
        beta_a = beta_binomial_win_pct(float(h2h_a.wins), h2h_a.games, away_pyth)
    else:
        n_recent = config.BAYES_RECENT_GAMES
        beta_h = beta_binomial_win_pct(h_recent * n_recent, n_recent, home_pyth)
        beta_a = beta_binomial_win_pct(a_recent * n_recent, n_recent, away_pyth)

    ctx = None
    markov_h, markov_a = log5_h, log5_a
    ctx_lr_h, ctx_lr_a = 1.0, 1.0

    if db is not None and config.USE_CONTEXT_FEATURES:
        ctx = build_match_context(db, sport, home_team, away_team, match_date)
        markov_h, markov_a = markov_matchup_win_prob(ctx, sport)
        ctx_lr_h = _context_likelihood_ratio(ctx, is_home=True)
        ctx_lr_a = _context_likelihood_ratio(ctx, is_home=False)
        if h2h_n >= 1 and ctx.h2h_home_win_pct is not None:
            extra = 1.0 + (ctx.h2h_home_win_pct - 0.5) * config.PLAYOFF_CONTEXT_H2H_EXTRA
            ctx_lr_h = max(0.7, min(1.35, ctx_lr_h * extra))
            ctx_lr_a = max(0.7, min(1.35, ctx_lr_a / extra if extra > 0 else ctx_lr_a))

    w_log5, w_bayes, w_beta, w_markov = playoff_ensemble_weights(h2h_n)
    w_sum = w_log5 + w_bayes + w_beta + w_markov
    if w_sum <= 0:
        w_sum = 1.0

    raw_h = (
        w_log5 * log5_h
        + w_bayes * bayes_h
        + w_beta * beta_h
        + w_markov * markov_h
    ) / w_sum
    raw_a = (
        w_log5 * log5_a
        + w_bayes * bayes_a
        + w_beta * beta_a
        + w_markov * markov_a
    ) / w_sum

    raw_h = analytics.bayesian_update(raw_h, ctx_lr_h)
    raw_a = analytics.bayesian_update(raw_a, ctx_lr_a)

    total = raw_h + raw_a
    final_h = raw_h / total if total > 0 else 0.5
    final_a = raw_a / total if total > 0 else 0.5
    final_h = min(max(final_h, 0.001), 0.999)
    final_a = min(max(final_a, 0.001), 0.999)

    return ProbabilityBreakdown(
        log5_home=log5_h,
        log5_away=log5_a,
        bayesian_home=bayes_h,
        bayesian_away=bayes_a,
        beta_home=beta_h,
        beta_away=beta_a,
        markov_home=markov_h,
        markov_away=markov_a,
        context_lr_home=ctx_lr_h,
        context_lr_away=ctx_lr_a,
        final_home=final_h,
        final_away=final_a,
        context=ctx,
    )
