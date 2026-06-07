"""Capture /services JSON from sportslottery event page."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

EVENT_URL = (
    "https://www.sportslottery.com.tw/sportsbook/sport/"
    "%E7%B1%83%E7%90%83/%E7%BE%8E%E5%9C%8B/%E7%BE%8E%E5%9C%8B%E8%81%B7%E7%B1%83/34801.1/event/3472877.1"
)
OUT = ROOT / "scripts" / "_talo_captures"


def main() -> None:
    from playwright.sync_api import sync_playwright

    from sportsbet import config

    OUT.mkdir(exist_ok=True)
    state = config.SPORTSLOTTERY_PLAYWRIGHT_STATE_PATH
    payloads: list[tuple[str, str, int]] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
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

        def grab(response) -> None:
            url = response.url
            if "/services" not in url:
                return
            try:
                body = response.text()
            except Exception:
                return
            if body.startswith("{"):
                payloads.append((url, body, len(body)))

        page.on("response", grab)
        page.goto("https://www.sportslottery.com.tw/sportsbook/", wait_until="load", timeout=120000)
        page.wait_for_timeout(3000)
        for sel in ("button:has-text('accept')", "button:has-text('Accept')", "button:has-text('接受')"):
            try:
                loc = page.locator(sel).first
                if loc.count() and loc.is_visible(timeout=1500):
                    loc.click()
                    break
            except Exception:
                pass
        page.wait_for_timeout(2000)
        page.goto(EVENT_URL, wait_until="load", timeout=120000)
        page.wait_for_timeout(50000)
        text = page.inner_text("body")
        context.storage_state(path=state)
        browser.close()

    print(f"captured {len(payloads)} payloads, body len={len(text)}")
    keywords = (
        "3472877", "idfoevent", "idfomarket", "idfoselection",
        "decimalprice", "price", "handicap", "尼克", "馬刺", "1.75", "1.85",
    )
    for i, (url, body, n) in enumerate(payloads):
        path = OUT / f"event_svc_{i}.json"
        path.write_text(body, encoding="utf-8")
        hits = [k for k in keywords if k.lower() in body.lower() or k in body]
        if hits or n > 500:
            print(f"[{i}] {url[:90]} len={n} hits={hits[:8]}")
            if hits:
                print(body[:1200])
                print("---")

    (OUT / "event_body.txt").write_text(text[:8000], encoding="utf-8")
    odds = sorted(set(__import__("re").findall(r"1\.\d{2}", text)))
    print("visible odds:", odds[:20])
    for kw in ("尼克", "馬刺", "讓分", "大小", "不讓分"):
        print(kw, kw in text)


if __name__ == "__main__":
    main()
