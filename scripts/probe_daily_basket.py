"""Daily coupons: click 籃球 + date tab, dump iframe odds."""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DAILY = "https://www.sportslottery.com.tw/sportsbook/daily-coupons"
NBA_LEAGUE = (
    "https://www.sportslottery.com.tw/sportsbook/sport/"
    "%E7%B1%83%E7%90%83/%E7%BE%8E%E5%9C%8B/%E7%BE%8E%E5%9C%8B%E8%81%B7%E7%B1%83/34801.1"
)
OUT = ROOT / "scripts" / "_talo_captures"


def talo_frame(page):
    for fr in page.frames:
        if "talo-ssb" in fr.url:
            return fr
    return page


def main() -> None:
    from playwright.sync_api import sync_playwright

    from sportsbet import config

    OUT.mkdir(exist_ok=True)
    state = config.SPORTSLOTTERY_PLAYWRIGHT_STATE_PATH

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, args=["--disable-blink-features=AutomationControlled"])
        ctx_opts = {
            "user_agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
            "locale": "zh-TW",
            "viewport": {"width": 1400, "height": 900},
        }
        if Path(state).is_file():
            ctx_opts["storage_state"] = state
        context = browser.new_context(**ctx_opts)
        page = context.new_page()

        for label, url, clicks in (
            ("daily_basket", DAILY, ["籃球", "06, 09"]),
            ("nba_league", NBA_LEAGUE, []),
        ):
            print(f"\n=== {label} ===")
            page.goto(url, wait_until="domcontentloaded", timeout=120000)
            page.wait_for_timeout(20000)
            fr = talo_frame(page)
            for c in clicks:
                try:
                    loc = fr.get_by_text(c, exact=False).first
                    if loc.count():
                        loc.click(timeout=5000)
                        fr.wait_for_timeout(5000)
                        print(f"clicked {c}")
                except Exception as exc:
                    print(f"click fail {c}: {exc}")
            text = fr.inner_text("body")
            odds = sorted(set(re.findall(r"\b\d\.\d{2}\b", text)))
            print(f"len={len(text)} odds_sample={odds[:15]}")
            for kw in ("尼克", "馬刺", "NBA", "美國職籃", "06, 09", "06, 06"):
                print(f"  {kw}: {kw in text}")
            (OUT / f"{label}_body.txt").write_text(text, encoding="utf-8")

        context.storage_state(path=state)
        browser.close()


if __name__ == "__main__":
    main()
