"""分析引擎：畢達哥拉斯、貝氏修正、大小分卜瓦松（OOP 封裝）。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sportsbet import analytics, config
from sportsbet.models.totals import expected_lambdas, prob_total_over, prob_total_under


@dataclass
class MatchupPrediction:
    sport: str
    home_win_prob: float
    away_win_prob: float
    home_pyth: float
    away_pyth: float
    lambda_home: float
    lambda_away: float


class AnalyticsEngine:
    """獨立分析類別，處理所有機率運算。"""

    def __init__(
        self,
        sport: Literal["nba", "mlb"],
        *,
        pyth_exponent: float | None = None,
        home_advantage: float | None = None,
        recent_weight: float | None = None,
    ):
        self.sport = sport
        self.pyth_exponent = pyth_exponent or (
            config.PYTH_EXPONENT_NBA if sport == "nba" else config.PYTH_EXPONENT_MLB
        )
        self.home_advantage = home_advantage if home_advantage is not None else config.BAYES_HOME_ADVANTAGE
        self.recent_weight = recent_weight if recent_weight is not None else config.BAYES_RECENT_WEIGHT

    def pythagorean_win_pct(self, runs_scored: float, runs_allowed: float) -> float:
        return analytics.pythagorean_win_pct(runs_scored, runs_allowed, self.pyth_exponent)

    def team_win_pct(self, runs_scored: float, runs_allowed: float, games: int = 0) -> float:
        if self.sport == "mlb" and config.USE_DYNAMIC_MLB_EXPONENT and games > 0:
            exp = analytics.mlb_dynamic_exponent(runs_scored, runs_allowed, games)
            return analytics.pythagorean_win_pct(runs_scored, runs_allowed, exp)
        return self.pythagorean_win_pct(runs_scored, runs_allowed)

    def bayesian_posterior(
        self,
        prior: float,
        *,
        is_home: bool = False,
        recent_win_pct: float | None = None,
        season_win_pct: float | None = None,
        key_player_out: bool = False,
        recent_weight: float | None = None,
    ) -> float:
        return analytics.apply_bayesian_adjustments(
            prior,
            is_home=is_home,
            recent_win_pct=recent_win_pct,
            season_win_pct=season_win_pct,
            key_player_out=key_player_out,
            recent_weight=recent_weight,
        )

    def predict_matchup(
        self,
        home_rs: float,
        home_ra: float,
        away_rs: float,
        away_ra: float,
        *,
        home_games: int = 0,
        away_games: int = 0,
        home_recent_win_pct: float | None = None,
        away_recent_win_pct: float | None = None,
        home_injury: bool = False,
        away_injury: bool = False,
    ) -> MatchupPrediction:
        home_pyth = self.team_win_pct(home_rs, home_ra, home_games)
        away_pyth = self.team_win_pct(away_rs, away_ra, away_games)
        p_home, p_away = analytics.matchup_win_prob(home_pyth, away_pyth, self.home_advantage)

        if home_recent_win_pct is not None:
            p_home = self.bayesian_posterior(
                p_home,
                is_home=True,
                recent_win_pct=home_recent_win_pct,
                season_win_pct=home_pyth,
                key_player_out=home_injury,
            )
        if away_recent_win_pct is not None:
            p_away = self.bayesian_posterior(
                p_away,
                recent_win_pct=away_recent_win_pct,
                season_win_pct=away_pyth,
                key_player_out=away_injury,
            )

        total = p_home + p_away
        p_home, p_away = p_home / total, p_away / total
        lam_h, lam_a = self.expected_score_lambdas(home_rs, home_ra, away_rs, away_ra)

        return MatchupPrediction(
            sport=self.sport,
            home_win_prob=p_home,
            away_win_prob=p_away,
            home_pyth=home_pyth,
            away_pyth=away_pyth,
            lambda_home=lam_h,
            lambda_away=lam_a,
        )

    def expected_score_lambdas(
        self,
        home_rs: float,
        home_ra: float,
        away_rs: float,
        away_ra: float,
    ) -> tuple[float, float]:
        ha = 3.0 if self.sport == "nba" else 0.15
        return expected_lambdas(home_rs, home_ra, away_rs, away_ra, home_advantage_pts=ha)

    def prob_total_over(self, line: float, lambda_home: float, lambda_away: float) -> float:
        return prob_total_over(line, lambda_home, lambda_away)

    def prob_total_under(self, line: float, lambda_home: float, lambda_away: float) -> float:
        return prob_total_under(line, lambda_home, lambda_away)
