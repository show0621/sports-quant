"""Use Playwright browser context to POST content/get (bypass CF)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

EVENT = "3472877.1"
LEAGUE = "34801.1"
WWW_EVENT = (
    "https://www.sportslottery.com.tw/sportsbook/sport/"
    "%E7%B1%83%E7%90%83/%E7%BE%8E%E5%9C%8B/%E7%BE%8E%E5%9C%8B%E8%81%B7%E7%B1%83/34801.1/event/3472877.1"
)


def main() -> None:
    from playwright.sync_api import sync_playwright

    from sportsbet import config

    state = config.SPORTSLOTTERY_PLAYWRIGHT_STATE_PATH
    types_ids = [
        ("foEvent", EVENT),
        ("foEventDetail", EVENT),
        ("foEventMarkets", EVENT),
        ("gameGroup", EVENT),
        ("gameGroupList", LEAGUE),
        ("foEventList", LEAGUE),
        ("dailyCouponEventList", "2026-06-09"),
        ("sportEventList", LEAGUE),
        ("marketGroupList", EVENT),
        ("boNavigationList", LEAGUE),
        ("boNavigationList", f"1355/{LEAGUE}"),
    ]

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, args=["--disable-blink-features=AutomationControlled"])
        ctx_opts = {
            "user_agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
            "locale": "zh-TW",
        }
        if Path(state).is_file():
            ctx_opts["storage_state"] = state
        context = browser.new_context(**ctx_opts)
        page = context.new_page()
        page.goto("https://www-talo-ssb-pr.sportslottery.com.tw/sportsbook/", wait_until="load", timeout=120000)
        page.wait_for_timeout(8000)

        for typ, cid in types_ids:
            result = page.evaluate(
                """async ([typ, cid]) => {
                    const r = await fetch('/services/content/get', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({
                            contentId: {type: typ, id: cid},
                            clientContext: {language: 'ZH', ipAddress: '0.0.0.0'}
                        })
                    });
                    const t = await r.text();
                    return {status: r.status, len: t.length, head: t.slice(0, 1500)};
                }""",
                [typ, cid],
            )
            text = result["head"]
            keys = ("idfoevent", "3472877", "decimalprice", "currentprice", "foselection", "gamegroups", "尼克", "馬刺", "market")
            hit = [k for k in keys if k.lower() in text.lower() or k in text]
            if hit or (result["status"] == 200 and result["len"] > 400 and "bonavigationnodes" not in text[:300]):
                print(f"HIT {typ}/{cid} status={result['status']} len={result['len']} keys={hit}")
                print(text[:1500])
                print("---")

        # event page iframe scrape
        print("\n=== www event page ===")
        page.goto(WWW_EVENT, wait_until="load", timeout=120000)
        page.wait_for_timeout(60000)
        for i, fr in enumerate(page.frames):
            try:
                t = fr.inner_text("body")
                if len(t) > 300:
                    print(f"frame[{i}] {fr.url[:80]} len={len(t)}")
                    for kw in ("尼克", "馬刺", "1.75", "不讓分", "讓分"):
                        if kw in t:
                            print(f"  has {kw}")
                    if "1." in t or "尼克" in t:
                        Path(ROOT / "scripts/_talo_captures/www_event_frame.txt").write_text(t[:15000], encoding="utf-8")
            except Exception:
                pass

        context.storage_state(path=state)
        browser.close()


if __name__ == "__main__":
    main()
