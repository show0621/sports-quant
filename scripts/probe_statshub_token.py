"""Extract fishnetToken and feed names from StatsHub HTML stream."""
from __future__ import annotations

import json
import re
from pathlib import Path

html = Path(__file__).resolve().parents[1].joinpath("logs/statshub_report.html").read_text(encoding="utf-8")
for kw in ["fishnetToken", "fishnetHost", "fishnetBase", "fishnetUserAgent", "fishnet"]:
    print(kw, html.find(kw))

chunks = re.findall(r'window\.__reactRouterContext\.streamController\.enqueue\("((?:\\.|[^"])*)"\)', html)
text = "".join(bytes(c, "utf-8").decode("unicode_escape") for c in chunks)
arr = json.loads(text)
strings = [v for v in arr if isinstance(v, str) and ("fish" in v.lower() or "gismo" in v.lower() or "http" in v.lower())]
print("interesting strings", strings[:30])

# find token-like strings (long alphanumeric)
tokens = [v for v in arr if isinstance(v, str) and len(v) > 20 and len(v) < 80 and v.replace("-", "").replace("_", "").isalnum()]
print("token candidates", tokens[:10])
