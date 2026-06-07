"""Try Talo content/get with guessed contentId types for NBA event."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TALO = "https://www-talo-ssb-pr.sportslottery.com.tw/services/content/get"
EVENT = "3472877.1"
LEAGUE = "34801.1"
NAV = "34801.1"


def cookies_from_state(path: Path) -> dict[str, str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, str] = {}
    for c in data.get("cookies", []):
        out[c["name"]] = c["value"]
    return out


def try_post(cookies: dict[str, str], payload: dict) -> None:
    r = requests.post(
        TALO,
        json=payload,
        cookies=cookies,
        timeout=30,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131.0.0.0 Safari/537.36",
            "Content-Type": "application/json",
            "Origin": "https://www-talo-ssb-pr.sportslottery.com.tw",
            "Referer": "https://www-talo-ssb-pr.sportslottery.com.tw/sportsbook/",
        },
    )
    text = r.text
    keys = ("idfoevent", "3472877", "decimalprice", "currentprice", "foselection", "gamegroups", "尼克", "馬刺")
    hit = [k for k in keys if k.lower() in text.lower() or k in text]
    if hit or (r.status_code == 200 and len(text) > 500 and "bonavigation" not in text[:200]):
        print("HIT", payload["contentId"], "status", r.status_code, "len", len(text), "keys", hit)
        print(text[:1200])
        print("---")


def main() -> None:
    from sportsbet import config

    state = Path(config.SPORTSLOTTERY_PLAYWRIGHT_STATE_PATH)
    if not state.is_file():
        state = ROOT / "scripts" / "_talo_captures" / "state.json"
    cookies = cookies_from_state(state)
    ctx = {"language": "ZH", "ipAddress": "0.0.0.0"}

    types_ids = [
        ("foEvent", EVENT),
        ("foEvent", "3472877"),
        ("foEventDetail", EVENT),
        ("foEventMarkets", EVENT),
        ("event", EVENT),
        ("eventDetail", EVENT),
        ("gameGroup", EVENT),
        ("gameGroupList", LEAGUE),
        ("foEventList", LEAGUE),
        ("boNavigationList", NAV),
        ("boNavigationList", f"1355/{NAV}"),
        ("dailyCouponList", "BKB"),
        ("dailyCouponList", LEAGUE),
        ("dailyCouponEventList", "2026-06-09"),
        ("sportEventList", LEAGUE),
        ("marketGroupList", EVENT),
        ("selectionList", EVENT),
    ]
    for typ, cid in types_ids:
        try_post(cookies, {"contentId": {"type": typ, "id": cid}, "clientContext": ctx})


if __name__ == "__main__":
    main()
