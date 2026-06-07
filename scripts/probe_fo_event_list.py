import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from playwright.sync_api import sync_playwright

from sportsbet import config
from sportsbet.data.sportslottery_web import _accept_cookies, _talo_frame, league_url

state = config.SPORTSLOTTERY_PLAYWRIGHT_STATE_PATH
with sync_playwright() as p:
    b = p.chromium.launch(headless=False, args=["--disable-blink-features=AutomationControlled"])
    opts = {"user_agent": "Mozilla/5.0", "locale": "zh-TW", "viewport": {"width": 1400, "height": 900}}
    if Path(state).is_file():
        opts["storage_state"] = state
    ctx = b.new_context(**opts)
    page = ctx.new_page()
    page.goto("https://www.sportslottery.com.tw/sportsbook/", timeout=120000)
    page.wait_for_timeout(3000)
    _accept_cookies(page)
    page.goto(league_url("nba"), timeout=120000)
    page.wait_for_timeout(15000)
    fr = _talo_frame(page)
    for typ, cid in (
        ("foEventList", "34801.1"),
        ("foEventList", "25793"),
        ("eventCouponList", "34801.1"),
        ("matchCouponList", "60067.1"),
    ):
        t = fr.evaluate(
            """async ([typ, cid]) => {
                const r = await fetch('/services/content/get', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        contentId: {type: typ, id: cid},
                        clientContext: {language: 'ZH', ipAddress: '0.0.0.0'},
                    }),
                });
                return await r.text();
            }""",
            [typ, cid],
        )
        print(typ, cid, "len", len(t), "3472877" in t, "error" in t)
        if "3472877" in t or ("idfoevent" in t and "errorType" not in t):
            print(t[:1500])
            print("---")
    b.close()
