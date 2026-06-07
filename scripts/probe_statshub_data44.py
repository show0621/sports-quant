"""Decode matchInfo data index 44 from report/statistics streams."""
from __future__ import annotations

import json
from pathlib import Path

from probe_statshub7 import decode, load_arr

for page in ("report", "statistics"):
    arr = load_arr(page)
    data = decode(arr, 44)
    out = Path(__file__).resolve().parents[1] / "logs" / f"statshub_data44_{page}.json"
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(page, "type", type(data).__name__)
    if isinstance(data, dict):
        print(" keys", list(data.keys())[:20])
        doc = data.get("doc") or data.get("_doc")
        print(" doc", doc)
        if isinstance(data.get("match"), dict):
            print(" match keys", list(data["match"].keys())[:15])
