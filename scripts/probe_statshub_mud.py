"""Try mud.sportradar.com and match_info_statshub feed."""
from __future__ import annotations

import json
import urllib.parse
import urllib.request

from probe_statshub7 import decode, load_arr

cctx = decode(load_arr("report"), 6)["cctx"]
token = cctx["fishnetToken"]
alias = cctx["fishnetClientAlias"]
base = cctx["fishnetUrl"].rstrip("/")
match_id = "70505022"

feeds = ["match_info_statshub", "match_stats", "match_squads"]
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://statshub.sportradar.com/",
    "Origin": "https://statshub.sportradar.com",
    "Sec-Fetch-Site": "cross-site",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Dest": "empty",
}

for feed in feeds:
    url = f"{base}/{alias}/zht/Asia/Taipei/gismo/{feed}/{match_id}?T={urllib.parse.quote(token, safe='')}"
    req = urllib.request.Request(url, headers=headers)
    body = urllib.request.urlopen(req, timeout=20).read().decode()
    print(feed, body[:200])

# mud api
for path in [
    f"https://mud.sportradar.com/v1/match/{match_id}",
    f"https://mud.sportradar.com/v1/matches/{match_id}/statistics",
]:
    try:
        r = urllib.request.urlopen(urllib.request.Request(path, headers=headers), timeout=15)
        print("MUD", path, r.read(200))
    except Exception as e:
        print("MUD ERR", path, e)
