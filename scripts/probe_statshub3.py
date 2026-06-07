"""Extract embedded JSON / API hints from StatsHub HTML."""
from __future__ import annotations

import json
import re
from pathlib import Path

import urllib.request

URL = "https://statshub.sportradar.com/taiwansportslottery/zht/match/70505022/report"
OUT = Path(__file__).resolve().parents[1] / "logs" / "statshub_report.html"

req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0"})
html = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(html, encoding="utf-8")
print("saved", OUT, "len", len(html))

for kw in ["70505022", "lineup", "injur", "starter", "player", "statistics", "api/", "graphql", "__NUXT", "__NEXT", "window.", "fetch("]:
    idx = html.lower().find(kw.lower())
    print(kw, "first@", idx)

# all script tags
for i, m in enumerate(re.finditer(r"<script[^>]*>(.*?)</script>", html, re.S)):
    body = m.group(1).strip()
    if len(body) < 40:
        continue
    if any(k in body.lower() for k in ("70505022", "lineup", "injur", "match", "player")):
        print(f"\n--- script #{i} len={len(body)} ---")
        print(body[:1500])

# link/modulepreload
for pat in [r'rel="modulepreload"[^>]+href="([^"]+)"', r'src="([^"]+\.js[^"]*)"', r'href="([^"]+\.js[^"]*)"']:
    hits = re.findall(pat, html)
    print(pat, len(hits))
    for h in hits[:10]:
        print(" ", h[:120])
