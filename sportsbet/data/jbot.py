"""
JBot 運動數據 API — 台灣運彩歷史賠率（開盤 / 收盤時間軸）。

文件：https://sportsbot.tech/api/sportslottery/
"""
from __future__ import annotations

import logging
import time
from datetime import date, datetime, timezone
from typing import Any, Literal

import pandas as pd
import requests

from sportsbet import config
from sportsbet.data.sportslottery import STANDARD_ODDS_COLUMNS
from sportsbet.data.team_names import normalize_matchup

logger = logging.getLogger(__name__)

JBotMode = Literal["open", "close", "both", "all"]
OddsPhase = Literal["open", "close", "update"]

# JBot sport 代碼 → 內部 sport
JBOT_TO_SPORT: dict[str, str] = {
    "BKB": "nba",
    "NBA": "nba",
    "BSB": "mlb",
    "MLB": "mlb",
}


class JBotClient:
    """JBot 歷史賠率 API。"""

    API_URL = "https://api.sportsbot.tech/v2/odds"
    MIN_INTERVAL_SEC = 5.0

    def __init__(self, token: str | None = None):
        self.token = token or config.JBOT_TOKEN
        self._last_request_at: float = 0.0
        self.session = requests.Session()

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self.MIN_INTERVAL_SEC:
            time.sleep(self.MIN_INTERVAL_SEC - elapsed)
        self._last_request_at = time.monotonic()

    def _headers(self) -> dict[str, str]:
        if not self.token:
            logger.warning("未設定 JBOT_TOKEN，JBot API 請求可能失敗")
        return {"X-JBot-Token": self.token}

    def fetch_raw(
        self,
        sport_code: str,
        match_date: str | date,
        mode: JBotMode = "both",
    ) -> dict[str, Any]:
        """GET /v2/odds 原始 JSON。"""
        if isinstance(match_date, date):
            match_date = match_date.isoformat()
        self._throttle()
        params = {"sport": sport_code, "date": match_date, "mode": mode}
        resp = self.session.get(
            self.API_URL,
            headers=self._headers(),
            params=params,
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    def _infer_phase(index: int, total: int, mode: str) -> OddsPhase:
        if mode == "open":
            return "open"
        if mode == "close":
            return "close"
        if total == 1:
            return "close"
        if index == 0:
            return "open"
        if index == total - 1:
            return "close"
        return "update"

    def _expand_market_block(
        self,
        *,
        sport: str,
        event_id: str,
        league: str,
        home: str,
        away: str,
        match_dt: str,
        match_date: str,
        block: dict[str, Any],
        odds_phase: OddsPhase,
        scrape_time: str,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        home_en, away_en = normalize_matchup(home, away, sport)

        def _add(market: str, selection: str, odds: float, handicap: float | None, min_parlay: int) -> None:
            if odds <= 1.0:
                return
            rows.append(
                {
                    "source": "jbot",
                    "scrape_time": scrape_time,
                    "event_id": event_id,
                    "sport": sport,
                    "league": league,
                    "match_datetime": match_dt,
                    "match_date": match_date,
                    "home_team": home_en,
                    "away_team": away_en,
                    "market": market,
                    "selection": selection,
                    "handicap": handicap,
                    "odds": odds,
                    "min_parlay": min_parlay,
                    "odds_phase": odds_phase,
                }
            )

        normal = block.get("normal") or {}
        if normal:
            s = int(normal.get("s", 1))
            if "h" in normal:
                _add("moneyline", "home", float(normal["h"]), None, s)
            if "a" in normal:
                _add("moneyline", "away", float(normal["a"]), None, s)

        for hcap_str, hdata in (block.get("handi") or {}).items():
            if not isinstance(hdata, dict):
                continue
            try:
                line = float(hcap_str)
            except ValueError:
                line = None
            s = int(hdata.get("s", 2))
            if "h" in hdata:
                _add("spread", "home", float(hdata["h"]), line, s)
            if "a" in hdata:
                _add("spread", "away", float(hdata["a"]), -line if line is not None else None, s)

        for total_str, tdata in (block.get("total") or {}).items():
            if not isinstance(tdata, dict):
                continue
            try:
                line = float(total_str)
            except ValueError:
                line = None
            s = int(tdata.get("s", 2))
            if "o" in tdata:
                _add("total", "over", float(tdata["o"]), line, s)
            if "u" in tdata:
                _add("total", "under", float(tdata["u"]), line, s)

        return rows

    def parse_response(
        self,
        payload: dict[str, Any],
        sport: str,
        mode: str = "both",
    ) -> pd.DataFrame:
        """將 JBot JSON 轉為標準賠率 DataFrame。"""
        if payload.get("status") != "OK":
            logger.error("JBot 回應異常: %s", payload.get("status"))
            return pd.DataFrame(columns=STANDARD_ODDS_COLUMNS)

        rows: list[dict[str, Any]] = []
        for game in payload.get("data") or []:
            event_id = str(game.get("id", ""))
            home = str(game.get("home", ""))
            away = str(game.get("away", ""))
            league = str(game.get("league", ""))
            match_dt = str(game.get("time", ""))
            match_date = match_dt[:10] if match_dt else ""
            odds_list = game.get("odds") or []

            for i, snap in enumerate(odds_list):
                phase = self._infer_phase(i, len(odds_list), mode)
                update_time = str(snap.get("update", match_dt))
                rows.extend(
                    self._expand_market_block(
                        sport=sport,
                        event_id=event_id,
                        league=league,
                        home=home,
                        away=away,
                        match_dt=match_dt,
                        match_date=match_date,
                        block=snap,
                        odds_phase=phase,
                        scrape_time=update_time or datetime.now(timezone.utc).isoformat(),
                    )
                )

        if not rows:
            return pd.DataFrame(columns=STANDARD_ODDS_COLUMNS)
        return pd.DataFrame(rows)

    def fetch_odds(
        self,
        sport: str,
        match_date: str | date,
        mode: JBotMode = "both",
    ) -> pd.DataFrame:
        """依內部 sport (nba/mlb) 抓取並解析賠率。"""
        code = config.JBOT_SPORT_CODES.get(sport, "")
        if not code:
            raise ValueError(f"未定義 JBOT sport code: {sport}")

        payload = self.fetch_raw(code, match_date, mode)
        return self.parse_response(payload, sport=sport, mode=mode)

    def fetch_date_range(
        self,
        sport: str,
        start: str | date,
        end: str | date,
        mode: JBotMode = "both",
    ) -> pd.DataFrame:
        """抓取日期區間（含端點），自動節流。"""
        if isinstance(start, str):
            start_d = date.fromisoformat(start)
        else:
            start_d = start
        if isinstance(end, str):
            end_d = date.fromisoformat(end)
        else:
            end_d = end

        frames: list[pd.DataFrame] = []
        cur = start_d
        while cur <= end_d:
            try:
                df = self.fetch_odds(sport, cur, mode)
                if not df.empty:
                    frames.append(df)
            except requests.HTTPError as exc:
                logger.warning("JBot %s %s 失敗: %s", sport, cur, exc)
            cur = date.fromordinal(cur.toordinal() + 1)

        if not frames:
            return pd.DataFrame(columns=STANDARD_ODDS_COLUMNS)
        return pd.concat(frames, ignore_index=True)
