"""Playwright with anti-bot args to capture gismo feeds."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from playwright.async_api import async_playwright

URL = "https://statshub.sportradar.com/taiwansportslottery/zht/match/70505022/statistics"


async def main() -> None:
    feeds = {}
    urls = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ],
        )
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            locale="zh-TW",
            extra_http_headers={
                "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
            },
        )
        await context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        page = await context.new_page()
        page.on("response", lambda r: urls.append(f"{r.status} {r.url[:120]}"))

        async def capture(response) -> None:
            if "/gismo/" in response.url and response.status == 200:
                try:
                    feeds[response.url.split("/gismo/")[-1].split("?")[0]] = await response.json()
                except Exception:
                    pass

        page.on("response", capture)
        resp = await page.goto(URL, wait_until="domcontentloaded", timeout=90000)
        print("goto", resp.status if resp else None, await page.title())
        await page.wait_for_timeout(10000)
        await browser.close()

    print("gismo feeds", list(feeds.keys()))
    for u in urls:
        if "gismo" in u or "403" in u or "statshub" in u:
            print(u)
    Path("../logs/statshub_pw_feeds.json").write_text(json.dumps(feeds, ensure_ascii=False, indent=2), encoding="utf-8")


asyncio.run(main())
