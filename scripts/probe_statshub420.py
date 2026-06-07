"""Inspect report route index 420 payload."""
from __future__ import annotations

import json
from pathlib import Path

from probe_statshub7 import decode, load_arr

arr = load_arr("report")
for idx in [420, 421, 423, 650, 568, 570]:
    obj = decode(arr, idx)
    p = Path(__file__).resolve().parents[1] / "logs" / f"idx_{idx}.json"
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2)[:50000], encoding="utf-8")
    print(idx, type(obj).__name__, len(json.dumps(obj, ensure_ascii=False)))

text = json.dumps(decode(arr, 420), ensure_ascii=False)
for kw in ["missing", "lineup", "injur", "player", "stat", "points", "starter"]:
    print(kw, kw in text.lower())
