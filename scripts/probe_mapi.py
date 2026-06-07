"""Probe Sportradar MAPI with key from StatsHub cctx."""
from __future__ import annotations

import json
import urllib.parse
import urllib.request

from probe_statshub7 import decode, load_arr

cctx = decode(load_arr("report"), 6)["cctx"]
base = cctx["mapiUrl"].rstrip("/")
key = cctx["mapiAppKey"]
match = "70505022"

paths = [
    f"/match/{match}",
    f"/matches/{match}",
    f"/match/{match}/stats",
    f"/match/{match}/statistics",
    f"/match/{match}/lineups",
    f"/match/{match}/squads",
    f"/basketball/match/{match}",
    f"/nba/match/{match}",
]

for path in paths:
    for param in [
        f"?appKey={key}",
        f"?api_key={key}",
        f"?key={key}",
    ]:
        url = base + path + param
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
            body = urllib.request.urlopen(req, timeout=15).read().decode("utf-8", "replace")
            print("OK", path, param[:10], body[:160])
            break
        except Exception as exc:
            err = str(exc)
            if hasattr(exc, "read"):
                err = exc.read(120).decode("utf-8", "replace")  # type: ignore[attr-defined]
            if "404" not in err and "403" not in err:
                print("?", path, err[:80])

# try header auth
url = f"{base}/match/{match}"
req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "x-app-key": key, "Accept": "application/json"})
try:
    print("header", urllib.request.urlopen(req, timeout=15).read()[:200])
except Exception as e:
    print("header err", e)
