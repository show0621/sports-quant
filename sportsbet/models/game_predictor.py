"""整合畢達哥拉斯 + 貝氏 + EV 的單場預測器。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import pandas as pd

from sportsbet import analytics, config


@dataclass
class PredictionResult:
    sport: str
    home_team: str
    away_team: str
    home_win_prob: float
    away_win_prob: float
    home_signal: analytics.BetSignal | None
    away_signal: analytics.BetSignal | None
    home_pyth: float
    away_pyth: float


class GamePredictor:
    def __init__(self, sport: Literal["nba", "mlb"]):
        self.sport = sport

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
        home_odds: float | None = None,
        away_odds: float | None = None,
    ) -> PredictionResult:
        home_pyth = analytics.team_win_pct(self.sport, home_rs, home_ra, home_games)
        away_pyth = analytics.team_win_pct(self.sport, away_rs, away_ra, away_games)

        p_home, p_away = analytics.matchup_win_prob(home_pyth, away_pyth)

        if home_recent_win_pct is not None:
            p_home = analytics.apply_bayesian_adjustments(
                p_home,
                is_home=True,
                recent_win_pct=home_recent_win_pct,
                season_win_pct=home_pyth,
                key_player_out=home_injury,
            )
        if away_recent_win_pct is not None:
            p_away = analytics.apply_bayesian_adjustments(
                p_away,
                is_home=False,
                recent_win_pct=away_recent_win_pct,
                season_win_pct=away_pyth,
                key_player_out=away_injury,
            )

        # 重新正規化
        total = p_home + p_away
        p_home, p_away = p_home / total, p_away / total

        home_sig = analytics.evaluate_bet(p_home, home_odds) if home_odds else None
        away_sig = analytics.evaluate_bet(p_away, away_odds) if away_odds else None

        return PredictionResult(
            sport=self.sport,
            home_team="home",
            away_team="away",
            home_win_prob=p_home,
            away_win_prob=p_away,
            home_signal=home_sig,
            away_signal=away_sig,
            home_pyth=home_pyth,
            away_pyth=away_pyth,
        )

    def scan_dataframe(
        self,
        team_stats: pd.DataFrame,
        odds_df: pd.DataFrame,
    ) -> pd.DataFrame:
        """
        批次掃描：team_stats 需含 team, rs_per_game, ra_per_game, win_pct
        odds_df 需含 home_team, away_team, selection, odds, min_parlay
        """
        stats = team_stats.set_index("team") if "team" in team_stats.columns else team_stats
        results = []

        for _, row in odds_df.iterrows():
            ht, at = row.get("home_team"), row.get("away_team")
            if ht not in stats.index or at not in stats.index:
                continue
            h = stats.loc[ht]
            a = stats.loc[at]
            pred = self.predict_matchup(
                h["rs_per_game"],
                h["ra_per_game"],
                a["rs_per_game"],
                a["ra_per_game"],
                home_games=int(h.get("games", 0)),
                away_games=int(a.get("games", 0)),
                home_recent_win_pct=h.get("win_pct"),
                away_recent_win_pct=a.get("win_pct"),
                home_odds=row["odds"] if row.get("selection") == "home" else None,
                away_odds=row["odds"] if row.get("selection") == "away" else None,
            )
            sel = row.get("selection", "home")
            prob = pred.home_win_prob if sel == "home" else pred.away_win_prob
            sig = pred.home_signal if sel == "home" else pred.away_signal
            results.append(
                {
                    "home_team": ht,
                    "away_team": at,
                    "selection": sel,
                    "model_prob": prob,
                    "odds": row["odds"],
                    "ev": sig.ev if sig else None,
                    "kelly": sig.recommended_stake_fraction if sig else None,
                    "signal": sig.is_positive_ev if sig else False,
                    "min_parlay": row.get("min_parlay", 1),
                }
            )
        return pd.DataFrame(results)
