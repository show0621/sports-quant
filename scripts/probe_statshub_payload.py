"""Full decode of report route payload."""
from __future__ import annotations

import json
from pathlib import Path

from probe_statshub7 import decode, load_arr

arr = load_arr("statistics")
payload = decode(arr, 12)
Path("../logs/statshub_statistics_payload.json").write_text(
    json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8",
)
mi = payload.get("matchInfo", {})
print("matchInfo keys", list(mi.keys()) if isinstance(mi, dict) else mi)
data = mi.get("data") if isinstance(mi, dict) else None
print("data type", type(data).__name__)
if isinstance(data, dict):
    print("data keys", list(data.keys())[:20])

# walk for squads/lineups/stats in entire payload
text = json.dumps(payload, ensure_ascii=False)
for kw in ["lineup", "injur", "starter", "playerstats", "matchstats", "squads", "statistics"]:
    print(kw, text.lower().count(kw))
