"""Probe Talo with longer CF wait and www wrapper."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

WRAPPER = (
    "https://www.sportslottery.com.tw/sportsbook/sport/"
    "%E7%B1%83%E7%90%83/%E7%BE%8E%E5%9C%8B/%E7%BE%8E%E5%9C%8B%E8%81%B7%E7%B1%83/34801.1/event/3472877.1"
)


def main() -> None:
    from playwright.sync_api import sync_playwright

    captured: list[tuple[str, str, int]] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
            locale="zh-TW",
            viewport={"width": 1400, "height": 900},
        )
        page = context.new_page()

        def on_response(response) -> None:
            url = response.url
            ct = response.headers.get("content-type", "")
            if "/services" in url or "apidata" in url or "application/json" in ct:
                try:
                    body = response.text()
                except Exception:
                    return
                if body.startswith("{") or body.startswith("["):
                    captured.append((url, body, len(body)))

        page.on("response", on_response)
        print("goto wrapper", WRAPPER)
        page.goto(WRAPPER, wait_until="load", timeout=120000)
        for wait in (10, 15, 20):
            page.wait_for_timeout(wait * 1000)
            print(f"  waited {wait}s, captures={len(captured)} title={page.title()[:60]}")
            if captured:
                break
        browser.close()

    print(f"json captures: {len(captured)}")
    for url, body, n in captured[:10]:
        print(url[:100], n)
        print(body[:400])


if __name__ == "__main__":
    main()
