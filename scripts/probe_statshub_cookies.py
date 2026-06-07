"""Retry fishnet with all cookies from StatsHub session."""
from __future__ import annotations

import json
import re
import urllib.parse

import requests

from probe_statshub7 import decode

MATCH = "70505022"
page = f"https://statshub.sportradar.com/taiwansportslottery/zht/match/{MATCH}/statistics"
s = requests.Session()
s.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
html = s.get(page, timeout=30).text
print("page", len(html), "cookies", dict(s.cookies))
chunks = re.findall(r'window\.__reactRouterContext\.streamController\.enqueue\("((?:\\.|[^"])*)"\)', html)
arr = json.loads("".join(bytes(c, "utf-8").decode("unicode_escape") for c in chunks))
cctx = decode(arr, 6)["cctx"]
token = cctx["fishnetToken"]
base = cctx["fishnetUrl"].rstrip("/")
alias = cctx["fishnetClientAlias"]
url = f"{base}/{alias}/zht/Asia/Taipei/gismo/match_stats/{MATCH}?T={urllib.parse.quote(token, safe='')}"
r = s.get(url, headers={"Referer": page, "Origin": "https://statshub.sportradar.com"}, timeout=25)
print("fishnet", r.status_code, r.text[:250])
