"""Probe bddp.sportradar.com for match data."""
from __future__ import annotations

import urllib.request

match = "70505022"
urls = [
    f"https://bddp.sportradar.com/match/{match}",
    f"https://bddp.sportradar.com/api/match/{match}",
    f"https://bddp.sportradar.com/v1/match/{match}",
]
for url in urls:
    try:
        r = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=15)
        print(url, r.status, r.read(200))
    except Exception as e:
        print(url, e)
