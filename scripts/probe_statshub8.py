"""List all queryKey strings and _doc types in StatsHub stream."""
from __future__ import annotations

import json
import re
import urllib.request

def load(page: str):
    url = f"https://statshub.sportradar.com/taiwansportslottery/zht/match/70505022/{page}"
    html = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=30).read().decode()
    chunks = re.findall(r'window\.__reactRouterContext\.streamController\.enqueue\("((?:\\.|[^"])*)"\)', html)
    return json.loads("".join(bytes(c, "utf-8").decode("unicode_escape") for c in chunks))

for page in ("report", "statistics"):
    arr = load(page)
    qkeys = [v for v in arr if isinstance(v, str) and v.startswith("match_")]
    docs = [v for v in arr if isinstance(v, str) and v in ("lineups", "statistics", "injuries", "players", "match_lineup", "match_statistics", "team_statistics", "player_statistics")]
    print(page, "queryKeys", qkeys[:30], "count", len(qkeys))
    print(page, "docs", docs[:30])
    # any dict keys containing lineup
    for i, v in enumerate(arr):
        if isinstance(v, str) and ("lineup" in v.lower() or "injur" in v.lower() or "statistic" in v.lower()):
            if len(v) < 80:
                print(i, v)
