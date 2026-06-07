"""Test session-based fishnet fetch after StatsHub page load."""
from __future__ import annotations

import json
import re
import urllib.parse

import requests

MATCH = "70505022"
TENANT = "taiwansportslottery"
page_url = f"https://statshub.sportradar.com/{TENANT}/zht/match/{MATCH}/statistics"

s = requests.Session()
s.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
})
html = s.get(page_url, timeout=30).text
chunks = re.findall(
    r'window\.__reactRouterContext\.streamController\.enqueue\("((?:\\.|[^"])*)"\)',
    html,
)
from probe_statshub7 import decode

arr = json.loads("".join(bytes(c, "utf-8").decode("unicode_escape") for c in chunks))
cctx = decode(arr, 6)["cctx"]
token = cctx["fishnetToken"]
base = cctx["fishnetUrl"].rstrip("/")
alias = cctx["fishnetClientAlias"]

for feed in ["match_stats", "match_squads", "match_playerdetails", "match_details"]:
    url = f"{base}/{alias}/zht/Asia/Taipei/gismo/{feed}/{MATCH}?T={urllib.parse.quote(token, safe='')}"
    r = s.get(
        url,
        headers={
            "Referer": page_url,
            "Origin": "https://statshub.sportradar.com",
            "Accept": "application/json",
        },
        timeout=25,
    )
    print(feed, r.status_code, r.text[:180].replace("\n", " "))
