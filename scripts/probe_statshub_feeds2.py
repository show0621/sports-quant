"""Dump fishnet/gismo URL construction from feeds bundle."""
from __future__ import annotations

import re
import urllib.request

BASE = "https://statshub.sportradar.com"
text = urllib.request.urlopen(
    urllib.request.Request(BASE + "/assets/feeds-Dw9H1J78.js", headers={"User-Agent": "Mozilla/5.0"}),
    timeout=30,
).read().decode("utf-8", "replace")

for kw in ["fishnet", "gismo", "fn.sportradar", "fishnetToken", "fishnetUserAgent", "match_stats", "match_squads", "match_playerdetails", "injuries", "lineup"]:
    print(kw, text.lower().count(kw.lower()))

# extract fn.sportradar urls
urls = sorted(set(re.findall(r"https://[a-z0-9./\-_]+", text)))
for u in urls:
    print("URL", u)

# find function fe( or fishnet base
for m in re.finditer(r"fishnet[A-Za-z]*", text):
    s = max(0, m.start()-80); e = min(len(text), m.end()+120)
    snippet = text[s:e].replace("\n"," ")
    if "Token" in snippet or "http" in snippet or "gismo" in snippet:
        print("SNIP:", snippet[:240])
