"""Try Sportradar fishnet gismo feeds for match 70505022."""
from __future__ import annotations

import json
import urllib.parse
import urllib.request

from probe_statshub7 import decode, load_arr

arr = load_arr("report")
root = decode(arr, 6)
cctx = root["cctx"]
base = cctx["fishnetUrl"].rstrip("/")
alias = cctx["fishnetClientAlias"]
token = cctx["fishnetToken"]
lang = "zht"
tz = "Asia/Taipei"
match_id = "70505022"

feeds = [
    "match_info",
    "match_stats",
    "match_squads",
    "match_playerdetails",
    "match_timeline",
    "match_details",
    "match_detailsextended",
    "match_form",
    "stats_season_teamstats",
    "stats_season_playerstats",
    "stats_teamstats",
    "stats_playerstats",
]

patterns = [
    f"{base}/{alias}/{lang}/{tz}/gismo/match/{match_id}",
    f"{base}/{alias}/{lang}/agnostic/gismo/match/{match_id}",
]
for feed in feeds:
    patterns.append(f"{base}/{alias}/{lang}/{tz}/gismo/{feed}/{match_id}")
    patterns.append(f"{base}/{alias}/{lang}/agnostic/gismo/{feed}/{match_id}")

headers = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json",
    "X-Requested-With": "XMLHttpRequest",
    "Authorization": token,
    "x-fishnet-token": token,
}

for url in patterns:
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = resp.read(500).decode("utf-8", "replace")
            print(resp.status, url.split("/gismo/")[-1][:60], body[:120].replace("\n", " "))
    except Exception as exc:
        msg = str(exc)
        if hasattr(exc, "read"):
            try:
                msg = exc.read(200).decode("utf-8", "replace")  # type: ignore[attr-defined]
            except Exception:
                pass
        print("ERR", url.split("/gismo/")[-1][:60], msg[:120])
