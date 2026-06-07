"""
台灣運彩官網 SPA 賠率（Playwright）。

官網 event 頁範例：
https://www.sportslottery.com.tw/sportsbook/sport/籃球/美國/美國職籃/34801.1/event/3472877.1

後端為 Orako/Talo iframe + /services/content/get（非舊 Register Blob）。
需瀏覽器通過 Cloudflare；本地以 Playwright 攔截 JSON 或解析 DOM。
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

import pandas as pd

from sportsbet import config
from sportsbet.data.sportslottery import STANDARD_ODDS_COLUMNS
from sportsbet.data.team_names import normalize_matchup

logger = logging.getLogger(__name__)

NBA_LEAGUE_PATH = "籃球/美國/美國職籃/34801.1"
MLB_LEAGUE_PATH = "棒球/美國/美國職棒/34802.1"  # 後備；以 config 覆寫

SPORT_PATHS: dict[str, str] = {
    "nba": NBA_LEAGUE_PATH,
    "mlb": MLB_LEAGUE_PATH,
}


def _www_base() -> str:
    return config.SPORTSLOTTERY_WWW_BASE.rstrip("/")


def league_url(sport: str) -> str:
    path = SPORT_PATHS.get(sport, NBA_LEAGUE_PATH)
    return f"{_www_base()}/sportsbook/sport/{quote(path, safe='/')}"


def event_url(sport: str, event_id: str) -> str:
    eid = event_id if "." in event_id else f"{event_id}.1"
    path = SPORT_PATHS.get(sport, NBA_LEAGUE_PATH)
    return f"{_www_base()}/sportsbook/sport/{quote(path, safe='/')}/event/{quote(eid, safe='.')}"


def daily_coupons_url() -> str:
    return f"{_www_base()}/sportsbook/daily-coupons"


def _accept_cookies(page) -> None:
    for sel in (
        "button:has-text('accept')",
        "button:has-text('Accept')",
        "button:has-text('接受')",
        "#acceptCookies",
    ):
        try:
            loc = page.locator(sel).first
            if loc.count() and loc.is_visible(timeout=1500):
                loc.click()
                return
        except Exception:
            pass


def _walk_json(obj: Any, out: list[dict[str, Any]], path: str = "") -> None:
    """遞迴搜尋含 price/odds 的 market 節點。"""
    if isinstance(obj, dict):
        keys = {str(k).lower() for k in obj}
        price = None
        for pk in ("decimalprice", "price", "odds", "o"):
            if pk in keys:
                try:
                    price = float(obj.get(pk) or obj.get(pk.upper()) or 0)
                except (TypeError, ValueError):
                    price = None
                if price and price > 1.0:
                    out.append({"_path": path, **{str(k): v for k, v in obj.items()}})
                    break
        for k, v in obj.items():
            _walk_json(v, out, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _walk_json(v, out, f"{path}[{i}]")


def _parse_services_payloads(payloads: list[str], sport: str) -> pd.DataFrame:
    """從 /services JSON 嘗試萃取標準賠率列（通用遞迴）。"""
    scrape_time = datetime.now(timezone.utc).isoformat()
    rows: list[dict[str, Any]] = []
    for raw in payloads:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        hits: list[dict[str, Any]] = []
        _walk_json(data, hits)
        for h in hits:
            odds_val = None
            for pk in ("decimalprice", "price", "odds", "o"):
                if pk in h or pk.upper() in h:
                    try:
                        odds_val = float(h.get(pk) or h.get(pk.upper()))
                    except (TypeError, ValueError):
                        continue
            if not odds_val or odds_val <= 1.0:
                continue
            name = str(h.get("name") or h.get("selectionname") or h.get("label") or "")
            market = "moneyline"
            selection = "home"
            if "讓" in name or "handicap" in name.lower():
                market = "spread"
            elif "大" in name or "over" in name.lower():
                market = "total"
                selection = "over"
            elif "小" in name or "under" in name.lower():
                market = "total"
                selection = "under"
            rows.append(
                {
                    "source": "sportslottery_web",
                    "scrape_time": scrape_time,
                    "event_id": str(h.get("idfoevent") or h.get("event_id") or ""),
                    "sport": sport,
                    "league": "NBA" if sport == "nba" else "MLB",
                    "match_datetime": "",
                    "match_date": "",
                    "home_team": "",
                    "away_team": "",
                    "market": market,
                    "selection": selection,
                    "handicap": None,
                    "odds": odds_val,
                    "min_parlay": 1,
                    "odds_phase": "register",
                }
            )
    if not rows:
        return pd.DataFrame(columns=STANDARD_ODDS_COLUMNS)
    return pd.DataFrame(rows)[STANDARD_ODDS_COLUMNS]


def _parse_dom_text(text: str, sport: str, *, event_id: str = "") -> pd.DataFrame:
    """DOM 文字後備：解析 1.xx 賠率與隊名。"""
    scrape_time = datetime.now(timezone.utc).isoformat()
    rows: list[dict[str, Any]] = []
    odds = sorted(set(float(x) for x in re.findall(r"\b1\.\d{2}\b", text) if 1.0 < float(x) < 20))
    if len(odds) < 2:
        return pd.DataFrame(columns=STANDARD_ODDS_COLUMNS)

    teams_zh: list[str] = []
    for pat in (r"紐約尼克|尼克|聖安東尼奧馬刺|馬刺|洛杉磯湖人|湖人"):
        if re.search(pat, text):
            teams_zh.append(re.search(pat, text).group(0))  # type: ignore[union-attr]

    home_zh, away_zh = "", ""
    if "VS" in text.upper() or "vs" in text:
        parts = re.split(r"\bvs\.?\b", text, flags=re.I, maxsplit=1)
        if len(parts) == 2:
            home_zh, away_zh = parts[0][-20:].strip(), parts[1][:20].strip()

    if not home_zh and len(teams_zh) >= 2:
        home_zh, away_zh = teams_zh[0], teams_zh[1]
    home_en, away_en = normalize_matchup(home_zh or "home", away_zh or "away", sport)

    if len(odds) >= 2:
        rows.append(
            {
                "source": "sportslottery_web_dom",
                "scrape_time": scrape_time,
                "event_id": event_id,
                "sport": sport,
                "league": "NBA" if sport == "nba" else "MLB",
                "match_datetime": "",
                "match_date": "",
                "home_team": home_en,
                "away_team": away_en,
                "market": "moneyline",
                "selection": "home",
                "handicap": None,
                "odds": odds[0],
                "min_parlay": 1,
                "odds_phase": "register",
            }
        )
        rows.append(
            {
                **rows[0],
                "selection": "away",
                "odds": odds[1],
            }
        )
    return pd.DataFrame(rows)[STANDARD_ODDS_COLUMNS] if rows else pd.DataFrame(columns=STANDARD_ODDS_COLUMNS)


def _extract_event_ids_from_html(html: str) -> list[str]:
    ids = re.findall(r"/event/(\d+\.1)", html)
    return list(dict.fromkeys(ids))


class SportLotteryWebClient:
    """官網 Playwright 客戶端。"""

    def __init__(
        self,
        *,
        headless: bool | None = None,
        wait_ms: int | None = None,
    ):
        self.headless = headless if headless is not None else config.SPORTSLOTTERY_PLAYWRIGHT_HEADLESS
        self.wait_ms = wait_ms or config.SPORTSLOTTERY_PLAYWRIGHT_WAIT_MS

    def _browse(
        self,
        urls: list[str],
        *,
        storage_state: str | None = None,
    ) -> tuple[list[str], str, str]:
        from playwright.sync_api import sync_playwright

        payloads: list[str] = []
        final_text = ""
        final_html = ""

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=self.headless,
                args=["--disable-blink-features=AutomationControlled"],
            )
            ctx_opts: dict[str, Any] = {
                "user_agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
                ),
                "locale": "zh-TW",
                "viewport": {"width": 1400, "height": 900},
            }
            if storage_state:
                ctx_opts["storage_state"] = storage_state
            context = browser.new_context(**ctx_opts)
            page = context.new_page()

            def on_response(response) -> None:
                url = response.url
                if "/services" not in url:
                    return
                try:
                    body = response.text()
                except Exception:
                    return
                if body.startswith("{"):
                    payloads.append(body)

            page.on("response", on_response)
            page.goto(f"{_www_base()}/sportsbook/", wait_until="load", timeout=120000)
            page.wait_for_timeout(4000)
            _accept_cookies(page)
            page.wait_for_timeout(2000)

            for url in urls:
                logger.info("運彩官網載入 %s", url[:100])
                page.goto(url, wait_until="load", timeout=120000)
                page.wait_for_timeout(self.wait_ms)

            final_text = page.inner_text("body")
            final_html = page.content()

            state_path = config.SPORTSLOTTERY_PLAYWRIGHT_STATE_PATH
            if state_path:
                try:
                    context.storage_state(path=state_path)
                except Exception as exc:
                    logger.debug("storage_state 略過: %s", exc)
            browser.close()

        return payloads, final_text, final_html

    def fetch_league_event_ids(self, sport: str) -> list[str]:
        _, _, html = self._browse([league_url(sport), daily_coupons_url()])
        return _extract_event_ids_from_html(html)

    def fetch_event_odds(self, sport: str, event_id: str) -> pd.DataFrame:
        url = event_url(sport, event_id)
        state = config.SPORTSLOTTERY_PLAYWRIGHT_STATE_PATH
        use_state = state if state and __import__("pathlib").Path(state).is_file() else None
        payloads, text, _html = self._browse([url], storage_state=use_state)
        df = _parse_services_payloads(payloads, sport)
        if df.empty:
            df = _parse_dom_text(text, sport, event_id=event_id)
        if not df.empty and not df["event_id"].astype(str).str.len().any():
            df["event_id"] = event_id.split(".")[0]
        return df

    def fetch_upcoming(
        self,
        sport: str,
        *,
        event_ids: list[str] | None = None,
        max_events: int | None = None,
    ) -> pd.DataFrame:
        ids = event_ids or self.fetch_league_event_ids(sport)
        cap = max_events or config.SPORTSLOTTERY_MAX_EVENTS_PER_SYNC
        ids = ids[:cap]
        frames: list[pd.DataFrame] = []
        for eid in ids:
            try:
                part = self.fetch_event_odds(sport, eid)
                if not part.empty:
                    frames.append(part)
            except Exception as exc:
                logger.warning("運彩 event %s 失敗: %s", eid, exc)
        if not frames:
            return pd.DataFrame(columns=STANDARD_ODDS_COLUMNS)
        return pd.concat(frames, ignore_index=True)


def fetch_web_odds_df(sport: str) -> pd.DataFrame:
    """官網 Playwright 抓取（需本機瀏覽器）。"""
    if not config.SPORTSLOTTERY_PLAYWRIGHT_ENABLED:
        return pd.DataFrame(columns=STANDARD_ODDS_COLUMNS)
    try:
        return SportLotteryWebClient().fetch_upcoming(sport)
    except Exception as exc:
        logger.warning("運彩官網 Playwright 失敗: %s", exc)
        return pd.DataFrame(columns=STANDARD_ODDS_COLUMNS)
