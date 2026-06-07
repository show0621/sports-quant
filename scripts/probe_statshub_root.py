"""Decode root loader cctx from StatsHub."""
from __future__ import annotations

import json
from pathlib import Path

from probe_statshub7 import decode, load_arr

arr = load_arr("report")
root_payload = decode(arr, 6)  # loaderData.root
Path("../logs/statshub_root.json").write_text(
    json.dumps(root_payload, ensure_ascii=False, indent=2), encoding="utf-8",
)
print("root keys", list(root_payload.keys()) if isinstance(root_payload, dict) else root_payload)
if isinstance(root_payload, dict):
    cctx = root_payload.get("cctx") or root_payload.get("loaderData")
    print("cctx type", type(cctx))
    if isinstance(cctx, dict):
        for k in cctx:
            if "fish" in k.lower() or "token" in k.lower() or "host" in k.lower() or "gismo" in k.lower():
                print(k, cctx[k])
