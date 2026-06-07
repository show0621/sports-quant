"""Find how fishnet token is appended to URLs."""
from __future__ import annotations

import re
import urllib.request

text = urllib.request.urlopen(
    urllib.request.Request(
        "https://statshub.sportradar.com/assets/feeds-Dw9H1J78.js",
        headers={"User-Agent": "Mozilla/5.0"},
    ),
    timeout=30,
).read().decode("utf-8", "replace")

# locate fe=function or const fe=
for name in ["function fe", "fe=(", "fe=function", "fishnetToken", "Authorization", "x-fishnet"]:
    idx = text.find(name)
    print(name, idx)
    if idx >= 0:
        print(text[idx:idx+400])

# search token query param patterns
for pat in [r"token[^;]{0,120}", r"Referer[^;]{0,80}", r"origincheck[^;]{0,120}"]:
    hits = sorted(set(re.findall(pat, text, re.I)))
    for h in hits[:10]:
        print("HIT", h[:160])
