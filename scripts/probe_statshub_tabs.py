"""Extract tab/query config from StatsHub tabs bundle."""
from __future__ import annotations

import re
import urllib.request

BASE = "https://statshub.sportradar.com"
for path in ("/assets/tabs.config-BHY3UqYx.js", "/assets/_report-pIDOmK3V.js", "/assets/clientFetching-DCKJzxMm.js"):
    text = urllib.request.urlopen(
        urllib.request.Request(BASE + path, headers={"User-Agent": "Mozilla/5.0"}),
        timeout=30,
    ).read().decode("utf-8", "replace")
    print("\n===", path, "len", len(text), "===")
    for pat in [r"match_[a-zA-Z0-9_\-]+", r"queryKey[^;]{0,120}", r"fetch[A-Za-z]+\([^)]{0,80}\)"]:
        hits = sorted(set(re.findall(pat, text)))
        for h in hits[:20]:
            print(" ", h[:160])
