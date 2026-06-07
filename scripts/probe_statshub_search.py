"""Probe StatsHub search for match id discovery."""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request

from probe_statshub7 import decode

queries = ["Knicks", "Spurs", "尼克", "馬刺"]
for q in queries:
    url = "https://statshub.sportradar.com/taiwansportslottery/zht/search?" + urllib.parse.urlencode({"q": q})
    html = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=30).read().decode()
    chunks = re.findall(r'window\.__reactRouterContext\.streamController\.enqueue\("((?:\\.|[^"])*)"\)', html)
    if not chunks:
        print(q, "no stream", len(html))
        continue
    arr = json.loads("".join(bytes(c, "utf-8").decode("unicode_escape") for c in chunks))
    s = json.dumps(decode(arr, 0), ensure_ascii=False)
    ids = re.findall(r'"_id"\s*:\s*(\d{6,})', s)
    print(q, "ids", ids[:10], "match refs", re.findall(r'match/\d+', s)[:5])
