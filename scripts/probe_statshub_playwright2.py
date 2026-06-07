"""Debug Playwright network on StatsHub."""
from __future__ import annotations

import asyncio

from playwright.async_api import async_playwright

MATCH = "70505022"
URL = f"https://statshub.sportradar.com/taiwansportslottery/zht/match/{MATCH}/statistics"


async def main() -> None:
    urls: list[str] = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        page.on("response", lambda r: urls.append(f"{r.status} {r.url[:140]}"))
        await page.goto(URL, wait_until="domcontentloaded", timeout=90000)
        await page.wait_for_timeout(8000)
        title = await page.title()
        print("title", title)
        for u in urls:
            if any(x in u for x in ("gismo", "fn.sportradar", "fishnet", "70505022")):
                print(u)
        print("total responses", len(urls))
        await browser.close()


asyncio.run(main())
