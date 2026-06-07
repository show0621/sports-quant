"""Deep scrape event page: iframe + DOM + all network."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

EVENT_WWW = (
    "https://www.sportslottery.com.tw/sportsbook/sport/"
    "%E7%B1%83%E7%90%83/%E7%BE%8E%E5%9C%8B/%E7%BE%8E%E5%9C%8B%E8%81%B7%E7%B1%83/34801.1/event/3472877.1"
)
EVENT_TALO = (
    "https://www-talo-ssb-pr.sportslottery.com.tw/sportsbook/sport/"
    "%E7%B1%83%E7%90%83/%E7%BE%8E%E5%9C%8B/%E7%BE%8E%E5%9C%8B%E8%81%B7%E7%B1%83/34801.1/event/3472877.1"
)


def scrape_url(url: str, state_path: str) -> None:
    from playwright.sync_api import sync_playwright

    payloads: list[tuple[str, str]] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        ctx = browser.new_context(
            storage_state=state_path if Path(state_path).is_file() else None,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131.0.0.0 Safari/537.36",
            locale="zh-TW",
            viewport={"width": 1400, "height": 900},
        )
        page = ctx.new_page()

        def grab(r):
            u = r.url
            if any(x in u for x in ("/services", "apidata", "poseidon")):
                try:
                    t = r.text()
                except Exception:
                    return
                if t and (t.startswith("{") or t.startswith("[")):
                    payloads.append((u, t))

        page.on("response", grab)
        page.goto(url, wait_until="load", timeout=120000)
        page.wait_for_timeout(60000)

        text = page.inner_text("body")
        html = page.content()
        frames_text = []
        for i, fr in enumerate(page.frames):
            try:
                ft = fr.inner_text("body")[:5000]
                frames_text.append((i, fr.url[:80], len(ft), ft[:500]))
            except Exception:
                pass

        # try click 不讓分 / 讓分 tabs if present
        for label in ("不讓分", "讓分", "大小", "Moneyline", "Spread", "Total"):
            try:
                loc = page.get_by_text(label, exact=False).first
                if loc.count() and loc.is_visible(timeout=1000):
                    loc.click()
                    page.wait_for_timeout(3000)
            except Exception:
                pass

        text2 = page.inner_text("body")
        ctx.storage_state(path=state_path)
        browser.close()

    out = ROOT / "scripts" / "_talo_captures"
    tag = "talo" if "talo" in url else "www"
    (out / f"deep_{tag}_body.txt").write_text(text2, encoding="utf-8")
    print(f"=== {tag} body len {len(text2)} odds {sorted(set(re.findall(r'1\\.\\d{2}', text2)))[:15]}")
    for kw in ("尼克", "馬刺", "Knicks", "Spurs", "不讓分", "讓分", "大小"):
        print(kw, kw in text2)
    print("frames:", len(frames_text))
    for i, u, ln, snip in frames_text[:5]:
        print(f" frame[{i}] {u} len={ln}")
        if "1." in snip or "尼克" in snip:
            print(snip[:400])

    hits = 0
    for i, (u, t) in enumerate(payloads):
        if re.search(r"idfoevent|3472877|decimalprice|currentprice|marketgroup|selection", t, re.I):
            hits += 1
            path = out / f"deep_{tag}_svc_{i}.json"
            path.write_text(t, encoding="utf-8")
            print(f"HIT svc[{i}] {u[:90]} len={len(t)}")
            print(t[:800])
    print(f"total payloads {len(payloads)} hits {hits}")


def main() -> None:
    from sportsbet import config

    state = config.SPORTSLOTTERY_PLAYWRIGHT_STATE_PATH
    scrape_url(EVENT_WWW, state)
    scrape_url(EVENT_TALO, state)


if __name__ == "__main__":
    main()
