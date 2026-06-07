"""Brute common sportslottery internal API paths."""
from __future__ import annotations

import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

EVENT_ID = "3472877"
LEAGUE_ID = "34801"
HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json",
    "Referer": "https://www.sportslottery.com.tw/sportsbook/",
}

BASES = [
    "https://www.sportslottery.com.tw/api",
    "https://www.sportslottery.com.tw/sportsbook/api",
    "https://api.sportslottery.com.tw",
]


def main() -> None:
    paths = [
        f"/services/app/LiveGames/GetLiveOnAndRegister?isContainRegister=true",
        f"/services/app/RegisterGames/GetRegisterOn",
        f"/sportsbook/events/{EVENT_ID}",
        f"/events/{EVENT_ID}",
        f"/event/{EVENT_ID}",
        f"/v1/events/{EVENT_ID}",
        f"/v2/events/{EVENT_ID}",
        f"/SportsBook/Event/{EVENT_ID}",
        f"/SportsBook/Events/{EVENT_ID}/Odds",
        f"/leagues/{LEAGUE_ID}/events",
        f"/leagues/{LEAGUE_ID}/events/{EVENT_ID}",
    ]
    for base in BASES:
        for path in paths:
            url = base + path
            try:
                r = requests.get(url, timeout=15, headers=HEADERS)
                if r.status_code == 200 and len(r.text) > 20 and "cf-chl" not in r.text[:200]:
                    print("OK", url, len(r.text), r.text[:180])
                elif r.status_code not in (403, 404):
                    print(r.status_code, url, r.text[:80])
            except Exception as exc:
                print("ERR", url, exc)


if __name__ == "__main__":
    main()
