"""Try StatsHub-hosted feed proxy paths."""
from __future__ import annotations

import json
import urllib.parse
import urllib.request

from probe_statshub7 import decode, load_arr

cctx = decode(load_arr("report"), 6)["cctx"]
alias = cctx["fishnetClientAlias"]
token = cctx["fishnetToken"]
match_id = "70505022"
lang = "zht"
tz = "Asia/Taipei"
feed = "match_stats"

candidates = [
    f"https://statshub.sportradar.com/{alias}/{lang}/{tz}/gismo/{feed}/{match_id}?T={urllib.parse.quote(token, safe='')}",
    f"https://statshub.sportradar.com/{alias}/feeds/{feed}/{match_id}",
    f"https://statshub.sportradar.com/{alias}/feeds/cache/{feed}/{match_id}",
    f"https://statshub.sportradar.com/feeds/cache/{alias}/{lang}/{tz}/gismo/{feed}/{match_id}",
    f"https://statshub.sportradar.com/api/feeds/{feed}/{match_id}",
    f"https://statshub.sportradar.com/{alias}/api/gismo/{feed}/{match_id}",
]

headers = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json",
    "Referer": f"https://statshub.sportradar.com/{alias}/zht/match/{match_id}/statistics",
}

for url in candidates:
    req = urllib.request.Request(url, headers=headers)
    try:
        body = urllib.request.urlopen(req, timeout=20).read()[:300].decode("utf-8", "replace")
        print("OK", url.replace(token[:20], "TOKEN")[:120], body[:120])
    except Exception as exc:
        err = str(exc)
        if hasattr(exc, "read"):
            err = exc.read(200).decode("utf-8", "replace")  # type: ignore[attr-defined]
        print("ERR", url.split("sportradar.com")[-1][:80], err[:100])
