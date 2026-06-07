"""
台灣運動彩券 Blob API 客戶端。

公開端點（無需登入）：
- {base}/Live/On.json   — 場中 / 即時開盤
- {base}/Register/On.json — 受注中賽事

文件參考：https://hackmd.io/@willy541222/SJSkY7Abu
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Literal

import pandas as pd
import requests

from sportsbet import config
from sportsbet.data.team_names import normalize_matchup

logger = logging.getLogger(__name__)

# 運彩 si 球種代碼
SI_NBA = 442
SI_MLB = 443

SI_TO_SPORT: dict[int, str] = {
    SI_NBA: "nba",
    SI_MLB: "mlb",
}

# ms.id → 標準 market（與官網玩法對應，見 HackMD 運彩爬蟲）
MARKET_ID_MAP: dict[int, str] = {
    1: "moneyline",   # 不讓分
    3: "spread",      # 讓分
    5: "total",       # 大小分
    7: "margin",      # 勝分差
}

# 勝分差選項位置（NBA 12 格常見配置）
NBA_MARGIN_BY_POS: list[str] = [
    "home_1_5", "home_6_10", "home_11_15", "home_16_20", "home_21_25", "home_26_plus",
    "away_1_5", "away_6_10", "away_11_15", "away_16_20", "away_21_25", "away_26_plus",
]

# Blob 受注中（賽前）路徑：Register/On.json 已下架，依序嘗試後備
REGISTER_BLOB_PATHS: tuple[str, ...] = (
    "Register/On.json",
    "Prematch/On.json",
    "Pre/On.json",
    "Sports/On.json",
    "Book/On.json",
    "Scheduled/On.json",
)

# 選項位置 p → selection
POSITION_MAP: dict[int, str] = {
    1: "home",
    2: "draw",
    3: "away",
    4: "over",
    5: "under",
}

STANDARD_ODDS_COLUMNS = [
    "source",
    "scrape_time",
    "event_id",
    "sport",
    "league",
    "match_datetime",
    "match_date",
    "home_team",
    "away_team",
    "market",
    "selection",
    "handicap",
    "odds",
    "min_parlay",
    "odds_phase",
]


def _team_label(raw: Any) -> str:
    if isinstance(raw, list) and raw:
        return str(raw[0])
    return str(raw or "")


def _parse_kdt(kdt: Any) -> tuple[str, str]:
    """kdt 為毫秒時間戳 → (iso datetime, YYYY-MM-DD)。"""
    if kdt is None:
        now = datetime.now(timezone.utc)
        return now.isoformat(), now.date().isoformat()
    try:
        ts = int(kdt) / 1000.0
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        return dt.isoformat(), dt.date().isoformat()
    except (TypeError, ValueError, OSError):
        return "", ""


def _guess_selection(market: str, position: int, n_selections: int, *, sport: str = "nba") -> str:
    if market == "total":
        if position in (4, 5):
            return POSITION_MAP.get(position, "over" if position == 4 else "under")
        return "over" if position == 1 else "under"
    if market == "margin":
        if sport == "nba" and 1 <= position <= len(NBA_MARGIN_BY_POS):
            return NBA_MARGIN_BY_POS[position - 1]
        return POSITION_MAP.get(position, f"band_{position}")
    if market == "moneyline" and n_selections == 2:
        return "home" if position == 1 else "away"
    if market == "spread":
        if position == 1:
            return "home"
        if position == 3:
            return "away"
    return POSITION_MAP.get(position, f"p{position}")


def _parse_ms_rows(
    event: dict[str, Any],
    sport: str,
    scrape_time: str,
    source: str,
    odds_phase: str,
) -> list[dict[str, Any]]:
    """將單場 ms 陣列展開為標準賠率列。"""
    rows: list[dict[str, Any]] = []
    event_id = str(event.get("id", event.get("no", "")))
    league_raw = event.get("ln", "")
    league = league_raw[0] if isinstance(league_raw, list) and league_raw else str(league_raw)
    home_zh = _team_label(event.get("htn"))
    away_zh = _team_label(event.get("atn"))
    home_en, away_en = normalize_matchup(home_zh, away_zh, sport)
    match_dt, match_date = _parse_kdt(event.get("kdt"))

    for market_block in event.get("ms") or []:
        mid = int(market_block.get("id", 0))
        market = MARKET_ID_MAP.get(mid, f"market_{mid}")
        min_parlay = int(market_block.get("ma", 1) or 1)
        # ma 在運彩有時為玩法屬性；串關數常見於 1/2/3，過大則視為 1
        if min_parlay > 5:
            min_parlay = 1

        for line_group in market_block.get("cs") or []:
            if not isinstance(line_group, list):
                continue
            n_sel = len(line_group)
            for cell in line_group:
                if not isinstance(cell, dict):
                    continue
                try:
                    odds_val = float(cell.get("o", 0))
                except (TypeError, ValueError):
                    continue
                if odds_val <= 1.0:
                    continue
                pos = int(cell.get("p", 0))
                handicap = cell.get("h")
                if handicap is not None:
                    try:
                        handicap = float(handicap)
                    except (TypeError, ValueError):
                        handicap = None
                selection = _guess_selection(market, pos, n_sel, sport=sport)
                rows.append(
                    {
                        "source": source,
                        "scrape_time": scrape_time,
                        "event_id": event_id,
                        "sport": sport,
                        "league": league,
                        "match_datetime": match_dt,
                        "match_date": match_date,
                        "home_team": home_en,
                        "away_team": away_en,
                        "home_team_zh": home_zh,
                        "away_team_zh": away_zh,
                        "market": market,
                        "selection": selection,
                        "handicap": handicap,
                        "odds": odds_val,
                        "min_parlay": min_parlay,
                        "odds_phase": odds_phase,
                    }
                )
    return rows


class SportLotteryClient:
    """台灣運彩 Blob JSON 客戶端。"""

    def __init__(self, base_url: str | None = None, timeout: float = 30.0):
        self.base_url = (base_url or config.SPORTSLOTTERY_BLOB_BASE).rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "sportsbet/1.0 (+research)",
                "Accept": "application/json",
            }
        )

    def _get_json(self, path: str) -> Any:
        url = f"{self.base_url}/{path.lstrip('/')}"
        resp = self.session.get(url, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    def _unwrap_events(payload: Any) -> list[dict[str, Any]]:
        """相容 2020 包裝格式與 2021+ 純陣列。"""
        if isinstance(payload, list):
            return [e for e in payload if isinstance(e, dict)]
        if isinstance(payload, dict):
            result = payload.get("result", payload)
            if isinstance(result, dict):
                live = result.get("liveOn") or result.get("registerOn") or []
                if isinstance(live, list):
                    return [e for e in live if isinstance(e, dict)]
            if "liveOn" in payload:
                return payload["liveOn"] or []
        return []

    def _get_json_path(self, path: str) -> Any:
        return self._get_json(path)

    def fetch_register_raw(self) -> list[dict[str, Any]]:
        """受注中（賽前）賽事；Register/On.json 404 時嘗試後備路徑。"""
        for path in REGISTER_BLOB_PATHS:
            try:
                events = self._unwrap_events(self._get_json(path))
                if events:
                    logger.info("運彩受注 Blob 命中：%s（%d 場）", path, len(events))
                    return events
            except requests.HTTPError as exc:
                if exc.response is not None and exc.response.status_code == 404:
                    logger.debug("Blob 404: %s", path)
                    continue
                raise
            except Exception as exc:
                logger.debug("Blob 失敗 %s: %s", path, exc)
        return []

    def fetch_live_raw(self) -> list[dict[str, Any]]:
        try:
            events = self._unwrap_events(self._get_json("Live/On.json"))
            if events:
                logger.info("運彩 Live Blob：%d 場", len(events))
            return events
        except Exception as exc:
            logger.warning("Live/On.json 失敗: %s", exc)
            return []

    def parse_events(
        self,
        events: list[dict[str, Any]],
        *,
        source: str = "sportslottery",
        odds_phase: str = "live",
        sports: set[str] | None = None,
    ) -> pd.DataFrame:
        """將原始賽事列表轉為標準賠率 DataFrame。"""
        scrape_time = datetime.now(timezone.utc).isoformat()
        rows: list[dict[str, Any]] = []
        target = sports or {"nba", "mlb"}

        for ev in events:
            si = ev.get("si")
            sport = SI_TO_SPORT.get(int(si)) if si is not None else None
            if sport is None or sport not in target:
                continue
            rows.extend(_parse_ms_rows(ev, sport, scrape_time, source, odds_phase))

        if not rows:
            return pd.DataFrame(columns=STANDARD_ODDS_COLUMNS)

        df = pd.DataFrame(rows)
        return df[STANDARD_ODDS_COLUMNS + [c for c in df.columns if c not in STANDARD_ODDS_COLUMNS]]

    def fetch_live(
        self,
        sports: set[str] | None = None,
    ) -> pd.DataFrame:
        events = self.fetch_live_raw()
        return self.parse_events(events, source="sportslottery_live", odds_phase="live", sports=sports)

    def fetch_register(
        self,
        sports: set[str] | None = None,
    ) -> pd.DataFrame:
        events = self.fetch_register_raw()
        return self.parse_events(
            events,
            source="sportslottery_register",
            odds_phase="register",
            sports=sports,
        )

    def fetch_all(
        self,
        sports: set[str] | None = None,
    ) -> pd.DataFrame:
        """合併 Live + Register（賽前受注）。"""
        live_ev = self.fetch_live_raw()
        reg_ev = self.fetch_register_raw()
        frames: list[pd.DataFrame] = []
        if live_ev:
            frames.append(
                self.parse_events(live_ev, source="sportslottery_live", odds_phase="live", sports=sports)
            )
        if reg_ev:
            frames.append(
                self.parse_events(reg_ev, source="sportslottery_register", odds_phase="register", sports=sports)
            )
        if not frames:
            logger.warning(
                "台灣運彩 Blob 無資料（Live=[]、Register 後備皆空）。"
                "賽前盤口請啟用 SPORTSLOTTERY_PLAYWRIGHT 由官網 event 頁抓取。"
            )
            return pd.DataFrame(columns=STANDARD_ODDS_COLUMNS)
        if len(frames) == 1:
            return frames[0]
        return pd.concat(frames, ignore_index=True).drop_duplicates(
            subset=["event_id", "market", "selection", "handicap", "odds_phase", "odds"],
            keep="last",
        )


def empty_odds_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=STANDARD_ODDS_COLUMNS)
