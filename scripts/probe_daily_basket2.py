import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from playwright.sync_api import sync_playwright

from sportsbet import config
from sportsbet.data.sportslottery_web import _extract_event_ids_from_html, _talo_frame

state = config.SPORTSLOTTERY_PLAYWRIGHT_STATE_PATH
with sync_playwright() as p:
    b = p.chromium.launch(headless=False, args=["--disable-blink-features=AutomationControlled"])
    opts = {"user_agent": "Mozilla/5.0", "locale": "zh-TW", "viewport": {"width": 1400, "height": 900}}
    if Path(state).is_file():
        opts["storage_state"] = state
    ctx = b.new_context(**opts)
    page = ctx.new_page()
    page.goto("https://www.sportslottery.com.tw/sportsbook/daily-coupons", timeout=120000)
    page.wait_for_timeout(25000)
    fr = _talo_frame(page)
    try:
        fr.locator("span", has_text="籃球").first.click(force=True, timeout=5000)
        fr.wait_for_timeout(8000)
        print("clicked basket")
    except Exception as exc:
        print("click err", exc)
    html = fr.content()
    text = fr.inner_text("body")
    print("ids", _extract_event_ids_from_html(html))
    for ln in text.splitlines():
        if "尼克" in ln or "馬刺" in ln:
            print("line", ln)
    print("odds", re.findall(r"\d\.\d{2}", text)[:10])
    b.close()
