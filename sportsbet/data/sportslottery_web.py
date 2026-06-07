"""
台灣運彩官網 SPA 賠率（Playwright）。

官網 event 頁範例：
https://www.sportslottery.com.tw/sportsbook/sport/籃球/美國/美國職籃/34801.1/event/3472877.1

後端為 Orako/Talo iframe + POST /services/content/get。
賽事 metadata：contentId type=foEvent；賠率自 Talo iframe DOM 解析。
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
MLB_LEAGUE_PATH = "棒球/美國/美國職棒/34802.1"

SPORT_PATHS: dict[str, str] = {
    "nba": NBA_LEAGUE_PATH,
    "mlb": MLB_LEAGUE_PATH,
}

TALO_HOST = "www-talo-ssb-pr.sportslottery.com.tw"


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


def _talo_frame(page):
    for fr in page.frames:
        if TALO_HOST in fr.url:
            return fr
    return page


def _iframe_text_and_html(page) -> tuple[str, str]:
    fr = _talo_frame(page)
    try:
        return fr.inner_text("body"), fr.content()
    except Exception:
        return page.inner_text("body"), page.content()


def _clean_lines(text: str) -> list[str]:
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


def _next_odds(lines: list[str], start: int) -> tuple[float | None, int]:
    for i in range(start, min(start + 8, len(lines))):
        if re.fullmatch(r"\d\.\d{2}", lines[i]):
            return float(lines[i]), i + 1
    return None, start


def _fetch_fo_event_meta(page, event_id: str) -> dict[str, Any]:
    """在 Talo 頁面內 POST foEvent（需通過 CF 的瀏覽器 context）。"""
    eid = event_id if "." in event_id else f"{event_id}.1"
    target = _talo_frame(page)
    try:
        raw = target.evaluate(
            """async (eid) => {
                const r = await fetch('/services/content/get', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        contentId: {type: 'foEvent', id: eid},
                        clientContext: {language: 'ZH', ipAddress: '0.0.0.0'},
                    }),
                });
                return await r.text();
            }""",
            eid,
        )
        data = json.loads(raw)
        if isinstance(data.get("data"), dict) and data["data"].get("idfoevent"):
            return data["data"]
    except Exception as exc:
        logger.debug("foEvent %s 失敗: %s", eid, exc)
    return {}


def _teams_from_meta_or_text(meta: dict[str, Any], text: str, sport: str) -> tuple[str, str, str, str]:
    home_zh = str(meta.get("participantname_home") or "").strip()
    away_zh = str(meta.get("participantname_away") or "").strip()
    if not home_zh or not away_zh:
        for line in _clean_lines(text):
            if "@" in line and len(line) < 50:
                left, right = [p.strip() for p in line.split("@", 1)]
                if left and right:
                    away_zh, home_zh = left, right
                    break
    home_en, away_en = normalize_matchup(home_zh or "home", away_zh or "away", sport)
    return home_en, away_en, home_zh, away_zh


def _row_base(
    *,
    sport: str,
    event_id: str,
    home_en: str,
    away_en: str,
    match_datetime: str,
    scrape_time: str,
) -> dict[str, Any]:
    match_date = match_datetime[:10] if match_datetime else ""
    return {
        "source": "sportslottery_web",
        "scrape_time": scrape_time,
        "event_id": event_id.split(".")[0],
        "sport": sport,
        "league": "NBA" if sport == "nba" else "MLB",
        "match_datetime": match_datetime,
        "match_date": match_date,
        "home_team": home_en,
        "away_team": away_en,
        "min_parlay": 1,
        "odds_phase": "register",
    }


def _parse_event_dom_text(
    text: str,
    sport: str,
    *,
    event_id: str = "",
    meta: dict[str, Any] | None = None,
) -> pd.DataFrame:
    """自 Talo event iframe DOM 文字解析 moneyline / spread / total。"""
    scrape_time = datetime.now(timezone.utc).isoformat()
    meta = meta or {}
    home_en, away_en, home_zh, away_zh = _teams_from_meta_or_text(meta, text, sport)
    if not home_en or not away_en:
        return pd.DataFrame(columns=STANDARD_ODDS_COLUMNS)

    match_datetime = str(meta.get("tsstart") or "")
    base = _row_base(
        sport=sport,
        event_id=event_id or str(meta.get("idfoevent") or ""),
        home_en=home_en,
        away_en=away_en,
        match_datetime=match_datetime,
        scrape_time=scrape_time,
    )
    rows: list[dict[str, Any]] = []
    lines = _clean_lines(text)

    # 不讓分（moneyline）
    if "不讓分" in lines:
        idx = lines.index("不讓分")
        scan = idx + 1
        while scan < len(lines) and lines[scan] in ("主場", "客場"):
            scan += 1
        teams: list[str] = []
        while scan < len(lines) and len(teams) < 2:
            if re.fullmatch(r"\d\.\d{2}", lines[scan]):
                break
            if lines[scan] not in ("主場", "客場", "不讓分"):
                teams.append(lines[scan])
            scan += 1
        home_odds, scan = _next_odds(lines, scan)
        away_odds, _scan2 = _next_odds(lines, scan)
        if home_odds and away_odds:
            rows.append({**base, "market": "moneyline", "selection": "home", "handicap": None, "odds": home_odds})
            rows.append({**base, "market": "moneyline", "selection": "away", "handicap": None, "odds": away_odds})

    # 第一組讓分盤
    for i, line in enumerate(lines):
        m = re.match(r"\[總分\]讓分\s+([+-]?\d+(?:\.\d+)?)$", line)
        if not m:
            continue
        handicap_home = float(m.group(1))
        j = i + 1
        away_line = lines[j] if j < len(lines) else ""
        away_odds, k = _next_odds(lines, j + 1)
        home_line = lines[k] if k < len(lines) else ""
        home_odds, _ = _next_odds(lines, k + 1)
        if home_odds and away_odds:
            rows.append(
                {**base, "market": "spread", "selection": "home", "handicap": handicap_home, "odds": home_odds}
            )
            rows.append(
                {**base, "market": "spread", "selection": "away", "handicap": -handicap_home, "odds": away_odds}
            )
        break

    # 全場大小（不含 combo）
    for i, line in enumerate(lines):
        if not re.match(r"\[總分\]大小\s+\d+(?:\.\d+)?$", line):
            continue
        if i > 0 and "不讓分" in lines[i - 1]:
            continue
        total_line = float(line.split()[-1])
        over_odds, j = _next_odds(lines, i + 2)
        under_odds, _ = _next_odds(lines, j)
        if over_odds and under_odds:
            rows.append(
                {**base, "market": "total", "selection": "over", "handicap": total_line, "odds": over_odds}
            )
            rows.append(
                {**base, "market": "total", "selection": "under", "handicap": total_line, "odds": under_odds}
            )
        break

    if not rows:
        return pd.DataFrame(columns=STANDARD_ODDS_COLUMNS)
    return pd.DataFrame(rows)[STANDARD_ODDS_COLUMNS]



def _parse_services_payloads(payloads: list[str], sport: str) -> pd.DataFrame:
    """保留 foEvent 以外之通用解析（後備）。"""
    scrape_time = datetime.now(timezone.utc).isoformat()
    rows: list[dict[str, Any]] = []
    for raw in payloads:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        meta = data.get("data") if isinstance(data, dict) else None
        if isinstance(meta, dict) and meta.get("idfoevent"):
            continue
        hits: list[dict[str, Any]] = []
        _walk_json(data, hits)
        for h in hits:
            odds_val = None
            for pk in ("decimalprice", "price", "odds", "o", "currentprice"):
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


def _walk_json(obj: Any, out: list[dict[str, Any]], path: str = "") -> None:
    if isinstance(obj, dict):
        keys = {str(k).lower() for k in obj}
        price = None
        for pk in ("decimalprice", "price", "odds", "o", "currentprice"):
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


def _extract_event_ids_from_html(html: str) -> list[str]:
    ids = re.findall(r"/event/(\d+\.1)", html)
    return list(dict.fromkeys(ids))


def _is_event_url(url: str) -> bool:
    return "/event/" in url


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
    ) -> tuple[list[str], str, str, dict[str, Any]]:
        from playwright.sync_api import sync_playwright

        payloads: list[str] = []
        final_text = ""
        final_html = ""
        fo_meta: dict[str, Any] = {}

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
                wait_ms = self.wait_ms
                if _is_event_url(url):
                    wait_ms = max(wait_ms, 55000)
                    fr = _talo_frame(page)
                    try:
                        fr.wait_for_function(
                            "() => document.body && document.body.innerText.includes('不讓分')",
                            timeout=wait_ms,
                        )
                    except Exception:
                        page.wait_for_timeout(wait_ms)
                else:
                    page.wait_for_timeout(wait_ms)

                if _is_event_url(url):
                    m = re.search(r"/event/(\d+(?:\.\d+1)?)", url)
                    if m:
                        fo_meta = _fetch_fo_event_meta(page, m.group(1))

            final_text, final_html = _iframe_text_and_html(page)

            state_path = config.SPORTSLOTTERY_PLAYWRIGHT_STATE_PATH
            if state_path:
                try:
                    context.storage_state(path=state_path)
                except Exception as exc:
                    logger.debug("storage_state 略過: %s", exc)
            browser.close()

        return payloads, final_text, final_html, fo_meta

    def fetch_league_event_ids(self, sport: str) -> list[str]:
        configured = config.sportslottery_event_ids(sport)
        _, _, html, _ = self._browse([league_url(sport)])
        found = _extract_event_ids_from_html(html)
        return list(dict.fromkeys([*configured, *found]))

    def _fetch_events_batch(self, sport: str, event_ids: list[str]) -> pd.DataFrame:
        from playwright.sync_api import sync_playwright

        frames: list[pd.DataFrame] = []
        state = config.SPORTSLOTTERY_PLAYWRIGHT_STATE_PATH
        use_state = state if __import__("pathlib").Path(state).is_file() else None

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
            if use_state:
                ctx_opts["storage_state"] = use_state
            context = browser.new_context(**ctx_opts)
            page = context.new_page()
            page.goto(f"{_www_base()}/sportsbook/", wait_until="load", timeout=120000)
            page.wait_for_timeout(3000)
            _accept_cookies(page)

            for eid in event_ids:
                url = event_url(sport, eid)
                logger.info("運彩官網 event %s", eid)
                page.goto(url, wait_until="load", timeout=120000)
                wait_ms = max(self.wait_ms, 55000)
                fr = _talo_frame(page)
                try:
                    fr.wait_for_function(
                        "() => document.body && document.body.innerText.includes('不讓分')",
                        timeout=wait_ms,
                    )
                except Exception:
                    page.wait_for_timeout(wait_ms)
                meta = _fetch_fo_event_meta(page, eid)
                text, _html = _iframe_text_and_html(page)
                part = _parse_event_dom_text(text, sport, event_id=eid, meta=meta)
                if not part.empty:
                    frames.append(part)

            if state:
                try:
                    context.storage_state(path=state)
                except Exception as exc:
                    logger.debug("storage_state 略過: %s", exc)
            browser.close()

        if not frames:
            return pd.DataFrame(columns=STANDARD_ODDS_COLUMNS)
        return pd.concat(frames, ignore_index=True)

    def fetch_event_odds(self, sport: str, event_id: str) -> pd.DataFrame:
        return self._fetch_events_batch(sport, [event_id])

    def fetch_upcoming(
        self,
        sport: str,
        *,
        event_ids: list[str] | None = None,
        max_events: int | None = None,
    ) -> pd.DataFrame:
        ids = list(event_ids or [])
        if not ids:
            ids = self.fetch_league_event_ids(sport)
        if not ids:
            ids = config.sportslottery_event_ids(sport)
        cap = max_events or config.SPORTSLOTTERY_MAX_EVENTS_PER_SYNC
        ids = ids[:cap]
        if not ids:
            logger.warning("運彩官網無 event id（聯盟頁未解析到；可設 SPORTSLOTTERY_EVENT_IDS_%s）", sport.upper())
            return pd.DataFrame(columns=STANDARD_ODDS_COLUMNS)
        try:
            return self._fetch_events_batch(sport, ids)
        except Exception as exc:
            logger.warning("運彩官網 batch 失敗: %s", exc)
            return pd.DataFrame(columns=STANDARD_ODDS_COLUMNS)


def fetch_web_odds_df(sport: str) -> pd.DataFrame:
    """官網 Playwright 抓取（需本機瀏覽器）。"""
    if not config.SPORTSLOTTERY_PLAYWRIGHT_ENABLED:
        return pd.DataFrame(columns=STANDARD_ODDS_COLUMNS)
    try:
        return SportLotteryWebClient().fetch_upcoming(sport)
    except Exception as exc:
        logger.warning("運彩官網 Playwright 失敗: %s", exc)
        return pd.DataFrame(columns=STANDARD_ODDS_COLUMNS)
