"""資料獲取層：抽象介面與 MOCK 產生器，供後續串接 nba_api / statsapi。"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date, datetime, timedelta
from typing import Literal

import numpy as np
import pandas as pd

from sportsbet.data.database import Sport, SportsDatabase

SportLit = Literal["nba", "mlb"]

# NBA / MLB 範例隊名
NBA_TEAMS = [
    "Lakers", "Celtics", "Warriors", "Nuggets", "Bucks", "Suns", "Heat", "Knicks",
    "Mavericks", "Clippers", "76ers", "Thunder",
]
MLB_TEAMS = [
    "Yankees", "Dodgers", "Astros", "Braves", "Orioles", "Rangers", "Phillies",
    "Padres", "Mariners", "Twins", "Rays", "Guardians",
]


class DataIngestionProvider(ABC):
    """預留 API 串接介面。"""

    @abstractmethod
    def fetch_daily_schedule(self, sport: SportLit, match_date: str | None = None) -> pd.DataFrame:
        """取得指定日期賽程。"""

    @abstractmethod
    def fetch_historical_stats(self, sport: SportLit, season: str | int | None = None) -> pd.DataFrame:
        """取得球隊賽季統計（得分/失分、近況等）。"""

    @abstractmethod
    def fetch_odds(self, sport: SportLit, match_date: str | None = None) -> pd.DataFrame:
        """取得莊家開盤賠率。"""


class MockDataProvider(DataIngestionProvider):
    """模擬數據產生器，寫入 SQLite 並回傳 DataFrame。"""

    def __init__(self, db: SportsDatabase | None = None, seed: int = 42):
        self.db = db or SportsDatabase()
        self.rng = np.random.default_rng(seed)

    def fetch_daily_schedule(self, sport: SportLit, match_date: str | None = None) -> pd.DataFrame:
        d = match_date or date.today().isoformat()
        teams = NBA_TEAMS if sport == "nba" else MLB_TEAMS
        n_games = 6 if sport == "nba" else 8
        shuffled = self.rng.permutation(teams)[: n_games * 2]
        rows = []
        for i in range(0, len(shuffled), 2):
            home, away = shuffled[i], shuffled[i + 1]
            gid = self.db.upsert_game(sport, d, home, away, match_datetime=f"{d}T19:00:00")
            rows.append(
                {
                    "game_id": gid,
                    "sport": sport,
                    "match_date": d,
                    "home_team": home,
                    "away_team": away,
                    "status": "scheduled",
                }
            )
        return pd.DataFrame(rows)

    def fetch_historical_stats(self, sport: SportLit, season: str | int | None = None) -> pd.DataFrame:
        season = str(season or date.today().year)
        teams = NBA_TEAMS if sport == "nba" else MLB_TEAMS
        if sport == "nba":
            rs_mu, ra_mu = 112.0, 111.0
        else:
            rs_mu, ra_mu = 4.6, 4.5

        rows = []
        for team in teams:
            rs = float(self.rng.normal(rs_mu, 4 if sport == "nba" else 0.4))
            ra = float(self.rng.normal(ra_mu, 4 if sport == "nba" else 0.4))
            rs, ra = max(rs, 80 if sport == "nba" else 3.0), max(ra, 80 if sport == "nba" else 3.0)
            win_pct = rs / (rs + ra)
            recent = float(np.clip(self.rng.normal(win_pct, 0.08), 0.2, 0.8))
            self.db.upsert_team_stats(
                sport, team, rs, ra, season=season, games=82 if sport == "nba" else 162,
                win_pct=win_pct, recent_win_pct=recent,
            )
            rows.append(
                {
                    "sport": sport,
                    "team": team,
                    "season": season,
                    "rs_per_game": rs,
                    "ra_per_game": ra,
                    "win_pct": win_pct,
                    "recent_win_pct": recent,
                }
            )
        return pd.DataFrame(rows)

    def fetch_odds(self, sport: SportLit, match_date: str | None = None) -> pd.DataFrame:
        d = match_date or date.today().isoformat()
        games = self.db.get_games(sport, d)
        if games.empty:
            games = self.fetch_daily_schedule(sport, d)

        rows = []
        for _, g in games.iterrows():
            gid = int(g["id"] if "id" in g else g["game_id"])
            home_odds = round(float(self.rng.uniform(1.55, 2.15)), 2)
            away_odds = round(float(self.rng.uniform(1.55, 2.15)), 2)
            total_line = round(
                float(self.rng.uniform(210, 235) if sport == "nba" else self.rng.uniform(7.5, 9.5)),
                1,
            )
            over_odds = round(float(self.rng.uniform(1.75, 1.95)), 2)

            for market, sel, odds, handicap in [
                ("moneyline", "home", home_odds, None),
                ("moneyline", "away", away_odds, None),
                ("total", "over", over_odds, total_line),
                ("total", "under", over_odds, total_line),
            ]:
                self.db.insert_odds(gid, market, sel, odds, handicap=handicap)
                rows.append(
                    {
                        "game_id": gid,
                        "match_date": d,
                        "home_team": g["home_team"],
                        "away_team": g["away_team"],
                        "market": market,
                        "selection": sel,
                        "handicap": handicap,
                        "odds": odds,
                    }
                )
        return pd.DataFrame(rows)

    def seed_historical_backtest(
        self,
        sport: SportLit,
        *,
        days: int = 60,
        season: str | int | None = None,
    ) -> pd.DataFrame:
        """產生含賽果的歷史資料，供 Brier / 資金回測。"""
        from sportsbet.models.analytics_engine import AnalyticsEngine
        from sportsbet.risk.ev import RiskManager

        self.fetch_historical_stats(sport, season)
        stats = self.db.get_team_stats(sport).set_index("team")
        engine = AnalyticsEngine(sport)
        risk = RiskManager()
        start = date.today() - timedelta(days=days)
        all_rows = []

        for offset in range(days):
            d = (start + timedelta(days=offset)).isoformat()
            sched = self.fetch_daily_schedule(sport, d)
            odds_df = self.fetch_odds(sport, d)

            for _, g in sched.iterrows():
                gid = int(g["game_id"])
                ht, at = g["home_team"], g["away_team"]
                if ht not in stats.index or at not in stats.index:
                    continue
                h, a = stats.loc[ht], stats.loc[at]
                pred = engine.predict_matchup(
                    h["rs_per_game"], h["ra_per_game"], a["rs_per_game"], a["ra_per_game"],
                    home_recent_win_pct=h.get("recent_win_pct"),
                    away_recent_win_pct=a.get("recent_win_pct"),
                )
                lam_h, lam_a = engine.expected_score_lambdas(
                    h["rs_per_game"], h["ra_per_game"], a["rs_per_game"], a["ra_per_game"],
                )
                hs = int(max(0, self.rng.poisson(lam_h)))
                aws = int(max(0, self.rng.poisson(lam_a)))
                self.db.upsert_game(
                    sport, d, ht, at, home_score=hs, away_score=aws, status="final",
                )

                game_odds = odds_df[odds_df["game_id"] == gid]
                for _, o in game_odds.iterrows():
                    if o["market"] == "moneyline":
                        prob = pred.home_win_prob if o["selection"] == "home" else pred.away_win_prob
                    else:
                        line = float(o["handicap"])
                        prob = engine.prob_total_over(line, lam_h, lam_a)
                        if o["selection"] == "under":
                            prob = 1.0 - prob
                    sig = risk.evaluate(prob, float(o["odds"]))
                    self.db.insert_prediction(
                        gid, o["market"], prob, selection=o["selection"],
                        ev=sig.ev, kelly_fraction=sig.kelly_fraction,
                        stake_fraction=sig.recommended_stake_fraction,
                    )
                    all_rows.append(
                        {
                            "game_id": gid,
                            "match_date": d,
                            "market": o["market"],
                            "selection": o["selection"],
                            "model_prob": prob,
                            "odds": o["odds"],
                            "won": None,
                        }
                    )

        return self.db.get_backtest_frame(sport)


class ApiSportsIngestionAdapter(DataIngestionProvider):
    """
    橋接既有 ApiSportsClient（未來可擴充實作）。
    目前 fetch_* 仍委派給 Mock，避免無 API key 時失敗。
    """

    def __init__(self, fallback: DataIngestionProvider | None = None):
        self._fallback = fallback or MockDataProvider()

    def fetch_daily_schedule(self, sport: SportLit, match_date: str | None = None) -> pd.DataFrame:
        return self._fallback.fetch_daily_schedule(sport, match_date)

    def fetch_historical_stats(self, sport: SportLit, season: str | int | None = None) -> pd.DataFrame:
        return self._fallback.fetch_historical_stats(sport, season)

    def fetch_odds(self, sport: SportLit, match_date: str | None = None) -> pd.DataFrame:
        return self._fallback.fetch_odds(sport, match_date)
