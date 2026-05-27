"""資料獲取層：抽象介面與 MOCK 產生器，供後續串接 nba_api / statsapi。"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import date, datetime, timedelta
from typing import Any, Literal

import numpy as np
import pandas as pd

from sportsbet.data.database import Sport, SportsDatabase

logger = logging.getLogger(__name__)

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
            from sportsbet.data.team_logos import espn_logo_url

            hour = 18 + (i // 2) % 5
            gid = self.db.upsert_game(
                sport, d, home, away,
                match_datetime=f"{d}T{hour:02d}:30:00+00:00",
                home_logo_url=espn_logo_url(home, sport),
                away_logo_url=espn_logo_url(away, sport),
            )
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
        days: int | None = None,
        season: str | int | None = None,
    ) -> pd.DataFrame:
        """產生含賽果的歷史資料，供 Brier / 資金回測（預設 3 年）。"""
        from sportsbet import config
        from sportsbet.models.analytics_engine import AnalyticsEngine
        from sportsbet.risk.ev import RiskManager

        days = days if days is not None else config.BACKTEST_DAYS
        self.fetch_historical_stats(sport, season)
        stats = self.db.get_team_stats(sport).set_index("team")
        engine = AnalyticsEngine(sport)
        risk = RiskManager()
        start = date.today() - timedelta(days=days)
        all_rows = []

        for offset in range(days):
            days_ago = days - offset
            if days_ago > 120 and offset % 2 != 0:
                continue
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

        from sportsbet.services.prediction_service import PredictionService

        PredictionService(self.db).run_backtest_reconcile(sport)
        return self.db.get_backtest_frame(sport)


class ApiSportsIngestionAdapter(DataIngestionProvider):
    """API-Sports 賽程/統計 + 台灣運彩 Blob 賠率。"""

    def __init__(
        self,
        db: SportsDatabase | None = None,
        client: Any | None = None,
    ):
        from sportsbet.data.api_sports import ApiSportsClient, infer_season

        self.db = db or SportsDatabase()
        self.client = client or ApiSportsClient()
        self._infer_season = infer_season

    def fetch_daily_schedule(self, sport: SportLit, match_date: str | None = None) -> pd.DataFrame:
        d = match_date or date.today().isoformat()
        if not self.client.is_configured:
            raise RuntimeError("API_SPORTS_KEY 未設定，API-only 模式下不可抓取賽程。")
        return self.client.sync_daily_to_database(self.db, sport, d)

    def fetch_historical_stats(self, sport: SportLit, season: str | int | None = None) -> pd.DataFrame:
        if not self.client.is_configured:
            raise RuntimeError("API_SPORTS_KEY 未設定，API-only 模式下不可抓取歷史統計。")
        season_int = int(season) if season else self._infer_season(sport)
        self.client.sync_team_logos(self.db, sport, season_int)
        stats = self.client.sync_to_database(self.db, sport, season_int)
        if stats.empty:
            logger.warning("API-Sports 未回傳球隊統計，賽季=%s", season_int)
        return stats

    def fetch_odds(self, sport: SportLit, match_date: str | None = None) -> pd.DataFrame:
        d = match_date or date.today().isoformat()
        rows = self._fetch_sportslottery_odds(sport, d)
        if not rows.empty:
            return rows
        logger.warning("運彩 Blob 無賠率，API-only 模式不再使用 MOCK 補值")
        return pd.DataFrame()

    def _fetch_sportslottery_odds(self, sport: SportLit, match_date: str) -> pd.DataFrame:
        from sportsbet.data.sportslottery import SportLotteryClient
        from sportsbet.data.team_names import normalize_matchup

        try:
            client = SportLotteryClient()
            odds_df = client.fetch_all(sports={sport})
        except Exception as exc:
            logger.warning("運彩 Blob 抓取失敗: %s", exc)
            return pd.DataFrame()

        if odds_df.empty:
            return odds_df

        odds_df = odds_df.copy()
        odds_df[["home_team", "away_team"]] = odds_df.apply(
            lambda r: pd.Series(normalize_matchup(r["home_team"], r["away_team"], sport)),
            axis=1,
        )
        if "match_date" in odds_df.columns:
            odds_df = odds_df[odds_df["match_date"].astype(str).str[:10] == d]

        games = self.db.get_games(sport, d)
        if games.empty:
            return pd.DataFrame()

        inserted = []
        for _, o in odds_df.iterrows():
            match = games[
                (games["home_team"] == o["home_team"]) & (games["away_team"] == o["away_team"])
            ]
            if match.empty:
                continue
            gid = int(match.iloc[0]["id"])
            self.db.insert_odds(
                gid,
                str(o.get("market", "moneyline")),
                str(o.get("selection", "home")),
                float(o["odds"]),
                handicap=float(o["handicap"]) if pd.notna(o.get("handicap")) else None,
                bookmaker="sportslottery",
            )
            inserted.append({**o.to_dict(), "game_id": gid})

        return pd.DataFrame(inserted)
