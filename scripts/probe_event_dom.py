"""Load sportslottery event page after cookie accept; dump visible odds."""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

EVENT_URL = (
    "https://www.sportslottery.com.tw/sportsbook/sport/"
    "%E7%B1%83%E7%90%83/%E7%BE%8E%E5%9C%8B/%E7%BE%8E%E5%9C%8B%E8%81%B7%E7%B1%83/34801.1/event/3472877.1"
)


def _accept_cookies(page) -> None:
    selectors = [
        "button:has-text('accept')",
        "button:has-text('Accept')",
        "button:has-text('接受')",
        "#acceptCookies",
        "[data-testid='accept-cookies']",
    ]
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if loc.count() and loc.is_visible(timeout=2000):
                loc.click()
                print("clicked cookies:", sel)
                return
        except Exception:
            pass


def main() -> None:
    from playwright.sync_api import sync_playwright

    captured: list[tuple[str, str]] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
            locale="zh-TW",
            viewport={"width": 1400, "height": 900},
        )

        def grab(response) -> None:
            url = response.url
            if "/services" not in url:
                return
            try:
                body = response.text()
            except Exception:
                return
            if body.startswith("{"):
                captured.append((url, body))

        page.on("response", grab)
        page.goto("https://www.sportslottery.com.tw/sportsbook/", wait_until="load", timeout=120000)
        page.wait_for_timeout(5000)
        _accept_cookies(page)
        page.wait_for_timeout(2000)
        page.goto(EVENT_URL, wait_until="load", timeout=120000)
        page.wait_for_timeout(40000)

        text = page.inner_text("body")
        html = page.content()
        browser.close()

    print("text len", len(text))
    for kw in ("尼克", "馬刺", "讓分", "大小", "不讓分", "1.75", "1.85"):
        print(kw, kw in text or kw in html)
    print("odds", sorted(set(re.findall(r"1\.\d{2}", text)))[:20])
    print("services captures", len(captured))
    for url, body in captured:
        if re.search(r"idfoevent|3472877|decimal|handicap|market", body, re.I):
            print("JSON HIT", url[:80], len(body))
            print(body[:800])

    print("\n--- body snippet ---")
    print(text[:3000])


if __name__ == "__main__":
    main()
