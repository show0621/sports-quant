"""
台灣運彩賠率抓取（Facade）。

整合：
- `SportLotteryClient` — 運彩官方 Blob（Live/Register On.json）
- `JBotClient` — 歷史開盤/收盤時間軸

對外仍稱 WandaScraper 以相容既有腳本；實際資料來源見 `source` 欄位。
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Literal

import pandas as pd

from sportsbet import config
from sportsbet.data.jbot import JBotClient, JBotMode
from sportsbet.data.sportslottery import STANDARD_ODDS_COLUMNS, SportLotteryClient
from sportsbet.data.storage import save_odds

logger = logging.getLogger(__name__)

Sport = Literal["nba", "mlb"]


class WandaScraper:
    """運彩賠率 Facade（即時 Blob + 歷史 JBot）。"""

    def __init__(
        self,
        *,
        blob_base: str | None = None,
        jbot_token: str | None = None,
    ):
        self.lottery = SportLotteryClient(blob_base)
        self.jbot = JBotClient(jbot_token)
        self._sports: set[str] = {"nba", "mlb"}

    def fetch_live(self, sport: Sport | None = None) -> pd.DataFrame:
        sports = {sport} if sport else self._sports
        return self.lottery.fetch_live(sports=sports)

    def fetch_register(self, sport: Sport | None = None) -> pd.DataFrame:
        sports = {sport} if sport else self._sports
        return self.lottery.fetch_register(sports=sports)

    def fetch_current(self, sport: Sport | None = None) -> pd.DataFrame:
        """Live + Register 合併。"""
        sports = {sport} if sport else self._sports
        return self.lottery.fetch_all(sports=sports)

    def fetch_historical(
        self,
        sport: Sport,
        match_date: str | date,
        mode: JBotMode = "both",
    ) -> pd.DataFrame:
        return self.jbot.fetch_odds(sport, match_date, mode)

    def fetch_historical_range(
        self,
        sport: Sport,
        start: str | date,
        end: str | date,
        mode: JBotMode = "both",
    ) -> pd.DataFrame:
        return self.jbot.fetch_date_range(sport, start, end, mode)

    def scrape_and_save(
        self,
        sport: Sport = "nba",
        *,
        use_jbot: bool = False,
        days_back: int = 7,
        jbot_mode: JBotMode = "close",
    ) -> pd.DataFrame:
        """
        抓取並存檔。

        - use_jbot=False：僅 Blob 即時/受注（預設）
        - use_jbot=True：另含近 N 日 JBot 歷史（需 JBOT_TOKEN）
        """
        frames: list[pd.DataFrame] = []
        current = self.fetch_current(sport)
        if not current.empty:
            frames.append(current)

        if use_jbot and config.JBOT_TOKEN:
            end = date.today()
            start = end - timedelta(days=days_back)
            try:
                hist = self.fetch_historical_range(sport, start, end, jbot_mode)
                if not hist.empty:
                    frames.append(hist)
            except Exception as exc:
                logger.warning("JBot 歷史抓取失敗: %s", exc)
        elif use_jbot:
            logger.warning("未設定 JBOT_TOKEN，略過 JBot 歷史")

        if not frames:
            logger.warning("未取得任何賠率")
            return pd.DataFrame(columns=STANDARD_ODDS_COLUMNS)

        df = pd.concat(frames, ignore_index=True)
        source_tag = "wanda_merged"
        path = save_odds(df, source=source_tag)
        logger.info("已儲存 %d 筆賠率至 %s", len(df), path)
        return df

    def scrape_history_page(self, path: str = "", sport: str = "nba") -> pd.DataFrame:
        """
        相容舊介面：path 未使用，改抓 Blob。

        path 保留參數僅為向後相容。
        """
        _ = path
        return self.fetch_current(sport)  # type: ignore[arg-type]

    def load_sample_format(self) -> pd.DataFrame:
        """回傳標準 schema 範例（離線開發）。"""
        return pd.DataFrame(
            [
                {
                    "source": "sample",
                    "scrape_time": "2025-10-01T00:00:00+00:00",
                    "event_id": "demo-1",
                    "sport": "nba",
                    "league": "NBA",
                    "match_datetime": "2025-10-02T00:00:00+00:00",
                    "match_date": "2025-10-02",
                    "home_team": "Los Angeles Lakers",
                    "away_team": "Boston Celtics",
                    "market": "moneyline",
                    "selection": "home",
                    "handicap": None,
                    "odds": 1.75,
                    "min_parlay": 1,
                    "odds_phase": "close",
                },
                {
                    "source": "sample",
                    "scrape_time": "2025-10-01T00:00:00+00:00",
                    "event_id": "demo-1",
                    "sport": "nba",
                    "league": "NBA",
                    "match_datetime": "2025-10-02T00:00:00+00:00",
                    "match_date": "2025-10-02",
                    "home_team": "Los Angeles Lakers",
                    "away_team": "Boston Celtics",
                    "market": "moneyline",
                    "selection": "away",
                    "handicap": None,
                    "odds": 1.75,
                    "min_parlay": 2,
                    "odds_phase": "close",
                },
            ]
        )
