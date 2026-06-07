"""Probe StatsHub POST actions for feed/token refresh."""
from __future__ import annotations

import json
import re
import urllib.request

html = urllib.request.urlopen(
    urllib.request.Request(
        "https://statshub.sportradar.com/taiwansportslottery/zht/match/70505022/statistics",
        headers={"User-Agent": "Mozilla/5.0"},
    ),
    timeout=30,
).read().decode("utf-8", "replace")
# remix/react-router action paths
for pat in [r'action="([^"]+)"', r'"/[^"]*action[^"]*"', r"refreshToken", r"fishnetToken"]:
    hits = sorted(set(re.findall(pat, html)))
    if hits:
        print(pat, hits[:10])

text = urllib.request.urlopen(
    urllib.request.Request("https://statshub.sportradar.com/assets/root-1YqisYqT.js", headers={"User-Agent": "Mozilla/5.0"}),
    timeout=30,
).read().decode("utf-8", "replace")
for kw in ["refreshToken", "fishnetToken", "action/", "_action", "routes/_sh"]:
    if kw in text:
        i = text.find(kw)
        print(kw, text[i:i+200])
