"""Extract gismo/feed URLs from StatsHub feeds bundle."""
from __future__ import annotations

import re
import urllib.request

BASE = "https://statshub.sportradar.com"
PATH = "/assets/feeds-Dw9H1J78.js"
text = urllib.request.urlopen(
    urllib.request.Request(BASE + PATH, headers={"User-Agent": "Mozilla/5.0"}),
    timeout=30,
).read().decode("utf-8", "replace")
print("len", len(text))
for pat in [
    r"https://[^\"']+",
    r"gismo[^\"']{0,120}",
    r"feed[^\"']{0,120}",
    r"match_[a-z_]+",
    r"70505022",
]:
    hits = sorted(set(re.findall(pat, text, flags=re.I)))
    if hits:
        print("\nPAT", pat, "count", len(hits))
        for h in hits[:25]:
            print(" ", h[:160])

# show context around 'gismo'
for m in re.finditer("gismo", text, re.I):
    start = max(0, m.start() - 120)
    end = min(len(text), m.end() + 200)
    print("\nCTX:", text[start:end].replace("\n", " ")[:320])
    if m.start() > 5000:
        break
