"""Test gismo feeds with ?T= token query param."""
from __future__ import annotations

import json
import urllib.request

from probe_statshub7 import decode, load_arr

arr = load_arr("report")
cctx = decode(arr, 6)["cctx"]
base = cctx["fishnetUrl"].rstrip("/")
alias = cctx["fishnetClientAlias"]
token = cctx["fishnetToken"]
ua = cctx.get("fishnetUserAgent") or "StatsHub/1.0"
match_id = "70505022"
lang = "zht"
tz = "Asia/Taipei"

feeds = ["match_info", "match_stats", "match_squads", "match_playerdetails", "match_details", "match_detailsextended"]

for feed in feeds:
    path = f"/{alias}/{lang}/{tz}/gismo/{feed}/{match_id}"
    url = f"{base}{path}?T={urllib.request.quote(token, safe='')}"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": ua,
            "Accept": "application/json",
            "Referer": "https://statshub.sportradar.com/",
            "Origin": "https://statshub.sportradar.com",
        },
    )
    try:
        body = urllib.request.urlopen(req, timeout=25).read().decode("utf-8", "replace")
        data = json.loads(body)
        doc = data.get("doc") or data
        preview = json.dumps(doc, ensure_ascii=False)[:200]
        print("OK", feed, preview)
        if feed == "match_stats":
            open("../logs/gismo_match_stats.json", "w", encoding="utf-8").write(json.dumps(data, ensure_ascii=False, indent=2))
        if feed == "match_squads":
            open("../logs/gismo_match_squads.json", "w", encoding="utf-8").write(json.dumps(data, ensure_ascii=False, indent=2))
    except Exception as exc:
        err = str(exc)
        if hasattr(exc, "read"):
            err = exc.read(300).decode("utf-8", "replace")  # type: ignore[attr-defined]
        print("ERR", feed, err[:180])
