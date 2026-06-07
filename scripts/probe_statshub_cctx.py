"""Search cctx bundle for fishnetUserAgent and fetch proxy."""
from __future__ import annotations

import re
import urllib.request

for path in ("/assets/cctx-COjvLmDL.js", "/assets/feeds-Dw9H1J78.js"):
    text = urllib.request.urlopen(
        urllib.request.Request("https://statshub.sportradar.com" + path, headers={"User-Agent": "Mozilla/5.0"}),
        timeout=30,
    ).read().decode("utf-8", "replace")
    print("\n===", path, "===")
    for kw in ["fishnetUserAgent", "feeds/cache", "proxy", "Unauthorized", "origincheck", "hostheader"]:
        if kw.lower() in text.lower():
            for m in re.finditer(kw, text, re.I):
                s=max(0,m.start()-80); e=min(len(text), m.end()+160)
                print(text[s:e].replace("\n"," ")[:240])
