"""Debug RR array indices around dehydratedState."""
from __future__ import annotations

import json
import re
import urllib.request

URL = "https://statshub.sportradar.com/taiwansportslottery/zht/match/70505022/report"
req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0"})
html = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")
chunks = re.findall(
    r"window\.__reactRouterContext\.streamController\.enqueue\(\"((?:\\.|[^\"])*)\"\)",
    html,
)
text = "".join(bytes(c, "utf-8").decode("unicode_escape") for c in chunks)
arr = json.loads(text)
print("len", len(arr))
for i in range(min(30, len(arr))):
    v = arr[i]
    t = type(v).__name__
    s = str(v)
    if len(s) > 120:
        s = s[:120] + "..."
    print(i, t, s)

# find index of dehydratedState string
for i, v in enumerate(arr):
    if v == "dehydratedState":
        print("dehydratedState at", i, "next", arr[i + 1] if i + 1 < len(arr) else None)

for i, v in enumerate(arr):
    if isinstance(v, str) and "70505022" in v:
        print("match ref", i, v)
