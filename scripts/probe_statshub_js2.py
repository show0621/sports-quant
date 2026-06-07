"""Search StatsHub JS assets for fetch URLs."""
from __future__ import annotations

import re
import urllib.request
from pathlib import Path

BASE = "https://statshub.sportradar.com"
html = Path(__file__).resolve().parents[1].joinpath("logs/statshub_report.html").read_text(encoding="utf-8")
assets = sorted(set(re.findall(r'href="(/assets/[^"]+\.js)"', html)))
needles = (
    "match_statistics", "match_lineup", "matchLineup", "match_report",
    "gismo", "graphql", "queryFn", "fetcher", "loader", "/bff/",
    "injuries", "lineups", "playerStatistics", "teamStatistics",
    "statshub", "70505022",
)
found: dict[str, list[str]] = {}
for path in assets:
    url = BASE + path
    try:
        text = urllib.request.urlopen(
            urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=20,
        ).read().decode("utf-8", "replace")
    except Exception:
        continue
    hits = [n for n in needles if n.lower() in text.lower()]
    if hits:
        found[path] = hits

for path, hits in sorted(found.items(), key=lambda x: -len(x[1]))[:25]:
    print(path[-55:], hits)

# deep scan a few high-value bundles
for path in [p for p, h in found.items() if "match" in "".join(h).lower()][:5]:
    text = urllib.request.urlopen(BASE + path, timeout=20).read().decode("utf-8", "replace")
    urls = sorted(set(re.findall(r"https://[a-zA-Z0-9./_\-?=&]+", text)))
    rel = sorted(set(re.findall(r'["\'](/[a-zA-Z0-9./_\-?=&]+)["\']', text)))
    print("\nFILE", path)
    for u in urls[:20]:
        if "sportradar" in u:
            print(" abs", u[:140])
    for u in rel[:30]:
        if any(x in u for x in ("api", "bff", "data", "match", "stat", "gismo")):
            print(" rel", u[:140])
