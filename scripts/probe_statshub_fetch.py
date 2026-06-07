"""Extract fetch helper _e from feeds.js."""
from __future__ import annotations

import re
import urllib.request

text = urllib.request.urlopen(
    urllib.request.Request("https://statshub.sportradar.com/assets/feeds-Dw9H1J78.js", headers={"User-Agent": "Mozilla/5.0"}),
    timeout=30,
).read().decode("utf-8", "replace")

for m in re.finditer(r"function _e\(", text):
    print(text[m.start():m.start()+800])

for m in re.finditer(r"function ee\(", text):
    print("\nee:\n", text[m.start():m.start()+600])
