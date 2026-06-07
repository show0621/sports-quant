"""Probe Taiwan sport lottery API from event page."""
from __future__ import annotations

import re
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

EVENT_URL = (
    "https://www.sportslottery.com.tw/sportsbook/sport/"
    "%E7%B1%83%E7%90%83/%E7%BE%8E%E5%9C%8B/%E7%BE%8E%E5%9C%8B%E8%81%B7%E7%B1%83/34801.1/event/3472877.1"
)
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-TW,zh;q=0.9",
}


def main() -> None:
    import re

    for root_url in (
        "https://www.sportslottery.com.tw/sportsbook/",
        "https://www.sportslottery.com.tw/",
    ):
        r = requests.get(root_url, timeout=45, headers=HEADERS)
        print("root", root_url, r.status_code, len(r.text))
        if r.status_code != 200:
            continue
        hits = re.findall(r"https?://[^\s\"'>]+\.json[^\s\"'>]*", r.text)
        for h in sorted(set(hits))[:40]:
            print(" json", h)
        for kw in ("apidata", "Register", "Live/On", "blob.sportslottery"):
            if kw.lower() in r.text.lower():
                print(" contains", kw)

    r = requests.get(EVENT_URL, timeout=45, headers=HEADERS)
    print("page", r.status_code, len(r.text))
    patterns = [
        r"https?://[^\"'\s>]+",
        r"blob[^\"'\s>]+",
        r"3472877[^\"'\s>]*",
        r"Register[^\"'\s>]+",
        r"Live/[^\"'\s>]+",
    ]
    for pat in patterns:
        hits = sorted(set(re.findall(pat, r.text, re.I)))
        if hits:
            print(f"\n--- {pat} ---")
            for h in hits[:30]:
                print(h)

    bases = [
        "https://blob.sportslottery.com.tw/apidata",
        "https://blob.sportslottery.com.tw",
        "https://www.sportslottery.com.tw/api",
    ]
    paths = [
        "Live/On.json",
        "Register/On.json",
        "Pre/On.json",
        "Off/On.json",
        "Event/3472877.json",
        "Events/On.json",
        "Sports/On.json",
    ]
    for base in bases:
        for p in paths:
            url = f"{base.rstrip('/')}/{p}"
            try:
                rr = requests.get(url, timeout=15, headers=HEADERS)
                if rr.status_code == 200 and len(rr.text) > 5:
                    print("HIT", url, len(rr.text), rr.text[:120])
            except Exception as exc:
                print("ERR", url, exc)


if __name__ == "__main__":
    main()
