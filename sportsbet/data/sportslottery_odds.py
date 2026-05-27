"""台灣運彩 Blob 賠率寫入（混合模式共用）。"""
from __future__ import annotations

import logging

import pandas as pd

from sportsbet.data.database import SportsDatabase

logger = logging.getLogger(__name__)

SportLit = str


class SportLotteryOddsMixin:
    """需由 DataIngestionProvider 子類設定 self.db。"""

    db: SportsDatabase

    def fetch_odds(self, sport: SportLit, match_date: str | None = None) -> pd.DataFrame:
        from datetime import date

        d = match_date or date.today().isoformat()
        rows = self._fetch_sportslottery_odds(sport, d)
        if rows.empty:
            logger.warning("運彩 Blob 無 %s 賠率（%s）", sport, d)
        return rows

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
            odds_df = odds_df[odds_df["match_date"].astype(str).str[:10] == match_date]

        games = self.db.get_games(sport, match_date)
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
