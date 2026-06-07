"""Find fishnet config in StatsHub root/client bundles."""
from __future__ import annotations

import re
import urllib.request

BASE = "https://statshub.sportradar.com"
paths = [
    "/assets/root-1YqisYqT.js",
    "/assets/_root-DgfxFXe7.js",
    "/assets/cctx-COjvLmDL.js",
    "/clients/taiwansportslottery/config.json",
    "/clients/taiwansportslottery/config.js",
]
for path in paths:
    url = BASE + path
    try:
        text = urllib.request.urlopen(
            urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=20,
        ).read().decode("utf-8", "replace")
    except Exception as exc:
        print(path, "ERR", exc)
        continue
    print("\n===", path, "len", len(text), "===")
    if path.endswith(".json") or "fishnet" in text.lower() or "gismo" in text.lower():
        print(text[:2000])
    for kw in ["fishnet", "gismo", "fishnetToken", "fishnetHost", "fishnetBase"]:
        if kw.lower() in text.lower():
            for m in re.finditer(kw, text, re.I):
                s=max(0,m.start()-100); e=min(len(text), m.end()+180)
                print(text[s:e].replace("\n"," ")[:260])
