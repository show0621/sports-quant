"""每日開盤賠率掃描，比對模型 EV。"""
from __future__ import annotations

import logging
from datetime import date

import pandas as pd

from sportsbet.data.storage import load_team_stats
from sportsbet.data.wanda_scraper import WandaScraper
from sportsbet.models.game_predictor import GamePredictor

logger = logging.getLogger(__name__)


class DailyScanner:
    def __init__(self, sport: str = "nba"):
        self.sport = sport
        self.predictor = GamePredictor(sport)  # type: ignore[arg-type]
        self.scraper = WandaScraper()

    def run(self, wanda_path: str = "", use_live_scrape: bool = True) -> pd.DataFrame:
        team_stats = load_team_stats(self.sport)
        if team_stats.empty:
            logger.error("無球隊統計，請先執行 fetch 腳本抓取 API 資料")
            return pd.DataFrame()

        if use_live_scrape and wanda_path:
            odds = self.scraper.scrape_history_page(wanda_path, self.sport)
        else:
            odds = self.scraper.load_sample_format()

        signals = self.predictor.scan_dataframe(team_stats, odds)
        if not signals.empty:
            signals["scan_date"] = date.today().isoformat()
            positive = signals[signals["signal"] == True]  # noqa: E712
            logger.info("掃描完成：%d 筆賠率，%d 筆正 EV", len(signals), len(positive))
        return signals

    def positive_ev_only(self, **kwargs) -> pd.DataFrame:
        df = self.run(**kwargs)
        return df[df["signal"] == True] if not df.empty else df  # noqa: E712
