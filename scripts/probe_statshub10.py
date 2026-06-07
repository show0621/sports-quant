"""Inspect decoded indices 420+ for report tab widgets."""
from __future__ import annotations

import json
from pathlib import Path

from probe_statshub7 import decode, load_arr

arr = load_arr("report")
for idx in [420, 421, 423, 44, 417, 419, 650, 568]:
    obj = decode(arr, idx)
    path = Path(f"logs/statshub_idx_{idx}.json")
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    print(idx, type(obj).__name__, "keys" if isinstance(obj, dict) else str(obj)[:80])
    if isinstance(obj, dict):
        print(" ", list(obj.keys())[:15])
