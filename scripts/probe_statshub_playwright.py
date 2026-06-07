"""Playwright capture of StatsHub gismo feeds."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from playwright.async_api import async_playwright

MATCH = "70505022"
URL = f"https://statshub.sportradar.com/taiwansportslottery/zht/match/{MATCH}/statistics"
OUT = Path(__file__).resolve().parents[1] / "logs" / "statshub_playwright_feeds.json"


async def main() -> None:
    feeds: dict[str, dict] = {}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            locale="zh-TW",
        )

        async def on_response(response) -> None:
            u = response.url
            if "/gismo/" not in u or response.status != 200:
                return
            try:
                data = await response.json()
            except Exception:
                return
            key = u.split("/gismo/")[-1].split("?")[0]
            feeds[key] = data

        page.on("response", on_response)
        await page.goto(URL, wait_until="networkidle", timeout=90000)
        await page.wait_for_timeout(3000)
        await browser.close()

    OUT.write_text(json.dumps(feeds, ensure_ascii=False, indent=2), encoding="utf-8")
    print("feeds", list(feeds.keys()))
    for k, v in feeds.items():
        doc = v.get("doc", [{}])
        ev = doc[0].get("event") if doc else None
        print(k, ev, str(v)[:120])


if __name__ == "__main__":
    asyncio.run(main())
