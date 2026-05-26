"""
V2 動態陣容實力評估 (Bottom-Up Analytics)。

流程：
1. 讀取預計上場名單 (projected_lineups)
2. 依 injury_reports 剔除 Out / Doubtful，Questionable 打折
3. 以 VORP (NBA) 或 WAR (MLB) 按上場時間加權 → Adjusted Team Rating
4. 與全陣容 Baseline 比較得出 injury_penalty
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import pandas as pd

from sportsbet import config
from sportsbet.data.database import SportsDatabase

Sport = Literal["nba", "mlb"]

EXCLUDE_STATUSES = set(config.INJURY_EXCLUDE_STATUSES)
DISCOUNT_MAP = config.INJURY_DISCOUNT


@dataclass
class MissingPlayerImpact:
    player_id: str
    name: str
    status: str
    injury_type: str | None
    metric_value: float
    minutes_share: float
    win_prob_penalty: float


@dataclass
class RosterRatingResult:
    sport: str
    team: str
    match_date: str
    baseline_rating: float
    adjusted_rating: float
    injury_penalty: float
    active_count: int
    excluded_players: list[MissingPlayerImpact] = field(default_factory=list)
    discounted_players: list[MissingPlayerImpact] = field(default_factory=list)

    @property
    def rating_delta(self) -> float:
        return self.adjusted_rating - self.baseline_rating


class DynamicRosterRatingEngine:
    """Bottom-Up 陣容實力引擎。"""

    def __init__(self, db: SportsDatabase | None = None):
        self.db = db or SportsDatabase()

    def _player_metric(self, sport: Sport, row: pd.Series) -> float:
        if sport == "nba":
            return float(row.get("vorp") or row.get("bpm") or 0.0)
        return float(row.get("war") or (row.get("wrc_plus", 100) - 100) / 30.0 or 0.0)

    def _minutes_weight(self, sport: Sport, row: pd.Series, total_minutes: float) -> float:
        if sport == "nba":
            m = float(row.get("expected_minutes") or 0.0)
            return m / total_minutes if total_minutes > 0 else 0.0
        inn = float(row.get("expected_innings") or 0.0)
        return inn / max(total_minutes, 1e-6)

    def _injury_status_map(self, sport: Sport, team: str, match_date: str) -> dict[str, str]:
        from sportsbet.data.team_logos import resolve_team_in_database

        inj = self.db.get_injuries(sport, match_date)
        if inj.empty:
            return {}
        resolved = resolve_team_in_database(self.db, sport, team)  # type: ignore[arg-type]
        team_inj = inj[inj["team"].isin({team, resolved})]
        if team_inj.empty:
            last = team.split()[-1].lower()
            team_inj = inj[inj["team"].str.split().str[-1].str.lower() == last]
        return dict(zip(team_inj["player_id"], team_inj["status"]))

    def compute_team_rating(
        self,
        sport: Sport,
        team: str,
        match_date: str,
    ) -> RosterRatingResult:
        lineup = self.db.get_projected_lineup(sport, team, match_date)
        players = self.db.get_players_by_team(sport, team)
        if players.empty:
            return RosterRatingResult(
                sport=sport, team=team, match_date=match_date,
                baseline_rating=0.0, adjusted_rating=0.0, injury_penalty=0.0, active_count=0,
            )

        players = players.drop_duplicates(subset=["player_id"])
        if not lineup.empty:
            players = players.merge(
                lineup[["player_id", "expected_minutes", "expected_innings", "is_starter"]],
                on="player_id",
                how="left",
            )
        else:
            players = players.head(8 if sport == "nba" else 9).copy()
            if sport == "nba":
                players["expected_minutes"] = [34, 32, 30, 28, 26, 22, 18, 15][: len(players)]
            else:
                players["expected_innings"] = [6, 1, 1, 1, 1, 0, 0, 0, 0][: len(players)]

        status_map = self._injury_status_map(sport, team, match_date)

        if sport == "nba":
            total_minutes = float(players["expected_minutes"].fillna(0).sum()) or 240.0
        else:
            total_minutes = float(players["expected_innings"].fillna(0).sum()) or 9.0

        baseline_rating = 0.0
        adjusted_rating = 0.0
        excluded: list[MissingPlayerImpact] = []
        discounted: list[MissingPlayerImpact] = []

        for _, row in players.iterrows():
            pid = row["player_id"]
            metric = self._player_metric(sport, row)
            weight = self._minutes_weight(sport, row, total_minutes)
            if weight <= 0:
                continue

            baseline_rating += metric * weight
            status = status_map.get(pid, "Available")

            if status in EXCLUDE_STATUSES:
                impact = MissingPlayerImpact(
                    player_id=pid,
                    name=str(row.get("name", pid)),
                    status=status,
                    injury_type=None,
                    metric_value=metric,
                    minutes_share=weight,
                    win_prob_penalty=metric * weight * 0.02,
                )
                excluded.append(impact)
                continue

            discount = DISCOUNT_MAP.get(status, 1.0)
            effective_metric = metric * discount
            adjusted_rating += effective_metric * weight

            if discount < 1.0:
                discounted.append(
                    MissingPlayerImpact(
                        player_id=pid,
                        name=str(row.get("name", pid)),
                        status=status,
                        injury_type=None,
                        metric_value=metric,
                        minutes_share=weight * discount,
                        win_prob_penalty=(metric - effective_metric) * weight * 0.015,
                    )
                )

        if baseline_rating <= 0:
            baseline_rating = adjusted_rating or 1.0

        injury_penalty = max(0.0, baseline_rating - adjusted_rating)
        active_count = len(players) - len(excluded)

        return RosterRatingResult(
            sport=sport,
            team=team,
            match_date=match_date,
            baseline_rating=baseline_rating,
            adjusted_rating=adjusted_rating,
            injury_penalty=injury_penalty,
            active_count=active_count,
            excluded_players=excluded,
            discounted_players=discounted,
        )

    def blend_win_probability(
        self,
        sport: Sport,
        team_rating: RosterRatingResult,
        opponent_rating: RosterRatingResult,
        *,
        team_topdown_win_pct: float,
        home_advantage: float | None = None,
    ) -> tuple[float, float]:
        """
        將 Bottom-Up 評分轉為勝率，並與 Top-Down (畢達哥拉斯) 混合。

        使用 logistic 風格差值：rating_diff → win prob
        """
        diff = team_rating.adjusted_rating - opponent_rating.adjusted_rating
        scale = 3.5 if sport == "nba" else 2.5
        roster_prob = 1.0 / (1.0 + 10 ** (-diff / scale))

        blend = config.ROSTER_RATING_BLEND
        if not config.USE_ROSTER_RATING:
            return team_topdown_win_pct, 0.0

        ha = home_advantage or config.BAYES_HOME_ADVANTAGE
        roster_prob = min(max(roster_prob + ha, 0.05), 0.95)
        mixed = (1 - blend) * team_topdown_win_pct + blend * roster_prob
        penalty = team_rating.injury_penalty * 0.01
        mixed = min(max(mixed - penalty, 0.02), 0.98)
        return mixed, roster_prob

    def matchup_with_roster(
        self,
        sport: Sport,
        home_team: str,
        away_team: str,
        match_date: str,
        home_topdown: float,
        away_topdown: float,
    ) -> dict:
        """單場雙隊陣容評估 + 混合勝率。"""
        home_rr = self.compute_team_rating(sport, home_team, match_date)
        away_rr = self.compute_team_rating(sport, away_team, match_date)
        p_home, _ = self.blend_win_probability(
            sport, home_rr, away_rr, team_topdown_win_pct=home_topdown, home_advantage=config.BAYES_HOME_ADVANTAGE,
        )
        p_away, _ = self.blend_win_probability(
            sport, away_rr, home_rr, team_topdown_win_pct=away_topdown, home_advantage=0.0,
        )
        total = p_home + p_away
        return {
            "home": home_rr,
            "away": away_rr,
            "home_win_prob": p_home / total,
            "away_win_prob": p_away / total,
        }
