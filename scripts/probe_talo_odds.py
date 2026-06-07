"""Capture Talo sportsbook /services responses for event odds."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

EVENT_URL = (
    "https://www-talo-ssb-pr.sportslottery.com.tw/sportsbook/sport/"
    "%E7%B1%83%E7%90%83/%E7%BE%8E%E5%9C%8B/%E7%BE%8E%E5%9C%8B%E8%81%B7%E7%B1%83/34801.1/event/3472877.1"
)
LEAGUE_URL = (
    "https://www-talo-ssb-pr.sportslottery.com.tw/sportsbook/sport/"
    "%E7%B1%83%E7%90%83/%E7%BE%8E%E5%9C%8B/%E7%BE%8E%E5%9C%8B%E8%81%B7%E7%B1%83/34801.1"
)


def main() -> None:
    from playwright.sync_api import sync_playwright

    captured: list[tuple[str, str]] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
            locale="zh-TW",
        )
        page = context.new_page()

        def on_response(response) -> None:
            url = response.url
            if "/services" not in url:
                return
            try:
                body = response.text()
            except Exception:
                return
            if len(body) < 30:
                return
            captured.append((url, body[:8000]))

        page.on("response", on_response)
        print("Loading league...", LEAGUE_URL[:80])
        page.goto(LEAGUE_URL, wait_until="domcontentloaded", timeout=90000)
        page.wait_for_timeout(8000)
        print("Loading event...", EVENT_URL[:80])
        page.goto(EVENT_URL, wait_until="domcontentloaded", timeout=90000)
        page.wait_for_timeout(15000)
        browser.close()

    print(f"\nCaptured {len(captured)} /services responses")
    out_dir = ROOT / "scripts" / "_talo_captures"
    out_dir.mkdir(exist_ok=True)
    for i, (url, body) in enumerate(captured):
        print(f"\n--- [{i}] {url[:120]} ---")
        print(body[:500])
        safe = url.split("?")[0].replace("/", "_")[-80:]
        (out_dir / f"{i}_{safe}.json").write_text(body, encoding="utf-8")


if __name__ == "__main__":
    main()
