"""Capture all /services JSON from sportslottery event page."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

EVENT_URL = (
    "https://www.sportslottery.com.tw/sportsbook/sport/"
    "%E7%B1%83%E7%90%83/%E7%BE%8E%E5%9C%8B/%E7%BE%8E%E5%9C%8B%E8%81%B7%E7%B1%83/34801.1/event/3472877.1"
)


def main() -> None:
    from playwright.sync_api import sync_playwright

    captured: list[tuple[str, str]] = []

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
            if "/services" not in url:
                return
            try:
                body = response.text()
            except Exception:
                return
            if body.startswith("{") or body.startswith("["):
                captured.append((url, body))

        page.on("response", on_response)
        page.goto(EVENT_URL, wait_until="load", timeout=120000)
        page.wait_for_timeout(25000)
        browser.close()

    out_dir = ROOT / "scripts" / "_talo_captures"
    out_dir.mkdir(exist_ok=True)
    keywords = re.compile(
        r"idfoevent|idfomarket|idfoselection|3472877|handicap|decimalprice|price|odds|market",
        re.I,
    )
    hits = 0
    for i, (url, body) in enumerate(captured):
        path = out_dir / f"svc_{i}.json"
        path.write_text(body, encoding="utf-8")
        if keywords.search(body):
            hits += 1
            print(f"HIT [{i}] {url[:80]} len={len(body)}")
            print(body[:600])
            print("---")
    print(f"total={len(captured)} odds_hits={hits}")


if __name__ == "__main__":
    main()
