"""Search StatsHub JS bundles for backend API paths."""
from __future__ import annotations

import re
import urllib.request

BASE = "https://statshub.sportradar.com"
html = urllib.request.urlopen(
    urllib.request.Request(f"{BASE}/taiwansportslottery/zht/match/70505022/report", headers={"User-Agent": "Mozilla/5.0"}),
    timeout=30,
).read().decode("utf-8", "replace")
assets = sorted(set(re.findall(r'href="(/assets/[^"]+\.js)"', html)))
print("assets", len(assets))
patterns = []
for path in assets:
    url = BASE + path
    try:
        text = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=30).read().decode("utf-8", "replace")
    except Exception as exc:
        continue
    hits = set(re.findall(r'["\'](/(?:api|bff|data|proxy)[^"\']+)["\']', text))
    hits |= set(re.findall(r'https://[^"\']+sportradar[^"\']+', text))
    api_hits = [h for h in hits if "match" in h.lower() or "stat" in h.lower() or "lineup" in h.lower() or "injur" in h.lower() or "player" in h.lower()]
    if api_hits:
        print(path[-45:], len(api_hits))
        for h in sorted(api_hits)[:12]:
            print(" ", h[:130])
