"""Capture Talo POST /services requests + iframe DOM."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TALO_EVENT = (
    "https://www-talo-ssb-pr.sportslottery.com.tw/sportsbook/sport/"
    "%E7%B1%83%E7%90%83/%E7%BE%8E%E5%9C%8B/%E7%BE%8E%E5%9C%8B%E8%81%B7%E7%B1%83/34801.1/event/3472877.1"
)
TALO_LEAGUE = (
    "https://www-talo-ssb-pr.sportslottery.com.tw/sportsbook/sport/"
    "%E7%B1%83%E7%90%83/%E7%BE%8E%E5%9C%8B/%E7%BE%8E%E5%9C%8B%E8%81%B7%E7%B1%83/34801.1"
)
DAILY = "https://www.sportslottery.com.tw/sportsbook/daily-coupons"
OUT = ROOT / "scripts" / "_talo_captures"


def main() -> None:
    from playwright.sync_api import sync_playwright

    from sportsbet import config

    OUT.mkdir(exist_ok=True)
    state = config.SPORTSLOTTERY_PLAYWRIGHT_STATE_PATH
    posts: list[tuple[str, str, str]] = []
    responses: list[tuple[str, str, int]] = []

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

        def on_request(req) -> None:
            url = req.url
            if "/services" in url and req.method == "POST":
                try:
                    body = req.post_data or ""
                except Exception:
                    body = ""
                posts.append((req.method, url, body))

        def on_response(resp) -> None:
            url = resp.url
            if "/services" not in url:
                return
            try:
                body = resp.text()
            except Exception:
                return
            if body.startswith("{"):
                responses.append((url, body, len(body)))

        page.on("request", on_request)
        page.on("response", on_response)

        for label, url in (
            ("talo_event", TALO_EVENT),
            ("talo_league", TALO_LEAGUE),
            ("daily", DAILY),
        ):
            print(f"\n=== goto {label} ===")
            page.goto(url, wait_until="domcontentloaded", timeout=120000)
            page.wait_for_timeout(45000)
            text = page.inner_text("body")
            odds = sorted(set(re.findall(r"\b1\.\d{2}\b", text)))
            print(f"body len={len(text)} odds={odds[:12]}")
            for kw in ("尼克", "馬刺", "不讓分", "讓分", "大小"):
                print(f"  {kw}: {kw in text}")

            for i, fr in enumerate(page.frames):
                try:
                    ft = fr.inner_text("body")
                    if len(ft) > 200 and ("1." in ft or "尼克" in ft or "馬刺" in ft):
                        print(f"  frame[{i}] url={fr.url[:70]} len={len(ft)}")
                        (OUT / f"frame_{label}_{i}.txt").write_text(ft[:12000], encoding="utf-8")
                except Exception:
                    pass

        context.storage_state(path=state)
        browser.close()

    print(f"\nPOSTs={len(posts)} responses={len(responses)}")
    for i, (m, url, body) in enumerate(posts[:20]):
        print(f"POST[{i}] {url[:90]} body_len={len(body)}")
        if body:
            (OUT / f"post_{i}.json").write_text(body, encoding="utf-8")
            print(body[:500])

    for i, (url, body, n) in enumerate(responses):
        if re.search(r"idfoevent|3472877|decimalprice|currentprice|foselection|gamegroups", body, re.I):
            path = OUT / f"resp_hit_{i}.json"
            path.write_text(body, encoding="utf-8")
            print(f"HIT resp[{i}] {url[:80]} len={n}")
            print(body[:1000])


if __name__ == "__main__":
    main()
